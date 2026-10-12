import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.model_preferences import write_preferences
from app.core.model_runtime import RuntimeModel
from app.db.models import Conversation, Message
from app.main import create_app
from app.services import model_comparison as comparison
from test_model_configs import login, settings_for


def saved_models(path):
    write_preferences(path, {
        "providers": {"deepseek": {"name": "DeepSeek", "runtimeProvider": "deepseek",
            "apiKey": "private-comparison-key", "configs": {
                "text": {"baseUrl": "https://models.example/v1", "model": "saved-model"}}}},
        "active": {"text": None},
    })


def mock_client(monkeypatch, handler):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(comparison.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs))


def events(response):
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_comparison_uses_saved_credentials_and_draft_model_without_saving_chat(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    saved_models(settings.model_config_path)
    original = settings.model_config_path.read_bytes()
    requests = []

    def handler(request):
        assert request.url == "https://models.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer private-comparison-key"
        body = json.loads(request.content)
        requests.append(body)
        data = [
            {"choices": [{"delta": {"reasoning_content": "Consider the evidence."}}]},
            {"choices": [{"delta": {"content": "A useful "}}]},
            {"choices": [{"delta": {"content": "answer."}}]},
            {"choices": [], "usage": {"prompt_tokens": 23, "completion_tokens": 7}},
        ]
        text = "".join("data: " + json.dumps(item) + "\n\n" for item in data) + "data: [DONE]\n\n"
        return httpx.Response(200, content=text, headers={"Content-Type": "text/event-stream"})

    mock_client(monkeypatch, handler)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        payload = {"providerId": "deepseek", "model": "trial-model", "prompt": "Same question",
                   "systemPrompt": "Use the same instructions", "maxTokens": 512, "temperature": 0.3}
        response = client.post("/api/v1/model-configs/compare", headers=headers, json=payload)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-type"].startswith("application/x-ndjson")
        result = events(response)
        assert [item["type"] for item in result] == ["reasoning", "delta", "delta", "done"]
        assert "".join(item.get("text", "") for item in result if item["type"] == "delta") == "A useful answer."
        assert result[-1]["tokens"] == {"input": 23, "output": 7}
        assert result[-1]["latencyMs"] >= result[-1]["firstTokenMs"] >= 0
        assert result[-1]["tokensPerSecond"] > 0
        assert requests[0]["model"] == "trial-model"
        assert requests[0]["messages"] == [{"role": "system", "content": payload["systemPrompt"]},
                                           {"role": "user", "content": payload["prompt"]}]
        assert requests[0]["max_tokens"] == 512 and requests[0]["temperature"] == 0.3
        assert "private-comparison-key" not in response.text
        # A second model under the same provider receives exactly the same inputs.
        payload["model"] = "another-trial-model"
        assert client.post("/api/v1/model-configs/compare", headers=headers, json=payload).status_code == 200
        assert requests[0]["messages"] == requests[1]["messages"]
        with client.app.state.session_factory() as db:
            assert db.scalar(select(func.count()).select_from(Conversation)) == 0
            assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert settings.model_config_path.read_bytes() == original


def test_comparison_permissions_missing_config_and_input_validation(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    saved_models(settings.model_config_path)
    calls = []
    mock_client(monkeypatch, lambda request: calls.append(request))
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        payload = {"providerId": "deepseek", "model": "trial-model", "prompt": "test"}
        assert client.post("/api/v1/model-configs/compare", json=payload).status_code == 401
        client.post("/api/v1/auth/register", json={"username": "guest", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "guest", "password": "strong-password-123"}).json()["accessToken"]
        assert client.post("/api/v1/model-configs/compare", headers={"Authorization": "Bearer " + token}, json=payload).status_code == 403
        for overrides in ({"prompt": "   "}, {"model": " "}, {"providerId": "unknown"},
                          {"maxTokens": 0}, {"temperature": 3}, {"prompt": "x" * 32001}):
            response = client.post("/api/v1/model-configs/compare", headers=headers, json={**payload, **overrides})
            assert response.status_code == 422
        assert client.put("/api/v1/model-configs/deepseek", headers=headers,
                          json={"name": "DeepSeek", "clearApiKey": True}).status_code == 200
        assert client.post("/api/v1/model-configs/compare", headers=headers, json=payload).status_code == 422
        assert calls == []


@pytest.mark.parametrize("status,body", [
    (401, "private-comparison-key"), (429, "vendor internal details"), (500, "private-comparison-key"),
    (200, "data: broken-json\n\n"),
    (200, 'data: {"error":{"message":"private-comparison-key"}}\n\n'),
    (200, 'data: {"choices":[{"delta":{"content":[]}}]}\n\n'),
    (200, 'data: {"choices":[]}\n\ndata: [DONE]\n\n'),
    (200, 'data: {"choices":[{"delta":{"content":"incomplete answer"}}]}\n\n'),
])
def test_vendor_failures_are_sanitized_and_do_not_report_success(status, body, monkeypatch):
    mock_client(monkeypatch, lambda request: httpx.Response(status, content=body))

    async def run():
        return [json.loads(line) async for line in comparison.compare_text(
            RuntimeModel("text", "openai", "https://example.com/v1", "model", "private-comparison-key"),
            prompt="question")]

    result = asyncio.run(run())
    assert result[-1]["type"] == "error" and not any(item["type"] == "done" for item in result)
    assert "private-comparison-key" not in json.dumps(result)


def test_missing_usage_stays_unknown_and_default_temperature_is_omitted(monkeypatch):
    def handler(request):
        assert "temperature" not in json.loads(request.content)
        # No space after data:, a comment, multiline data and no final blank line.
        return httpx.Response(200, content=': ping\n\ndata:{"choices":\ndata:[{"delta":{"content":"answer"}}]}\n\ndata:[DONE]')
    mock_client(monkeypatch, handler)

    async def run():
        return [json.loads(line) async for line in comparison.compare_text(
            RuntimeModel("text", "openai", "https://example.com", "model", "key"), prompt="question")]

    result = asyncio.run(run())
    assert result[-1]["type"] == "done"
    assert result[-1]["tokens"] == {"input": None, "output": None}
    assert result[-1]["tokensPerSecond"] is None


def test_cancellation_closes_upstream_stream_without_error_event(monkeypatch):
    async def run():
        entered = asyncio.Event()
        closed = []

        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                entered.set()
                await asyncio.Event().wait()

            async def aclose(self):
                closed.append(True)

        mock_client(monkeypatch, lambda request: httpx.Response(200, stream=SlowStream()))
        collected = []

        async def consume():
            async for line in comparison.compare_text(
                    RuntimeModel("text", "openai", "https://example.com", "model", "key"), prompt="question"):
                collected.append(json.loads(line))

        task = asyncio.create_task(consume())
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == [True]
        assert [item["type"] for item in collected] == ["delta"]

    asyncio.run(run())


def test_parallel_models_complete_independently_with_one_vendor_failure(monkeypatch):
    def handler(request):
        model = json.loads(request.content)["model"]
        if model == "failure":
            return httpx.Response(500, content="private-comparison-key")
        return httpx.Response(200, content='data: {"choices":[{"delta":{"content":"answer"},"finish_reason":"stop"}]}\n\n')
    mock_client(monkeypatch, handler)

    async def trial(model):
        return [json.loads(line) async for line in comparison.compare_text(
            RuntimeModel("text", "openai", "https://example.com", model, "private-comparison-key"), prompt="same")]

    async def run():
        return await asyncio.gather(trial("failure"), trial("success"))

    failed, succeeded = asyncio.run(run())
    assert failed[-1]["type"] == "error" and succeeded[-1]["type"] == "done"
    assert succeeded[-1]["finishReason"] == "stop"
    assert "private-comparison-key" not in json.dumps([failed, succeeded])
