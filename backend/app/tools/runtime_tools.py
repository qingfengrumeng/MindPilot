"""Tool adapters exposed to plugins through validated runtime schemas."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.db.models import Document, WorkbenchEntry
from app.services.document_ingestion import search_documents
from app.skills import ai_drawing
from app.skills.drawing_engine import build_diagram
from dataclasses import asdict
from app.tools.current_datetime import current_datetime_answer
from app.tools.search_knowledge_base import hybrid_search
from app.tools.web_search import web_search_context
from app.runtime.tool_registry import ToolRegistry


class SearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=3000)
    top_k: int = Field(default=5, ge=1, le=12)
    source_ids: list[str] = Field(default_factory=list, max_length=30)


class DiagramRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    kind: str = Field(pattern="^(flowchart|mindmap)$")
    previous_xml: str | None = None
    plan: dict | None = None
    layout_mode: str | None = None
    editor_history: list[dict] = Field(default_factory=list, max_length=12)


class ArtifactRead(BaseModel):
    artifact_id: str
    max_chars: int = Field(default=16000, ge=100, le=2_000_000)


class MarkdownWrite(BaseModel):
    content: str = Field(min_length=1, max_length=500000)
    filename: str = Field(default="document.md", max_length=180)
    source_ids: list[str] = Field(default_factory=list)


class DateQuery(BaseModel):
    query: str = "现在几点"


class PosterRenderRequest(BaseModel):
    design: dict
    image_preview_ids: list[str] = Field(default_factory=list, max_length=8)
    image_names: list[str] = Field(default_factory=list, max_length=8)
    version: int = Field(default=1, ge=1, le=4)
    generated_artifact_id: str | None = None
    qr_preview_ids: list[str] = Field(default_factory=list)


class PosterImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class PosterAssetRequest(BaseModel):
    image_preview_ids: list[str] = Field(min_length=1, max_length=8)
    image_names: list[str] = Field(default_factory=list, max_length=8)


def _poster_assets(context, image_preview_ids: list[str], image_names: list[str],
                   qr_preview_ids: list[str] | None = None) -> list[dict]:
    import re

    assets = []
    folder = (context.settings.data_dir / "chat_previews" / context.user_id).resolve()
    for index, preview_id in enumerate(image_preview_ids):
        if not re.fullmatch(r"[0-9a-f]{32}", preview_id):
            raise ValueError("上传图片标识无效")
        path = next((folder / f"{preview_id}{ext}" for ext in (".png", ".jpg", ".gif", ".webp")
                     if (folder / f"{preview_id}{ext}").is_file()), None)
        if path is None or not path.resolve().is_relative_to(folder):
            raise ValueError("上传图片已失效，请重新上传")
        name = image_names[index] if index < len(image_names) else "用户图片"
        assets.append({"id": preview_id, "name": name[:80], "data": path.read_bytes(),
                       "qr": preview_id in (qr_preview_ids or []) or
                       bool(re.search(r"二维码|qr.?code|qrcode", name, re.I))})
    return assets


def _poster_prepare_assets(arguments: PosterAssetRequest, context):
    """Send bounded, real image pixels to the vision model through the Agent."""
    import base64
    from io import BytesIO
    from PIL import Image, ImageOps

    result = []
    for asset in _poster_assets(context, arguments.image_preview_ids, arguments.image_names):
        with Image.open(BytesIO(asset["data"])) as source:
            if source.width * source.height > 25_000_000:
                raise ValueError("海报素材尺寸过大")
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1024, 1024))
            output = BytesIO()
            if asset["qr"]:
                image.convert("RGB").save(output, format="PNG", optimize=True)
                mime = "image/png"
            else:
                if image.mode in {"RGBA", "LA"}:
                    background = Image.new("RGBA", image.size, "white")
                    background.alpha_composite(image.convert("RGBA"))
                    image = background
                image.convert("RGB").save(output, format="JPEG", quality=85, optimize=True)
                mime = "image/jpeg"
            result.append({"id": asset["id"], "name": asset["name"],
                           "width": source.width, "height": source.height,
                           "image_url": f"data:{mime};base64,{base64.b64encode(output.getvalue()).decode('ascii')}"})
    return {"assets": result}


def _poster_render(arguments: PosterRenderRequest, context):
    from app.plugins.poster_agent.render import render_html, export_browser, inspect_screenshot, screenshot_evidence

    assets = _poster_assets(context, arguments.image_preview_ids, arguments.image_names,
                            arguments.qr_preview_ids)
    generated_data = None
    if arguments.generated_artifact_id:
        generated_row, generated_data = context.artifacts.read(arguments.generated_artifact_id,
                                                               user_id=context.user_id)
        if generated_row.kind != "poster_generated_image" or generated_row.mime_type != "image/png":
            raise ValueError("生成的海报视觉素材无效")
    html = render_html(arguments.design, assets, generated_data)
    for preview_id in arguments.image_preview_ids:
        if f'data-asset-id="{preview_id}"' not in html:
            raise ValueError("用户上传的图片未完整进入海报")
    png, pdf = export_browser(html)
    issues = inspect_screenshot(png, arguments.design, assets)
    kwargs = {"user_id": context.user_id, "task_id": context.task_id,
              "source_ids": arguments.image_preview_ids, "version": arguments.version}
    html_id = context.artifacts.save_text(html, kind="poster_html", filename="poster.html",
                                          mime_type="text/html", **kwargs)
    png_id = context.artifacts.save(png, kind="poster_png", filename="poster.png",
                                    mime_type="image/png", **kwargs)
    pdf_id = context.artifacts.save(pdf, kind="poster_pdf", filename="poster.pdf",
                                    mime_type="application/pdf", **kwargs)
    return {"html_artifact_id": html_id, "png_artifact_id": png_id,
            "pdf_artifact_id": pdf_id, "issues": issues,
            "screenshot_evidence": screenshot_evidence(png), "asset_count": len(assets)}


def _poster_image(arguments: PosterImageRequest, context):
    from app.core.model_runtime import require_runtime_model
    from app.services.image_generation import download_image, generate_image

    config = require_runtime_model("image", context.settings.model_config_path)
    generated = generate_image(config, arguments.prompt, size="1024x1024")
    content = download_image(generated["url"])
    artifact_id = context.artifacts.save(content, user_id=context.user_id, task_id=context.task_id,
                                          kind="poster_generated_image", filename="poster-element.png",
                                          mime_type="image/png")
    return {"artifact_id": artifact_id, "model": generated["model"]}


def _rag(arguments: SearchQuery, context):
    hits = hybrid_search(arguments.query, context.settings, context.session_factory,
                         context.user_id, top_k=arguments.top_k, dense_search=search_documents,
                         document_ids=arguments.source_ids or None)
    document_ids = {hit.get("documentId") for hit in hits if hit.get("documentId")}
    with context.session_factory() as db:
        documents = {row.id: row for row in db.scalars(
            select(Document).where(Document.id.in_(document_ids), Document.user_id == context.user_id,
                                   Document.status == "ready")).all()}
    verified = []
    for hit in hits:
        document = documents.get(hit.get("documentId"))
        if document:
            verified.append({"documentId": document.id, "title": document.title,
                             "filename": document.filename, "page": hit.get("page"),
                             "text": str(hit.get("text") or "")[:6000]})
    # Database Wiki pages are knowledge sources too. Keep owner and optional
    # source scope checks independent from the filesystem-backed documents.
    phrase = arguments.query.strip()[:160]
    tokens = []
    for part in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", phrase):
        tokens.extend([part] if not '\u4e00' <= part[0] <= '\u9fff' else
                      [part[index:index + 2] for index in range(max(1, len(part) - 1))])
    tokens = list(dict.fromkeys(token for token in tokens if token))[:12]
    if tokens:
        matches = [column.ilike(f"%{token}%") for token in tokens
                   for column in (WorkbenchEntry.title, WorkbenchEntry.summary, WorkbenchEntry.body)]
        with context.session_factory() as db:
            wiki_query = select(WorkbenchEntry).where(
                WorkbenchEntry.user_id == context.user_id,
                WorkbenchEntry.kind == "wiki",
                or_(*matches),
            ).order_by(WorkbenchEntry.updated_at.desc()).limit(arguments.top_k * 5)
            pages = list(db.scalars(wiki_query))
            pages.sort(key=lambda page: sum(4 * page.title.lower().count(token.lower()) +
                                            (page.summary or '').lower().count(token.lower()) +
                                            (page.body or '').lower().count(token.lower())
                                            for token in tokens), reverse=True)
            for page in pages[:arguments.top_k]:
                source_id = f"wiki:{page.id}"
                if arguments.source_ids and source_id not in arguments.source_ids:
                    continue
                verified.append({"documentId": source_id, "title": page.title,
                                 "filename": "数据库 Wiki", "page": 1,
                                 "text": (page.summary + "\n" + page.body)[:6000],
                                 "sourceType": "wiki"})
    verified = verified[:arguments.top_k]
    context_text = "\n\n".join(f"[资料 {index}] {row['title']}\n{row['text']}"
                                  for index, row in enumerate(verified, 1))
    return {"context": context_text, "hits": verified,
            "source_ids": list(dict.fromkeys(row["documentId"] for row in verified))}


def _web(arguments: SearchQuery, context):
    result = web_search_context(arguments.query)
    return {"context": result.context, "sources": result.sources,
            "status": result.status, "error": result.error,
            "source_ids": [row["url"] for row in result.sources if row.get("url")]}


def _diagram(arguments: DiagramRequest, context):
    def model_call(config, messages):
        return context.model(messages, purpose="diagram_planning",
                             complete_fn=ai_drawing.complete_text, config=config)
    if arguments.previous_xml:
        return ai_drawing.edit_diagram(arguments.prompt, arguments.previous_xml,
                                       model_config_path=context.settings.model_config_path,
                                       complete_fn=model_call,
                                       history=arguments.editor_history)
    if arguments.plan is not None:
        diagram_type = ("architecture" if arguments.kind == "flowchart" and
                        arguments.layout_mode == "layers" else arguments.kind)
        return {**asdict(build_diagram(arguments.plan, diagram_type)),
                "model": "content + layout + draw.io renderer"}
    return ai_drawing.generate_diagram(arguments.prompt, arguments.kind,
                                       model_config_path=context.settings.model_config_path,
                                       complete_fn=model_call)


def _read(arguments: ArtifactRead, context):
    row, data = context.artifacts.read(arguments.artifact_id, user_id=context.user_id)
    if row.mime_type not in {"text/markdown", "text/plain", "application/xml", "image/svg+xml"}:
        raise ValueError("Artifact is not readable text")
    content = data.decode("utf-8")
    if row.kind in {"diagram", "editor_draft"} and len(content) > arguments.max_chars:
        raise ValueError("图表文件超过读取上限，不能截断 XML；请提高 max_chars")
    return {"artifact_id": row.id, "kind": row.kind, "content": content[:arguments.max_chars],
            "source_ids": row.source_ids_json}


def _write_markdown(arguments: MarkdownWrite, context):
    name = arguments.filename if arguments.filename.lower().endswith(".md") else arguments.filename + ".md"
    artifact_id = context.artifacts.save_text(arguments.content, user_id=context.user_id,
                                               task_id=context.task_id, kind="markdown",
                                               filename=name, mime_type="text/markdown",
                                               source_ids=arguments.source_ids)
    return {"artifact_id": artifact_id}


def _date(arguments: DateQuery, context):
    answer, detail = current_datetime_answer(arguments.query)
    return {"answer": answer, "detail": detail}


def make_tool_registry() -> ToolRegistry:

    tools = ToolRegistry()
    tools.register("rag_search", SearchQuery, _rag)
    tools.register("web_search", SearchQuery, _web)
    tools.register("diagram_render", DiagramRequest, _diagram)
    tools.register("read_artifact", ArtifactRead, _read)
    tools.register("write_markdown", MarkdownWrite, _write_markdown)
    tools.register("current_datetime", DateQuery, _date)
    tools.register("poster_render", PosterRenderRequest, _poster_render)
    tools.register("poster_asset_prepare", PosterAssetRequest, _poster_prepare_assets)
    tools.register("poster_image_generate", PosterImageRequest, _poster_image)
    return tools
