"""Research loop: gather verifiable evidence, draft, optionally review, store report."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agents.reflection_agent import ReflectionAgent
from app.runtime.agent_loop import ModelCall, ToolCall
from app.runtime.protocol import TaskResult, TaskSpec
from app.services.text_generation import complete_text


class ResearchInputs(BaseModel):
    query: str | None = Field(default=None, max_length=12000)
    source_scope: Literal["all", "local", "web"] = "all"
    deep_thinking: bool = False
    artifact_ids: list[str] = Field(default_factory=list, max_length=10)


def run(spec: TaskSpec, context) -> TaskResult:
    if spec.constraints.get("output_format") not in {None, "markdown", "md"}:
        return TaskResult(status="waiting", error="科研 Agent 不支持所需输出格式")
    query = str(spec.inputs.get("query") or spec.goal).strip()
    scope = str(spec.inputs.get("source_scope") or "all")
    if scope not in {"all", "local", "web"}:
        raise ValueError("source_scope must be all, local, or web")
    evidence, sources, citations = [], [], []
    for artifact_id in spec.inputs.get("artifact_ids", []):
        material = yield ToolCall("read_artifact", {"artifact_id": artifact_id, "max_chars": 18000})
        evidence.append("上游资料：\n" + material["content"])
        sources.extend(material["source_ids"])
    if scope in {"all", "local"}:
        local = yield ToolCall("rag_search", {"query": query, "top_k": 8})
        if local["context"]:
            evidence.append("本地资料：\n" + local["context"])
        sources.extend(local["source_ids"])
        citations.extend({"type": "document", "title": hit["title"],
                          "source_id": hit["documentId"]} for hit in local["hits"])
    if scope in {"all", "web"}:
        web = yield ToolCall("web_search", {"query": query})
        if web["context"]:
            evidence.append("联网资料：\n" + web["context"])
        sources.extend(web["source_ids"])
        citations.extend({"type": "web", "title": item.get("title"), "url": item.get("url"),
                          "source_id": item.get("url")} for item in web["sources"] if item.get("url"))
    if not evidence:
        return TaskResult(status="waiting", summary="尚无足够资料生成可核查的研究报告",
                          error="未找到可用的本地或联网来源")
    if spec.constraints.get("must_cite_sources") and not sources:
        return TaskResult(status="waiting", error="研究资料缺少可核查的来源")
    evidence_text = "\n\n".join(evidence)[:30000]
    reflection = ReflectionAgent(None, lambda _config, messages: context.model(
        messages, purpose="research_review", complete_fn=complete_text))
    prior, suggestions, review = "", [], None
    max_attempts = 3 if spec.inputs.get("deep_thinking") else 1
    for attempt in range(1, max_attempts + 1):
        revision = ("\n上一稿：\n" + prior[:12000] + "\n修正建议：\n" + "\n".join(suggestions)) if prior else ""
        report, _ = yield ModelCall([
            {"role": "system", "content": "你是科研报告 Agent。只基于给定资料写 Markdown 报告，区分事实、推断与资料缺口。"
             "每个关键事实附资料标题或 URL；不要虚构论文、年份和实验数据。"},
            {"role": "user", "content": f"研究问题：{query}\n\n可用证据：\n{evidence_text}{revision}"},
        ], purpose="research_draft", complete_fn=complete_text)
        report = report.strip()
        if not report:
            raise ValueError("Research model returned empty report")
        context.event("draft", {"attempt": attempt, "characters": len(report)})
        if max_attempts == 1:
            break
        review = reflection.evaluate(query, report, evidence_text)
        context.event("reflection", {"attempt": attempt, "score": review.score,
                                     "approved": review.approved})
        if review.approved:
            break
        prior, suggestions = report, review.suggestions
    context.check_active()
    sources = list(dict.fromkeys(sources))
    saved = yield ToolCall("write_markdown", {"content": report, "filename": "research_report.md",
                                              "source_ids": sources})
    return TaskResult(status="completed", summary=f"已生成研究报告，引用 {len(sources)} 个来源",
                      artifact_ids=[saved["artifact_id"]], source_ids=sources,
                      outputs={"citations": citations[:30], "attempts": attempt,
                               "reflection": review.model_dump() if review else None})
