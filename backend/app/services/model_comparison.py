"""Isolated, cancellable text-model trials; never create chats or change routes."""
import asyncio
import json
from time import perf_counter

import httpx


class ComparisonError(Exception):
    pass


def event(kind, **payload):
    return json.dumps({"type": kind, **payload}, ensure_ascii=False) + "\n"


def token_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


async def response_chunks(response):
    """Read complete SSE events, including multiline data and a final nonblank event."""
    data = []
    async for line in response.aiter_lines():
        if line == "":
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
            if sum(len(part) for part in data) > 1024 * 1024:
                raise ComparisonError("模型返回的数据过大，请减少输出长度")
    if data:
        yield "\n".join(data)


async def compare_text(config, *, prompt, system_prompt="", max_tokens=2048, temperature=None):
    started = perf_counter()
    first_token_ms = None
    output_chars = 0
    has_answer = False
    finished = False
    finish_reason = None
    usage = {}
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
    messages.append({"role": "user", "content": prompt})
    body = {"model": config.model, "messages": messages, "stream": True,
            "stream_options": {"include_usage": True}, "max_tokens": max_tokens}
    if temperature is not None:
        body["temperature"] = temperature

    try:
        async with asyncio.timeout(120):
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10),
                                         follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", config.base_url.rstrip("/") + "/chat/completions",
                                         headers={"Authorization": f"Bearer {config.api_key}",
                                                  "Content-Type": "application/json"}, json=body) as response:
                    if response.status_code in {401, 403}:
                        raise ComparisonError("API Key 无效或没有此模型的调用权限")
                    if response.status_code == 429:
                        raise ComparisonError("厂商请求限流，请稍后重试")
                    if response.status_code not in range(200, 300):
                        raise ComparisonError(f"模型请求失败（HTTP {response.status_code}），请检查模型名称和参数")
                    async for chunk in response_chunks(response):
                        if chunk.strip() == "[DONE]":
                            finished = True
                            break
                        try:
                            item = json.loads(chunk)
                            if not isinstance(item, dict):
                                raise ValueError()
                            if item.get("error"):
                                raise ComparisonError("厂商返回模型错误，请检查模型名称、权限和参数")
                            if isinstance(item.get("usage"), dict):
                                usage.update(item["usage"])
                            choices = item.get("choices") or []
                            if not isinstance(choices, list):
                                raise ValueError()
                            if not choices:
                                continue  # Usage-only final event.
                            reason = choices[0].get("finish_reason")
                            if isinstance(reason, str) and reason:
                                finished = True
                                finish_reason = reason
                            delta = choices[0].get("delta", {})
                            if not isinstance(delta, dict):
                                raise ValueError()
                            for field, kind in (("reasoning_content", "reasoning"), ("content", "delta")):
                                text = delta.get(field)
                                if text is None or text == "":
                                    continue
                                if not isinstance(text, str):
                                    raise ValueError()
                                output_chars += len(text)
                                if output_chars > 1024 * 1024:
                                    raise ComparisonError("模型输出过大，请减少输出长度")
                                if kind == "delta":
                                    if first_token_ms is None:
                                        first_token_ms = round((perf_counter() - started) * 1000, 1)
                                    has_answer = has_answer or bool(text.strip())
                                yield event(kind, text=text)
                        except (ValueError, TypeError, AttributeError, IndexError):
                            raise ComparisonError("厂商返回的流式数据格式不正确") from None
            if not has_answer:
                raise ComparisonError("模型没有返回有效回答，请检查模型是否支持文本对话")
            if not finished:
                raise ComparisonError("模型响应意外中断，已保留接收到的部分回答")
            elapsed = max(perf_counter() - started, 0.001)
            output_tokens = token_count(usage.get("completion_tokens"))
            yield event("done", latencyMs=round(elapsed * 1000, 1), firstTokenMs=first_token_ms,
                        finishReason=finish_reason,
                        tokens={"input": token_count(usage.get("prompt_tokens")), "output": output_tokens},
                        tokensPerSecond=round(output_tokens / elapsed, 2) if output_tokens is not None else None)
    except ComparisonError as exc:
        yield event("error", message=str(exc))
    except (TimeoutError, httpx.TimeoutException):
        yield event("error", message="模型响应超时，请稍后重试")
    except httpx.HTTPError:
        yield event("error", message="无法连接模型服务，请检查接口地址和网络")
    except Exception:
        # Do not expose vendor bodies, headers, URLs with secrets, or exception text.
        yield event("error", message="模型测试失败，请检查厂商配置后重试")
    # CancelledError is a BaseException: cancellation propagates and closes the upstream.
