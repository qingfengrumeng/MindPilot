"""Bounded execution for installed agents and their child tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from threading import BoundedSemaphore
from time import monotonic
from uuid import uuid4

from app.runtime.agent_loop import AgentLoop
from app.runtime.model_gateway import ModelGateway
from app.runtime.protocol import TaskResult, TaskSpec


@dataclass
class RunContext:
    task_id: str
    user_id: str
    conversation_id: str | None
    settings: object
    session_factory: object
    manager: object
    artifacts: object
    tools: object
    allowed_tools: set[str]
    deadline: float
    max_steps: int
    steps: int = 0
    model_gateway: ModelGateway | None = None
    skills: object | None = None

    def check_active(self):
        if monotonic() > self.deadline:
            raise TimeoutError("Task execution timed out")
        if self.manager.get(self.task_id).status == "cancelled":
            raise InterruptedError("Task was cancelled")

    def consume_step(self):
        self.check_active()
        self.steps += 1
        if self.steps > self.max_steps:
            raise RuntimeError("Agent step limit reached")

    def event(self, kind: str, detail: dict | None = None):
        self.manager.event(self.task_id, kind, detail)

    def start_step(self, kind: str, name: str) -> str:
        self.consume_step()
        step_id = str(uuid4())
        self.event("step_start", {"step_id": step_id, "number": self.steps,
                                  "kind": kind, "name": name})
        return step_id

    def end_step(self, step_id: str, *, status: str, error: str | None = None):
        self.event("step_end", {"step_id": step_id, "status": status,
                                **({"error": error} if error else {})})

    def tool(self, name: str, arguments: dict, *, count_step: bool = True,
             step_id: str | None = None):
        return self.tools.call(name, arguments, allowed=self.allowed_tools, context=self,
                               count_step=count_step, step_id=step_id)

    def model(self, messages: list[dict], *, purpose: str = "generation",
              complete_fn=None, count_step: bool = True, step_id: str | None = None,
              config=None):
        if count_step:
            step_id = self.start_step("model", purpose)
        try:
            gateway = self.model_gateway or ModelGateway()
            result = gateway.complete(self, messages, purpose=purpose,
                                      complete_fn=complete_fn, step_id=step_id,
                                      config=config)
        except BaseException as exc:
            if count_step:
                self.end_step(step_id, status="failed", error=str(exc)[:500])
            raise
        if count_step:
            self.end_step(step_id, status="completed")
        return result


class AgentRunner:
    def __init__(self, registry, tools, skills, manager, artifacts, settings, session_factory,
                 *, max_concurrency: int = 4, timeout_seconds: int = 120,
                 max_steps: int = 24, model_gateway: ModelGateway | None = None):
        self.registry = registry
        self.tools = tools
        self.skills = skills
        self.manager = manager
        self.artifacts = artifacts
        self.settings = settings
        self.session_factory = session_factory
        self.timeout_seconds = timeout_seconds
        self.max_steps = max_steps
        self.loop = AgentLoop()
        self.model_gateway = model_gateway or ModelGateway()
        self.executor = ThreadPoolExecutor(max_workers=max_concurrency, thread_name_prefix="mindpilot-agent")
        self.dispatch_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mindpilot-task")
        self.capacity = BoundedSemaphore(max_concurrency)

    def shutdown(self):
        self.dispatch_executor.shutdown(wait=True, cancel_futures=True)
        self.executor.shutdown(wait=True, cancel_futures=True)

    def submit(self, spec: TaskSpec, *, user_id: str, conversation_id: str | None = None):
        self.manager.create(spec, user_id=user_id, conversation_id=conversation_id)
        return self.run(spec.task_id)

    def enqueue(self, spec: TaskSpec, *, user_id: str, conversation_id: str | None = None):
        self.manager.create(spec, user_id=user_id, conversation_id=conversation_id)
        self.dispatch_executor.submit(self.run, spec.task_id)
        return self.manager.get(spec.task_id, user_id=user_id)

    def run(self, task_id: str):
        spec, user_id, conversation_id = self.manager.spec(task_id)
        if self.manager.get(task_id).status not in {"queued", "waiting"}:
            raise ValueError("Task is not queued or waiting")
        if spec.agent == "supervisor":
            self.manager.transition(task_id, "running")
            self.manager.event(task_id, "turn_start", {"agent": "supervisor",
                                                       "attempt": self.manager.get(task_id).attempt})
            try:
                from app.agents.supervisor import run_supervisor
                result = TaskResult.model_validate(run_supervisor(spec, self))
            except Exception as exc:
                result = TaskResult(status="failed", error=str(exc), summary="主 Agent 执行失败")
            self.manager.event(task_id, "turn_end", {"status": result.status,
                                                     "artifact_ids": result.artifact_ids})
            return self.manager.finish(task_id, result)
        if not self.capacity.acquire(timeout=1):
            if self.manager.get(task_id).status == "queued":
                self.manager.transition(task_id, "waiting")
            return self.manager.get(task_id)
        self.manager.transition(task_id, "running")
        try:
            manifest, handler, input_schema = self.registry.load(spec.agent)
            timeout_seconds = manifest.timeout_seconds or self.timeout_seconds
            spec = spec.model_copy(update={"inputs": input_schema.model_validate(spec.inputs)
                                    .model_dump(exclude_none=True)})
            context = RunContext(task_id, user_id, conversation_id, self.settings,
                                 self.session_factory, self.manager, self.artifacts, self.tools,
                                 set(manifest.required_tools), monotonic() + timeout_seconds,
                                 max(self.max_steps, 32) if manifest.id == "diagram_agent" else self.max_steps,
                                 model_gateway=self.model_gateway,
                                 skills=self.skills)
            self.manager.event(task_id, "turn_start", {"agent": manifest.id,
                                                       "version": manifest.version,
                                                       "attempt": self.manager.get(task_id).attempt,
                                                       "allowed_tools": sorted(manifest.required_tools)})
            future = self.executor.submit(self.loop.run, handler, spec, context)
            future.add_done_callback(lambda _: self.capacity.release())
            try:
                result = TaskResult.model_validate(future.result(timeout=timeout_seconds))
            except FutureTimeout:
                future.cancel()
                result = TaskResult(status="failed", error="Task execution timed out", summary="子 Agent 超时")
            except InterruptedError:
                result = TaskResult(status="cancelled", summary="子 Agent 已取消")
            except Exception as exc:
                result = TaskResult(status="failed", error=str(exc), summary="子 Agent 执行失败")
        except Exception as exc:
            self.capacity.release()
            result = TaskResult(status="failed", error=str(exc), summary="子 Agent 加载失败")
        self.manager.event(task_id, "turn_end", {"status": result.status,
                                                 "artifact_ids": result.artifact_ids,
                                                 "source_ids": result.source_ids})
        return self.manager.finish(task_id, result)

    def run_child(self, parent: TaskSpec, *, agent: str, goal: str, inputs: dict,
                  user_id: str, conversation_id: str | None, constraints: dict | None = None):
        child = TaskSpec(agent=agent, goal=goal, inputs=inputs, constraints=constraints or {},
                         parent_task_id=parent.task_id)
        self.manager.create(child, user_id=user_id, conversation_id=conversation_id)
        self.manager.event(parent.task_id, "dispatch_handoff", {
            "child_task_id": child.task_id, "agent": agent,
        })
        return self.run(child.task_id)
