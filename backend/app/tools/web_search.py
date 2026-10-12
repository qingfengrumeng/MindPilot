"""Baidu search-only tool with explicit errors for the run monitor."""

from dataclasses import dataclass, field
import json
import re
from urllib.parse import urlparse

import httpx

from app.core.config import read_model_configuration


class BaiduSearchError(Exception):
    pass


@dataclass(frozen=True)
class WebSearchResult:
    context: str = ""
    error: str = ""
    sources: list[dict] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "error" if self.error else "ok" if self.context else "empty"


def _authorization(config_path=None) -> str:
    return read_model_configuration(config_path).integrations.baidu_search.authorization.get_secret_value()


def search(query: str, count: int = 8, freshness: str | None = None, *, config_path=None) -> dict:
    authorization = _authorization(config_path) if config_path is not None else _authorization()
    if not authorization or authorization == "CHANGE_ME":
        raise BaiduSearchError("百度搜索鉴权字段尚未配置")
    if not re.fullmatch(r"Bearer bce-v3\S+", authorization):
        raise BaiduSearchError("百度搜索鉴权字段格式错误，必须填写完整的 Bearer bce-v3…")
    query = str(query or "").strip()
    if not query:
        raise BaiduSearchError("搜索关键词不能为空")
    count = max(1, min(int(count or 8), 20))
    payload = {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": count}],
    }
    if freshness:
        payload["search_recency_filter"] = freshness
    try:
        response = httpx.post(
            "https://qianfan.baidubce.com/v2/ai_search/web_search",
            headers={"X-Appbuilder-Authorization": authorization, "Content-Type": "application/json"},
            json=payload, timeout=45, follow_redirects=False, trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise BaiduSearchError("无法连接百度搜索服务") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise BaiduSearchError("百度搜索返回的数据格式不正确") from exc
    if response.status_code in (401, 403):
        raise BaiduSearchError("百度搜索鉴权字段无效或没有调用权限")
    if isinstance(body, dict):
        error = body.get("error")
        code = body.get("code") or (error.get("code") if isinstance(error, dict) else None)
        message = body.get("message") or (error.get("message") if isinstance(error, dict) else None)
        if code or error:
            if str(code) == "invalid_model":
                raise BaiduSearchError("百度搜索请求的模型不可用；请使用纯搜索接口或检查模型权限")
            raise BaiduSearchError(f"百度搜索接口报错（{code or 'unknown'}）：{str(message or error)[:160]}")
    if response.status_code >= 400:
        raise BaiduSearchError("百度搜索请求失败，请检查搜索配置")
    if not isinstance(body, dict) or not isinstance(body.get("references"), list):
        raise BaiduSearchError("百度搜索返回的数据缺少网页结果列表")
    return {"query": query, "result": body}


def web_search_context(query: str) -> WebSearchResult:
    """Return results or a user-safe failure reason; never silently swallow an error."""
    try:
        result = search(query, count=8)
    except BaiduSearchError as exc:
        return WebSearchResult(error=str(exc))
    references = []
    sources = []
    for item in result["result"]["references"]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or len(url) > 2000:
            continue
        number = len(sources) + 1
        title = str(item.get("title") or parsed.netloc).strip()[:300]
        date = str(item.get("date") or "").strip()[:80]
        icon = str(item.get("icon") or "").strip()
        icon_url = urlparse(icon)
        if icon_url.scheme not in ("http", "https") or not icon_url.netloc or len(icon) > 2000:
            icon = ""
        sources.append({"sourceNumber": number, "title": title, "url": url,
                        "date": date, "icon": icon})
        references.append({"sourceNumber": number, "title": title, "url": url,
                           "date": date, "content": str(item.get("content") or "")[:2000]})
    if not references:
        return WebSearchResult()
    context = (
        "以下是联网检索到的网页片段，编号仅对本轮有效。若使用某条网页的信息，"
        "请紧贴对应事实句子或列表项末尾标注〔网页编号〕，例如〔网页1〕；"
        "多条来源可以连续标注。只引用确实支持该内容的网页，不能编造来源。"
        "不要在回答末尾另列来源清单，也不要输出裸网址；界面会根据编号显示可点击的来源标签。\n"
        + json.dumps(references, ensure_ascii=False)[:30000]
    )
    return WebSearchResult(context=context, sources=sources)
