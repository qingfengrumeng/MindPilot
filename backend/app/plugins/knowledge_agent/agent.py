"""Knowledge plugin reuses the existing generation and reflection agents."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.knowledge_supervisor import KnowledgeSupervisor
from app.agents.reflection_agent import ReflectionAgent
from app.core.model_runtime import require_runtime_model
from app.runtime.agent_loop import ToolCall
from app.runtime.protocol import TaskResult, TaskSpec
from app.services.text_generation import complete_text, stream_text
from app.tools.current_datetime import is_current_datetime_question


class KnowledgeInputs(BaseModel):
    query: str | None = Field(default=None, max_length=12000)
    deep_thinking: bool = False
    use_web: bool = False
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    artifact_ids: list[str] = Field(default_factory=list, max_length=10)


def run(spec: TaskSpec, context) -> TaskResult:
    query = str(spec.inputs.get("query") or spec.goal).strip()
    if not query:
        raise ValueError("Knowledge query is empty")
    if spec.constraints.get("output_format") not in {None, "text", "markdown", "md"}:
        return TaskResult(status="waiting", error="知识问答 Agent 不支持所需输出格式")
    source_labels = []
    if is_current_datetime_question(query):
        result = yield ToolCall("current_datetime", {"query": query})
        answer = result["answer"]
        sources = []
        attempts = 0
        reflection = None
    else:
        context.event("retrieval", {"query": query})
        rag = yield ToolCall("rag_search", {"query": query, "top_k": 5,
                                            "source_ids": spec.inputs.get("source_ids", [])})
        sources = list(rag["source_ids"])
        source_labels.extend(dict.fromkeys(hit["title"] for hit in rag["hits"]))
        evidence = rag["context"]
        use_web = bool(spec.inputs.get("use_web")) or any(
            term in query for term in ("最新", "近期", "联网", "新闻", "实时", "current", "latest"))
        if use_web:
            web = yield ToolCall("web_search", {"query": query})
            evidence += "\n\n" + web["context"]
            sources.extend(web["source_ids"])
            source_labels.extend(row["url"] for row in web["sources"] if row.get("url"))
        for artifact_id in spec.inputs.get("artifact_ids", []):
            material = yield ToolCall("read_artifact", {"artifact_id": artifact_id})
            evidence += "\n\n[上游产物]\n" + material["content"]
            sources.extend(material["source_ids"])
        if spec.constraints.get("must_cite_sources") and not sources:
            return TaskResult(status="waiting", error="没有可核查的资料来源，无法生成要求引用的回答")
        config = require_runtime_model("text", context.settings.model_config_path)
        supervisor = KnowledgeSupervisor(
            KnowledgeAgent(config, lambda _config, messages: context.model(
                messages, purpose="knowledge_generation", complete_fn=complete_text), stream_text),
            ReflectionAgent(config, lambda _config, messages: context.model(
                messages, purpose="knowledge_review", complete_fn=complete_text)))
        messages = [{"role": "system", "content": "请用用户的语言回答。根据提供的证据作答；引用资料时注明对应的资料编号。无法确认时明确说明。"}]
        if evidence.strip():
            messages.append({"role": "system", "content": evidence[:26000]})
        messages.append({"role": "user", "content": query})
        if spec.inputs.get("deep_thinking"):
            outcome = None
            for step in supervisor.run_deep(messages, query, evidence):
                context.event("agent_step", {key: value for key, value in step.items()
                                             if key not in {"answer", "outcome"}})
                if step["type"] == "result":
                    outcome = step["outcome"]
        else:
            outcome = supervisor.complete_standard(messages)
        answer, attempts, reflection = outcome.answer, outcome.attempts, outcome.reflection
    if spec.constraints.get("must_cite_sources"):
        if not sources:
            return TaskResult(status="waiting", error="没有可核查的资料来源，无法生成要求引用的回答")
        if source_labels:
            answer += "\n\n来源：\n" + "\n".join(f"- {label}" for label in dict.fromkeys(source_labels))
    context.check_active()
    artifact_id = context.artifacts.save_text(answer, user_id=context.user_id, task_id=context.task_id,
                                              kind="answer", filename="answer.md", mime_type="text/markdown",
                                              source_ids=list(dict.fromkeys(sources)))
    return TaskResult(status="completed", summary=answer[:300], artifact_ids=[artifact_id],
                      source_ids=list(dict.fromkeys(sources)),
                      outputs={"attempts": attempts,
                               "reflection": reflection.model_dump() if reflection else None})
