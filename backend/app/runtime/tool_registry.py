"""Validated tool calls with per-agent allowlists."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import json

from pydantic import BaseModel
from app.services.session_journal import protected_data


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, tuple[type[BaseModel], Callable]] = {}

    def register(self, name: str, schema: type[BaseModel], handler: Callable) -> None:
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = (schema, handler)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def validate_arguments(self, name: str, arguments: dict, *, allowed: set[str]) -> dict:
        """Validate a proposed tool call without executing it or exposing the handler."""
        if name not in allowed:
            raise PermissionError(f"Agent cannot call tool: {name}")
        if name not in self._tools:
            raise LookupError(f"Tool is not installed: {name}")
        return self._tools[name][0].model_validate(arguments).model_dump(exclude_none=True)

    def call(self, name: str, arguments: dict, *, allowed: set[str], context,
             count_step: bool = True, step_id: str | None = None):
        if name not in allowed:
            raise PermissionError(f"Agent cannot call tool: {name}")
        if name not in self._tools:
            raise LookupError(f"Tool is not installed: {name}")
        schema, handler = self._tools[name]
        validated = schema.model_validate(arguments)
        if count_step:
            step_id = context.start_step("tool", name)
        safe_arguments = {}
        for key, value in validated.model_dump().items():
            if any(secret in key.lower() for secret in ("token", "password", "api_key", "secret")):
                safe_arguments[key] = "[redacted]"
            elif isinstance(value, str) and len(value) > 240:
                safe_arguments[key] = {"characters": len(value)}
            elif isinstance(value, list) and len(value) > 12:
                safe_arguments[key] = {"items": len(value)}
            else:
                safe_arguments[key] = value
        context.event("tool_call", {"tool": name, "step_id": step_id,
                                    "arguments": safe_arguments,
                                    "input": protected_data(validated.model_dump(mode="json"))})
        try:
            result = handler(validated, context)
        except Exception as exc:
            context.event("tool_result", {"tool": name, "step_id": step_id,
                                          "status": "failed", "error": str(exc)[:500]})
            if count_step:
                context.end_step(step_id, status="failed", error=str(exc)[:500])
            raise
        try:
            context.check_active()
            encoded = json.dumps(result, ensure_ascii=False, default=str)
            summary = {"type": type(result).__name__, "characters": len(encoded),
                       "sha256": sha256(encoded.encode("utf-8")).hexdigest(),
                       "keys": sorted(result)[:30] if isinstance(result, dict) else []}
            status = "ok"
            if isinstance(result, dict):
                summary["artifact_ids"] = [result[key] for key in ("artifact_id", "diagram_artifact_id")
                                           if isinstance(result.get(key), str)]
                if isinstance(result.get("source_ids"), list):
                    summary["source_ids"] = result["source_ids"][:50]
                if result.get("status") in {"failed", "error"}:
                    status = "failed"
                    summary["upstream_status"] = result["status"]
                    summary["upstream_error"] = str(result.get("error") or "")[:500]
            context.event("tool_result", {"tool": name, "step_id": step_id,
                                          "status": status, "result": summary, "output": json.loads(encoded)})
        except BaseException as exc:
            if count_step:
                context.end_step(step_id, status="failed", error=str(exc)[:500])
            raise
        if count_step:
            context.end_step(step_id, status="completed")
        return result
