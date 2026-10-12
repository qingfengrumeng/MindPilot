import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import tts_voices
from app.api.routes import model_configs as routes
from app.core.model_preferences import write_preferences
from tests.test_model_configs import login, settings_for


HTML = '''<h2>System voices</h2><h3>qwen-audio-3.1-tts-flash</h3>
<h4>Chinese voices</h4><table><tr><th>Name</th><th>Voice ID</th></tr>
<tr><td>龙安温</td><td><code>longanwen_v3.1</code></td></tr></table>
<h4>English voices</h4><table><tr><th>Name</th><th>Voice ID</th></tr>
<tr><td>Emily</td><td>Emily_v3.1</td></tr></table>
<h3>qwen-audio-3.0-tts-flash</h3><table><tr><th>Name</th><th>Voice ID</th></tr>
<tr><td>Wrong model</td><td>wrong_voice</td></tr></table>'''


@pytest.mark.parametrize('embedded', [False, True])
def test_voice_parser_isolates_model_and_preserves_case(embedded):
    page = HTML
    if embedded:
        props = {'docDetailData': {'storeData': {'data': {'content': HTML}}}}
        page = '<script>window.__ICE_PAGE_PROPS__=' + json.dumps(props) + ';</script>'
    assert tts_voices.parse_system_voices(page, 'qwen-audio-3.1-tts-flash') == [
        {'id': 'longanwen_v3.1', 'name': '龙安温'}, {'id': 'Emily_v3.1', 'name': 'Emily'}]
    assert tts_voices.parse_system_voices(page, 'missing') == []
    assert tts_voices.parse_system_voices(page, 'qwen-audio-3.1-tts') == []


def test_voice_information_cells_and_real_time_section():
    html = '''<h2>Real-time</h2><p>The following voices support qwen3-tts-flash-realtime.</p>
    <table><tr><th>Voice information</th><th>Languages</th></tr>
    <tr><td><p>Name: Cherry</p><p>voice parameter: <code>Cherry</code></p><p>Description: Sunny voice</p></td><td>Chinese</td></tr>
    <tr><td><p>Name: Elder</p><p>voice parameter: Eldric Sage</p><p>Description: Calm</p></td></tr></table>
    <h2>Non-real-time</h2><p>qwen3-tts-flash</p><table><tr><td>voice parameter: Wrong</td></tr></table>'''
    assert [v['id'] for v in tts_voices.parse_system_voices(html, 'qwen3-tts-flash-realtime')] == ['Cherry', 'Eldric Sage']
    chinese = html.replace('Name: Cherry', '名称：芊悦').replace('voice parameter: ', 'voice <b>参数</b>：')
    voice = tts_voices.parse_system_voices(chinese, 'qwen3-tts-flash-realtime')[0]
    assert voice['id']=='Cherry' and voice['name']=='芊悦'
    assert voice['description']=='Sunny voice'


def test_voice_preview_and_description_stay_with_their_model_and_row():
    html = '''<h3>qwen-audio-3.1-tts-flash</h3><table>
    <tr><th>Name</th><th>Voice ID</th><th>Gender</th><th>Voice characteristics</th><th>Preview</th></tr>
    <tr><td>温柔女声</td><td>first</td><td>女</td><td>优雅</td><td><audio src="https://g-adoc.alcasset.com/first.wav"></audio></td></tr>
    <tr><td>男声</td><td>second</td><td>男</td><td>清晰</td><td><audio><source src="https://g-adoc.alcasset.com/second.mp3"></audio></td></tr>
    <tr><td>无试听</td><td>third</td><td>女</td><td></td><td><audio src="javascript:bad"></audio></td></tr>
    </table><h3>qwen-audio-other-tts</h3><table><tr><td>voice parameter: wrong</td><td><audio src="https://example.com/wrong.wav"></audio></td></tr></table>'''
    voices = tts_voices.parse_system_voices(html, 'qwen-audio-3.1-tts-flash')
    assert [voice['id'] for voice in voices] == ['first', 'second', 'third']
    assert voices[0]['previewUrl']=='https://g-adoc.alcasset.com/first.wav'
    assert voices[1]['previewUrl']=='https://g-adoc.alcasset.com/second.mp3'
    assert voices[0]['description']=='女 · 优雅'
    assert voices[1]['description']=='男 · 清晰'
    assert 'previewUrl' not in voices[2]


def test_voice_discovery_is_owner_only_draft_model_read_only_and_no_credentials(tmp_path, monkeypatch):
    settings = settings_for(tmp_path)
    calls = []
    original_client = httpx.Client
    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=HTML)
    monkeypatch.setattr(tts_voices.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    with TestClient(create_app(settings)) as client:
        headers = login(client)
        before = settings.model_config_path.read_bytes() if settings.model_config_path.exists() else None
        path = '/api/v1/model-configs/dashscope/voices/tts'
        payload = {'model': 'qwen-audio-3.1-tts-flash'}
        assert client.post(path, json=payload).status_code == 401
        assert client.post(path, headers=headers, json={'model': '   '}).status_code == 422
        result = client.post(path, headers=headers, json=payload)
        assert result.status_code == 200 and len(result.json()['voices']) == 2
        assert result.json()['model'] == payload['model']
        assert result.headers['cache-control'] == 'no-store'
        assert len(calls) == 1 and 'authorization' not in calls[0].headers
        assert str(calls[0].url) == 'https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list'
        assert client.post('/api/v1/model-configs/volcengine/voices/tts', headers=headers, json=payload).status_code == 422
        assert client.post(path, headers=headers, json={'model':'qwen-audio-unknown-tts'}).status_code == 502
        client.post('/api/v1/auth/register',json={'username':'guest','password':'strong-password-123'})
        token=client.post('/api/v1/auth/login',json={'username':'guest','password':'strong-password-123'}).json()['accessToken']
        assert client.post(path,headers={'Authorization':'Bearer '+token},json=payload).status_code == 403
        after = settings.model_config_path.read_bytes() if settings.model_config_path.exists() else None
        assert before == after


def test_voice_fetch_reports_vendor_failures_and_unknown_models(monkeypatch):
    with pytest.raises(tts_voices.VoiceListError):
        tts_voices.fetch_system_voices('unrelated-model')
    original_client = httpx.Client
    monkeypatch.setattr(tts_voices.httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(lambda request: httpx.Response(503)), **kwargs))
    with pytest.raises(tts_voices.VoiceListError):
        tts_voices.fetch_system_voices('qwen-audio-3.1-tts-flash')


def test_short_preview_uses_selected_voice_and_saved_key_without_saving(tmp_path, monkeypatch):
    settings=settings_for(tmp_path)
    write_preferences(settings.model_config_path,{'providers':{'dashscope':{'name':'Qwen','runtimeProvider':'dashscope','apiKey':'private-test-key','configs':{}}},'active':{}})
    before=settings.model_config_path.read_bytes()
    seen=[]
    def synthesize(config,text):
        seen.append((config,text))
        yield b'test-mp3'
    monkeypatch.setattr(routes,'stream_mp3',synthesize)
    payload={'baseUrl':'wss://ws-test.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference','model':'qwen-audio-3.1-tts-flash','voice':'longanwen_v3.1'}
    with TestClient(create_app(settings)) as client:
        headers=login(client)
        path='/api/v1/model-configs/dashscope/voices/tts/preview'
        assert client.post(path,json=payload).status_code==401
        result=client.post(path,headers=headers,json=payload)
        assert result.status_code==200 and result.content==b'test-mp3'
        assert result.headers['cache-control']=='no-store'
        assert seen[0][0].voice==payload['voice'] and seen[0][0].api_key=='private-test-key'
        def fail(config,text):raise ValueError('private-test-key')
        monkeypatch.setattr(routes,'stream_mp3',fail)
        result=client.post(path,headers=headers,json=payload)
        assert result.status_code==502 and 'private-test-key' not in result.text
    assert settings.model_config_path.read_bytes()==before
