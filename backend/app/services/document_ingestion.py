"""Local document extraction, chunking and Chroma persistence."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import chromadb

from app.core.model_runtime import require_runtime_model
from app.services.embedding_generation import EmbeddingError, embed_texts


DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 120
MAX_CHUNK_SIZE = 10_000
EMBED_BATCH_SIZE = 20


class DocumentIngestionError(Exception):
    pass


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_document(path: Path, content_type: str) -> tuple[list[tuple[int, str]], int]:
    """Return page-numbered text and page count, using pdfplumber for PDFs."""
    suffix = path.suffix.lower()
    if suffix == ".pdf" or content_type == "application/pdf":
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                pages = [(_index + 1, _clean_text(page.extract_text() or "")) for _index, page in enumerate(pdf.pages)]
            pages = [(page, text) for page, text in pages if text]
            if not pages:
                raise DocumentIngestionError("PDF 未提取到可读文本，可能是扫描件或文件内容为空")
            return pages, len(pdf.pages)
        except DocumentIngestionError:
            raise
        except Exception as exc:
            raise DocumentIngestionError(f"PDF 解析失败：{exc}") from exc

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise DocumentIngestionError("无法读取上传的资料") from exc
    text = _clean_text(text)
    if not text:
        raise DocumentIngestionError("资料中没有可读取的文本")
    return [(1, text)], 1


def split_pages(pages: list[tuple[int, str]], chunk_size: int, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[dict]:
    chunk_size = max(100, min(int(chunk_size), MAX_CHUNK_SIZE))
    overlap = min(max(0, overlap), chunk_size // 3)
    chunks: list[dict] = []
    for page, text in pages:
        start = 0
        while start < len(text):
            end = min(len(text), start + chunk_size)
            if end < len(text):
                boundary = max(text.rfind("。", start + chunk_size // 2, end), text.rfind(" ", start + chunk_size // 2, end))
                if boundary > start:
                    end = boundary + 1
            value = text[start:end].strip()
            if value:
                chunks.append({"page": page, "text": value})
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
    return chunks


def _hash_embedding(text: str, dimensions: int) -> list[float]:
    """Small deterministic fallback when no remote embedding model is configured."""
    values = [0.0] * dimensions
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower()) or [text]
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        for offset in range(0, len(digest), 4):
            index = int.from_bytes(digest[offset:offset + 4], "big") % dimensions
            values[index] += 1.0 if digest[offset] & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in values)) or 1.0
    return [item / norm for item in values]


def _embeddings(texts: list[str], model_config_path: Path) -> tuple[list[list[float]], str, int]:
    try:
        config = require_runtime_model("embedding", model_config_path)
    except RuntimeError:
        dimensions = 384
        return [_hash_embedding(text, dimensions) for text in texts], "local-hash-384", dimensions

    vectors: list[list[float]] = []
    try:
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            result = embed_texts(config, texts[start:start + EMBED_BATCH_SIZE])
            vectors.extend(item["embedding"] for item in result["data"])
    except EmbeddingError:
        # 网络或业务空间暂时不可用时仍完成本地资料入库，使用确定性的轻量向量，
        # 避免用户因为远程 Embedding 短暂故障而丢失已上传的资料。
        dimensions = 384
        return [_hash_embedding(text, dimensions) for text in texts], "local-hash-384", dimensions
    return vectors, config.model, config.dimensions or len(vectors[0])


def get_collection(data_dir: Path, dimensions: int | None = None):
    path = data_dir / "chroma"
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))
    name = f"mindpilot_documents_{dimensions or 'default'}"
    return client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})


def index_chunks(chunks: list[dict], data_dir: Path, model_config_path: Path, document_id: str, user_id: str, on_progress=None) -> dict:
    """Embed prepared chunks in small batches and report completed batch counts."""
    if not chunks:
        raise DocumentIngestionError("资料没有可保存的知识分块")
    texts = [item["text"] for item in chunks]
    first_batch = texts[:EMBED_BATCH_SIZE]
    vectors, embedding_model, dimensions = _embeddings(first_batch, model_config_path)
    collection = get_collection(data_dir, dimensions)
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch_chunks = chunks[start:start + EMBED_BATCH_SIZE]
        batch_texts = texts[start:start + EMBED_BATCH_SIZE]
        if start:
            if embedding_model == "local-hash-384":
                vectors = [_hash_embedding(text, dimensions) for text in batch_texts]
            else:
                vectors, batch_model, batch_dimensions = _embeddings(batch_texts, model_config_path)
                if batch_dimensions != dimensions or batch_model != embedding_model:
                    raise DocumentIngestionError("Embedding 服务在处理中发生变化，请重新向量化")
        ids = [f"{document_id}:{index}" for index in range(start, start + len(batch_chunks))]
        metadatas = [{"document_id": document_id, "user_id": user_id, "page": item["page"], "chunk_index": index} for index, item in enumerate(batch_chunks, start=start)]
        collection.add(ids=ids, documents=batch_texts, metadatas=metadatas, embeddings=vectors)
        if on_progress:
            on_progress(start + len(batch_chunks))
    return {"embedding_model": embedding_model, "embedding_dimensions": dimensions}


def index_document(path: Path, content_type: str, data_dir: Path, model_config_path: Path, document_id: str, user_id: str, chunk_size: int) -> dict:
    pages, page_count = extract_document(path, content_type)
    chunks = split_pages(pages, chunk_size)
    result = index_chunks(chunks, data_dir, model_config_path, document_id, user_id)
    return {"pages": page_count, "chunks": chunks, **result}


def search_documents(query: str, data_dir: Path, model_config_path: Path, user_id: str, top_k: int = 5) -> list[dict]:
    text = query.strip()
    if not text:
        return []
    path = data_dir / "chroma"
    if not path.exists():
        return []
    client = chromadb.PersistentClient(path=str(path))
    if not client.list_collections():
        return []
    vectors, embedding_model, dimensions = _embeddings([text], model_config_path)
    collection = client.get_or_create_collection(f"mindpilot_documents_{dimensions}", metadata={"hnsw:space": "cosine"})
    if collection.count() == 0:
        return []
    result = collection.query(
        query_embeddings=vectors,
        n_results=max(1, min(top_k, 20)),
        where={"user_id": user_id},
        include=["documents", "metadatas", "distances"],
    )
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    return [
        {
            "text": value,
            "documentId": metadata.get("document_id"),
            "page": metadata.get("page"),
            "chunkIndex": metadata.get("chunk_index"),
            "distance": distance,
            "embeddingModel": embedding_model,
        }
        for value, metadata, distance in zip(documents, metadatas, distances)
    ]


def remove_document_vectors(data_dir: Path, document_id: str) -> None:
    try:
        path = data_dir / "chroma"
        if not path.exists():
            return
        client = chromadb.PersistentClient(path=str(path))
        for item in client.list_collections():
            collection = client.get_collection(item.name)
            collection.delete(where={"document_id": document_id})
    except Exception:
        # SQLite metadata remains authoritative if the local Chroma directory is unavailable.
        pass
