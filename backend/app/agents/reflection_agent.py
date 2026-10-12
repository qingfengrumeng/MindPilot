"""Four-dimension quality review for the knowledge domain."""

import json

from pydantic import BaseModel, Field, ValidationError

from app.services.text_generation import TextGenerationError


class _Scorecard(BaseModel):
    accuracy: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    safety: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    suggestions: list[str] = Field(default_factory=list)


class ReflectionResult(BaseModel):
    accuracy: float
    completeness: float
    safety: float
    relevance: float
    score: float
    threshold: float
    approved: bool
    suggestions: list[str]


class ReflectionAgent:
    WEIGHTS = {"accuracy": 0.35, "completeness": 0.25, "safety": 0.25, "relevance": 0.15}

    def __init__(self, config, complete_fn, threshold: float = 0.8):
        self.config = config
        self.complete_fn = complete_fn
        self.threshold = threshold

    @staticmethod
    def _score_accuracy(scorecard: _Scorecard) -> float:
        return scorecard.accuracy

    @staticmethod
    def _score_completeness(scorecard: _Scorecard) -> float:
        return scorecard.completeness

    @staticmethod
    def _score_safety(scorecard: _Scorecard) -> float:
        return scorecard.safety

    @staticmethod
    def _score_relevance(scorecard: _Scorecard) -> float:
        return scorecard.relevance

    def evaluate(self, query: str, answer: str, context: str) -> ReflectionResult:
        prompt = (
            "你是知识问答的反思 Agent。只评估下面的候选回答，不要重新回答问题。"
            "分别按 0 到 1 评分：accuracy=与已提供证据和可靠事实是否一致；"
            "completeness=是否覆盖问题的主要要求；safety=是否有错误、误导或不安全建议；"
            "relevance=是否切题。没有证据时不要假定已检索到资料。"
            "只返回一个 JSON 对象，键为 accuracy、completeness、safety、relevance、suggestions。"
            "suggestions 为具体、可执行的修正建议数组；若已经足够好则为空数组。\n\n"
            f"用户问题：\n{query[:6000]}\n\n可用证据：\n{context[:16000] or '无检索证据'}\n\n候选回答：\n{answer[:16000]}"
        )
        raw, _ = self.complete_fn(self.config, [{"role": "system", "content": "你是严格、公正的回答质量评估员。只输出 JSON。"},
                                                 {"role": "user", "content": prompt}])
        try:
            start, end = raw.index("{"), raw.rindex("}") + 1
            card = _Scorecard.model_validate(json.loads(raw[start:end]))
        except (ValueError, ValidationError, TypeError) as exc:
            raise TextGenerationError("反思 Agent 未返回有效的四维评分") from exc
        scores = {
            "accuracy": self._score_accuracy(card),
            "completeness": self._score_completeness(card),
            "safety": self._score_safety(card),
            "relevance": self._score_relevance(card),
        }
        weighted = sum(scores[name] * weight for name, weight in self.WEIGHTS.items())
        suggestions = [item.strip()[:500] for item in card.suggestions if isinstance(item, str) and item.strip()][:6]
        if weighted < self.threshold and not suggestions:
            suggestions = ["补足问题要求，核对事实和证据，删除不确定的断言。"]
        return ReflectionResult(**scores, score=round(weighted, 4), threshold=self.threshold,
                                approved=weighted >= self.threshold, suggestions=suggestions)
