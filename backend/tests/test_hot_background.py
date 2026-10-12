import json
import threading
import time
from tests.test_workbench import _client, _login
from app.api.routes import workbench
from app.core.model_runtime import RuntimeModel


def wait_status(client,headers,status):
    for _ in range(100):
        result=client.get('/api/v1/workbench/hot-sync',headers=headers).json()
        if result['status']==status:return result
        time.sleep(.02)
    raise AssertionError(result)


def test_background_task_continues_without_stream_and_restores_private_progress(tmp_path,monkeypatch):
    monkeypatch.setattr(workbench,'require_runtime_model',lambda *args:RuntimeModel('text','test','https://example.com','test','secret'))
    monkeypatch.setattr(workbench,'_authorization',lambda *args:'Bearer search-secret')
    entered,release=threading.Event(),threading.Event()
    def run(self,prefs,existing,cancelled):
        yield {'type':'progress','stage':'searching','detail':'正在联网搜索','round':1}
        entered.set();release.wait(5)
        assert not cancelled.is_set()
        yield {'type':'result','articles':[{'title':'真实来源热点测试','summary':'基于测试来源整理的摘要内容','body':'基于来源事实整理的正文内容，不自动向量化。',
            'sources':[{'url':'https://example.com/news','title':'来源','publishedAt':'2026-10-11'}],
            'publishedAt':'2026-10-11','eventKey':'a'*64,'evidence':[]}],'searched':1,'requested':prefs.max_items,'warnings':[]}
    monkeypatch.setattr(workbench.HotAgent,'run',run)
    with _client(tmp_path) as client:
        alice,bob=_login(client,'alice'),_login(client,'bob')
        path='/api/v1/workbench/hot-sync'
        assert client.get(path).status_code==401 and client.post(path).status_code==401
        assert client.get(path,headers=alice).json()['status']=='idle'
        try:
            response=client.post(path,headers=alice)
            assert response.status_code==202,response.text
            assert entered.wait(2)
            assert client.post(path,headers=alice).status_code==409
            assert client.get(path,headers=bob).json()['status']=='idle'
            # Requesting another page/data does not disconnect or cancel the job.
            assert client.get('/api/v1/documents',headers=alice).status_code==200
            status=client.get(path,headers=alice).json()
            assert status['status']=='running' and status['stage']=='searching'
            assert 'secret' not in json.dumps(status)
        finally:release.set()
        done=wait_status(client,alice,'completed')
        assert done['imported']==1 and done['id']==response.json()['id']
        assert client.get('/api/v1/workbench/items?kind=hot',headers=alice).json()['total']==1
        def fail(self,*args):
            yield {'type':'progress','stage':'organizing','detail':'正在整理'}
            raise workbench.HotAgentError('内容整理阶段失败')
        monkeypatch.setattr(workbench.HotAgent,'run',fail)
        assert client.post(path,headers=alice).status_code==202
        assert wait_status(client,alice,'failed')['detail']=='内容整理阶段失败'
        assert client.get('/api/v1/workbench/items?kind=hot',headers=alice).json()['total']==1
        assert not workbench._hot_runs
