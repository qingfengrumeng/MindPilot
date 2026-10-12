"""Knowledge-domain answer generation, independent of quality review."""

from app.services.text_generation import TextGenerationError


class KnowledgeAgent:
    def __init__(self, config, complete_fn, stream_fn):
        self.config = config
        self.complete_fn = complete_fn
        self.stream_fn = stream_fn
        self.last_meta = {}

    def stream(self, messages: list[dict]):
        self.last_meta = {}
        self.last_meta = (yield from self.stream_fn(self.config, messages)) or {}

    def generate(self, messages: list[dict], previous_answer: str = "", suggestions: list[str] | None = None) -> str:
        request = list(messages)
        if previous_answer and suggestions:
            request.insert(1, {"role": "system", "content": (
                "请根据质量评估修订上一版回答。保留正确内容，修正问题，直接输出完整的新答案。"
                "不要声称完成了未执行的检索，也不要编造引用。\n"
                f"上一版回答：\n{previous_answer[:9000]}\n"
                "修正建议：\n" + "\n".join(f"- {item}" for item in suggestions[:6])
            )})
        answer, self.last_meta = self.complete_fn(self.config, request)
        answer = answer.strip()
        if not answer:
            raise TextGenerationError("知识生成 Agent 未返回有效内容")
        return answer
