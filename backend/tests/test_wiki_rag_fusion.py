import hashlib
import json
from types import SimpleNamespace
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.requests import Request

from app.api.routes import conversations
from app.core.model_preferences import write_preferences
from app.db.models import Document, DocumentChunk, DocumentWikiCompilation, WikiSupplementJob
from app.main import create_app
from app.services import knowledge_fusion, wiki_supplement
from app.services.wiki_retrieval import wiki_search
from test_model_configs import settings_for, login


class CapturedExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, function, *args):
        self.calls.append((function, args))

    def finish(self):
        function, args = self.calls.pop(0)
        function(*args)


def add_document(client, auth, text='Retention is 30 days. Exceptions need manager approval.', status='ready', wiki=False):
    item = client.post('/api/v1/documents', headers=auth,
                       files={'file': ('facts.txt', text.encode(), 'text/plain')}).json()
    with client.app.state.session_factory() as db:
        doc = db.get(Document, item['id'])
        doc.status = status
        doc.pages = 1
        doc.chunk_count = 1 if status == 'ready' else 0
        if status == 'ready':
            db.add(DocumentChunk(document_id=doc.id, chunk_index=0, page=1, text=text, chroma_id=doc.id))
        if wiki:
            db.add(DocumentWikiCompilation(document_id=doc.id, user_id=doc.user_id, status='done',
                markdown='# Facts\n\n## Retention\n\nRetention is 30 days [S1].\n\n## 原始来源\n- [S1] facts',
                data_json={'sourceHash': hashlib.sha256(text.encode()).hexdigest(),
                           'sources': [{'id': 'S1', 'chunkId': 'raw:snapshot', 'page': 1, 'text': text}]}))
        db.commit()
        return doc.id, doc.user_id, Path(doc.storage_path)


def configure(settings):
    write_preferences(settings.model_config_path, {'providers': {'deepseek': {
        'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-key',
        'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'test-model'}}}},
        'active': {'text': 'deepseek'}})


def test_retrieval_engines_start_in_parallel_and_failure_isolated(tmp_path, monkeypatch):
    barrier = Barrier(2, timeout=3)
    hit = {'documentId': 'doc', 'page': 1, 'text': 'Same raw fact'}

    def raw(*args, **kwargs):
        barrier.wait()
        return [hit]

    def wiki(*args, **kwargs):
        barrier.wait()
        return [{**hit, 'wikiOverview': 'Overview', 'wikiId': 'doc'}]

    monkeypatch.setattr(knowledge_fusion, 'hybrid_search', raw)
    monkeypatch.setattr(knowledge_fusion, 'wiki_search', wiki)
    result = knowledge_fusion.retrieve_knowledge('fact', settings_for(tmp_path), None, 'owner', None)
    assert len(result['hits']) == 1
    assert result['hits'][0]['retrievalOrigins'] == ['raw', 'wiki']
    assert result['hits'][0]['wikiOverview'] == 'Overview'
    monkeypatch.setattr(knowledge_fusion, 'hybrid_search', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(knowledge_fusion, 'wiki_search', lambda *args, **kwargs: [{**hit, 'wikiId': 'doc'}])
    result = knowledge_fusion.retrieve_knowledge('fact', settings_for(tmp_path), None, 'owner', None)
    assert result['hits'] and result['errors'] == ['raw']


def test_wiki_uses_owned_fresh_snapshots_without_vectorization(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, owner, source = add_document(client, auth, status='uploaded', wiki=True)
        hits = wiki_search('retention', settings, client.app.state.session_factory, owner)
        assert len(hits) == 1 and hits[0]['documentId'] == doc_id
        assert wiki_search('retention', settings, client.app.state.session_factory, 'another-user') == []
        monkeypatch.setattr(conversations, 'search_documents', lambda *args, **kwargs: [])
        context, verified = conversations.knowledge_context(Request({'type': 'http', 'app': client.app}), owner, 'retention')
        assert verified[0]['retrievalOrigins'] == ['wiki']
        assert 'Wiki编译概览' in context and 'Exceptions need manager approval.' in context
        source.write_text('Changed source', encoding='utf-8')
        assert wiki_search('retention', settings, client.app.state.session_factory, owner) == []


def test_fused_candidates_use_configured_reranker_with_safe_fallback(tmp_path, monkeypatch):
    raw = [{'documentId': 'a', 'page': 1, 'text': 'First fact'},
           {'documentId': 'b', 'page': 1, 'text': 'Second fact'}]
    monkeypatch.setattr(knowledge_fusion, 'hybrid_search', lambda *args, **kwargs: raw)
    monkeypatch.setattr(knowledge_fusion, 'wiki_search', lambda *args, **kwargs: [])
    monkeypatch.setattr(knowledge_fusion, 'require_runtime_model', lambda *args: SimpleNamespace(provider='dashscope'))
    monkeypatch.setattr(knowledge_fusion, 'rerank_texts', lambda *args, **kwargs: {
        'results': [{'index': 1, 'relevanceScore': .9}, {'index': 0, 'relevanceScore': .3}]})
    result = knowledge_fusion.retrieve_knowledge('fact', settings_for(tmp_path), None, 'owner', None)
    assert [hit['documentId'] for hit in result['hits']] == ['b', 'a']
    assert result['hits'][0]['rerankScore'] == .9
    monkeypatch.setattr(knowledge_fusion, 'rerank_texts', lambda *args, **kwargs: {'results': []})
    result = knowledge_fusion.retrieve_knowledge('fact', settings_for(tmp_path), None, 'owner', None)
    assert result['hits'] == knowledge_fusion.fuse_results(raw, [])
    assert result['errors'] == ['reranker']


def test_context_merges_both_origins_and_schedules_background_supplement(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    configure(settings)
    monkeypatch.setattr(conversations, 'search_documents', lambda *args, **kwargs: [])
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, owner, source = add_document(client, auth, wiki=True)
        executor = CapturedExecutor()
        client.app.state.wiki_executor = executor
        context, hits = conversations.knowledge_context(Request({'type': 'http', 'app': client.app}), owner, 'retention exceptions')
        assert len(hits) == 1 and hits[0]['retrievalOrigins'] == ['raw', 'wiki']
        assert '〔证据1〕' in context
        assert conversations.knowledge_citations(hits)[0]['wikiId'] == doc_id
        assert len(executor.calls) == 1
        pending = client.get('/api/v1/documents', headers=auth).json()['items'][0]
        assert pending['wikiSupplementStatus'] == 'queued'
        assert pending['wikiStatus'] == 'done'
        assert client.delete(f'/api/v1/documents/{doc_id}', headers=auth).status_code == 409
        assert client.post(f'/api/v1/documents/{doc_id}/wiki-compile', headers=auth).status_code == 409
        monkeypatch.setattr(wiki_supplement, 'complete_text', lambda *args: (
            json.dumps({'needsUpdate': True, 'markdown': 'Exceptions need manager approval [S1].'}), {}))
        executor.finish()
        result = client.get(f'/api/v1/documents/{doc_id}', headers=auth).json()
        assert 'Retention is 30 days [S1]' in result['wikiMarkdown']
        assert 'Exceptions need manager approval [S1]' in result['wikiMarkdown']
        assert result['wikiSupplementCount'] == 1
        assert result['wikiSupplementStatus'] == 'done'
        assert source.read_text() == 'Retention is 30 days. Exceptions need manager approval.'
        conversations.knowledge_context(Request({'type': 'http', 'app': client.app}), owner, 'retention exceptions')
        assert not executor.calls


def test_supplement_creates_missing_wiki_and_rejects_fake_citations(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    configure(settings)
    executor = CapturedExecutor()
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, owner, source = add_document(client, auth)
        raw = [{'documentId': doc_id, 'page': 1, 'text': source.read_text()}]
        assert wiki_supplement.schedule_supplements(settings, client.app.state.session_factory, executor, 'other-owner', 'retention', raw) == []
        monkeypatch.setattr(wiki_supplement, 'complete_text', lambda *args: (
            '{"needsUpdate":true,"markdown":"Retention is 30 days [S999]"}', {}))
        assert wiki_supplement.schedule_supplements(settings, client.app.state.session_factory, executor, owner, 'retention', raw) == [doc_id]
        executor.finish()
        with client.app.state.session_factory() as db:
            assert db.get(DocumentWikiCompilation, doc_id) is None
            assert db.get(WikiSupplementJob, doc_id).status == 'failed'
        monkeypatch.setattr(wiki_supplement, 'complete_text', lambda *args: (
            '{"needsUpdate":true,"markdown":"Retention is 30 days [S1]."}', {}))
        wiki_supplement.schedule_supplements(settings, client.app.state.session_factory, executor, owner, 'retention', raw)
        executor.finish()
        assert wiki_search('retention', settings, client.app.state.session_factory, owner)
        assert client.get(f'/api/v1/documents/{doc_id}', headers=auth).json()['wikiStatus'] == 'done'


def test_no_update_and_concurrent_revision_preserve_wiki(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    configure(settings)
    executor = CapturedExecutor()
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, owner, source = add_document(client, auth, wiki=True)
        raw = [{'documentId': doc_id, 'page': 1, 'text': source.read_text()}]
        monkeypatch.setattr(wiki_supplement, 'complete_text', lambda *args: ('{"needsUpdate":false,"markdown":""}', {}))
        wiki_supplement.schedule_supplements(settings, client.app.state.session_factory, executor, owner, 'retention', raw)
        executor.finish()
        with client.app.state.session_factory() as db:
            original = db.get(DocumentWikiCompilation, doc_id).markdown
            assert db.get(WikiSupplementJob, doc_id).status == 'unchanged'

        def concurrent_edit(*args):
            with client.app.state.session_factory() as db:
                db.get(DocumentWikiCompilation, doc_id).markdown = original + '\nManual protected edit'
                db.commit()
            return '{"needsUpdate":true,"markdown":"Exceptions need manager approval [S1]."}', {}

        monkeypatch.setattr(wiki_supplement, 'complete_text', concurrent_edit)
        wiki_supplement.schedule_supplements(settings, client.app.state.session_factory, executor, owner, 'exceptions', raw)
        executor.finish()
        with client.app.state.session_factory() as db:
            assert db.get(DocumentWikiCompilation, doc_id).markdown == original + '\nManual protected edit'
            assert db.get(WikiSupplementJob, doc_id).status == 'failed'


def test_fake_raw_evidence_rejected_before_generation_and_restart_recovery(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    configure(settings)
    executor = CapturedExecutor()
    monkeypatch.setattr(wiki_supplement, 'complete_text', lambda *args: (_ for _ in ()).throw(AssertionError('Invalid raw reached model')))
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, owner, source = add_document(client, auth, wiki=True)
        fake = [{'documentId': doc_id, 'page': 1, 'text': 'A fact that does not exist'}]
        wiki_supplement.schedule_supplements(settings, client.app.state.session_factory, executor, owner, 'fact', fake)
        executor.finish()
        with client.app.state.session_factory() as db:
            assert db.get(WikiSupplementJob, doc_id).status == 'failed'
            assert not db.get(DocumentWikiCompilation, doc_id).data_json.get('supplements')
        real = [{'documentId': doc_id, 'page': 1, 'text': source.read_text()}]
        wiki_supplement.schedule_supplements(settings, client.app.state.session_factory, executor, owner, 'fact', real)
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc = client.get(f'/api/v1/documents/{doc_id}', headers=auth).json()
        assert doc['wikiStatus'] == 'done'
        assert doc['wikiSupplementStatus'] == 'failed'
        assert '重启' in doc['wikiSupplementError']
