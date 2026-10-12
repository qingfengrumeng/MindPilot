"""DeepSeek Files API adapter for image uploads."""

from pathlib import Path

import httpx

from app.core.model_runtime import RuntimeModel


class DeepSeekFileError(Exception):
    pass


ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_BYTES = 64 * 1024 * 1024


def upload_image(config: RuntimeModel, filename: str, content_type: str, data: bytes) -> dict:
    if config.provider != "deepseek":
        raise DeepSeekFileError("当前文本模型不是 DeepSeek，无法使用 DeepSeek 文件接口")
    if content_type not in ALLOWED_TYPES:
        raise DeepSeekFileError("DeepSeek 文件接口仅支持 JPEG、PNG、GIF 和 WebP 图片")
    if not data or len(data) > MAX_BYTES:
        raise DeepSeekFileError("图片大小必须在 1 至 64 MiB 之间")
    base = config.base_url.rstrip("/")
    url = base if base.endswith("/files") else f"{base}/files"
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            data={"purpose": "user_data"},
            files={"file": (Path(filename).name or "image", data, content_type)},
            timeout=120,
            follow_redirects=False,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise DeepSeekFileError("无法连接 DeepSeek 文件服务") from exc
    if response.status_code in (401, 403):
        raise DeepSeekFileError("DeepSeek API Key 无效或没有文件上传权限")
    if response.status_code >= 400:
        raise DeepSeekFileError("DeepSeek 文件上传失败，请检查图片和模型配置")
    try:
        result = response.json()
        file_id = result["id"]
    except (ValueError, KeyError, TypeError) as exc:
        raise DeepSeekFileError("DeepSeek 文件服务返回的数据格式不正确") from exc
    return {"id": file_id, "name": result.get("filename", filename), "bytes": result.get("bytes", len(data)), "mimeType": content_type}
