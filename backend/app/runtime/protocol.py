"""Stable handoff protocol. Agents exchange IDs and small metadata, not payload files."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4
import json
import re

from pydantic import BaseModel, Field, field_validator


TaskStatus = Literal["queued", "running", "waiting", "completed", "failed", "cancelled"]


class TaskSpec(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    agent: str = "supervisor"
    goal: str = Field(min_length=1, max_length=12000)
    inputs: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)
    parent_task_id: str | None = None

    @field_validator("task_id", "parent_task_id")
    @classmethod
    def valid_task_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,35}", value):
            raise ValueError("Task id must be 1–36 letters, numbers, underscores or dashes")
        return value

    @field_validator("agent")
    @classmethod
    def valid_agent(cls, value: str) -> str:
        if value != "supervisor" and not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value):
            raise ValueError("Invalid agent id")
        return value

    @field_validator("inputs")
    @classmethod
    def bounded_inputs(cls, value: dict) -> dict:
        if len(json.dumps(value, ensure_ascii=False)) > 250_000:
            raise ValueError("Task inputs exceed 250 KB; pass an artifact ID instead")
        return value

    @field_validator("constraints")
    @classmethod
    def known_constraints(cls, value: dict) -> dict:
        if "must_cite_sources" in value and not isinstance(value["must_cite_sources"], bool):
            raise ValueError("must_cite_sources must be boolean")
        if "output_format" in value and not isinstance(value["output_format"], str):
            raise ValueError("output_format must be a string")
        return value


class TaskResult(BaseModel):
    status: Literal["completed", "waiting", "failed", "cancelled"]
    summary: str = ""
    artifact_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    outputs: dict = Field(default_factory=dict)
    error: str | None = None


class TaskSnapshot(BaseModel):
    task_id: str
    parent_task_id: str | None
    agent: str
    goal: str
    status: TaskStatus
    attempt: int
    result: TaskResult | None = None
    error: str | None = None


class TaskEvent(BaseModel):
    kind: str
    detail: dict = Field(default_factory=dict)
