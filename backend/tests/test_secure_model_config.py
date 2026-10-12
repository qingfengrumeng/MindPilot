import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import configuration_json, migrate_model_configuration, read_model_configuration
from app.core.model_preferences import write_preferences
from app.core.model_runtime import require_runtime_model
from app.main import create_app
from tests.test_model_configs import login, settings_for


def state():
    return {'providers': {'deepseek': {'name': 'DeepSeek', 'runtimeProvider': 'deepseek', 'apiKey': 'private-key',
            'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}},
            'active': {'text': 'deepseek'}, 'integrations': {'baidu_search': {'authorization': 'Bearer bce-v3-private'}}}


def test_atomic_file_schema_secret_masking_and_live_reload(tmp_path):
    path = tmp_path / 'models.json'
    write_preferences(path, state())
    document = json.loads(path.read_text(encoding='utf8'))
    assert document['format_version'] == 1 and document['model_routes']['text'] == 'deepseek'
    assert document['providers']['deepseek']['credentials']['api_key'] == 'private-key'
    assert document['providers']['deepseek']['models']['text']['model_id'] == 'deepseek-flash'
    config = read_model_configuration(path)
    assert 'private-key' not in repr(config)
    assert 'private' not in json.dumps(configuration_json(config))
    runtime = require_runtime_model('text', path)
    assert runtime.api_key == 'private-key' and 'private-key' not in repr(runtime)
    document['providers']['deepseek']['credentials']['api_key'] = 'rotated-key'
    path.write_text(json.dumps(document), encoding='utf8')
    assert require_runtime_model('text', path).api_key == 'rotated-key'
    assert not list(tmp_path.glob('.models-*'))


@pytest.mark.parametrize('change', ['version', 'endpoint', 'route', 'masked-key', 'category'])
def test_invalid_file_rejected_without_secret_in_error(tmp_path, change):
    path = tmp_path / 'models.json'
    write_preferences(path, state())
    document = json.loads(path.read_text(encoding='utf8'))
    p = document['providers']['deepseek']
    if change == 'version': document['format_version'] = 99
    if change == 'endpoint': p['models']['text']['endpoint'] = 'https://private-key@host.example/v1'
    if change == 'route': document['model_routes']['text'] = 'missing'
    if change == 'masked-key': p['credentials']['api_key'] = '••••••••'
    if change == 'category': document['model_routes']['unknown'] = None
    path.write_text(json.dumps(document), encoding='utf8')
    with pytest.raises(RuntimeError) as exc:
        read_model_configuration(path)
    assert 'private-key' not in str(exc.value)


def test_document_endpoint_requires_auth_and_never_returns_credentials(tmp_path):
    settings = settings_for(tmp_path)
    write_preferences(settings.model_config_path, state())
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/model-configs/document').status_code == 401
        response = client.get('/api/v1/model-configs/document', headers=login(client))
        assert response.status_code == 200
        assert 'private' not in response.text
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['providers']['deepseek']['credentials']['api_key'] == '••••••••'


def test_model_file_relocation_preserves_credentials_and_reads_runtime_from_new_location(tmp_path):
    legacy = tmp_path / 'backend' / '.mindpoilt'
    target = tmp_path / '.mindpoilt' / 'models.json'
    legacy.parent.mkdir()
    write_preferences(target, state())
    original = target.read_bytes()
    target.replace(legacy)
    migrate_model_configuration(legacy, target)
    migrate_model_configuration(legacy, target)
    assert target.read_bytes() == original and not legacy.exists()
    runtime = require_runtime_model('text', target)
    assert runtime.api_key == 'private-key' and runtime.model == 'deepseek-flash'
    assert read_model_configuration(target).integrations.baidu_search.authorization.get_secret_value() == 'Bearer bce-v3-private'
    assert 'private' not in json.dumps(configuration_json(read_model_configuration(target)))


def test_relocation_conflict_or_invalid_legacy_never_overwrites_credentials(tmp_path):
    legacy = tmp_path / 'backend' / '.mindpoilt'
    target = tmp_path / '.mindpoilt' / 'models.json'
    legacy.parent.mkdir()
    write_preferences(target, state())
    original = target.read_bytes()
    legacy.write_text('{}', encoding='utf-8')
    with pytest.raises(RuntimeError, match='避免覆盖'):
        migrate_model_configuration(legacy, target)
    assert target.read_bytes() == original and legacy.read_text(encoding='utf-8') == '{}'
    legacy.write_text('{"secret":"private-key", "format_version":99}', encoding='utf-8')
    with pytest.raises(RuntimeError) as error:
        migrate_model_configuration(legacy, target)
    assert 'private-key' not in str(error.value)
    assert target.read_bytes() == original


def test_models_api_reports_new_file_and_mutations_remain_on_it(tmp_path):
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        response = client.get('/api/v1/model-configs', headers=headers)
        assert response.status_code == 200
        assert response.json()['configFile'] == '.mindpoilt/models.json'
        saved = client.put('/api/v1/model-configs/deepseek', json={
            'name': 'DeepSeek', 'apiKey': 'saved-through-api', 'configs': {
                'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}
            }
        }, headers=headers)
        assert saved.status_code == 200
        assert client.put('/api/v1/model-configs/active/text', json={'providerId': 'deepseek'}, headers=headers).status_code == 200
        assert settings.model_config_path.name == 'models.json'
        assert require_runtime_model('text', settings.model_config_path).api_key == 'saved-through-api'
