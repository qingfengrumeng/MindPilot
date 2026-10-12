"""Small provider probes. No probe changes saved settings or active model routes."""
import json
from time import perf_counter

import httpx
import websocket

from app.services.asr_transcription import _event, _url
from app.services.embedding_generation import embed_texts
from app.services.rerank_generation import rerank_texts
from app.services.tts_synthesis import stream_mp3
from app.services.volcengine_speech import VolcAsrSession


def probe_model(config):
    started = perf_counter()
    kind = '模型响应'
    if config.category in {'text', 'image'}:
        with httpx.Client(timeout=25, follow_redirects=False, trust_env=False) as client:
            headers = {'Authorization': f'Bearer {config.api_key}'}
            if config.category == 'text':
                response = client.post(config.base_url.rstrip('/') + '/chat/completions', headers=headers,
                    json={'model': config.model, 'messages': [{'role': 'user', 'content': 'Reply OK'}], 'max_tokens': 8, 'stream': False})
            else:
                response = client.get(config.base_url.rstrip('/') + '/models', headers=headers)
                kind = '图像服务鉴权（未生成图片）'
            if response.status_code not in range(200, 300):
                raise RuntimeError(f'连接测试失败（HTTP {response.status_code}），请检查接口地址、密钥和模型权限')
            body = response.json()
            if config.category == 'text':
                if not body.get('choices') or not isinstance(body['choices'][0].get('message'), dict):
                    raise RuntimeError('服务未返回有效的模型响应')
            elif not isinstance(body.get('data'), list):
                raise RuntimeError('图像服务未返回有效的鉴权响应')
    elif config.category == 'embedding':
        embed_texts(config, ['连接测试'])
    elif config.category == 'reranker':
        rerank_texts(config, '连接测试', ['连接测试'], top_n=1)
    elif config.category == 'tts':
        stream = stream_mp3(config, '好')
        try:
            if not next(stream, None):
                raise RuntimeError('语音服务未返回音频')
        finally:
            stream.close()
        kind = '语音首段响应'
    elif config.category == 'asr':
        kind = '语音连接与会话校验'
        if config.provider == 'volcengine':
            session = VolcAsrSession(config)
            session.close()
        else:
            connection = websocket.create_connection(_url(config), timeout=15,
                header=[f'Authorization: Bearer {config.api_key}', 'OpenAI-Beta: realtime=v1'])
            try:
                connection.send(_event('session.update', session={'modalities': ['text'], 'input_audio_format': 'pcm', 'sample_rate': 16000, 'turn_detection': None}))
                for _ in range(8):
                    event = json.loads(connection.recv())
                    if event.get('type') == 'session.updated':
                        break
                    if event.get('type') == 'error':
                        raise RuntimeError('语音服务未接受会话配置')
                else:
                    raise RuntimeError('语音服务未确认连接')
            finally:
                connection.close()
    else:
        raise RuntimeError('当前类别不支持连接测试')
    return {'ok': True, 'latencyMs': round((perf_counter() - started) * 1000, 1), 'checked': kind}
