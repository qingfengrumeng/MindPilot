from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, field_validator

from app.api.deps import CurrentContext
from app.core.model_runtime import require_runtime_model
from app.schemas.base import CamelModel
from app.services.rerank_generation import RerankError, rerank_texts


router = APIRouter(prefix="/rerank", tags=["rerank"])


class RerankRequest(CamelModel):
    query: str = Field(min_length=1, max_length=100_000)
    documents: list[str] = Field(min_length=1, max_length=500)
    top_n: int | None = Field(default=None, ge=1, le=500)

    @field_validator("query", "documents")
    @classmethod
    def nonempty_text(cls, value):
        texts = [value] if isinstance(value, str) else value
        if any(not text.strip() or len(text) > 100_000 for text in texts):
            raise ValueError("查询文本和候选文档不能为空，单条最多 100000 字符")
        return value


@router.post("")
def rerank(payload: RerankRequest, request: Request, _context: CurrentContext):
    try:
        config = require_runtime_model("reranker", request.app.state.settings.model_config_path)
        return rerank_texts(config, payload.query, payload.documents, payload.top_n)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    except RerankError as exc:
        raise HTTPException(502, str(exc)) from None
