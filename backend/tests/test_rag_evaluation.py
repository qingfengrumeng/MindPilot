import asyncio
from copy import deepcopy
from datetime import timedelta
import json
import math
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.model_preferences import write_preferences
from app.core.security import utcnow
from app.db.models import Conversation, Document, EvaluationWorkspace, Message
from app.main import create_app
from app.services import embedding_generation, model_comparison, rag_evaluation
from app.services.rag_evaluation import RunInput, chunks_for, evaluate, prepare_models
from app.services.rag_metrics import retrieval_metrics
from app.services.evaluation_models import TrialModel, resolve_trial
from test_model_configs import login, settings_for

PREFIX = "/api/v1/model-evaluations/rag"


def configure(path, key="secret-evaluation-key"):
    write_preferences(path, {"providers": {"custom-eval": {"name": "Test vendor", "runtimeProvider": "openai", "apiKey": key,
        "configs": {"text": {"baseUrl": "https://eval.invalid/v1", "model": "configured-text"},
                    "embedding": {"baseUrl": "https://eval.invalid/v1", "model": "configured-embedding", "dimensions": 2},
                    "reranker": {"baseUrl": "https://eval.invalid/v1", "model": "configured-rerank"}}}}, "active": {}})


def selection(model):
    return {"providerId": "custom-eval", "model": model}


def setup_dataset(client, headers):
    workspace = client.post(PREFIX, headers=headers).json()
    for name, text in (("cats.txt", "Cats are mammals. They sleep."), ("birds.txt", "Birds have wings.")):
        response = client.post(f'{PREFIX}/{workspace["id"]}/documents', headers=headers,
            files={"file": (name, text.encode(), "text/plain")})
        assert response.status_code == 200, response.text
        workspace = response.json()
    cat, bird = workspace["documents"]
    question = {"id": "q1", "query": "What are cats?", "answer": "Cats are mammals.", "split": "dev", "complete": False,
        "judgments": {cat["id"]: 3}, "evidence": [{"documentId": cat["id"], "page": 1, "start": 0, "end": 17}]}
    workspace = client.put(f'{PREFIX}/{workspace["id"]}/gold', headers=headers,
        json={"revision": workspace["revision"], "questions": [question]}).json()
    return workspace


def payload(workspace, quality=False, rerank=False):
    return {"revision": workspace["revision"], "plans": [{"id": "p1", "name": "Trial", "embedding": selection("trial-embedding"),
        "chunkSize": 100, "overlap": 0, "topK": 2, "candidateK": 2, "reranker": selection("trial-rerank") if rerank else None}],
        "generator": selection("trial-text") if quality else None, "judge": selection("trial-judge") if quality else None}


def mock_models(monkeypatch):
    calls = []
    def handler(request):
        assert request.headers["authorization"] == "Bearer secret-evaluation-key"
        body = json.loads(request.content); calls.append((request.url.path, deepcopy(body)))
        if request.url.path.endswith("/embeddings"):
            vectors = [[1., 0.] if "cats" in text.lower() else [0., 1.] for text in body["input"]]
            return httpx.Response(200, json={"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})
        if request.url.path.endswith("/rerank"):
            return httpx.Response(200, json={"results": [{"index": 1, "relevance_score": .9}, {"index": 0, "relevance_score": .3}]})
        if body["model"] == "trial-judge":
            answer = json.dumps({"claims": [{"text": "Cats are mammals.", "supported": True, "sources": [0], "referenceSupported": True}],
                "referenceClaims": [{"text": "Cats are mammals.", "covered": True}]})
        else:
            answer = "Cats are mammals. [0]"
        output = [ {"choices": [{"delta": {"content": answer}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8}} ]
        return httpx.Response(200, content="".join('data: ' + json.dumps(part) + '\n\n' for part in output) + 'data: [DONE]\n\n', headers={"Content-Type": "text/event-stream"})
    sync, asynchronous = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(embedding_generation.httpx, "Client", lambda **kwargs: sync(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(model_comparison.httpx, "AsyncClient", lambda **kwargs: asynchronous(transport=httpx.MockTransport(handler), **kwargs))
    return calls


def test_metrics_known_values_deduplicate_documents_and_merge_span_overlap():
    question = {"judgments": {"a": 3, "b": 1}, "complete": False,
        "evidence": [{"documentId": "a", "page": 1, "start": 0, "end": 10}]}
    chunks = [{"documentId": "unknown", "page": 1, "start": 0, "end": 4},
        {"documentId": "a", "page": 1, "start": 0, "end": 7}, {"documentId": "a", "page": 1, "start": 5, "end": 10}]
    result = retrieval_metrics(chunks, question, 3)
    assert result["precision"] == pytest.approx(1 / 3)
    assert result["recall"] == .5
    assert result["mrr"] == .5
    assert result["ndcg"] == pytest.approx((7 / math.log2(3)) / (7 + 1 / math.log2(3)))
    assert result["judgedCoverage"] == .5 and result["provisional"]
    assert result["evidenceCoverage"] == 1
    assert result["retrievedDocuments"] == 2
    assert retrieval_metrics(chunks, {"judgments": {}}, 3)["recall"] is None


def test_chunk_offsets_and_evidence_survive_different_chunk_sizes():
    documents = [{"id": "d", "name": "source", "pages": [{"page": 2, "text": "abc" * 100}]}]
    for size in (100, 200):
        chunks = chunks_for(documents, size, 20)
        assert all(c["text"] == documents[0]["pages"][0]["text"][c["start"]:c["end"]] for c in chunks)
        gold = {"judgments": {"d": 3}, "complete": True, "evidence": [{"documentId": "d", "page": 2, "start": 0, "end": 300}]}
        assert retrieval_metrics(chunks, gold, 5)["evidenceCoverage"] == 1


def test_same_vendor_embedding_trials_can_override_protocol_without_changing_configuration(tmp_path):
    path = tmp_path / "models.json"
    write_preferences(path, {"providers": {"volcengine": {"name": "Doubao", "runtimeProvider": "volcengine",
        "apiKey": "private-vector-key", "configs": {"embedding": {"baseUrl": "https://vector.invalid/api/v3",
            "model": "saved-vision", "dimensions": 1024, "embeddingProtocol": "multimodal"}}}}, "active": {}})
    original = path.read_bytes()
    runtime = resolve_trial(path, TrialModel(providerId="volcengine", model="trial-text", dimensions=2048, embeddingProtocol="compatible"), "embedding")
    assert runtime.model == "trial-text" and runtime.dimensions == 2048 and runtime.embedding_protocol == "compatible"
    assert runtime.api_key == "private-vector-key"
    assert path.read_bytes() == original


def test_actual_adapter_pipeline_isolated_and_quality_rescore(tmp_path, monkeypatch):
    settings = settings_for(tmp_path); configure(settings.model_config_path)
    original = settings.model_config_path.read_bytes()
    calls = mock_models(monkeypatch)
    application = create_app(settings)
    with TestClient(application) as client:
        headers = login(client); workspace = setup_dataset(client, headers)
        response = client.post(f'{PREFIX}/{workspace["id"]}/run', headers=headers, json=payload(workspace, quality=True))
        assert response.status_code == 200, response.text
        report = [json.loads(line) for line in response.text.splitlines()][-1]["report"]
        result = report["plans"][0]["results"][0]
        assert not result.get("error"), result
        assert result["metrics"]["precision"] == .5 and result["metrics"]["recall"] == 1
        assert result["metrics"]["faithfulness"] == 1
        assert result["metrics"]["answerConsistency"] == 1
        assert result["metrics"]["referenceRecall"] == 1
        assert result["metrics"]["evidenceCoverage"] == 1
        assert result["generation"]["tokens"]["output"] == 8
        assert "secret-evaluation-key" not in response.text
        assert calls[0][1]["model"] == "trial-embedding"
        generation = next(body for path, body in calls if body.get("model") == "trial-text")
        assert "reference" not in generation["messages"][-1]["content"]
        current = client.get(f'{PREFIX}/{workspace["id"]}', headers=headers).json()
        q = current["questions"][0]; q["judgments"][current["documents"][1]["id"]] = 2; q["complete"] = True
        q["answer"] = "New gold answer"
        response = client.put(f'{PREFIX}/{workspace["id"]}/gold', headers=headers,
            json={"revision": current["revision"], "questions": [q]})
        assert response.status_code == 200
        count = len(calls)
        updated = client.post(f'{PREFIX}/{workspace["id"]}/reports/{report["id"]}/rescore', headers=headers).json()
        assert len(calls) == count  # Rescoring makes no paid model calls.
        scored = updated["plans"][0]["results"][0]["metrics"]
        assert scored["precision"] == 1 and scored["recall"] == 1 and not scored["provisional"]
        assert scored["faithfulness"] == 1 and "answerConsistency" not in scored
        assert updated["parentReportId"] == report["id"]
        assert client.get(f'{PREFIX}/{workspace["id"]}', headers=headers).json()["reports"][0] == report
        with application.state.session_factory() as db:
            for model in (Conversation, Message, Document):
                assert db.scalar(select(func.count()).select_from(model)) == 0
        with sqlite3.connect(settings.data_dir / "test.db") as db:
            assert db.execute("SELECT COUNT(*) FROM evaluation_workspaces").fetchone()[0] == 1
        assert not (settings.data_dir / "chroma").exists()
        assert settings.model_config_path.read_bytes() == original


def test_rerank_is_real_and_changes_order(tmp_path, monkeypatch):
    settings = settings_for(tmp_path); configure(settings.model_config_path); calls = mock_models(monkeypatch)
    with TestClient(create_app(settings)) as client:
        headers = login(client); workspace = setup_dataset(client, headers)
        response = client.post(f'{PREFIX}/{workspace["id"]}/run', headers=headers, json=payload(workspace, rerank=True))
        report = [json.loads(line) for line in response.text.splitlines()][-1]["report"]
        result = report["plans"][0]["results"][0]
        assert result["chunks"][0]["name"] == "birds.txt"
        assert result["metrics"]["mrr"] == .5
        assert any(path.endswith("/rerank") for path, _ in calls)


def test_no_fabricated_scores_when_credentials_or_judge_unavailable(tmp_path, monkeypatch):
    settings = settings_for(tmp_path); configure(settings.model_config_path, key="")
    with TestClient(create_app(settings)) as client:
        headers = login(client); workspace = setup_dataset(client, headers)
        assert client.post(f'{PREFIX}/{workspace["id"]}/run', headers=headers, json=payload(workspace)).status_code == 422
        configure(settings.model_config_path); mock_models(monkeypatch)
        response = client.post(f'{PREFIX}/{workspace["id"]}/run', headers=headers, json=payload(workspace))
        report = [json.loads(line) for line in response.text.splitlines()][-1]["report"]
        assert report["plans"][0]["summary"]["faithfulness"] is None


def test_workspace_ownership_versions_cleanup_and_import(tmp_path):
    settings = settings_for(tmp_path); configure(settings.model_config_path)
    application = create_app(settings)
    with TestClient(application) as client:
        headers = login(client); workspace = setup_dataset(client, headers)
        assert client.post(PREFIX, headers=headers).json()["id"] == workspace["id"]
        bad = client.put(f'{PREFIX}/{workspace["id"]}/gold', headers=headers, json={"revision": 1, "questions": workspace["questions"]})
        assert bad.status_code == 409
        question = deepcopy(workspace["questions"][0]); question["complete"] = True
        assert client.put(f'{PREFIX}/{workspace["id"]}/gold', headers=headers, json={"revision": workspace["revision"], "questions": [question]}).status_code == 422
        question["complete"] = False; question["evidence"][0]["end"] = 9999
        assert client.put(f'{PREFIX}/{workspace["id"]}/gold', headers=headers, json={"revision": workspace["revision"], "questions": [question]}).status_code == 422
        client.post("/api/v1/auth/register", json={"username": "guest", "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "guest", "password": "strong-password-123"}).json()["accessToken"]
        guest = {"Authorization": f"Bearer {token}"}
        assert client.get(f'{PREFIX}/{workspace["id"]}', headers=guest).status_code == 404
        assert client.post(f'{PREFIX}/{workspace["id"]}/run', headers=guest, json=payload(workspace)).status_code == 403
        files = list((settings.data_dir / "model_comparisons" / "rag" / workspace["id"]).iterdir())
        assert len(files) == 2
        imported = client.post(f'{PREFIX}/{workspace["id"]}/import', headers=headers, json={"revision": workspace["revision"],
            "schemaVersion": 1, "documents": workspace["documents"], "questions": workspace["questions"]})
        assert imported.status_code == 200, imported.text
        current = imported.json()
        assert current["documents"][0]["id"] != workspace["documents"][0]["id"]
        assert current["questions"][0]["evidence"][0]["documentId"] == current["documents"][0]["id"]
        assert all(not path.exists() for path in files)
        with application.state.session_factory() as db:
            db.get(EvaluationWorkspace, workspace["id"]).expires_at = utcnow() - timedelta(seconds=1); db.commit()
        replacement = client.post(PREFIX, headers=headers).json()
        assert replacement["id"] != workspace["id"] and replacement["documents"] == []
        assert not (settings.data_dir / "model_comparisons" / "rag" / workspace["id"]).exists()


def test_judge_rejects_fabricated_source_indices(tmp_path, monkeypatch):
    async def invalid(*args, **kwargs):
        return json.dumps({"claims": [{"text": "claim", "supported": True, "sources": [99], "referenceSupported": True}], "referenceClaims": []}), {}
    monkeypatch.setattr(rag_evaluation, "completion", invalid)
    with pytest.raises(ValueError, match="证据来源"):
        asyncio.run(rag_evaluation.judge_answer(None, {"query": "q", "answer": "a"}, [{"text": "source"}], "answer"))


def test_stopping_pipeline_propagates_cancellation(monkeypatch):
    cancelled = False
    async def blocking(*args):
        nonlocal cancelled
        try:
            await asyncio.sleep(20)
        finally:
            cancelled = True
    monkeypatch.setattr(rag_evaluation, "vectors", blocking)
    request = RunInput.model_validate({"revision": 1, "plans": [{"id": "p", "name": "p", "embedding": selection("e")}]})
    async def run_and_stop():
        stream = evaluate({"documents": [{"id": "d", "name": "d", "pages": [{"page": 1, "text": "hello"}]}], "questions": []}, request, ({"p": (None, None)}, None, None))
        await anext(stream)
        task = asyncio.create_task(anext(stream)); await asyncio.sleep(0); task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stream.aclose()
    asyncio.run(run_and_stop())
    assert cancelled
