"""User-scoped SQLite BM25 keyword retrieval."""

from collections import Counter
import math
import re

from sqlalchemy import select

from app.db.models import Document, DocumentChunk


TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+", re.I)


def _tokens(text: str) -> list[str]:
    result = []
    for match in TOKEN_PATTERN.finditer(text.lower()):
        value = match.group()
        if "\u4e00" <= value[0] <= "\u9fff":
            result.extend(value[index:index + 2] for index in range(len(value) - 1))
            if len(value) == 1:
                result.append(value)
        else:
            result.append(value)
    return result


def bm25_search(query: str, session_factory, user_id: str, top_k: int = 15,
                document_ids: list[str] | None = None) -> list[dict]:
    """Score ready document chunks without caching the full corpus in RAM."""
    terms = list(dict.fromkeys(_tokens(query)))[:32]
    if not terms:
        return []
    document_count = 0
    total_length = 0
    document_frequency = Counter()
    candidates = []
    statement = (
        select(DocumentChunk.document_id, DocumentChunk.chunk_index, DocumentChunk.page, DocumentChunk.text)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.user_id == user_id, Document.status == "ready")
    )
    if document_ids is not None:
        if not document_ids:
            return []
        statement = statement.where(Document.id.in_(document_ids))
    with session_factory() as db:
        for document_id, chunk_index, page, text in db.execute(statement).yield_per(200):
            counts = Counter(_tokens(text))
            document_count += 1
            length = sum(counts.values()) or 1
            total_length += length
            matches = {term: counts[term] for term in terms if counts[term]}
            if matches:
                document_frequency.update(matches.keys())
                candidates.append((document_id, chunk_index, page, text, length, matches))
    if not candidates:
        return []
    average_length = total_length / document_count
    ranked = []
    for document_id, chunk_index, page, text, length, matches in candidates:
        score = sum(
            math.log1p((document_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average_length))
            for term, frequency in matches.items()
        )
        ranked.append((score, {"documentId": document_id, "chunkIndex": chunk_index,
                               "page": page, "text": text, "bm25Score": score}))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked[:top_k]]
