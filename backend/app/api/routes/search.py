from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import CurrentContext
from app.tools.web_search import BaiduSearchError, search

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    count: int = Field(default=8, ge=1, le=20)
    freshness: str | None = Field(default=None, max_length=64)


@router.post("")
def web_search(payload: SearchRequest, request: Request, context: CurrentContext):
    try:
        return search(payload.query, payload.count, payload.freshness)
    except BaiduSearchError as exc:
        raise HTTPException(502, str(exc)) from None
