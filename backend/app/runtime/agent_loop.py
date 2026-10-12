"""One execution driver for plugin workflows.

Plugins yield model/tool requests and keep only domain decisions. The driver owns
step accounting, execution and durable step boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isgenerator
from typing import Callable

from app.runtime.protocol import TaskResult


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCall:
    messages: list[dict]
    purpose: str = "generation"
    complete_fn: Callable | None = None


class AgentLoop:
    """Drive a plugin's decisions through the same bounded, recorded execution path."""

    def run(self, handler: Callable, spec, context) -> TaskResult:
        workflow = handler(spec, context)
        if not isgenerator(workflow):
            return TaskResult.model_validate(workflow)
        result = None
        while True:
            context.check_active()
            try:
                action = workflow.send(result)
            except StopIteration as stopped:
                return TaskResult.model_validate(stopped.value)
            if not isinstance(action, (ToolCall, ModelCall)):
                raise TypeError(f"Unsupported agent action: {type(action).__name__}")
            step = context.start_step("tool" if isinstance(action, ToolCall) else "model",
                                      action.name if isinstance(action, ToolCall) else action.purpose)
            try:
                if isinstance(action, ToolCall):
                    result = context.tool(action.name, action.arguments, count_step=False,
                                          step_id=step)
                else:
                    result = context.model(action.messages, purpose=action.purpose,
                                           complete_fn=action.complete_fn, count_step=False,
                                           step_id=step)
            except BaseException as exc:
                context.end_step(step, status="failed", error=str(exc)[:500])
                raise
            context.end_step(step, status="completed")
