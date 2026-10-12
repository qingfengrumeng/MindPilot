import re
import math
import time
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
import pytest

from app.api.routes import documents
from app.core.model_preferences import write_preferences
from app.db.models import Document, DocumentChunk, DocumentWikiCompilation
from app.main import create_app
from app.services import wiki_compilation, document_jobs
from app.services.document_ingestion import extract_document, split_pages
from test_model_configs import settings_for, login


def prepared(client, auth, count=9):
    response = client.post('/api/v1/documents', headers=auth,
                           files={'file': ('notes.txt', (' '.join(f'Fact {i+1}: retention is 30 days. '+ 'x'*850 for i in range(count))).encode(), 'text/plain')})
    assert response.status_code == 201, response.text
    item = response.json()
    assert item['wikiStatus'] == 'uncompiled'
    with client.app.state.session_factory() as db:
        doc = db.get(Document, item['id'])
        doc.status = 'ready'
        doc.chunk_count = count
        for i in range(count):
            db.add(DocumentChunk(document_id=doc.id, chunk_index=i, page=i+1,
                                 text=f'Fact {i+1}: retention is 30 days.', chroma_id=f'{doc.id}-{i}'))
        db.commit()
        source = Path(doc.storage_path)
    return item['id'], source


def configure(settings):
    write_preferences(settings.model_config_path, {
        'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek',
                                  'apiKey': 'test-only-key', 'configs': {'text': {
                                      'baseUrl': 'https://api.deepseek.com', 'model': 'test-model'}}}},
        'active': {'text': 'deepseek'},
    })


def wait_result(client, auth, document_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get(f'/api/v1/documents/{document_id}', headers=auth).json()
        if result['wikiStatus'] in ('done', 'failed'):
            return result
        time.sleep(.02)
    raise AssertionError('Wiki task did not finish')


def test_compile_batches_preserves_original_and_persists_result(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    configure(settings)
    seen = []
    entered, release = Event(), Event()

    def generate(config, messages):
        source = messages[-1]['content']
        seen.append(source)
        entered.set()
        assert release.wait(5)
        cites = re.findall(r'\[(S\d+)\]', source)
        return '### Key facts\n\n' + '\n'.join(f'Retention is 30 days [{c}].' for c in cites), {}

    monkeypatch.setattr(wiki_compilation, 'complete_text', generate)
    monkeypatch.setattr(documents, 'remove_document_vectors', lambda *args: None)
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, source = prepared(client, auth)
        original = source.read_bytes()
        expected_chunks = len(split_pages(extract_document(source, 'text/plain')[0], 1000))
        endpoint = f'/api/v1/documents/{doc_id}/wiki-compile'
        assert client.post(endpoint).status_code == 401
        assert client.post('/api/v1/documents/missing/wiki-compile', headers=auth).status_code == 404
        assert client.post(endpoint, headers=auth).status_code == 202
        assert entered.wait(5)
        try:
            assert client.post(endpoint, headers=auth).status_code == 409
            assert client.delete(f'/api/v1/documents/{doc_id}', headers=auth).status_code == 409
        finally:
            release.set()
        result = wait_result(client, auth, doc_id)
        assert result['wikiStatus'] == 'done', result
        assert result['wikiCompletedBatches'] == result['wikiTotalBatches'] == math.ceil(expected_chunks/8)
        assert len(seen) == math.ceil(expected_chunks/8)
        assert all(f'Fact {i+1}:' in ''.join(seen) for i in range(9))
        assert '[S9]' in result['wikiMarkdown'] and result['relatedWiki']
        assert source.read_bytes() == original
        with client.app.state.session_factory() as db:
            job = db.get(DocumentWikiCompilation, doc_id)
            artifact = Path(job.data_json['artifactPath'])
            assert len(job.data_json['sources']) == expected_chunks
            assert artifact.read_text(encoding='utf-8') == result['wikiMarkdown']
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        assert client.get('/api/v1/documents', headers=auth).json()['items'][0]['wikiStatus'] == 'done'
        assert client.delete(f'/api/v1/documents/{doc_id}', headers=auth).status_code == 204
        assert not artifact.exists() and not source.exists()
        with client.app.state.session_factory() as db:
            assert db.get(DocumentWikiCompilation, doc_id) is None


def test_invalid_citation_fails_and_can_retry(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    configure(settings)
    monkeypatch.setattr(wiki_compilation, 'complete_text', lambda *args: ('Invented fact [S999]', {}))
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, source = prepared(client, auth, 1)
        endpoint = f'/api/v1/documents/{doc_id}/wiki-compile'
        assert client.post(endpoint, headers=auth).status_code == 202
        result = wait_result(client, auth, doc_id)
        assert result['wikiStatus'] == 'failed'
        assert 'wikiMarkdown' not in result
        assert source.exists()
        monkeypatch.setattr(wiki_compilation, 'complete_text', lambda *args: ('Retention is 30 days [S1]', {}))
        assert client.post(endpoint, headers=auth).status_code == 202
        assert wait_result(client, auth, doc_id)['wikiStatus'] == 'done'


def test_compile_prerequisites_and_restart_recovery(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        item = client.post('/api/v1/documents', headers=auth,
                           files={'file': ('new.txt', b'New source', 'text/plain')}).json()
        assert client.post(f"/api/v1/documents/{item['id']}/wiki-compile", headers=auth).status_code == 422
        doc_id, _ = prepared(client, auth, 1)
        assert client.post(f'/api/v1/documents/{doc_id}/wiki-compile', headers=auth).status_code == 422
        with client.app.state.session_factory() as db:
            doc = db.get(Document, doc_id)
            db.add(DocumentWikiCompilation(document_id=doc_id, user_id=doc.user_id, status='compiling'))
            db.commit()
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        result = client.get(f'/api/v1/documents/{doc_id}', headers=auth).json()
        assert result['wikiStatus'] == 'failed'
        assert '重启' in result['wikiErrorMessage']


def test_missing_original_preflight_and_worker_report_real_cause(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    configure(settings)
    monkeypatch.setattr(wiki_compilation, 'complete_text', lambda *args: (_ for _ in ()).throw(AssertionError('Model must not run')))
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, source = prepared(client, auth, 1)
        source.unlink()
        response = client.post(f'/api/v1/documents/{doc_id}/wiki-compile', headers=auth)
        assert response.status_code == 409 and '原始文件缺失' in response.json()['detail']
        with client.app.state.session_factory() as db:
            assert db.get(DocumentWikiCompilation, doc_id) is None
            doc = db.get(Document, doc_id)
            db.add(DocumentWikiCompilation(document_id=doc_id, user_id=doc.user_id, status='queued'))
            db.commit()
        wiki_compilation.compile_document(client.app.state.session_factory, settings, doc_id)
        result = client.get(f'/api/v1/documents/{doc_id}', headers=auth).json()
        assert result['sourceAvailable'] is False
        assert result['wikiStatus'] == 'failed' and '原始文件缺失' in result['wikiErrorMessage']
        assert result['chunks'] and result['status'] == 'ready'
        with client.app.state.session_factory() as db:
            assert db.get(DocumentWikiCompilation, doc_id).data_json['diagnostic']['code'] == 'source_missing'


def test_errors_identify_batch_and_never_echo_credentials(tmp_path, monkeypatch):
    from app.services.text_generation import TextGenerationError
    settings = settings_for(tmp_path)
    configure(settings)
    def fail(*args):
        raise TextGenerationError('DeepSeek request failed HTTP 503 sensitive-credential-marker')
    monkeypatch.setattr(wiki_compilation, 'complete_text', fail)
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id, _ = prepared(client, auth, 1)
        assert client.post(f'/api/v1/documents/{doc_id}/wiki-compile', headers=auth).status_code == 202
        result = wait_result(client, auth, doc_id)
        assert '第1批' in result['wikiErrorMessage'] and 'HTTP 503' in result['wikiErrorMessage']
        assert 'credential-marker' not in result['wikiErrorMessage']
    code, message = wiki_compilation.compilation_error(ValueError('private-path-and-secret'), '保存Wiki结果', 2)
    assert code == 'internal' and 'private-path' not in message


@pytest.mark.parametrize('vector_status', ['uploaded', 'failed', 'embedding'])
def test_wiki_is_independent_of_vector_status(tmp_path, monkeypatch, vector_status):
    settings = settings_for(tmp_path)
    configure(settings)
    prompts = []

    def generate(config, messages):
        prompts.append(messages[-1]['content'])
        return 'Original immutable facts [S1]', {}

    monkeypatch.setattr(wiki_compilation, 'complete_text', generate)
    monkeypatch.setattr(document_jobs, 'remove_document_vectors', lambda *args: None)
    monkeypatch.setattr(document_jobs, 'index_chunks', lambda *args: None)
    with TestClient(create_app(settings)) as client:
        auth = login(client)
        doc_id = client.post('/api/v1/documents', headers=auth,
                             files={'file': ('raw.txt', b'Original immutable facts.', 'text/plain')}).json()['id']
        with client.app.state.session_factory() as db:
            doc = db.get(Document, doc_id)
            doc.status = vector_status
            doc.error_message = 'Existing vector error' if vector_status == 'failed' else ''
            db.commit()
        assert client.post(f'/api/v1/documents/{doc_id}/wiki-compile', headers=auth).status_code == 202
        result = wait_result(client, auth, doc_id)
        assert result['wikiStatus'] == 'done', result
        assert result['status'] == vector_status
        assert result['chunkCount'] == result['indexedChunks'] == 0
        assert result['chunks'] == []
        assert 'Original immutable facts.' in prompts[0]
        if vector_status == 'failed':
            assert result['errorMessage'] == 'Existing vector error'
        with client.app.state.session_factory() as db:
            evidence = db.get(DocumentWikiCompilation, doc_id).data_json['sources']
            assert evidence[0]['chunkId'].startswith('raw:')
        if vector_status == 'uploaded':
            started = client.post(f'/api/v1/documents/{doc_id}/vectorize', headers=auth)
            assert started.status_code == 202
            assert started.json()['wikiStatus'] == 'done'
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                updated = client.get(f'/api/v1/documents/{doc_id}', headers=auth).json()
                if updated['status'] in ('ready', 'failed'):
                    break
                time.sleep(.02)
            assert updated['status'] == 'ready', updated
            assert updated['wikiStatus'] == 'done'
            assert updated['wikiMarkdown'] == result['wikiMarkdown']
            assert all(chunk['id'] != evidence[0]['chunkId'] for chunk in updated['chunks'])
