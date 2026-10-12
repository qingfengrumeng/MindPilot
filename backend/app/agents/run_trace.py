"""User-visible, factual trace of one knowledge-answering turn."""

from copy import deepcopy
from time import perf_counter, perf_counter_ns

from app.db.models import new_id


class RunTrace:
    def __init__(self, query: str, deep_thinking: bool, attachment_names: list[str] | None = None,
                 input_span: tuple[int, int] | None = None,
                 supervisor_span: tuple[int, int] | None = None):
        self.started = input_span[0] / 1_000_000_000 if input_span else perf_counter()
        self._stage_started = {}
        self.trace = {
            "runId": new_id(), "domain": "knowledge", "status": "running",
            "query": query, "deepThinking": deep_thinking, "stages": [],
        }
        input_stage = self.add("input", "收到用户输入", "正在接收问题并准备会话上下文", status="running")
        prepared_attachments = [name for name in (attachment_names or []) if name]
        self.update(input_stage, status="ok", summary="已接收问题并准备会话上下文", detail={
            "question": query, "attachments": prepared_attachments, "deepThinking": deep_thinking,
        })
        if input_span:
            self._record_span(input_stage, input_span)
        supervisor_stage = self.add("agent", "知识问答 Supervisor", "正在选择知识问答工作流", status="running")
        decision = ("深度思考：生成、反思与必要时修订" if deep_thinking
                    else "普通问答：只生成一次，不反思、不重试")
        self.update(supervisor_stage, status="ok", summary="选择知识问答工作流", detail={"decision": decision})
        if supervisor_span:
            self._record_span(supervisor_stage, supervisor_span)

    def set_supervisor_decision(self, summary: str, decision: str):
        stage = self.trace["stages"][1]
        stage["summary"] = summary
        stage["detail"] = {"decision": decision}

    def _record_span(self, stage_id: str, span: tuple[int, int]):
        start_ns, end_ns = span
        stage = next(item for item in self.trace["stages"] if item["id"] == stage_id)
        stage["durationMs"] = round(max(0, end_ns - start_ns) / 1_000_000, 6)
        stage["elapsedMs"] = round((end_ns / 1_000_000_000 - self.started) * 1000)

    def add(self, kind: str, title: str, summary: str, detail: dict | None = None, status: str = "ok") -> str:
        stage_id = new_id()
        self._stage_started[stage_id] = perf_counter_ns()
        self.trace["stages"].append({
            "id": stage_id, "kind": kind, "title": title, "summary": summary,
            "detail": detail or {}, "status": status,
            "elapsedMs": round((perf_counter() - self.started) * 1000), "durationMs": None,
        })
        return stage_id

    def update(self, stage_id: str, *, status: str | None = None, summary: str | None = None, detail: dict | None = None):
        stage = next(item for item in self.trace["stages"] if item["id"] == stage_id)
        if status is not None:
            stage["status"] = status
        if summary is not None:
            stage["summary"] = summary
        if detail is not None:
            stage["detail"] = detail
        stage["elapsedMs"] = round((perf_counter() - self.started) * 1000)
        stage["durationMs"] = round((perf_counter_ns() - self._stage_started[stage_id]) / 1_000_000, 6)

    def finish(self, answer: str, evidence_count: int, attempts: int, error: str = ""):
        for stage in self.trace["stages"]:
            if stage["status"] == "running":
                self.update(stage["id"], status="error" if error else "ok")
        self.trace["status"] = "error" if error else "ok"
        self.trace["durationMs"] = round((perf_counter() - self.started) * 1000)
        self.add("output", "本轮结束" if not error else "运行失败",
                 error or f"已生成回答，检索到 {evidence_count} 个资料片段，共 {attempts} 轮生成",
                 {"answer": answer, "evidenceCount": evidence_count, "attempts": attempts,
                  **({"error": error} if error else {})}, "error" if error else "ok")

    def snapshot(self) -> dict:
        return deepcopy(self.trace)
