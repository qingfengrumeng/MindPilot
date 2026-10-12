"""Authenticated local image gallery with backend-only model credentials."""

import os

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import CurrentContext, Db
from app.core.model_runtime import require_runtime_model
from app.db.models import GeneratedImage, new_id
from app.schemas.base import CamelModel
from app.services.image_generation import ImageGenerationError, download_image, generate_image


router = APIRouter(prefix="/images", tags=["images"])


class ImageRequest(CamelModel):
    prompt: str = Field(min_length=1, max_length=4000)
    size: str = Field(default="1024x1024", pattern=r"^(auto|1024x1024|1024x1536|1536x1024)$")
    references: list[str] = Field(default_factory=list, max_length=3)


def _image_path(request: Request, item: GeneratedImage):
    return request.app.state.settings.data_dir / "generated_images" / item.user_id / f"{item.id}.png"


def _image_out(item: GeneratedImage):
    return {
        "id": item.id,
        "prompt": item.prompt,
        "size": item.size,
        "mode": item.mode,
        "width": item.width,
        "height": item.height,
        "createdAt": item.created_at.isoformat() if item.created_at else None,
    }


def _owned_image(db: Db, user_id: str, image_id: str):
    item = db.scalar(select(GeneratedImage).where(GeneratedImage.id == image_id, GeneratedImage.user_id == user_id))
    if not item:
        raise HTTPException(404, "图片不存在")
    return item


@router.get("")
def list_images(db: Db, context: CurrentContext):
    items = db.scalars(
        select(GeneratedImage).where(GeneratedImage.user_id == context[0].id)
        .order_by(GeneratedImage.created_at.desc()).limit(100)
    ).all()
    return {"items": [_image_out(item) for item in items]}


@router.post("/generate")
def generate(payload: ImageRequest, request: Request, db: Db, context: CurrentContext):
    try:
        config = require_runtime_model("image", request.app.state.settings.model_config_path)
        result = generate_image(config, payload.prompt, payload.size, payload.references)
        content = download_image(result["url"])
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    except ImageGenerationError as exc:
        raise HTTPException(502, str(exc)) from None

    item = GeneratedImage(
        id=new_id(), user_id=context[0].id, prompt=payload.prompt.strip(), size=payload.size,
        mode="edit" if payload.references else "generate",
        width=result["width"], height=result["height"],
    )
    path = _image_path(request, item)
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(content)
        os.replace(temporary, path)
        db.add(item)
        db.commit()
        return _image_out(item)
    except (OSError, SQLAlchemyError):
        db.rollback()
        for candidate in (temporary, path):
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(500, "保存生成图片失败") from None


@router.get("/{image_id}/file")
def image_file(image_id: str, request: Request, db: Db, context: CurrentContext):
    item = _owned_image(db, context[0].id, image_id)
    path = _image_path(request, item)
    if not path.is_file():
        raise HTTPException(404, "图片文件不存在")
    return FileResponse(path, media_type="image/png", filename=f"mindpilot-{item.id}.png", headers={"Cache-Control": "private, no-store"})


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(image_id: str, request: Request, db: Db, context: CurrentContext):
    item = _owned_image(db, context[0].id, image_id)
    path = _image_path(request, item)
    db.delete(item)
    db.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # The record is gone; a failed local unlink can be cleaned up later.
        pass
