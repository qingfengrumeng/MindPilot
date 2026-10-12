"""Registered entrypoint for the drawing domain subgraph."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.runtime.protocol import TaskResult, TaskSpec

from .domain import run_domain


class DiagramInputs(BaseModel):
    query: str | None = Field(default=None, max_length=12000)
    kind: Literal["flowchart", "mindmap"] = "flowchart"
    artifact_ids: list[str] = Field(default_factory=list, max_length=10)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    previous_diagram_artifact_id: str | None = None
    previous_xml: str | None = Field(default=None, max_length=2_000_000)
    editor_history: list[dict] = Field(default_factory=list, max_length=12)
    base_version: int = Field(default=0, ge=0)


def run(spec: TaskSpec, context) -> TaskResult:
    return run_domain(spec, context)
