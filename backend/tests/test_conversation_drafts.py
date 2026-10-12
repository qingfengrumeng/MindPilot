from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AgentRun, Conversation, ConversationInheritance, ConversationMap, Message, User
from app.main import create_app
from test_model_configs import settings_for, login


def test_repeated_and_concurrent_creation_reuses_one_default_draft(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        headers = login(client)
        def create():
            result = client.post('/api/v1/conversations', headers=headers, json={'title': '新会话'})
            assert result.status_code == 201
            return result.json()['id']
        with ThreadPoolExecutor(max_workers=5) as pool:
            ids = list(pool.map(lambda _: create(), range(5)))
        assert len(set(ids)) == 1
        assert create() == ids[0]
        rows = client.get('/api/v1/conversations', headers=headers).json()['items']
        assert len(rows) == 1 and rows[0]['messages'] == 0
        client.post(f'/api/v1/conversations/{ids[0]}/messages', headers=headers,
                    json={'role': 'user', 'content': '实际发送的问题'})
        assert create() != ids[0]
        rows = client.get('/api/v1/conversations', headers=headers).json()['items']
        assert len(rows) == 2


def test_legacy_duplicates_are_cleaned_without_losing_content_or_branch_context(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        headers = login(client)
        with app.state.session_factory() as db:
            user = db.scalar(select(User))
            duplicate = [Conversation(user_id=user.id, title='新会话') for _ in range(3)]
            named = Conversation(user_id=user.id, title='用户命名的工作')
            history = Conversation(user_id=user.id, title='新会话')
            branch = Conversation(user_id=user.id, title='新会话')
            run = Conversation(user_id=user.id, title='新会话')
            skill = Conversation(user_id=user.id, title='新会话', task_id='mindmap')
            db.add_all([*duplicate, named, history, branch, run, skill]); db.flush()
            db.add(Message(conversation_id=history.id, role='assistant', content='已有内容也不能删除'))
            db.add(ConversationInheritance(conversation_id=branch.id, source_id=history.id, mode='digest', context='保留的分支上下文'))
            db.add(AgentRun(conversation_id=run.id, trace_json={'status': 'running'}))
            db.add(ConversationMap(user_id=user.id, state_json={'nodes': {item.id: {'x': 1} for item in duplicate},
                'groups': [], 'edges': [{'source': duplicate[0].id, 'target': history.id}]}))
            protected = {named.id, history.id, branch.id, run.id, skill.id}
            blank_ids = {item.id for item in duplicate}
            db.commit()
        rows = client.get('/api/v1/conversations', headers=headers).json()['items']
        remaining = {row['id'] for row in rows}
        assert protected <= remaining and len(remaining & blank_ids) == 1
        result = client.post('/api/v1/conversations', headers=headers, json={}).json()
        assert result['id'] in blank_ids & remaining
        with app.state.session_factory() as db:
            board = db.scalar(select(ConversationMap)).state_json
            assert set(board['nodes']) == blank_ids & remaining
            assert all(edge['source'] in remaining for edge in board['edges'])
        # Repeated list loads preserve the remaining draft's identity.
        assert {row['id'] for row in client.get('/api/v1/conversations', headers=headers).json()['items']} == remaining


def test_empty_drafts_are_isolated_between_accounts(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        owner_headers = login(client)
        owner_id = client.post('/api/v1/conversations', headers=owner_headers, json={}).json()['id']
        client.post('/api/v1/auth/register', json={'username': 'other', 'password': 'strong-password-123'})
        token = client.post('/api/v1/auth/login', json={'username': 'other', 'password': 'strong-password-123'}).json()['accessToken']
        other_headers = {'Authorization': 'Bearer ' + token}
        other_id = client.post('/api/v1/conversations', headers=other_headers, json={}).json()['id']
        assert other_id != owner_id
        assert len(client.get('/api/v1/conversations', headers=owner_headers).json()['items']) == 1
        assert len(client.get('/api/v1/conversations', headers=other_headers).json()['items']) == 1
