"""Registered entrypoint for the poster domain."""

from pydantic import BaseModel, Field

from app.runtime.protocol import TaskResult, TaskSpec

from .domain import run_domain


class PosterInputs(BaseModel):
    query: str = Field(min_length=1, max_length=12000)
    image_preview_ids: list[str] = Field(default_factory=list, max_length=8)
    image_names: list[str] = Field(default_factory=list, max_length=8)
    _step_index: int | None = None


def run(spec: TaskSpec, context) -> TaskResult:
    return run_domain(spec, context)
