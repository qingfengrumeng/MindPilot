"""Background document indexing with progress persisted in SQLite."""

from pathlib import Path

from sqlalchemy import delete

from app.db.models import Document, DocumentChunk
from app.services.document_ingestion import extract_document, index_chunks, remove_document_vectors, split_pages


ACTIVE_DOCUMENT_STATUSES = ("queued", "parsing", "chunking", "embedding")


def process_document(session_factory, settings, document_id: str) -> None:
    """Process a single document in a bounded worker thread, using fresh DB sessions."""
    try:
        with session_factory() as db:
            document = db.get(Document, document_id)
            if not document or document.status != "queued":
                return
            document.status = "parsing"
            db.commit()
            path = Path(document.storage_path)
            content_type = document.content_type
            chunk_size = document.chunk_size
            user_id = document.user_id

        remove_document_vectors(settings.data_dir, document_id)
        with session_factory() as db:
            db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            db.commit()

        pages, page_count = extract_document(path, content_type)

        with session_factory() as db:
            document = db.get(Document, document_id)
            if not document:
                return
            document.pages = page_count
            document.status = "chunking"
            db.commit()

        chunks = split_pages(pages, chunk_size)
        if not chunks:
            raise ValueError("资料中没有可切分的文本")

        with session_factory() as db:
            document = db.get(Document, document_id)
            if not document:
                return
            db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
            db.add_all(
                DocumentChunk(
                    document_id=document_id,
                    chunk_index=index,
                    page=chunk["page"],
                    text=chunk["text"],
                    chroma_id=f"{document_id}:{index}",
                )
                for index, chunk in enumerate(chunks)
            )
            document.chunk_count = len(chunks)
            document.indexed_chunks = 0
            document.status = "embedding"
            db.commit()

        def on_progress(completed: int) -> None:
            with session_factory() as db:
                document = db.get(Document, document_id)
                if document:
                    document.indexed_chunks = completed
                    db.commit()

        index_chunks(chunks, settings.data_dir, settings.model_config_path, document_id, user_id, on_progress)

        with session_factory() as db:
            document = db.get(Document, document_id)
            if document:
                document.indexed_chunks = len(chunks)
                document.status = "ready"
                document.error_message = ""
                db.commit()
    except Exception as exc:
        remove_document_vectors(settings.data_dir, document_id)
        with session_factory() as db:
            document = db.get(Document, document_id)
            if document:
                document.status = "failed"
                document.indexed_chunks = 0
                document.error_message = str(exc)[:500] or "处理失败，请重试"
                db.commit()
