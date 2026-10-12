from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, field_validator

from app.api.deps import CurrentContext
from app.core.model_runtime import require_runtime_model
from app.schemas.base import CamelModel
from app.services.embedding_generation import EmbeddingError, embed_texts


router = APIRouter(prefix="/embeddings", tags=["embeddings"])


class EmbeddingRequest(CamelModel):
    input: str | list[str] = Field(...)

    @field_validator("input")
    @classmethod
    def valid_input(cls, value: str | list[str]):
        texts = [value] if isinstance(value, str) else value
        if not 1 <= len(texts) <= 20 or any(not item.strip() or len(item) > 500_000 for item in texts):
            raise ValueError("请输入 1 至 20 条非空文本，每条最多 500000 字符")
        return value


@router.post("")
def create_embeddings(payload: EmbeddingRequest, request: Request, _context: CurrentContext):
    try:
        config = require_runtime_model("embedding", request.app.state.settings.model_config_path)
        texts = [payload.input] if isinstance(payload.input, str) else payload.input
        return embed_texts(config, texts)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None
    except EmbeddingError as exc:
        raise HTTPException(502, str(exc)) from None
