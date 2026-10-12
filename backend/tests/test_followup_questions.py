import json
import pytest
from app.services.followup_questions import generate_followups
from app.api.routes import conversations
from app.core.model_runtime import RuntimeModel
from tests.test_workbench import _client,_login


ITEMS=[{'title':'理解关键概念','question':'请解释 RAG 中检索和生成各自的作用。'},
       {'title':'实际操作示例','question':'如何用我的资料搭建一个小型 RAG 示例？'},
       {'title':'选择评测指标','question':'如何评估 RAG 的检索质量与回答质量？'}]


def test_three_contextual_suggestions_and_no_duplicate_or_invalid_payload():
    calls=[]
    def complete(config,messages):
        calls.append(messages)
        return '```json\n'+json.dumps({'items':ITEMS},ensure_ascii=False)+'\n```',{}
    result=generate_followups(None,'什么是 RAG？','RAG 将检索结果用于生成回答。',complete)
    assert result['items']==ITEMS
    assert json.loads(calls[0][1]['content'])['question']=='什么是 RAG？'
    for values in [ITEMS[:2],[ITEMS[0]]*3]:
        with pytest.raises(ValueError):generate_followups(None,'RAG','回答',lambda *a:(json.dumps({'items':values}),{}))


def test_suggestions_are_owner_scoped_and_never_added_to_history(tmp_path,monkeypatch):
    monkeypatch.setattr(conversations,'require_runtime_model',lambda *a:RuntimeModel('text','test','https://example.com','test','private-key'))
    monkeypatch.setattr(conversations,'complete_text',lambda *a:(json.dumps({'items':ITEMS},ensure_ascii=False),{}))
    with _client(tmp_path) as client:
        alice,bob=_login(client,'alice'),_login(client,'bob')
        conversation=client.post('/api/v1/conversations',headers=alice,json={'title':'RAG讨论'}).json()
        path=f"/api/v1/conversations/{conversation['id']}/messages"
        user=client.post(path,headers=alice,json={'role':'user','content':'什么是RAG？'}).json()
        reply=client.post(path,headers=alice,json={'role':'assistant','content':'RAG结合检索与生成。'}).json()
        target=f"{path}/{reply['id']}/suggestions"
        before=client.get(path,headers=alice).json()
        assert client.post(target).status_code==401
        assert client.post(target,headers=bob).status_code==404
        assert client.post(f"{path}/{user['id']}/suggestions",headers=alice).status_code==404
        response=client.post(target,headers=alice)
        assert response.status_code==200,response.text
        assert response.json()['items']==ITEMS
        assert 'private-key' not in response.text
        assert client.get(path,headers=alice).json()==before


def test_question_based_suggestions_start_without_waiting_for_reply_and_do_not_save(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(conversations,'require_runtime_model',lambda *a:RuntimeModel('text','test','https://example.com','test','private-key'))
    def complete(config,messages):
        calls.append(messages);return json.dumps({'items':ITEMS},ensure_ascii=False),{}
    monkeypatch.setattr(conversations,'complete_text',complete)
    with _client(tmp_path) as client:
        alice,bob=_login(client,'alice'),_login(client,'bob')
        conversation=client.post('/api/v1/conversations',headers=alice,json={'title':'并行推荐'}).json()
        path=f"/api/v1/conversations/{conversation['id']}"
        assert client.get(path+'/messages',headers=alice).json()['items']==[]
        assert client.post(path+'/suggestions',json={'question':'RAG是什么？'}).status_code==401
        assert client.post(path+'/suggestions',headers=bob,json={'question':'RAG是什么？'}).status_code==404
        assert client.post(path+'/suggestions',headers=alice,json={'question':' '}).status_code==422
        result=client.post(path+'/suggestions',headers=alice,json={'question':'RAG是什么？'})
        assert result.status_code==200 and result.json()['items']==ITEMS
        assert json.loads(calls[0][1]['content'])=={'question':'RAG是什么？','answer':''}
        assert client.get(path+'/messages',headers=alice).json()['items']==[]
        monkeypatch.setattr(conversations,'complete_text',lambda *a:('not json',{}))
        assert client.post(path+'/suggestions',headers=alice,json={'question':'RAG是什么？'}).status_code==503
        assert client.get(path+'/messages',headers=alice).json()['items']==[]
