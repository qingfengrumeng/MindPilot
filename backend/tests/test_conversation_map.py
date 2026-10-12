from app.core.model_preferences import write_preferences
from app.db.models import ConversationInheritance
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from tests.test_api import client_for, headers, login, register


def test_synapse_branch_freezes_selected_turn_and_nested_ancestry(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        access = headers(login(client).json()['accessToken'])
        source = client.post('/api/v1/conversations', headers=access, json={'title': 'root'}).json()['id']
        ids = []
        for role, content in [('user', 'question one'), ('assistant', 'answer one'), ('user', 'later question'), ('assistant', 'later answer')]:
            ids.append(client.post(f'/api/v1/conversations/{source}/messages', headers=access,
                                   json={'role': role, 'content': content}).json()['id'])
        response = client.post('/api/v1/conversation-map/branch', headers=access,
                               json={'sourceId': source, 'sourceMessageId': ids[1], 'mode': 'full', 'title': 'branch'})
        assert response.status_code == 200
        branch = response.json()['id']
        with client.app.state.session_factory() as db:
            inherited = db.get(ConversationInheritance, branch).context
            assert 'answer one' in inherited
            assert 'later question' not in inherited and 'later answer' not in inherited
        client.post(f'/api/v1/conversations/{branch}/messages', headers=access, json={'content': 'child question'})
        answer = client.post(f'/api/v1/conversations/{branch}/messages', headers=access,
                             json={'role': 'assistant', 'content': 'child answer'}).json()['id']
        nested = client.post('/api/v1/conversation-map/branch', headers=access,
                             json={'sourceId': branch, 'sourceMessageId': answer, 'mode': 'full', 'title': 'nested'}).json()['id']
        with client.app.state.session_factory() as db:
            inherited = db.get(ConversationInheritance, nested).context
            assert 'question one' in inherited and 'child answer' in inherited
            assert 'later answer' not in inherited
        assert client.post('/api/v1/conversation-map/branch', headers=access,
                           json={'sourceId': source, 'sourceMessageId': answer, 'mode': 'full'}).status_code == 404
        assert client.post('/api/v1/conversation-map/branch', headers=access,
                           json={'sourceId': source, 'sourceMessageId': ids[0], 'mode': 'full'}).status_code == 404
        state = {'nodes': {source: {'synapseSequences': {ids[0]: 1, ids[1]: 2}}},
                 'synapse': {'dsh-synapse:card-positions:v3': '[["card",{"x":123,"y":456}]]'}}
        assert client.put('/api/v1/conversation-map', headers=access, json=state).status_code == 200
        assert client.get('/api/v1/conversation-map', headers=access).json()['state']['synapse'] == state['synapse']
        register(client, username='bob')
        bob = headers(login(client, username='bob').json()['accessToken'])
        assert client.get('/api/v1/conversation-map', headers=bob).json()['state']['synapse'] == {}
        assert client.get(f'/api/v1/conversations/{source}/agent-runs', headers=bob).status_code == 404
        assert client.post('/api/v1/conversation-map/branch', headers=bob,
                           json={'sourceId': source, 'sourceMessageId': ids[1], 'mode': 'full'}).status_code == 404


def test_map_classifies_conversations_by_task_and_historical_feature_calls(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        auth = headers(login(client).json()['accessToken'])
        plain = client.post('/api/v1/conversations', headers=auth,
                            json={'title': 'plain', 'taskId': 'general'}).json()['id']
        called = client.post('/api/v1/conversations', headers=auth,
                             json={'title': 'called', 'taskId': 'general'}).json()['id']
        dedicated = client.post('/api/v1/conversations', headers=auth,
                                json={'title': 'dedicated', 'taskId': 'mindmap'}).json()['id']
        for conversation_id, metadata in (
            (plain, {}),
            (called, {'skill': {'id': 'mindmap', 'label': 'Mind map'}}),
        ):
            response = client.post(f'/api/v1/conversations/{conversation_id}/messages', headers=auth,
                                   json={'role': 'user', 'content': 'first', 'metadata': metadata})
            assert response.status_code == 201
            response = client.post(f'/api/v1/conversations/{conversation_id}/messages', headers=auth,
                                   json={'role': 'user', 'content': 'later plain message'})
            assert response.status_code == 201
        previews = client.get('/api/v1/conversation-map', headers=auth).json()['previews']
        assert previews[plain]['hasFeatureDomain'] is False
        assert previews[called]['hasFeatureDomain'] is True
        assert previews[dedicated]['hasFeatureDomain'] is True


def test_map_injection_persists_context_and_rejects_cross_region_links(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        auth = headers(login(client).json()['accessToken'])
        ids = [client.post('/api/v1/conversations', headers=auth,
                           json={'title': title}).json()['id'] for title in ('source', 'target', 'other')]
        source, target, other = ids
        client.post(f'/api/v1/conversations/{source}/messages', headers=auth,
                    json={'role': 'user', 'content': 'important decision'})
        client.post(f'/api/v1/conversations/{source}/messages', headers=auth,
                    json={'role': 'assistant', 'content': 'Use the agreed approach.'})
        state = {'nodes': {source: {'x': 0, 'y': 0, 'groupId': 'a'},
                           target: {'x': 100, 'y': 0, 'groupId': 'a'},
                           other: {'x': 300, 'y': 0, 'groupId': 'b'}},
                 'groups': [], 'edges': [], 'viewport': {'x': 0, 'y': 0, 'zoom': 1}}
        assert client.put('/api/v1/conversation-map', headers=auth, json=state).status_code == 200
        payload = {'sourceId': source, 'targetId': target, 'mode': 'digest'}
        assert client.post('/api/v1/conversation-map/inject', headers=auth, json=payload).status_code == 200
        with client.app.state.session_factory() as db:
            assert 'Use the agreed approach.' in db.get(ConversationInheritance, target).context
        assert client.post('/api/v1/conversation-map/inject', headers=auth,
                           json={**payload, 'targetId': other}).status_code == 400
        assert client.post('/api/v1/conversation-map/inject', headers=auth,
                           json={**payload, 'targetId': source}).status_code == 400
        assert client.post('/api/v1/conversation-map/inject', headers=auth,
                           json={**payload, 'mode': 'full'}).status_code == 200
        with client.app.state.session_factory() as db:
            assert 'important decision' in db.get(ConversationInheritance, target).context


def test_map_persists_and_branch_inherits_only_owned_source(tmp_path):
    with client_for(tmp_path) as client:
        register(client)
        alice = headers(login(client).json()["accessToken"])
        source = client.post("/api/v1/conversations", headers=alice, json={"title": "项目规划"}).json()["id"]
        client.post(f"/api/v1/conversations/{source}/messages", headers=alice,
                    json={"role": "user", "content": "实现地图与分支"})
        client.post(f"/api/v1/conversations/{source}/messages", headers=alice,
                    json={"role": "assistant", "content": "先建立地图，再接分支。"})
        assert client.get('/api/v1/conversation-map', headers=alice).json()['previews'][source]['status'] == 'done'
        client.post(f"/api/v1/conversations/{source}/messages", headers=alice,
                    json={"role": "user", "content": "下一步先建立项目区域"})
        waiting = client.get('/api/v1/conversation-map', headers=alice).json()['previews'][source]
        assert waiting['status'] == 'waiting'
        assert '项目区域' in waiting['summary']
        board = {"nodes": {source: {"x": 128, "y": 256,
                                   "digest": {"summary": "项目地图规划", "keyFindings": "需要连线", "nextStep": "创建分支"}}},
                 "groups": [{"id": "region-1", "title": "项目", "x": 64, "y": 100,
                             "width": 500, "height": 400, "color": "#7c3aed"}],
                 "edges": [], "viewport": {"x": 2, "y": 3, "zoom": 1}}
        assert client.put("/api/v1/conversation-map", headers=alice, json=board).status_code == 200
        assert client.get("/api/v1/conversation-map", headers=alice).json()["state"] == board
        branch = client.post("/api/v1/conversation-map/branch", headers=alice,
                             json={"sourceId": source, "mode": "digest", "title": "实现分支"})
        assert branch.status_code == 200
        branch_id = branch.json()["id"]
        preview = client.post("/api/v1/conversation-map/branch-preview", headers=alice,
                              json={"sourceId": source, "mode": "digest"})
        assert preview.status_code == 200
        assert "项目地图规划" in preview.json()["context"]
        with client.app.state.session_factory() as db:
            inheritance = db.get(ConversationInheritance, branch_id)
            assert "项目地图规划" in inheritance.context
            assert "创建分支" in inheritance.context
        full = client.post("/api/v1/conversation-map/branch", headers=alice,
                           json={"sourceId": source, "mode": "full", "title": "完整继承"})
        assert full.status_code == 200
        with client.app.state.session_factory() as db:
            assert "实现地图与分支" in db.get(ConversationInheritance, full.json()["id"]).context
        register(client, username="bob")
        bob = headers(login(client, username="bob").json()["accessToken"])
        assert client.get("/api/v1/conversation-map", headers=bob).json()["state"]["nodes"] == {}
        assert client.post("/api/v1/conversation-map/branch", headers=bob,
                           json={"sourceId": source, "mode": "full", "title": "越权"}).status_code == 404
        assert client.post("/api/v1/conversation-map/branch-preview", headers=bob,
                           json={"sourceId": source, "mode": "full"}).status_code == 404
        assert client.put("/api/v1/conversation-map", headers=bob, json=board).status_code == 400

    with client_for(tmp_path) as client:
        alice = headers(login(client).json()["accessToken"])
        assert client.get("/api/v1/conversation-map", headers=alice).json()["state"]["groups"][0]["title"] == "项目"


def test_branch_context_reaches_model_without_appearing_as_chat_message(tmp_path, monkeypatch):
    env_path = tmp_path / 'models.json'
    write_preferences(env_path, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-secret', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'test-model'}}}}, 'active': {'text': 'deepseek'}})
    for field in ('PROVIDER', 'BASE_URL', 'MODEL', 'API_KEY'):
        monkeypatch.delenv(f'MINDPILOT_TEXT_{field}', raising=False)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'reply.db').as_posix()}",
                        jwt_secret='test-secret-longer-than-thirty-two-bytes-for-jwt',
                        allowed_origins=('http://localhost:5173',), model_config_path=env_path)
    seen = []

    def fake_complete(_config, messages):
        seen.append(messages)
        return '已继续', {'model': 'test-model', 'latencyMs': 1, 'tokens': {'input': 1, 'output': 1}}

    monkeypatch.setattr('app.api.routes.conversations.complete_text', fake_complete)
    with TestClient(create_app(settings)) as client:
        register(client)
        auth = headers(login(client).json()['accessToken'])
        source = client.post('/api/v1/conversations', headers=auth, json={'title': '来源'}).json()['id']
        branch = client.post('/api/v1/conversation-map/branch', headers=auth,
                             json={'sourceId': source, 'mode': 'digest', 'title': '分支',
                                   'context': '重要决策：使用 SQLite 保存地图'}).json()['id']
        result = client.post(f'/api/v1/conversations/{branch}/reply', headers=auth, json={'content': '继续实现'})
        assert result.status_code == 200, result.text
        assert any('重要决策：使用 SQLite 保存地图' in item['content'] for item in seen[0] if item['role'] == 'system')
        stored = client.get(f'/api/v1/conversations/{branch}/messages', headers=auth).json()['items']
        assert [item['content'] for item in stored] == ['继续实现', '已继续']


def test_digest_returns_structured_summary_and_falls_back_on_bad_model_json(tmp_path, monkeypatch):
    monkeypatch.setattr('app.api.routes.conversation_map.require_runtime_model', lambda *_: object())
    monkeypatch.setattr('app.api.routes.conversation_map.complete_text',
                        lambda *_: ('{"summary":"已完成地图设计","keyFindings":"需要区域与连线","nextStep":"实现分支"}', {}))
    with client_for(tmp_path) as client:
        register(client)
        auth = headers(login(client).json()['accessToken'])
        source = client.post('/api/v1/conversations', headers=auth, json={'title': '地图任务'}).json()['id']
        client.post(f'/api/v1/conversations/{source}/messages', headers=auth,
                    json={'role': 'user', 'content': '请设计会话地图'})
        digest = client.post(f'/api/v1/conversation-map/{source}/digest', headers=auth)
        assert digest.status_code == 200
        assert digest.json()['nextStep'] == '实现分支'
        monkeypatch.setattr('app.api.routes.conversation_map.complete_text', lambda *_: ('not json', {}))
        fallback = client.post(f'/api/v1/conversation-map/{source}/digest', headers=auth)
        assert fallback.status_code == 200
        assert fallback.json()['summary'] == '请设计会话地图'
