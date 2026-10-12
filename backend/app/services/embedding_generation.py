"""Compatible batched embeddings and Ark's single-vector multimodal protocol."""

import math

import httpx

from app.core.model_runtime import RuntimeModel


SUPPORTED_DIMENSIONS = {256, 512, 768, 1024, 1536, 2048, 2560}


class EmbeddingError(Exception):
    pass


def embed_texts(config: RuntimeModel, texts: list[str]) -> dict:
    if not config.dimensions or not 1 <= config.dimensions <= 65536 or (config.provider == "dashscope" and config.model == "qwen3.7-text-embedding" and config.dimensions not in SUPPORTED_DIMENSIONS):
        raise EmbeddingError("Embedding 向量维度配置无效")
    if not 1 <= len(texts) <= 20 or any(not text.strip() for text in texts):
        raise EmbeddingError("请输入 1 至 20 条非空文本")
    # Model Studio v3/v4 accepts at most ten rows, unlike qwen3.7's twenty.
    if config.provider=='dashscope' and config.model.startswith(('text-embedding-v3','text-embedding-v4')) and len(texts)>10:
        records,total_tokens=[],0
        for start in range(0,len(texts),10):
            batch=embed_texts(config,texts[start:start+10])
            records.extend({'index':start+row['index'],'embedding':row['embedding']} for row in batch['data'])
            total_tokens+=batch['usage'].get('totalTokens') or 0
        return {'model':config.model,'dimensions':config.dimensions,'data':records,'usage':{'totalTokens':total_tokens}}

    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            def request(suffix, payload):
                response = client.post(config.base_url.rstrip("/") + suffix,
                    headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}, json=payload)
                if response.status_code in (401, 403):
                    raise EmbeddingError("Embedding API Key 无效，或没有模型调用权限")
                if response.status_code == 429:
                    raise EmbeddingError("Embedding 请求过于频繁，请稍后重试")
                if response.status_code < 200 or response.status_code >= 300:
                    raise EmbeddingError(f"Embedding 请求失败（HTTP {response.status_code}）")
                return response.json()

            payload = {"model": config.model, "dimensions": config.dimensions, "encoding_format": "float"}
            if config.embedding_protocol == "multimodal":
                if config.provider != "volcengine":
                    raise EmbeddingError("当前厂商不支持多模态向量协议")
                # Ark combines all items in a request into ONE vector. Request each
                # document separately so chunks never share a combined embedding.
                records, total_tokens = [], 0
                for index, text in enumerate(texts):
                    item_payload = {**payload, "input": [{"type": "text", "text": text}]}
                    if config.instruction and config.model != "doubao-embedding-vision-250615":
                        item_payload["instructions"] = config.instruction
                    item = request("/embeddings/multimodal", item_payload)
                    records.append({"index": index, "embedding": item["data"]["embedding"]})
                    total_tokens += (item.get("usage") or {}).get("total_tokens", 0)
                body = {"data": records, "usage": {"total_tokens": total_tokens}}
            else:
                body = request("/embeddings", {**payload, "input": texts})
        records = body["data"]
        if not isinstance(records, list) or len(records) != len(texts):
            raise EmbeddingError("模型返回的向量数量与输入文本不一致")
        vectors = []
        seen = set()
        for record in records:
            index, embedding = record["index"], record["embedding"]
            if not isinstance(index, int) or index < 0 or index >= len(texts) or index in seen:
                raise EmbeddingError("模型返回的向量序号无效")
            if not isinstance(embedding, list) or len(embedding) != config.dimensions:
                raise EmbeddingError("模型返回的向量维度与配置不一致")
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in embedding):
                raise EmbeddingError("模型返回的向量包含无效数值")
            seen.add(index)
            vectors.append({"index": index, "embedding": embedding})
        vectors.sort(key=lambda item: item["index"])
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return {"model": config.model, "dimensions": config.dimensions, "data": vectors, "usage": {"totalTokens": usage.get("total_tokens", 0)}}
    except httpx.TimeoutException as exc:
        raise EmbeddingError("Embedding 响应超时，请稍后重试") from exc
    except httpx.HTTPError as exc:
        raise EmbeddingError("无法连接向量模型，请检查接口地址与网络") from exc
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise EmbeddingError("向量模型返回的数据格式不正确") from exc
