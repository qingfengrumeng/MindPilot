"""OpenAI-compatible text completion using backend-only credentials."""

import time
import json

import httpx

from app.core.model_runtime import RuntimeModel


class TextGenerationError(Exception):
    pass


def stream_text(config: RuntimeModel, messages: list[dict]):
    """Yield visible answer chunks from an OpenAI-compatible SSE response."""
    url = config.base_url.rstrip("/") + "/chat/completions"
    usage = {}
    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            with client.stream("POST", url, headers={
                "Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json",
            }, json={"model": config.model, "messages": messages, "stream": True,
                     "stream_options": {"include_usage": True}}) as response:
                if response.status_code in (401, 403):
                    raise TextGenerationError("文本模型 API Key 无效或没有调用权限")
                if response.status_code == 429:
                    raise TextGenerationError("文本模型请求过于频繁，请稍后重试")
                if response.status_code >= 400:
                    raise TextGenerationError(f"文本模型请求失败（HTTP {response.status_code}）")
                for line in response.iter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    try:
                        body = json.loads(line[6:])
                        if isinstance(body.get("usage"), dict):
                            usage = body["usage"]
                        choices = body.get("choices") or []
                        delta = choices[0].get("delta", {}).get("content") if choices else None
                    except (ValueError, TypeError, IndexError, AttributeError) as exc:
                        raise TextGenerationError("文本模型返回的流式数据格式不正确") from exc
                    if isinstance(delta, str) and delta:
                        yield delta
        return {"model": config.model, "tokens": {
            "input": usage.get("prompt_tokens", 0), "output": usage.get("completion_tokens", 0),
        }}
    except httpx.TimeoutException as exc:
        raise TextGenerationError("文本模型响应超时，请稍后重试") from exc
    except httpx.HTTPError as exc:
        raise TextGenerationError("无法连接文本模型服务，请检查网络与接口地址") from exc


def complete_text(config: RuntimeModel, messages: list[dict]) -> tuple[str, dict]:
    url = config.base_url.rstrip("/") + "/chat/completions"
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
                json={"model": config.model, "messages": messages, "stream": False},
            )
        if response.status_code in (401, 403):
            raise TextGenerationError("DeepSeek API Key 无效或没有调用权限")
        if response.status_code == 429:
            raise TextGenerationError("DeepSeek 请求过于频繁，请稍后重试")
        if response.status_code >= 400 or response.status_code < 200:
            raise TextGenerationError(f"DeepSeek 请求失败（HTTP {response.status_code}）")
        body = response.json()
        answer = body["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise TextGenerationError("DeepSeek 未返回有效文本")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return answer.strip(), {
            "model": config.model,
            "latencyMs": round((time.perf_counter() - started) * 1000),
            "tokens": {
                "input": usage.get("prompt_tokens", 0),
                "output": usage.get("completion_tokens", 0),
            },
        }
    except httpx.TimeoutException as exc:
        raise TextGenerationError("DeepSeek 响应超时，请稍后重试") from exc
    except httpx.HTTPError as exc:
        raise TextGenerationError("无法连接 DeepSeek 服务，请检查网络与接口地址") from exc
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise TextGenerationError("DeepSeek 返回的数据格式不正确") from exc
