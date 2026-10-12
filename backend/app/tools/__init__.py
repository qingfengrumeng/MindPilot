"""Callable tools available to the knowledge-answering workflow."""

from collections.abc import Callable

from app.tools.web_search import WebSearchResult


class KnowledgeTools:
    """Inject only the tools this domain is allowed to call."""

    def __init__(self, knowledge_search: Callable, web_search: Callable):
        self._knowledge_search = knowledge_search
        self._web_search = web_search

    def search_knowledge_base(self, query: str) -> tuple[str, list[dict]]:
        return self._knowledge_search(query) if query else ("", [])

    def web_search(self, query: str) -> WebSearchResult:
        return self._web_search(query)
