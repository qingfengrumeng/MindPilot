"""Hybrid vector and BM25 knowledge-base retrieval."""

from app.services.document_ingestion import search_documents
from app.tools.bm25_search import bm25_search


def hybrid_search(query: str, settings, session_factory, user_id: str, top_k: int = 5,
                  dense_search=search_documents, document_ids: list[str] | None = None) -> list[dict]:
    """Fuse vector and BM25 ranks for ready documents owned by this user."""
    limit = max(1, min(top_k, 20))
    try:
        dense = dense_search(query, settings.data_dir, settings.model_config_path, user_id, top_k=limit * 3)
    except Exception:
        dense = []
    if document_ids is not None:
        allowed = set(document_ids)
        dense = [hit for hit in dense if hit.get("documentId") in allowed]
    lexical = bm25_search(query, session_factory, user_id, top_k=limit * 3, document_ids=document_ids)
    merged = {}
    for source in (dense, lexical):
        for rank, hit in enumerate(source, 1):
            key = (hit.get("documentId"), hit.get("chunkIndex"))
            if key[1] is None:
                key = (hit.get("documentId"), hit.get("page"), hit.get("text"))
            if key not in merged:
                merged[key] = {**hit, "hybridScore": 0.0}
            merged[key]["hybridScore"] += 1 / (60 + rank)
            if "distance" in hit:
                merged[key]["distance"] = hit["distance"]
            if "bm25Score" in hit:
                merged[key]["bm25Score"] = hit["bm25Score"]
    return sorted(merged.values(), key=lambda hit: hit["hybridScore"], reverse=True)[:limit]
