"""Qwen Image 3.0 Pro through Alibaba Cloud's OpenAI-compatible Images API."""

import base64
import binascii
import re
from urllib.parse import urlsplit

import httpx

from app.core.model_runtime import RuntimeModel


class ImageGenerationError(Exception):
    pass


DATA_URL = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$", re.IGNORECASE)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def validate_references(references: list[str]) -> list[str]:
    if len(references) > 3:
        raise ImageGenerationError("最多只能上传 3 张参考图片")
    for reference in references:
        match = DATA_URL.fullmatch(reference)
        if not match:
            raise ImageGenerationError("参考图仅支持 PNG、JPEG 或 WEBP 格式")
        try:
            data = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError):
            raise ImageGenerationError("参考图片数据无效") from None
        if not data or len(data) > 10 * 1024 * 1024:
            raise ImageGenerationError("单张参考图片不能超过 10 MB")
    return references


def generate_image(config: RuntimeModel, prompt: str, size: str = "1024x1024", references: list[str] | None = None) -> dict:
    if config.provider != "dashscope" or config.model != "qwen-image-3.0-pro":
        raise ImageGenerationError("当前仅支持百炼 qwen-image-3.0-pro 图像模型")
    if not prompt.strip() or len(prompt) > 4000:
        raise ImageGenerationError("请输入 1 至 4000 字的图像描述")
    if size not in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
        raise ImageGenerationError("不支持的图像尺寸")
    references = validate_references(references or [])
    base = urlsplit(config.base_url)
    if base.scheme != "https" or not base.hostname or not base.path.rstrip("/").endswith("/compatible-mode/v1"):
        raise ImageGenerationError("图像模型地址必须是 HTTPS 的 OpenAI 兼容接口地址")

    try:
        with httpx.Client(timeout=180, follow_redirects=False, trust_env=False) as client:
            body = {
                "model": config.model,
                "prompt": prompt.strip(),
                "size": size,
                "n": 1,
                "prompt_extend": True,
            }
            if references:
                body["image"] = references[0] if len(references) == 1 else references
            response = client.post(
                config.base_url.rstrip("/") + "/images/generations",
                headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
                json=body,
            )
        if response.status_code in (401, 403):
            raise ImageGenerationError("百炼 API Key 无效，或无权调用图像模型")
        if response.status_code == 429:
            raise ImageGenerationError("图像生成请求过于频繁，请稍后重试")
        if not 200 <= response.status_code < 300:
            raise ImageGenerationError(f"图像生成失败（HTTP {response.status_code}）")
        body = response.json()
        url = body["data"][0]["url"]
        if not isinstance(url, str) or urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
            raise ImageGenerationError("百炼未返回有效图片地址")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return {
            "url": url,
            "model": config.model,
            "width": usage.get("output_width"),
            "height": usage.get("output_height"),
            "expiresInHours": 24,
        }
    except httpx.TimeoutException as exc:
        raise ImageGenerationError("图像生成超时，请稍后重试") from exc
    except httpx.HTTPError as exc:
        raise ImageGenerationError("无法连接百炼图像服务，请检查网络与业务空间地址") from exc
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ImageGenerationError("百炼返回的图像结果格式不正确") from exc


def download_image(url: str) -> bytes:
    """Fetch a provider result before its short-lived URL expires."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or not parts.hostname.endswith(".aliyuncs.com"):
        raise ImageGenerationError("百炼返回的图片地址不安全")
    chunks = []
    total = 0
    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise ImageGenerationError("图片已生成，但下载到本机失败，请稍后重试")
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > 20 * 1024 * 1024:
                        raise ImageGenerationError("生成图片超过本机保存大小限制")
                    chunks.append(chunk)
        content = b"".join(chunks)
        if not content.startswith(PNG_MAGIC):
            raise ImageGenerationError("百炼返回的图片不是有效的 PNG 文件")
        return content
    except httpx.HTTPError as exc:
        raise ImageGenerationError("图片已生成，但无法下载到本机") from exc
