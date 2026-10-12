import json
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.base import CamelModel


class ConversationCreate(CamelModel):
    title: str = Field(default="新会话", min_length=1, max_length=160)
    task_id: str = Field(default="general", max_length=80)

    @field_validator("title")
    @classmethod
    def nonempty_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("会话标题不能为空")
        return value.strip()


class ConversationUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def nonempty_title(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("会话标题不能为空")
        return value.strip() if value is not None else None


class ConversationOut(CamelModel):
    id: str
    title: str
    task_id: str
    pinned: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    messages: int

    @classmethod
    def from_record(cls, conversation, count: int, last_message_at: datetime | None = None):
        return cls.model_validate({
            "id": conversation.id,
            "title": conversation.title,
            "taskId": conversation.task_id,
            "pinned": conversation.pinned,
            "createdAt": conversation.created_at,
            "updatedAt": conversation.updated_at,
            "lastMessageAt": last_message_at,
            "messages": count,
        })


class MessageCreate(CamelModel):
    role: Literal["user", "assistant", "system"] = "user"
    content: str = Field(min_length=1, max_length=100_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息不能为空")
        return value

    @field_validator("metadata")
    @classmethod
    def bounded_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 65536:
            raise ValueError("消息元数据过大")
        return value


class MessageOut(CamelModel):
    id: str
    role: str
    content: str
    created_at: datetime
    metadata: dict[str, Any]

    @classmethod
    def from_record(cls, message):
        return cls.model_validate({
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "createdAt": message.created_at,
            "metadata": message.metadata_json,
        })


class ChatSkill(CamelModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    system_prompt: str = Field(default="", max_length=8000)


class ChatTextAttachment(CamelModel):
    name: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=50000)
    mime_type: str = Field(default="text/plain", max_length=100)


class ChatSend(CamelModel):
    stream_id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9-]+$")
    content: str = Field(default="", max_length=20000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=16)
    attachment_names: list[str] = Field(default_factory=list, max_length=16)
    attachment_preview_ids: list[str] = Field(default_factory=list, max_length=16)
    text_attachments: list[ChatTextAttachment] = Field(default_factory=list, max_length=5)
    skill: ChatSkill | None = None
    deep_thinking: bool = False
    voice_mode: bool = False
    realtime_session_id: str | None = Field(default=None, max_length=80)
    regenerate_message_id: str | None = Field(default=None, max_length=80)

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_message_or_attachment(self):
        if not self.content and not self.attachment_ids and not self.text_attachments and not self.regenerate_message_id:
            raise ValueError("消息和附件不能同时为空")
        return self
