import re
from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentContext
from app.core.model_runtime import require_runtime_model
from app.services.deepseek_files import DeepSeekFileError, upload_image
from PIL import Image

router = APIRouter(prefix="/files", tags=["files"])
IMAGE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


@router.post("/poster-assets", status_code=status.HTTP_201_CREATED)
async def upload_poster_asset(request: Request, context: CurrentContext,
                              file: UploadFile = File(...)):
    """Persist a user-owned poster image without involving the chat model file API."""
    if file.content_type not in IMAGE_EXTENSIONS:
        raise HTTPException(415, "海报只支持 JPEG、PNG、GIF 和 WebP 图片")
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "单张海报图片不能超过 20 MB")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "GIF", "WEBP"}:
                raise ValueError("图片内容格式不受支持")
            if image.width * image.height > 25_000_000:
                raise ValueError("图片尺寸过大")
            image.verify()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "图片文件无效或已损坏") from None
    preview_id = uuid4().hex
    folder = request.app.state.settings.data_dir / "chat_previews" / context[0].id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{preview_id}.{IMAGE_EXTENSIONS[file.content_type]}").write_bytes(data)
    return {"id": f"poster-local-{preview_id}", "previewId": preview_id,
            "name": file.filename or "海报图片"}


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_file(request: Request, context: CurrentContext, file: UploadFile = File(...)):
    if file.content_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        raise HTTPException(415, "仅支持 JPEG、PNG、GIF 和 WebP 图片")
    data = await file.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise HTTPException(413, "图片不能超过 64 MiB")
    try:
        config = require_runtime_model("text", request.app.state.settings.model_config_path)
        uploaded = upload_image(config, file.filename or "image", file.content_type, data)
        preview_id = uuid4().hex
        directory = request.app.state.settings.data_dir / "chat_previews" / context[0].id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{preview_id}.{IMAGE_EXTENSIONS[file.content_type]}").write_bytes(data)
        return {**uploaded, "previewId": preview_id}
    except (RuntimeError, DeepSeekFileError) as exc:
        raise HTTPException(502, str(exc)) from None


@router.get("/previews/{preview_id}")
def get_image_preview(preview_id: str, request: Request, context: CurrentContext):
    if not re.fullmatch(r"[0-9a-f]{32}", preview_id):
        raise HTTPException(404, "图片不存在")
    directory = request.app.state.settings.data_dir / "chat_previews" / context[0].id
    for mime_type, extension in IMAGE_EXTENSIONS.items():
        path = directory / f"{preview_id}.{extension}"
        if path.is_file():
            return FileResponse(path, media_type=mime_type, headers={"Cache-Control": "private, max-age=3600"})
    raise HTTPException(404, "图片不存在")
