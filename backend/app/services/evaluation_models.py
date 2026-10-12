"""Resolve trial models through config.py; never accept credentials from a test."""
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.model_preferences import read_preferences
from app.core.model_runtime import RuntimeModel


class TrialModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providerId: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    dimensions: int | None = Field(default=None, ge=1, le=65536)
    embeddingProtocol: Literal["compatible", "multimodal"] | None = None

    @field_validator("model")
    @classmethod
    def trim(cls, value):
        if not value.strip():
            raise ValueError("模型名称不能为空")
        return value.strip()


def resolve_trial(path, selection: TrialModel, category: str) -> RuntimeModel:
    provider = read_preferences(path)["providers"].get(selection.providerId, {})
    config = provider.get("configs", {}).get(category, {})
    runtime = RuntimeModel(category, provider.get("runtimeProvider", selection.providerId),
        config.get("baseUrl", ""), selection.model, provider.get("apiKey", ""),
        selection.dimensions or config.get("dimensions"), config.get("voice"),
        config.get("instruction"), selection.embeddingProtocol or config.get("embeddingProtocol", "compatible"))
    if not runtime.configured:
        raise HTTPException(422, f"请先保存该厂商的 {category} 接口地址与 API Key")
    if category == "embedding" and not runtime.dimensions:
        raise HTTPException(422, "请配置向量维度")
    if category == "embedding" and runtime.embedding_protocol == "multimodal" and runtime.provider != "volcengine":
        raise HTTPException(422, "方舟多模态向量协议仅适用于火山引擎")
    return runtime
