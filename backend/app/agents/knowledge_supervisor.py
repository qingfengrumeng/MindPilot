"""Supervisor for the knowledge-answering domain."""

from dataclasses import dataclass

from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.reflection_agent import ReflectionAgent, ReflectionResult


@dataclass
class KnowledgeOutcome:
    answer: str
    attempts: int
    reflection: ReflectionResult | None


class KnowledgeSupervisor:
    """Ordinary turns generate once; deep-thinking turns review and may retry three times."""

    def __init__(self, generator: KnowledgeAgent, reflection: ReflectionAgent, max_retries: int = 3, tools=None):
        self.generator = generator
        self.reflection = reflection
        self.max_retries = max_retries
        self.tools = tools

    def stream_standard(self, messages: list[dict]):
        yield from self.generator.stream(messages)

    def complete_standard(self, messages: list[dict]) -> KnowledgeOutcome:
        return KnowledgeOutcome(self.generator.generate(messages), 1, None)

    def run_deep(self, messages: list[dict], query: str, context: str):
        """Yield progress and one final outcome; never expose a rejected draft as the final answer."""
        best = None
        previous_answer = ""
        suggestions = []
        for attempt in range(1, self.max_retries + 2):
            yield {"type": "agent_start", "agent": "knowledge_generator", "attempt": attempt}
            answer = self.generator.generate(messages, previous_answer, suggestions)
            yield {"type": "agent_generated", "agent": "knowledge_generator", "attempt": attempt, "answer": answer}
            yield {"type": "agent_start", "agent": "reflection", "attempt": attempt}
            review = self.reflection.evaluate(query, answer, context)
            yield {"type": "agent_review", "agent": "reflection", "attempt": attempt,
                   "score": review.score, "threshold": review.threshold, "approved": review.approved,
                   "reflection": review.model_dump()}
            if best is None or review.score > best.reflection.score:
                best = KnowledgeOutcome(answer, attempt, review)
            if review.approved:
                yield {"type": "result", "outcome": KnowledgeOutcome(answer, attempt, review)}
                return
            previous_answer, suggestions = answer, review.suggestions
        best.attempts = self.max_retries + 1
        yield {"type": "result", "outcome": best}
