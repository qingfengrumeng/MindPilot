"""A replaceable model seam with request/settlement records for every runtime call."""

from __future__ import annotations

import json
from time import perf_counter
from uuid import uuid4

from app.core.model_runtime import require_runtime_model
from app.services.text_generation import complete_text


class ModelGateway:
    def __init__(self, complete_fn=complete_text):
        self.complete_fn = complete_fn

    def complete(self, context, messages: list[dict], *, purpose: str,
                 complete_fn=None, step_id: str | None = None, config=None) -> tuple[str, dict]:
        context.check_active()
        config = config or require_runtime_model("text", context.settings.model_config_path)
        request_id = str(uuid4())
        # Keep the audit trail useful without storing uploaded image bytes a
        # second time inside the model-request artifact.
        def audit_value(value):
            if isinstance(value, str) and value.startswith("data:image/"):
                return {"inline_image": True, "encoded_characters": len(value)}
            if isinstance(value, dict):
                return {key: audit_value(item) for key, item in value.items()}
            if isinstance(value, list):
                return [audit_value(item) for item in value]
            return value

        request = {"model": config.model, "provider": config.provider,
                   "messages": audit_value(messages), "purpose": purpose}
        request_artifact_id = context.artifacts.save_text(
            json.dumps(request, ensure_ascii=False), user_id=context.user_id,
            task_id=context.task_id, kind="model_request",
            filename=f"model-request-{request_id}.json", mime_type="application/json")
        context.event("model_request", {"request_id": request_id, "step_id": step_id,
                                        "model": config.model, "purpose": purpose,
                                        "request_artifact_id": request_artifact_id})
        started = perf_counter()
        try:
            answer, metadata = (complete_fn or self.complete_fn)(config, messages)
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("Model returned an empty response")
            context.check_active()
            response_artifact_id = context.artifacts.save_text(
                answer, user_id=context.user_id, task_id=context.task_id,
                kind="model_response", filename=f"model-response-{request_id}.txt",
                mime_type="text/plain")
            context.event("model_response", {"request_id": request_id, "step_id": step_id,
                                             "response_artifact_id": response_artifact_id,
                                             "latency_ms": max(1, round((perf_counter() - started) * 1000)),
                                             "tokens": (metadata or {}).get("tokens", {})})
            return answer, metadata or {}
        except BaseException as exc:
            context.event("model_attempt", {"request_id": request_id, "step_id": step_id,
                                            "status": "failed", "error": str(exc)[:500],
                                            "latency_ms": max(1, round((perf_counter() - started) * 1000)),
                                            "error_type": type(exc).__name__,
                                            "cause_type": type(exc.__cause__).__name__
                                            if exc.__cause__ else None})
            raise
