import os
import re
from datetime import timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentContext, Db
from app.db.models import Document,DocumentWikiCompilation,WikiSupplementJob
from app.services.wiki_supplement import ACTIVE_SUPPLEMENT_STATUSES
from app.services.graph_build import remove_document_from_graph
from app.services.wiki_compilation import ACTIVE_WIKI_STATUSES,compile_document
from app.core.model_runtime import require_runtime_model
from app.core.storage_layout import business_directory
from app.schemas.base import CamelModel
from app.services.document_ingestion import remove_document_vectors, search_documents
from app.services.document_jobs import ACTIVE_DOCUMENT_STATUSES, process_document


router = APIRouter(prefix="/documents", tags=["documents"])
MAX_FILE_BYTES = 50 * 1024 * 1024
SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".markdown"}


class DocumentSearchRequest(CamelModel):
    query: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=5, ge=1, le=20)


def safe_name(filename: str) -> str:
    name = Path(filename or "document").name
    return re.sub(r"[^\w .()\-\u4e00-\u9fff]", "_", name)[:255] or "document"


def size_label(size: int) -> str:
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def document_out(item: Document, wiki=None, supplement=None) -> dict:
    source_available=Path(item.storage_path).is_file()
    return {
        "id": item.id,
        "title": item.title,
        "filename": item.filename,
        "type": "note",
        "typeLabel": "资料",
        "domain": item.domain,
        "source": f"本地文件 · {item.filename}",
        "importedAt": item.created_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if item.created_at.tzinfo is None else item.created_at.isoformat(),
        "pages": item.pages,
        "size": size_label(item.size_bytes),
        "chunks": item.chunk_count,
        "indexedChunks": item.indexed_chunks,
        "chunkSize": item.chunk_size,
        "version": "v1",
        "author": "本人",
        "year": item.created_at.year,
        "tags": [],
        "status": item.status,
        'wikiStatus':wiki.status if wiki else 'uncompiled',
        'wikiCompletedBatches':wiki.completed_batches if wiki else 0,
        'wikiTotalBatches':wiki.total_batches if wiki else 0,
        'wikiErrorMessage':('原始文件缺失，请重新上传这份资料后再编译Wiki。' if not source_available and wiki and wiki.status=='failed' else wiki.error_message if wiki else ''),
        'sourceAvailable':source_available,
        'wikiSupplementStatus':supplement.status if supplement else '',
        'wikiSupplementError':supplement.error_message if supplement else '',
        'wikiSupplementCount':len((wiki.data_json or {}).get('supplements', [])) if wiki else 0,
        "errorMessage": item.error_message,
        "readable": item.status == "ready",
        "summary": (
            f"已按每段 {item.chunk_size} 字切分，生成 {item.chunk_count} 个可引用知识分块。"
            if item.status == "ready" else "文件已保存。点击资料行中的向量化按钮，开始解析与建立索引。"
        ),
    }


@router.get("")
def list_documents(db: Db, context: CurrentContext, domain: str = "all", keyword: str = ""):
    query = select(Document).where(Document.user_id == context[0].id).order_by(Document.created_at.desc())
    if domain != "all":
        query = query.where(Document.domain == domain)
    items = db.scalars(query).all()
    if keyword.strip():
        needle = keyword.strip().lower()
        items = [item for item in items if needle in f"{item.title} {item.filename}".lower()]
    wiki_jobs={job.document_id:job for job in db.scalars(select(DocumentWikiCompilation).where(DocumentWikiCompilation.user_id==context[0].id))}
    supplements={job.document_id:job for job in db.scalars(select(WikiSupplementJob).where(WikiSupplementJob.user_id==context[0].id))}
    return {"items": [document_out(item,wiki_jobs.get(item.id),supplements.get(item.id)) for item in items], "total": len(items)}


@router.post("/search")
def search_document_chunks(payload: DocumentSearchRequest, request: Request, context: CurrentContext):
    return {"items": search_documents(payload.query, request.app.state.settings.data_dir, request.app.state.settings.model_config_path, context[0].id, payload.top_k)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    db: Db,
    context: CurrentContext,
    file: UploadFile = File(...),
    domain: str = Form("personal_learning"),
    chunk_size: int | None = Form(None),
):
    filename = safe_name(file.filename or "document")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(415, "当前支持 PDF、TXT 和 Markdown 文件")
    chunk_size = chunk_size or request.app.state.settings.document_chunk_size
    if not 100 <= chunk_size <= 10_000:
        raise HTTPException(422, "chunk_size 必须在 100 到 10000 之间")
    document_id = os.urandom(16).hex()
    user_dir = request.app.state.settings.data_dir / "documents" / context[0].id
    user_dir.mkdir(parents=True, exist_ok=True)
    storage_path = user_dir / f"{document_id}{suffix}"
    size_bytes = 0
    try:
        with storage_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > MAX_FILE_BYTES:
                    raise HTTPException(413, "资料不能超过 50 MiB")
                output.write(chunk)
        if size_bytes == 0:
            raise HTTPException(422, "不能上传空文件")
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise
    item = Document(
        id=document_id,
        user_id=context[0].id,
        title=Path(filename).stem,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        storage_path=str(storage_path),
        domain=domain.strip()[:80] or "personal_learning",
        size_bytes=size_bytes,
        chunk_size=chunk_size,
        status="uploaded",
        error_message="",
    )
    try:
        db.add(item)
        db.commit()
        return document_out(item)
    except Exception:
        db.rollback()
        storage_path.unlink(missing_ok=True)
        raise


@router.post("/{document_id}/vectorize", status_code=status.HTTP_202_ACCEPTED)
def vectorize_document(document_id: str, request: Request, db: Db, context: CurrentContext):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == context[0].id))
    if not item:
        raise HTTPException(404, "资料不存在")
    if item.status in ACTIVE_DOCUMENT_STATUSES:
        raise HTTPException(409, "该资料正在处理，请稍候")
    if item.status == "ready":
        raise HTTPException(409, "该资料已完成向量化")
    updated = db.execute(
        update(Document)
        .where(Document.id == document_id, Document.user_id == context[0].id, Document.status.in_(("uploaded", "failed")))
        .values(status="queued", error_message="", chunk_count=0, indexed_chunks=0)
    )
    if updated.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "该资料正在处理或已完成向量化")
    db.commit()
    try:
        request.app.state.document_executor.submit(
            process_document, request.app.state.session_factory, request.app.state.settings, document_id
        )
    except RuntimeError:
        db.execute(update(Document).where(Document.id == document_id).values(status="failed", error_message="后台任务不可用，请重试"))
        db.commit()
        raise HTTPException(503, "后台任务暂时不可用") from None
    db.refresh(item)
    return document_out(item, db.get(DocumentWikiCompilation, document_id), db.get(WikiSupplementJob, document_id))


@router.get("/{document_id}")
def get_document(document_id: str, db: Db, context: CurrentContext):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == context[0].id))
    if not item:
        raise HTTPException(404, "资料不存在")
    wiki=db.get(DocumentWikiCompilation,document_id)
    result = document_out(item,wiki,db.get(WikiSupplementJob,document_id))
    result["chunks"] = [{"id": chunk.id, "page": chunk.page or 1, "section": f"分块 {chunk.chunk_index + 1}", "text": chunk.text} for chunk in sorted(item.chunks, key=lambda value: value.chunk_index)]
    result["chunkCount"] = item.chunk_count
    result["relatedWiki"] = []
    if wiki and wiki.status=='done':
        result['relatedWiki']=[{'pageId':document_id,'title':item.title,'typeLabel':'文档编译初稿'}]
        result['wikiMarkdown']=wiki.markdown
    return result


@router.post('/{document_id}/wiki-compile',status_code=status.HTTP_202_ACCEPTED)
def start_wiki_compile(document_id:str,request:Request,db:Db,context:CurrentContext):
    document=db.scalar(select(Document).where(Document.id==document_id,Document.user_id==context[0].id))
    if not document:raise HTTPException(404,'资料不存在')
    if not Path(document.storage_path).is_file():
        raise HTTPException(409,'原始文件缺失，请重新上传这份资料后再编译Wiki。')
    supplement=db.get(WikiSupplementJob,document_id)
    if supplement and supplement.status in ACTIVE_SUPPLEMENT_STATUSES:
        raise HTTPException(409,'该资料正在后台补充Wiki，请稍候')
    try:require_runtime_model('text',request.app.state.settings.model_config_path)
    except RuntimeError:raise HTTPException(422,'请先配置并启用文本模型，再编译Wiki') from None
    job=db.get(DocumentWikiCompilation,document_id)
    if job and job.status in (*ACTIVE_WIKI_STATUSES,'done'):
        raise HTTPException(409,'该资料正在编译或已编译完成')
    if not job:
        job=DocumentWikiCompilation(document_id=document_id,user_id=context[0].id,status='queued')
        db.add(job)
    else:
        updated=db.execute(update(DocumentWikiCompilation).where(DocumentWikiCompilation.document_id==document_id,DocumentWikiCompilation.status=='failed').values(status='queued',error_message='',completed_batches=0,total_batches=0))
        if updated.rowcount!=1:
            db.rollback();raise HTTPException(409,'该资料正在编译或已编译完成')
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'该资料正在编译，请稍候') from None
    try:request.app.state.wiki_executor.submit(compile_document,request.app.state.session_factory,request.app.state.settings,document_id,request.app.state.graph_executor)
    except RuntimeError:
        db.execute(update(DocumentWikiCompilation).where(DocumentWikiCompilation.document_id==document_id).values(status='failed',error_message='后台任务暂不可用，请重试'));db.commit()
        raise HTTPException(503,'后台任务暂不可用，请重试') from None
    db.refresh(job)
    return document_out(document,job,supplement)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, request: Request, db: Db, context: CurrentContext):
    item = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == context[0].id))
    if not item:
        raise HTTPException(404, "资料不存在")
    if item.status in ACTIVE_DOCUMENT_STATUSES:
        raise HTTPException(409, "资料正在向量化，完成后再删除")
    wiki = db.get(DocumentWikiCompilation, document_id)
    supplement = db.get(WikiSupplementJob, document_id)
    if supplement and supplement.status in ACTIVE_SUPPLEMENT_STATUSES:
        raise HTTPException(409, "资料正在补充Wiki，完成后再删除")
    if wiki and wiki.status in ACTIVE_WIKI_STATUSES:
        raise HTTPException(409, "资料正在编译Wiki，完成后再删除")
    remove_document_vectors(request.app.state.settings.data_dir, item.id)
    Path(item.storage_path).unlink(missing_ok=True)
    if wiki:
        artifact = business_directory(request.app.state.settings, 'wiki', context[0].id, 'compiled') / (item.id + '.md')
        artifact.unlink(missing_ok=True)
        db.delete(wiki)
    if supplement:
        db.delete(supplement)
    db.delete(item)
    db.commit()
    remove_document_from_graph(request.app.state.settings, request.app.state.session_factory, context[0].id, document_id)
