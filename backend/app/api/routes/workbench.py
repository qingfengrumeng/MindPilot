"""User-scoped local knowledge workbench for Wiki and source records."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, or_, select

from app.api.deps import CurrentContext, Db
from app.db.models import AgentTask, Document, WorkbenchEntry, new_id
from app.schemas.base import CamelModel
from app.agents.hot_agent import HotAgent, HotAgentError, normalized_title
from app.core.model_runtime import require_runtime_model
from app.services.text_generation import TextGenerationError
from app.tools.web_search import BaiduSearchError, _authorization


router = APIRouter(prefix="/workbench", tags=["workbench"])
KINDS = {"wiki", "hot"}
STATUSES = {"draft", "active", "archived"}
_hot_runs = set()
_hot_lock = threading.Lock()


class HotPreferences(CamelModel):
    direction: str = Field(default="", max_length=1000)
    max_items: int | None = Field(default=30, ge=1, le=100)

    @model_validator(mode="before")
    @classmethod
    def migrate_preferences(cls, values):
        if not isinstance(values, dict): return values
        values = dict(values)
        if "direction" not in values:
            values["direction"] = "；".join([*values.get("topics", []), str(values.get("keywords") or "")]).strip("； ")
        values["direction"] = str(values.get("direction") or "").strip()
        if values.get("maxItems", values.get("max_items")) == "":
            values["maxItems"] = None
        return values


@router.get("/hot-preferences")
def get_hot_preferences(db: Db, context: CurrentContext):
    row = db.scalar(select(WorkbenchEntry).where(WorkbenchEntry.user_id == context[0].id,
                                                WorkbenchEntry.kind == "hot-preferences"))
    return HotPreferences.model_validate(row.data_json if row else {}).model_dump(by_alias=True)


@router.put("/hot-preferences")
def save_hot_preferences(payload: HotPreferences, db: Db, context: CurrentContext):
    # A hidden business record keeps user preferences out of agent state/config.
    row = db.scalar(select(WorkbenchEntry).where(WorkbenchEntry.user_id == context[0].id,
                                                WorkbenchEntry.kind == "hot-preferences"))
    if row is None:
        row = WorkbenchEntry(id=new_id(), user_id=context[0].id, kind="hot-preferences",
                             title="每日热点偏好", summary="", body="", status="active",
                             tags_json=[], links_json=[], data_json={})
        db.add(row)
    row.data_json = payload.model_dump(by_alias=True)
    db.commit()
    return row.data_json


@router.post("/hot-sync/stream")
async def sync_hot_agent(request: Request, db: Db, context: CurrentContext, background: bool = False):
    user_id = context[0].id
    config_path = request.app.state.settings.model_config_path
    try:
        config = require_runtime_model("text", config_path)
        if _authorization(config_path) in {"", "CHANGE_ME"}:
            raise RuntimeError("联网搜索工具尚未配置，请在功能配置中填写搜索凭证")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    preferences = HotPreferences.model_validate(get_hot_preferences(db, context))
    existing = db.scalars(select(WorkbenchEntry).where(WorkbenchEntry.user_id == user_id,
                          WorkbenchEntry.kind == "hot").order_by(WorkbenchEntry.created_at)).all()
    with _hot_lock:
        if user_id in _hot_runs:
            raise HTTPException(409, "当前账户的热点同步正在执行")
        _hot_runs.add(user_id)
    cancelled = threading.Event()
    factory = request.app.state.session_factory

    def workflow():
        try:
            for event in HotAgent(config, config_path).run(preferences, existing, cancelled):
                if cancelled.is_set(): return
                if event["type"] != "result":
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                    continue
                saved = []
                with factory() as session:
                    current = session.scalars(select(WorkbenchEntry).where(WorkbenchEntry.user_id == user_id,
                                                  WorkbenchEntry.kind == "hot")).all()
                    keys = {normalized_title(row.title) for row in current}
                    from app.core.security import utcnow
                    for article in event["articles"]:
                        if cancelled.is_set(): return
                        if normalized_title(article["title"]) in keys: continue
                        sources = article["sources"]
                        data = {"source": "hot-agent", "sources": sources, "sourceUrl": sources[0]["url"],
                                "hasFullContent": True, "contentKind": "source-grounded-digest",
                                "publishedAt": article["publishedAt"], "fetchedAt": utcnow().isoformat(),
                                "eventKey": article["eventKey"],
                                "articleType": article.get("articleType", "event"),
                                "evidence": [{"sourceIndex": next((index for index, source in enumerate(sources)
                                    if source["url"] == entry["sourceUrl"]), -1), "quote": entry["quote"]}
                                    for entry in article["evidence"]]}
                        # Reuse public write validation to bound stored metadata.
                        payload = EntryWrite(kind="hot", title=article["title"], summary=article["summary"],
                                             body=article["body"], status="active", data=data)
                        row = WorkbenchEntry(id=new_id(), user_id=user_id, kind="hot", title=payload.title,
                            summary=payload.summary, body=payload.body, status="active", tags_json=[], links_json=[], data_json=data)
                        session.add(row)
                        saved.append(row)
                        keys.add(normalized_title(row.title))
                    if cancelled.is_set(): return
                    session.commit()
                    items = [_out(row) for row in saved]
                yield json.dumps({"type": "done", "items": items, "imported": len(items),
                    "requested": event["requested"], "searched": event["searched"], "warnings": event["warnings"]}, ensure_ascii=False) + "\n"
        except (HotAgentError, TextGenerationError, BaiduSearchError) as exc:
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"
        except Exception:
            yield json.dumps({"type": "error", "message": "热点整理或保存失败，本次未保存，请重试"}, ensure_ascii=False) + "\n"

    if background:
        job = {"id": new_id(), "status": "queued", "stage": "planning", "detail": "正在等待热点获取",
               "startedAt": datetime.now(timezone.utc).isoformat()}
        with _hot_lock:
            request.app.state.hot_jobs[user_id] = job

        def run_background():
            try:
                with _hot_lock: job.update(status="running", detail="正在规划热点搜索")
                for line in workflow():
                    event = json.loads(line)
                    with _hot_lock:
                        if event["type"] == "progress":
                            job.update({key: value for key, value in event.items() if key != "type"})
                        elif event["type"] == "done":
                            job.update(status="completed", detail="热点获取完成", imported=event["imported"],
                                       requested=event["requested"], warnings=event["warnings"])
                        elif event["type"] == "error":
                            job.update(status="failed", detail=event["message"])
            except Exception:
                with _hot_lock: job.update(status="failed", detail="热点获取失败，请重试")
            finally:
                with _hot_lock: _hot_runs.discard(user_id)

        try:
            request.app.state.hot_executor.submit(run_background)
        except RuntimeError:
            with _hot_lock:
                _hot_runs.discard(user_id)
                job.update(status="failed", detail="后台服务不可用，请重试")
            raise HTTPException(503, "后台服务不可用，请重试") from None
        with _hot_lock: return dict(job)

    async def output():
        generator = workflow()
        try:
            async for line in iterate_in_threadpool(generator):
                yield line
        finally:
            cancelled.set()
            try: generator.close()
            except ValueError: pass
            with _hot_lock:
                _hot_runs.discard(user_id)
    return StreamingResponse(output(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/hot-sync", status_code=status.HTTP_202_ACCEPTED)
async def start_hot_job(request: Request, db: Db, context: CurrentContext):
    return await sync_hot_agent(request, db, context, background=True)


@router.get("/hot-sync")
def get_hot_job(request: Request, context: CurrentContext):
    with _hot_lock:
        return dict(request.app.state.hot_jobs.get(context[0].id, {"status": "idle"}))


@router.post("/items/{entry_id}/viewed")
def mark_hot_viewed(entry_id: str, db: Db, context: CurrentContext):
    row = _owned(db, context[0].id, entry_id)
    if row.kind != "hot":
        raise HTTPException(422, "只支持热点查看状态")
    if not row.data_json.get("viewedAt"):
        from app.core.security import utcnow
        row.data_json = {**row.data_json, "viewedAt": utcnow().isoformat()}
        db.commit()
        db.refresh(row)
    return _out(row)


class EntryWrite(CamelModel):
    kind: str
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    body: str = Field(default="", max_length=100_000)
    status: str = "draft"
    tags: list[str] = Field(default_factory=list, max_length=20)
    links: list[str] = Field(default_factory=list, max_length=60)
    data: dict = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def nonempty_title(cls, value):
        if value is None or not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()

    @field_validator("summary", "body")
    @classmethod
    def text_not_null(cls, value):
        if value is None:
            raise ValueError("内容不能为 null")
        return value

    @field_validator("kind")
    @classmethod
    def known_kind(cls, value):
        if value not in KINDS:
            raise ValueError("不支持的工作台分类")
        return value

    @field_validator("status")
    @classmethod
    def known_status(cls, value):
        if value not in STATUSES:
            raise ValueError("不支持的状态")
        return value

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values):
        if values is None or any(not isinstance(value, str) or not value.strip() or len(value) > 40 for value in values):
            raise ValueError("标签长度需在 1 到 40 字之间")
        return list(dict.fromkeys(value.strip() for value in values))

    @field_validator("links")
    @classmethod
    def valid_links(cls, values):
        if values is None:
            raise ValueError("关联条目不能为空")
        return list(dict.fromkeys(values))

    @field_validator("data")
    @classmethod
    def bounded_data(cls, value):
        if value is None:
            raise ValueError("附加信息不能为空")
        if len(json.dumps(value, ensure_ascii=False)) > 20_000:
            raise ValueError("附加信息过长")
        url = value.get("sourceUrl")
        if url:
            parsed = urlparse(str(url))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(str(url)) > 2000:
                raise ValueError("sourceUrl 必须是 HTTP(S) 地址")
        return value


class EntryPatch(EntryWrite):
    kind: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    body: str | None = Field(default=None, max_length=100_000)
    status: str | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    links: list[str] | None = Field(default=None, max_length=60)
    data: dict | None = None


def _stamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def _out(row: WorkbenchEntry) -> dict:
    return {"id": row.id, "kind": row.kind, "title": row.title,
            "summary": row.summary, "body": row.body, "status": row.status,
            "tags": row.tags_json, "links": row.links_json, "data": row.data_json,
            "createdAt": _stamp(row.created_at), "updatedAt": _stamp(row.updated_at)}


def _owned(db: Db, user_id: str, entry_id: str) -> WorkbenchEntry:
    row = db.scalar(select(WorkbenchEntry).where(WorkbenchEntry.id == entry_id,
                                                  WorkbenchEntry.user_id == user_id,
                                                  WorkbenchEntry.kind.in_(KINDS)))
    if row is None:
        raise HTTPException(404, "工作台条目不存在")
    return row


def _validate_links(db: Db, user_id: str, links: list[str], self_id: str | None = None):
    for link in links:
        if not isinstance(link, str) or len(link) > 80:
            raise HTTPException(422, "关联条目 ID 无效")
        if link == self_id:
            raise HTTPException(422, "不能关联自身")
        if link.startswith("doc:"):
            owned = db.scalar(select(Document.id).where(Document.id == link[4:], Document.user_id == user_id))
        else:
            owned = db.scalar(select(WorkbenchEntry.id).where(WorkbenchEntry.id == link,
                                                               WorkbenchEntry.user_id == user_id,
                                                               WorkbenchEntry.kind.in_(KINDS)))
        if not owned:
            raise HTTPException(422, "关联条目不存在或不属于当前用户")


@router.get("/items")
def list_items(db: Db, context: CurrentContext, kind: str = "all", q: str = "", limit: int = 100, offset: int = 0):
    if kind != "all" and kind not in KINDS:
        raise HTTPException(422, "不支持的工作台分类")
    if not 1 <= limit <= 500 or len(q) > 200 or offset < 0:
        raise HTTPException(422, "查询参数超出范围")
    query = select(WorkbenchEntry).where(WorkbenchEntry.user_id == context[0].id,
                                           WorkbenchEntry.kind.in_(KINDS))
    if kind != "all":
        query = query.where(WorkbenchEntry.kind == kind)
    if q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(or_(WorkbenchEntry.title.ilike(needle),
                                WorkbenchEntry.summary.ilike(needle),
                                WorkbenchEntry.body.ilike(needle)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    order = func.coalesce(func.datetime(func.json_extract(WorkbenchEntry.data_json, '$.publishedAt')), func.datetime(WorkbenchEntry.created_at)) if kind == "hot" else WorkbenchEntry.updated_at
    rows = db.scalars(query.order_by(order.desc(), WorkbenchEntry.id).offset(offset).limit(limit)).all()
    return {"items": [_out(row) for row in rows], "total": total}


@router.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(payload: EntryWrite, db: Db, context: CurrentContext):
    _validate_links(db, context[0].id, payload.links)
    row = WorkbenchEntry(id=new_id(), user_id=context[0].id, kind=payload.kind,
                         title=payload.title.strip(), summary=payload.summary,
                         body=payload.body, status=payload.status, tags_json=payload.tags,
                         links_json=payload.links, data_json=payload.data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


class BatchDelete(CamelModel):
    ids: list[str] = Field(min_length=1, max_length=500)


@router.post("/items/batch-delete")
def batch_delete_items(payload: BatchDelete, db: Db, context: CurrentContext):
    ids = set(payload.ids)
    rows = db.scalars(select(WorkbenchEntry).where(WorkbenchEntry.id.in_(ids),
        WorkbenchEntry.user_id == context[0].id, WorkbenchEntry.kind.in_(KINDS))).all()
    if len(rows) != len(ids):
        raise HTTPException(404, "部分条目不存在或不属于当前用户，本次未删除")
    for linked in db.scalars(select(WorkbenchEntry).where(WorkbenchEntry.user_id == context[0].id,
                                                         WorkbenchEntry.kind == "wiki")).all():
        if ids.intersection(linked.links_json):
            linked.links_json = [link for link in linked.links_json if link not in ids]
    for row in rows: db.delete(row)
    db.commit()
    return {"deletedIds": sorted(ids), "deleted": len(ids)}


@router.get("/items/{entry_id}")
def get_item(entry_id: str, db: Db, context: CurrentContext):
    return _out(_owned(db, context[0].id, entry_id))


@router.patch("/items/{entry_id}")
def update_item(entry_id: str, payload: EntryPatch, db: Db, context: CurrentContext):
    row = _owned(db, context[0].id, entry_id)
    changes = payload.model_dump(exclude_unset=True)
    if "kind" in changes and changes["kind"] != row.kind:
        raise HTTPException(422, "条目类型不能更改")
    if "links" in changes:
        _validate_links(db, context[0].id, changes["links"], row.id)
    for name, value in changes.items():
        if name in {"kind", "id"}:
            continue
        setattr(row, {"tags": "tags_json", "links": "links_json", "data": "data_json"}.get(name, name), value)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/items/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(entry_id: str, db: Db, context: CurrentContext):
    row = _owned(db, context[0].id, entry_id)
    for linked in db.scalars(select(WorkbenchEntry).where(WorkbenchEntry.user_id == context[0].id,
                                                            WorkbenchEntry.kind == "wiki")).all():
        if entry_id in linked.links_json:
            linked.links_json = [link for link in linked.links_json if link != entry_id]
    db.delete(row)
    db.commit()


@router.get("/link-candidates")
def link_candidates(db: Db, context: CurrentContext):
    user_id = context[0].id
    entries = db.scalars(select(WorkbenchEntry).where(WorkbenchEntry.user_id == user_id,
                                                      WorkbenchEntry.kind == "wiki")
                         .order_by(WorkbenchEntry.updated_at.desc()).limit(500)).all()
    docs = db.scalars(select(Document).where(Document.user_id == user_id)
                      .order_by(Document.created_at.desc()).limit(500)).all()
    nodes = [{"id": row.id, "title": row.title, "kind": "wiki"} for row in entries]
    nodes += [{"id": f"doc:{row.id}", "title": row.title, "kind": "document"} for row in docs]
    return {"nodes": nodes}


@router.get("/system")
def system_status(db: Db, context: CurrentContext):
    user_id = context[0].id
    doc_counts = dict(db.execute(select(Document.status, func.count(Document.id))
                                 .where(Document.user_id == user_id).group_by(Document.status)).all())
    task_counts = dict(db.execute(select(AgentTask.status, func.count(AgentTask.id))
                                  .where(AgentTask.user_id == user_id).group_by(AgentTask.status)).all())
    entries = db.scalar(select(func.count(WorkbenchEntry.id)).where(
        WorkbenchEntry.user_id == user_id, WorkbenchEntry.kind.in_(KINDS))) or 0
    return {"storage": "database", "documents": doc_counts,
            "tasks": task_counts, "entries": entries}
