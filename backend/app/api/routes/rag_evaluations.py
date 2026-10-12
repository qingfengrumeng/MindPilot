"""User-scoped, expiring RAG sandboxes; no production document/vector writes."""
import asyncio
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import shutil
from threading import Lock
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update

from app.api.deps import CurrentContext, Db
from app.api.routes.model_configs import require_owner
from app.core.security import utcnow
from app.core.state_home import checked_path
from app.core.storage_layout import business_directory
from app.db.models import EvaluationWorkspace
from app.services.document_ingestion import extract_document
from app.services.rag_evaluation import RunInput, evaluate, prepare_models
from app.services.rag_metrics import aggregate, retrieval_metrics
from app.services.rag_sample_dataset import sample_dataset

router = APIRouter(prefix="/model-evaluations/rag", tags=["model-evaluations"])
ACTIVE = set()
ACTIVE_LOCK = Lock()


def folder(settings, workspace_id):
    UUID(workspace_id)
    return business_directory(settings, "model_comparisons", "rag", workspace_id)


def remove_files(settings, workspace_id):
    root = business_directory(settings, "model_comparisons", "rag")
    target = checked_path(root / str(UUID(workspace_id))).resolve()
    if target.parent != root.resolve():
        raise ValueError("Unsafe evaluation path")
    if target.exists():
        shutil.rmtree(target)


def cleanup(settings, db):
    with ACTIVE_LOCK:
        active = set(ACTIVE)
    for item in db.scalars(select(EvaluationWorkspace).where(EvaluationWorkspace.expires_at <= utcnow())):
        if item.id not in active:
            remove_files(settings, item.id)
            db.delete(item)
    db.commit()
    # Account deletion cascades metadata; reclaim its now-orphaned test files too.
    known = set(db.scalars(select(EvaluationWorkspace.id))) | active
    root = business_directory(settings, "model_comparisons", "rag")
    for child in root.iterdir():
        try:
            value = str(UUID(child.name))
        except ValueError:
            continue
        if child.is_dir() and value not in known:
            remove_files(settings, value)


def owned(workspace_id, db, context):
    item = db.get(EvaluationWorkspace, workspace_id)
    if not item or item.user_id != context[0].id:
        raise HTTPException(404, "测试空间不存在")
    if item.expires_at.replace(tzinfo=None) <= utcnow().replace(tzinfo=None):
        raise HTTPException(410, "测试空间已过期，请新建测试空间")
    return item


def public(item):
    return {"id": item.id, "revision": item.revision, "expiresAt": item.expires_at.isoformat(), **item.data}


def require_idle(workspace_id):
    with ACTIVE_LOCK:
        if workspace_id in ACTIVE:
            raise HTTPException(409, "请先停止测试，再调整测试文档")


def save_dataset(db, item, revision, data):
    changed = db.execute(update(EvaluationWorkspace).where(EvaluationWorkspace.id == item.id,
        EvaluationWorkspace.revision == revision).values(data=data, revision=revision + 1, expires_at=utcnow() + timedelta(hours=24)))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "测试资料已变更，请重新载入后再保存")
    db.commit()
    db.refresh(item)
    return public(item)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documentId: str = Field(max_length=36)
    page: int = Field(ge=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=4000)
    answer: str = Field(default="", max_length=8000)
    split: str = Field(default="dev", pattern="^(dev|test)$")
    complete: bool = False
    judgments: dict[str, int] = Field(default_factory=dict, max_length=12)
    evidence: list[Evidence] = Field(default_factory=list, max_length=60)

    @field_validator("query")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("测试问题不能为空")
        return value.strip()


class GoldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    questions: list[Question] = Field(max_length=200)


def validate_gold(questions, documents):
    docs = {doc["id"]: {p["page"]: p["text"] for p in doc["pages"]} for doc in documents}
    if len({q.id for q in questions}) != len(questions):
        raise HTTPException(422, "问题 ID 不能重复")
    for q in questions:
        if any(doc not in docs or type(grade) is not int or not 0 <= grade <= 3 for doc, grade in q.judgments.items()):
            raise HTTPException(422, "相关性标注必须属于当前测试文档，等级应为 0—3")
        if q.complete and any(doc not in q.judgments for doc in docs):
            raise HTTPException(422, "声明标注完整前，请判断所有测试文档的相关性")
        for e in q.evidence:
            text = docs.get(e.documentId, {}).get(e.page)
            if text is None or not 0 <= e.start < e.end <= len(text):
                raise HTTPException(422, "黄金证据范围无效")


class PageInput(BaseModel):
    page: int = Field(ge=1, le=10000)
    text: str = Field(min_length=1, max_length=150000)


class DocumentInput(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    pages: list[PageInput] = Field(min_length=1, max_length=1000)


class DatasetInput(BaseModel):
    revision: int = Field(ge=1)
    schemaVersion: int = Field(default=1, ge=1, le=1)
    documents: list[DocumentInput] = Field(max_length=12)
    questions: list[Question] = Field(max_length=200)


@router.get('/samples/golden-dataset')
def golden_sample(response: Response, context: CurrentContext):
    response.headers['Cache-Control']='no-store'
    return sample_dataset()


class DocumentEdit(BaseModel):
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=160)
    pages: list[PageInput] = Field(min_length=1, max_length=1000)


@router.put('/{workspace_id}/documents/{document_id}')
def edit_document(workspace_id:str,document_id:str,payload:DocumentEdit,request:Request,context:CurrentContext,db:Db):
    item=owned(workspace_id,db,context)
    require_idle(workspace_id)
    data=deepcopy(item.data)
    document=next((d for d in data['documents'] if d['id']==document_id),None)
    if not document:
        raise HTTPException(404,'测试文档不存在')
    if not payload.name.strip():
        raise HTTPException(422,'文档名称不能为空')
    if len({p.page for p in payload.pages})!=len(payload.pages):
        raise HTTPException(422,'页码不能重复')
    if sum(len(p['text']) for d in data['documents'] if d['id']!=document_id for p in d['pages'])+sum(len(p.text) for p in payload.pages)>150000:
        raise HTTPException(422,'测试语料总计不超过15万字符')
    changed=document['pages']!=[p.model_dump() for p in payload.pages]
    previous_suffix=document['suffix']
    text='\n\n'.join(p.text for p in payload.pages)
    document.update(name=payload.name.strip(),pages=[p.model_dump() for p in payload.pages],suffix='.txt',bytes=len(text.encode('utf-8')))
    if changed:
        for question in data['questions']:
            question['evidence']=[e for e in question['evidence'] if e['documentId']!=document_id]
            question['complete']=False
    result=save_dataset(db,item,payload.revision,data)
    path=checked_path(folder(request.app.state.settings,workspace_id)/(str(UUID(document_id))+'.txt'))
    path.write_text(text,encoding='utf-8')
    if previous_suffix!='.txt':
        checked_path(folder(request.app.state.settings,workspace_id)/(str(UUID(document_id))+previous_suffix)).unlink(missing_ok=True)
    return result


@router.post("/{workspace_id}/import")
def import_dataset(workspace_id: str, payload: DatasetInput, request: Request, context: CurrentContext, db: Db):
    item = owned(workspace_id, db, context)
    require_idle(workspace_id)
    if sum(len(p.text) for d in payload.documents for p in d.pages) > 150000:
        raise HTTPException(422, "测试语料总计不超过 15 万字符")
    if len({d.id for d in payload.documents}) != len(payload.documents) or any(len({p.page for p in d.pages}) != len(d.pages) for d in payload.documents):
        raise HTTPException(422, "文档 ID 和页码不能重复")
    documents = [d.model_dump() for d in payload.documents]
    validate_gold(payload.questions, documents)
    mapping = {d.id: str(uuid4()) for d in payload.documents}
    rewritten = []
    for question in payload.questions:
        value = question.model_dump()
        value["judgments"] = {mapping[key]: grade for key, grade in value["judgments"].items()}
        for evidence in value["evidence"]:
            evidence["documentId"] = mapping[evidence["documentId"]]
        rewritten.append(value)
    paths = []
    try:
        for document in documents:
            document["id"] = mapping[document["id"]]
            text = "\n\n".join(p["text"] for p in document["pages"])
            path = checked_path(folder(request.app.state.settings, workspace_id) / (document["id"] + ".txt"))
            paths.append(path)
            path.write_text(text, encoding="utf-8")
            document.update(bytes=len(text.encode("utf-8")), suffix=".txt")
        old_docs = deepcopy(item.data["documents"])
        result = save_dataset(db, item, payload.revision, {"documents": documents, "questions": rewritten, "reports": []})
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    for doc in old_docs:
        checked_path(folder(request.app.state.settings, workspace_id) / (str(UUID(doc["id"])) + doc["suffix"])).unlink(missing_ok=True)
    return result


@router.post("")
def create_workspace(request: Request, context: CurrentContext, db: Db):
    cleanup(request.app.state.settings, db)
    existing = db.scalar(select(EvaluationWorkspace).where(EvaluationWorkspace.user_id == context[0].id))
    if existing:
        return public(existing)
    item = EvaluationWorkspace(user_id=context[0].id, expires_at=utcnow() + timedelta(hours=24),
        data={"documents": [], "questions": [], "reports": []})
    db.add(item)
    db.commit()
    folder(request.app.state.settings, item.id)
    return public(item)


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str, response: Response, context: CurrentContext, db: Db):
    response.headers["Cache-Control"] = "no-store"
    return public(owned(workspace_id, db, context))


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: str, request: Request, context: CurrentContext, db: Db):
    item = owned(workspace_id, db, context)
    with ACTIVE_LOCK:
        if workspace_id in ACTIVE:
            raise HTTPException(409, "请先停止测试，再清空测试空间")
    remove_files(request.app.state.settings, workspace_id)
    db.delete(item)
    db.commit()
    return {"deleted": True}


@router.post("/{workspace_id}/documents")
async def upload(workspace_id: str, request: Request, context: CurrentContext, db: Db, file: UploadFile = File(...)):
    item = owned(workspace_id, db, context)
    require_idle(workspace_id)
    revision, data = item.revision, deepcopy(item.data)
    if len(data["documents"]) >= 12:
        raise HTTPException(422, "最多上传 12 份测试文档")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise HTTPException(422, "测试文档支持 PDF、TXT、Markdown")
    content = await file.read(10 * 1024 * 1024 + 1)
    await file.close()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(422, "单份测试文档需要在 10 MB 以内且不能为空")
    doc_id = str(uuid4())
    path = checked_path(folder(request.app.state.settings, workspace_id) / (doc_id + suffix))
    path.write_bytes(content)
    try:
        pages, _ = await asyncio.to_thread(extract_document, path, "application/pdf" if suffix == ".pdf" else "text/plain")
        pages = [{"page": page, "text": text} for page, text in pages if text.strip()]
        if not pages or sum(len(p["text"]) for d in data["documents"] for p in d["pages"]) + sum(len(p["text"]) for p in pages) > 150000:
            raise HTTPException(422, "测试语料需非空，且总计不超过 15 万字符")
        data["documents"].append({"id": doc_id, "name": Path(file.filename or "测试文档").name[:160],
            "pages": pages, "bytes": len(content), "suffix": suffix})
        require_idle(workspace_id)
        return save_dataset(db, item, revision, data)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "无法读取测试文档，请检查文件内容；扫描 PDF 需先进行 OCR") from None


@router.delete("/{workspace_id}/documents/{document_id}")
def delete_document(workspace_id: str, document_id: str, request: Request, context: CurrentContext, db: Db):
    item = owned(workspace_id, db, context)
    require_idle(workspace_id)
    data = deepcopy(item.data)
    doc = next((d for d in data["documents"] if d["id"] == document_id), None)
    if not doc:
        raise HTTPException(404, "测试文档不存在")
    data["documents"] = [d for d in data["documents"] if d["id"] != document_id]
    for q in data["questions"]:
        q["judgments"].pop(document_id, None)
        q["evidence"] = [e for e in q["evidence"] if e["documentId"] != document_id]
        q["complete"] = False
    data["reports"] = []
    result = save_dataset(db, item, item.revision, data)
    checked_path(folder(request.app.state.settings, workspace_id) / (str(UUID(document_id)) + doc["suffix"])).unlink(missing_ok=True)
    return result


@router.put("/{workspace_id}/gold")
def save_gold(workspace_id: str, payload: GoldInput, context: CurrentContext, db: Db):
    item = owned(workspace_id, db, context)
    require_idle(workspace_id)
    validate_gold(payload.questions, item.data["documents"])
    data = deepcopy(item.data)
    data["questions"] = [q.model_dump() for q in payload.questions]
    return save_dataset(db, item, payload.revision, data)


@router.post("/{workspace_id}/run")
def run(workspace_id: str, payload: RunInput, request: Request, context: CurrentContext, db: Db):
    require_owner(db, context)
    item = owned(workspace_id, db, context)
    if payload.revision != item.revision:
        raise HTTPException(409, "测试数据版本已变化，请重新载入")
    dataset = deepcopy(item.data)
    if not dataset["documents"] or not any(payload.split == "all" or q["split"] == payload.split for q in dataset["questions"]):
        raise HTTPException(422, "请上传测试文档，并添加当前分组的黄金问答")
    runtimes = prepare_models(request.app.state.settings.model_config_path, payload)
    user_id = context[0].id
    with ACTIVE_LOCK:
        if workspace_id in ACTIVE:
            raise HTTPException(409, "当前测试空间正在运行")
        ACTIVE.add(workspace_id)
    factory = request.app.state.session_factory

    async def stream():
        try:
            async for event in evaluate(dataset, payload, runtimes):
                if event["type"] == "done":
                    for attempt in range(4):
                        with factory() as session:
                            current = session.get(EvaluationWorkspace, workspace_id)
                            if not current or current.user_id != user_id:
                                break
                            data = deepcopy(current.data)
                            data["reports"] = (data.get("reports", []) + [event["report"]])[-3:]
                            changed = session.execute(update(EvaluationWorkspace).where(
                                EvaluationWorkspace.id == workspace_id, EvaluationWorkspace.revision == current.revision)
                                .values(data=data, revision=current.revision + 1, expires_at=utcnow() + timedelta(hours=24)))
                            if changed.rowcount == 1:
                                session.commit()
                                break
                            session.rollback()
                    else:
                        raise RuntimeError("Concurrent workspace writes")
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except asyncio.CancelledError:
            raise
        except Exception:
            yield json.dumps({"type": "error", "message": "测试中断，已完成结果仍可在本次界面查看"}, ensure_ascii=False) + "\n"
        finally:
            with ACTIVE_LOCK:
                ACTIVE.discard(workspace_id)
    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/{workspace_id}/reports/{report_id}/rescore")
def rescore(workspace_id: str, report_id: str, context: CurrentContext, db: Db):
    item = owned(workspace_id, db, context)
    data = deepcopy(item.data)
    previous = next((r for r in data["reports"] if r["id"] == report_id), None)
    if not previous:
        raise HTTPException(404, "测试结果不存在")
    report = deepcopy(previous)
    report["id"] = str(uuid4())
    report["parentReportId"] = previous["id"]
    report["scoringRevision"] = item.revision
    questions = {q["id"]: q for q in data["questions"]}
    if report.get("documentIds") != [d["id"] for d in data["documents"]]:
        raise HTTPException(409, "测试语料已经变化，请重新运行检索后再评分")
    old_questions = {q["id"]: q for q in report["questions"]}
    for plan in report["plans"]:
        for result in plan["results"]:
            q = questions.get(result["questionId"])
            old = old_questions.get(result["questionId"])
            if not q or not old or q["query"] != old["query"]:
                result["metrics"] = {}
                result["error"] = "问题已删除或修改，需重新运行该问题"
                continue
            quality = {k: v for k, v in result.get("metrics", {}).items() if k in {"faithfulness", "answerConsistency", "referenceRecall", "groundedness", "potentialHallucinationRate", "semanticFaithfulness", "factualConsistency"}}
            if q.get("answer") != old.get("answer"):
                quality.pop("answerConsistency", None)
                quality.pop("referenceRecall", None)
                quality.pop('factualConsistency',None)
                result["qualityError"] = "参考答案已修改，参考一致性需重新调用评审模型"
            result["metrics"] = {**retrieval_metrics(result["chunks"], q, plan["settings"]["topK"]), **quality}
        plan["summary"] = aggregate(plan["results"])
    report["questions"] = [questions.get(q["id"], q) for q in previous["questions"]]
    data["reports"] = (data["reports"] + [report])[-3:]
    save_dataset(db, item, item.revision, data)
    return report
