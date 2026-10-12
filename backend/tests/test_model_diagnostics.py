import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import model_configs as routes
from app.core.model_preferences import write_preferences
from app.core.model_runtime import RuntimeModel
from app.main import create_app
from app.services import model_diagnostics as diagnostics
from test_model_configs import settings_for, login


def test_draft_discovery_pagination_and_test_never_change_configuration(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    write_preferences(settings.model_config_path, {'providers': {'deepseek': {
        'name': 'DeepSeek', 'runtimeProvider': 'deepseek', 'apiKey': 'saved-test-key',
        'configs': {'text': {'baseUrl': 'https://example.com/v1', 'model': 'saved-model'}}}},
        'active': {'text': 'deepseek'}})
    original = settings.model_config_path.read_bytes()
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, headers, **kwargs):
            assert headers['Authorization'] == 'Bearer draft-test-key'
            calls.append(kwargs)
            page = {'data': [{'id': f'model-{i}'} for i in range(600)], 'has_more': True, 'last_id': 'cursor'} if not kwargs else {'data': [{'id': 'last'}, {'id': 'model-0'}]}
            return SimpleNamespace(status_code=200, json=lambda: page)
    monkeypatch.setattr(routes.httpx, 'Client', FakeClient)
    checked = []
    def probe(config):
        checked.append(config)
        return {'ok': True, 'latencyMs': 123.4, 'checked': 'response'}
    monkeypatch.setattr(routes, 'probe_model', probe)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        result = client.post('/api/v1/model-configs/deepseek/models/text', headers=headers,
                             json={'baseUrl': 'https://example.com/v1', 'apiKey': 'draft-test-key'})
        assert result.status_code == 200 and len(result.json()['models']) == 601
        assert result.headers['cache-control'] == 'no-store'
        assert calls == [{}, {'params': {'after': 'cursor'}}]
        payload = {'name': 'DeepSeek', 'configs': {'text': {'baseUrl': 'https://example.com/v1', 'model': 'draft-model'}}}
        result = client.post('/api/v1/model-configs/deepseek/test/text', headers=headers, json=payload)
        assert result.json()['latencyMs'] == 123.4
        assert checked[-1].api_key == 'saved-test-key' and checked[-1].model == 'draft-model'
        payload['apiKey'] = 'draft-test-key'
        assert client.post('/api/v1/model-configs/deepseek/test/text', headers=headers, json=payload).status_code == 200
        assert checked[-1].api_key == 'draft-test-key'
        payload['clearApiKey'] = True
        assert client.post('/api/v1/model-configs/deepseek/test/text', headers=headers, json=payload).status_code == 422
        payload['clearApiKey'] = False
        def fail(config): raise RuntimeError('vendor echoed draft-test-key')
        monkeypatch.setattr(routes, 'probe_model', fail)
        failed = client.post('/api/v1/model-configs/deepseek/test/text', headers=headers, json=payload)
        assert failed.status_code == 502 and 'draft-test-key' not in failed.text
        assert client.post('/api/v1/model-configs/deepseek/test/text', json=payload).status_code == 401
        client.post('/api/v1/auth/register', json={'username': 'guest', 'password': 'strong-password-123'})
        token = client.post('/api/v1/auth/login', json={'username': 'guest', 'password': 'strong-password-123'}).json()['accessToken']
        guest = {'Authorization': 'Bearer ' + token}
        assert client.post('/api/v1/model-configs/deepseek/test/text', headers=guest, json=payload).status_code == 403
        assert client.post('/api/v1/model-configs/deepseek/models/text', headers=guest, json={'baseUrl': 'https://example.com'}).status_code == 403
    assert settings.model_config_path.read_bytes() == original


def test_discovery_never_returns_presets_or_lists_without_keys(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, headers, **kwargs):
            calls.append((url, headers['Authorization']))
            return SimpleNamespace(status_code=200, json=lambda: {'data': [{'id': 'actual-api-model'}]})
    monkeypatch.setattr(routes.httpx, 'Client', Client)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        state = client.get('/api/v1/model-configs', headers=headers).json()
        assert all('models' not in provider for provider in state['providers'])
        assert not calls
        for provider, category in [('zhipu', 'text'), ('dashscope', 'image'), ('volcengine', 'asr'), ('volcengine', 'tts')]:
            missing = client.get(f'/api/v1/model-configs/{provider}/models/{category}', headers=headers)
            assert missing.status_code == 422 and 'models' not in missing.json()
        payload = {'baseUrl': 'https://example.com/v1'}
        assert client.post('/api/v1/model-configs/zhipu/models/text', headers=headers, json=payload).status_code == 422
        assert not calls
        payload['apiKey'] = 'test-key'
        for _ in range(2):
            result = client.post('/api/v1/model-configs/zhipu/models/text', headers=headers, json=payload)
            assert result.json() == {'models': ['actual-api-model']}
        assert len(calls) == 2  # Every click contacts the vendor anew.
        for category in ['asr', 'tts']:
            result = client.post(f'/api/v1/model-configs/dashscope/models/{category}', headers=headers, json=payload)
            assert result.status_code == 200 and result.json() == {'models': []}
        result = client.post('/api/v1/model-configs/dashscope/models/image', headers=headers, json=payload)
        assert result.json() == {'models': []} and len(calls) == 5
        result = client.post('/api/v1/model-configs/dashscope/models/reranker', headers=headers, json=payload)
        assert result.status_code == 200 and result.json() == {'models': []}
        assert len(calls) == 6


def test_discovery_filters_categories_and_reads_native_pagination(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    calls = []
    pages = [
        [{'model': 'deepseek-chat'}, {'model': 'qwen3.7-text-embedding'},
         {'model': 'private-vector', 'capabilities': ['ME']}, {'model': 'qwen3-rerank'}],
        [{'model': 'gte-rerank-v2'}, {'model': 'Qwen/Qwen3-Reranker-8B'},
         {'model': 'BAAI/bge-m3'}, {'model': 'private-ranking', 'model_type': 'reranker'}],
    ]
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, headers, **kwargs):
            calls.append((url, kwargs))
            page = kwargs['params']['page_no']
            return SimpleNamespace(status_code=200, json=lambda: {'output': {'models': pages[page - 1], 'total': 8}})
    monkeypatch.setattr(routes.httpx, 'Client', Client)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        payload = {'baseUrl': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'apiKey': 'test-key'}
        result = client.post('/api/v1/model-configs/dashscope/models/embedding', headers=headers, json=payload)
        assert result.status_code == 200
        assert result.json()['models'] == ['qwen3.7-text-embedding', 'private-vector', 'BAAI/bge-m3']
        payload['baseUrl'] = 'https://dashscope.aliyuncs.com/api/v1'
        result = client.post('/api/v1/model-configs/dashscope/models/reranker', headers=headers, json=payload)
        assert result.status_code == 200
        assert result.json()['models'] == ['qwen3-rerank', 'gte-rerank-v2', 'Qwen/Qwen3-Reranker-8B', 'private-ranking']
        assert [kwargs['params']['page_no'] for _, kwargs in calls] == [1, 2, 1, 2]
        assert all(url == 'https://dashscope.aliyuncs.com/api/v1/models' for url, _ in calls)


def test_compatible_discovery_filters_rerankers_from_embeddings(monkeypatch):
    rows = [{'id': 'deepseek-chat'}, {'id': 'text-embedding-v4'}, {'id': 'bge-reranker-v2-m3'},
            {'id': 'custom-vector', 'type': 'embedding'}, {'id': 'gte-large'}, {'id': 'custom-rank', 'type': 'rerank'}]
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {'data': rows})
    monkeypatch.setattr(routes.httpx, 'Client', Client)
    assert routes.discover_models('https://example.com/v1', 'test-key', 'embedding')['models'] == ['text-embedding-v4', 'custom-vector', 'gte-large']
    assert routes.discover_models('https://example.com/v1', 'test-key', 'reranker')['models'] == ['bge-reranker-v2-m3', 'custom-rank']


@pytest.mark.parametrize('native', [False, True])
def test_image_discovery_excludes_chat_vision_embedding_and_video(native, monkeypatch):
    rows = [{'id': 'deepseek-chat'}, {'id': 'qwen-image-3.0-pro'}, {'id': 'qwen-vl-plus'},
            {'id': 'custom-image-reader', 'capabilities': ['VU']},
            {'id': 'tongyi-embedding-vision-plus', 'capabilities': ['ME']},
            {'id': 'wan-video', 'capabilities': ['VG']},
            {'id': 'private-generator', 'capabilities': ['IG']},
            {'id': 'another-generator', 'inference_metadata': {'response_modality': ['Image']}},
            {'id': 'wanx-v1'}, {'id': 'black-forest-labs/FLUX.1-schnell'}]
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, **kwargs):
            calls.append(url)
            if native:
                page = kwargs['params']['page_no']
                body = {'output': {'models': [dict(row, model=row['id']) for row in rows[(page-1)*5:page*5]], 'total': len(rows)}}
            else:
                body = {'data': rows}
            return SimpleNamespace(status_code=200, json=lambda: body)
    monkeypatch.setattr(routes.httpx, 'Client', Client)
    result = routes.discover_models('https://dashscope.aliyuncs.com/compatible-mode/v1', 'test-key', 'image', 'dashscope' if native else 'custom')
    assert result['models'] == ['qwen-image-3.0-pro', 'private-generator', 'another-generator', 'wanx-v1', 'black-forest-labs/FLUX.1-schnell']
    assert len(calls) == (2 if native else 1)
    assert calls[0].endswith('/api/v1/models' if native else '/compatible-mode/v1/models')


@pytest.mark.parametrize('category,path,expected', [
    ('asr', 'realtime', ['qwen3-asr-flash-realtime', 'private-realtime-asr']),
    ('asr', 'inference', ['paraformer-realtime-v2', 'qwen-audio-asr-streaming']),
    ('tts', 'realtime', ['qwen3-tts-flash-realtime', 'private-realtime-tts']),
    ('tts', 'inference', ['qwen-audio-3.1-tts-flash', 'cosyvoice-v3-plus']),
])
@pytest.mark.parametrize('host', ['ws-test.cn-beijing.maas.aliyuncs.com', 'ws-test.ap-southeast-1.maas.aliyuncs.com', 'dashscope.aliyuncs.com'])
def test_dashscope_speech_discovery_uses_workspace_http_and_filters_protocol(category, path, expected, host, tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    endpoint = f'wss://{host}/api-ws/v1/{path}'
    write_preferences(settings.model_config_path, {'providers': {'dashscope': {
        'name': 'Qwen', 'runtimeProvider': 'dashscope', 'apiKey': 'saved-test-key',
        'configs': {category: {'baseUrl': endpoint, 'model': expected[0]}}}}, 'active': {}})
    original = settings.model_config_path.read_bytes()
    rows = [{'model': name} for name in ['deepseek-chat', 'text-embedding-v4', 'qwen-image-3.0-pro',
            'qwen3-asr-flash-realtime', 'paraformer-realtime-v2', 'qwen-audio-asr-streaming',
            'qwen3-tts-flash-realtime', 'qwen-audio-3.1-tts-flash', 'cosyvoice-v3-plus']]
    rows.extend([{'model': 'private-realtime-asr', 'capabilities': ['Realtime-ASR']},
                 {'model': 'private-realtime-tts', 'capabilities': ['Realtime-Text-to-Speech']}])
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, headers, **kwargs):
            calls.append((url, headers['Authorization']))
            page = kwargs['params']['page_no']
            return SimpleNamespace(status_code=200, json=lambda: {'output': {'models': rows[(page-1)*6:page*6], 'total': len(rows)}})
    monkeypatch.setattr(routes.httpx, 'Client', Client)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        url = f'/api/v1/model-configs/dashscope/models/{category}'
        for response in [client.get(url, headers=headers), client.post(url, headers=headers, json={'baseUrl': endpoint})]:
            assert response.status_code == 200, response.text
            assert response.json() == {'models': expected}
            assert response.headers['cache-control'] == 'no-store'
            assert 'saved-test-key' not in response.text
        assert client.post(url, headers=headers, json={'baseUrl': f'wss://{host}/wrong'}).status_code == 422
    assert calls == [(f'https://{host}/api/v1/models', 'Bearer saved-test-key')] * 4
    assert settings.model_config_path.read_bytes() == original


@pytest.mark.parametrize('category', ['text', 'image', 'embedding', 'reranker', 'tts', 'asr'])
def test_all_diagnostic_adapters_and_resource_cleanup(category, monkeypatch):
    endpoint = 'wss://example.com/realtime' if category == 'asr' else 'https://example.com/v1'
    config = RuntimeModel(category, 'dashscope', endpoint, 'test-model', 'test-key', 1024)
    called = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            assert json['model'] == 'test-model' and json['max_tokens'] == 8
            return SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'content': 'OK'}}]})
        def get(self, url, headers):
            return SimpleNamespace(status_code=200, json=lambda: {'data': []})
    monkeypatch.setattr(diagnostics.httpx, 'Client', Client)
    monkeypatch.setattr(diagnostics, 'embed_texts', lambda c, texts: called.append(texts))
    monkeypatch.setattr(diagnostics, 'rerank_texts', lambda c, q, docs, top_n: called.append(docs))
    def audio(c, text):
        try: yield b'audio'
        finally: called.append('closed')
    monkeypatch.setattr(diagnostics, 'stream_mp3', audio)
    class Connection:
        def send(self, event): assert json.loads(event)['type'] == 'session.update'
        def recv(self): return json.dumps({'type': 'session.updated'})
        def close(self): called.append('closed')
    monkeypatch.setattr(diagnostics.websocket, 'create_connection', lambda *a, **k: Connection())
    result = diagnostics.probe_model(config)
    assert result['ok'] and result['latencyMs'] >= 0
    if category in {'tts', 'asr'}: assert called == ['closed']
    if category in {'embedding', 'reranker'}: assert called == [['连接测试']]


def test_invalid_model_response_is_not_a_success(monkeypatch):
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs): return SimpleNamespace(status_code=200, json=lambda: {'choices': [{}]})
    monkeypatch.setattr(diagnostics.httpx, 'Client', Client)
    with pytest.raises(RuntimeError):
        diagnostics.probe_model(RuntimeModel('text', 'openai', 'https://example.com', 'model', 'key'))
