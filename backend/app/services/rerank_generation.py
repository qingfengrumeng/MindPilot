"""Qwen text reranking through Alibaba Cloud's native DashScope API."""

import math

import httpx

from app.core.model_runtime import RuntimeModel


class RerankError(Exception):
    pass


def rerank_texts(config: RuntimeModel, query: str, documents: list[str], top_n: int | None = None) -> dict:
    if config.provider != "dashscope":
        raise RerankError("当前 Reranker 配置不支持该模型或厂商")
    if not query.strip() or not 1 <= len(documents) <= 500 or any(not doc.strip() for doc in documents):
        raise RerankError("请输入查询文本和 1 至 500 条非空候选文档")
    if top_n is not None and not 1 <= top_n <= 500:
        raise RerankError("topN 必须在 1 至 500 之间")

    body = {
        "model": config.model,
        "input": {"query": query, "documents": documents},
    }
    if top_n is not None:
        body["parameters"] = {"top_n": top_n}
    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                config.base_url.rstrip("/") + "/services/rerank/text-rerank/text-rerank",
                headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
                json=body,
            )
        if response.status_code in (401, 403):
            raise RerankError("百炼 API Key 无效，或无权调用当前业务空间")
        if response.status_code == 429:
            raise RerankError("百炼请求过于频繁，请稍后重试")
        if response.status_code < 200 or response.status_code >= 300:
            raise RerankError(f"百炼 Reranker 请求失败（HTTP {response.status_code}）")
        payload = response.json()
        records = payload["output"]["results"]
        if not isinstance(records, list) or len(records) > len(documents):
            raise RerankError("百炼返回的排序结果数量无效")
        seen = set()
        results = []
        for item in records:
            index = item["index"]
            score = item["relevance_score"]
            if not isinstance(index, int) or index < 0 or index >= len(documents) or index in seen:
                raise RerankError("百炼返回的文档序号无效")
            if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or not 0 <= score <= 1:
                raise RerankError("百炼返回的相关性分数无效")
            seen.add(index)
            results.append({"index": index, "relevanceScore": score, "document": documents[index]})
        results.sort(key=lambda item: item["relevanceScore"], reverse=True)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return {"model": config.model, "results": results, "usage": {"totalTokens": usage.get("total_tokens", 0)}}
    except httpx.TimeoutException as exc:
        raise RerankError("百炼 Reranker 响应超时，请稍后重试") from exc
    except httpx.HTTPError as exc:
        raise RerankError("无法连接百炼服务，请检查业务空间地址与网络") from exc
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RerankError("百炼返回的数据格式不正确") from exc
