from datetime import datetime, timedelta, timezone
import json
import threading
from types import SimpleNamespace

from app.agents.hot_agent import HotAgent, canonical_url, source_date
from app.api.routes.workbench import HotPreferences

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone(timedelta(hours=8)))
TEXT = '某公司发布新的检索模型，支持多语种文本检索，评测结果和方法已公开，适用于知识库检索场景。'
TEXT += ('发布材料说明了检索方法、数据构成、评测条件和适用范围。模型针对不同语言的表达方式进行处理，'
         '通过公开样例展示如何使用向量建立索引并查询相关资料。研究团队比较了多个检索基线，报告了测试集上的'
         '准确率、召回率和耗时，明确指出结果只适用于本次实验条件。对于企业知识库，材料建议先验证数据质量，'
         '检查分块边界和权限控制，再进行检索效果评估。团队公开了部署步骤、参数配置和复现实验的说明，便于使用者'
         '按自己的业务数据再次测试。材料也说明了当前模型在少见术语、混合语言输入和极短查询上的局限，后续会继续'
         '收集问题样本，改进训练与评测流程。发布方提醒，不同领域的数据分布可能造成效果变化，使用者应结合实际'
         '问题进行评估，而不能将某一项成绩作为所有场景的性能承诺。')


def ref(number, text=TEXT, date='2026-10-11 08:00:00'):
    return {'url':f'https://example.com/{number}','title':f'检索模型新闻{number}','date':date,'content':text}


def article(title, ids, quote=TEXT[:24], merge=None):
    return {'title':title,'summary':'公司发布检索模型，公开评测方法并支持多语种检索。',
            'mergeInto':merge, 'paragraphs':[{'text':TEXT,'evidence':[{'sourceId':number,'quote':quote} for number in ids]}]}


def test_merges_sources_supplements_and_filters_dates_urls_and_existing_events():
    searched=[]; organized=[]
    def complete(config,messages):
        system=messages[0]['content']; data=json.loads(messages[1]['content'])
        if '搜索Agent' in system:
            return json.dumps({'queries':[f"检索模型最新发布 第{data['round']}轮"]}),{}
        if '事实校验Agent' in system:
            return json.dumps({'approved':list(range(len(data['candidates'])))}),{}
        organized.append(data)
        ids=[source['id'] for source in data['sources']]
        return json.dumps({'articles':[article('首个检索模型发布' if not data['existingDrafts'] else '另一个研究进展',ids)]},ensure_ascii=False),{}
    def search(query,**kwargs):
        searched.append((query,kwargs))
        rows=([ref('a'),ref('a'),ref('b'),ref('old',date='2026-09-01'),ref('missing',date=''),ref('future',date='2027-01-01'),ref('existing')]
              if len(searched)==1 else [ref('new')])
        return {'result':{'references':rows}}
    existing=[SimpleNamespace(title='已存在事件',data_json={'sourceUrl':'https://example.com/existing'})]
    agent=HotAgent(None,'test-config',complete=complete,search_tool=search,now=NOW)
    events=list(agent.run(HotPreferences(direction='检索模型最新进展',maxItems=2),existing,threading.Event()))
    result=events[-1]
    assert result['type']=='result' and len(result['articles'])==2
    assert len(result['articles'][0]['sources'])==2
    assert len(searched)==2
    assert all(kwargs['freshness']=='week' and kwargs['config_path']=='test-config' for _,kwargs in searched)
    assert any(event.get('stage')=='supplementing' for event in events)
    assert len(organized[0]['sources'])==2
    assert 'original' not in result['articles'][0]


def test_invalid_evidence_is_rejected_and_search_is_bounded():
    def complete(config,messages):
        data=json.loads(messages[1]['content'])
        if '搜索Agent' in messages[0]['content']: result={'queries':[f"新闻{data['round']}"]}
        elif '事实校验Agent' in messages[0]['content']: result={'approved':[0,1,999]}
        else: result={'articles':[article('虚构来源的新闻',[999]),article('虚构引文的新闻',[data['sources'][0]['id']],quote='这是一段原文不存在的句子') ]}
        return json.dumps(result,ensure_ascii=False),{}
    calls=[]
    def search(query,**kwargs):
        calls.append(query);return {'result':{'references':[ref(len(calls))]}}
    result=list(HotAgent(None,None,complete=complete,search_tool=search,now=NOW).run(HotPreferences(maxItems=2),[],threading.Event()))[-1]
    assert result['articles']==[] and len(calls)==3 and result['warnings']


def test_excess_articles_are_trimmed_and_cancel_prevents_further_calls():
    calls=[]
    def complete(config,messages):
        data=json.loads(messages[1]['content']);calls.append(messages[0]['content'])
        if '搜索Agent' in calls[-1]: result={'queries':['新闻']}
        elif '事实校验Agent' in calls[-1]: result={'approved':[0,1]}
        else: result={'articles':[article('检索模型发布',[1]),article('另一个模型发布',[2])]}
        return json.dumps(result,ensure_ascii=False),{}
    search=lambda *args,**kwargs:{'result':{'references':[ref(1),ref(2)]}}
    agent=HotAgent(None,None,complete=complete,search_tool=search,now=NOW)
    result=list(agent.run(HotPreferences(maxItems=1),[],threading.Event()))[-1]
    assert len(result['articles'])==1
    cancelled=threading.Event();cancelled.set()
    assert list(agent.run(HotPreferences(),[],cancelled))==[] and len(calls)==3


def test_semantic_review_rejects_unsupported_content():
    def complete(config,messages):
        system=messages[0]['content']
        result={'queries':['新闻']} if '搜索Agent' in system else {'approved':[]} if '事实校验Agent' in system else {'articles':[article('改变原意的新闻',[1])]}
        return json.dumps(result,ensure_ascii=False),{}
    result=list(HotAgent(None,None,complete=complete,search_tool=lambda *a,**k:{'result':{'references':[ref(1)]}},now=NOW).run(HotPreferences(maxItems=1),[],threading.Event()))[-1]
    assert result['articles']==[]


def test_sources_are_canonical_and_date_missing_is_not_invented():
    assert canonical_url('https://EXAMPLE.com/news?utm_source=x&id=1#part')=='https://example.com/news?id=1'
    assert canonical_url('javascript:alert(1)')==''
    assert canonical_url('https://username:password@example.com')==''
    assert source_date('2026年10月11日').date()==NOW.date()
    assert source_date('日期未知') is None


def test_same_event_sources_across_search_rounds_merge_into_one_draft():
    searches=[]
    def search(query,**kwargs):
        searches.append(query);return {'result':{'references':[ref(len(searches))]}}
    def complete(config,messages):
        data=json.loads(messages[1]['content']);system=messages[0]['content']
        if '搜索Agent' in system: result={'queries':[f"新闻{data['round']}"]}
        elif '事实校验Agent' in system: result={'approved':[0]}
        else:
            existing=data['existingDrafts']
            result={'articles':[article('同一个检索模型发布',[data['sources'][0]['id']],merge=existing[0]['eventKey'] if existing else None)]}
        return json.dumps(result,ensure_ascii=False),{}
    result=list(HotAgent(None,None,complete=complete,search_tool=search,now=NOW).run(HotPreferences(maxItems=2),[],threading.Event()))[-1]
    assert len(result['articles'])==1 and len(result['articles'][0]['sources'])==3


def test_agent_sync_api_saves_business_records_atomically_with_multiple_sources(tmp_path,monkeypatch):
    from tests.test_workbench import _client, _login
    from app.core.model_runtime import RuntimeModel
    from app.api.routes import workbench
    monkeypatch.setattr(workbench,'require_runtime_model',lambda *args:RuntimeModel('text','test','https://example.com','test','secret-not-for-frontend'))
    monkeypatch.setattr(workbench,'_authorization',lambda *args:'Bearer test-search-secret')
    output={'title':'检索模型发布','summary':'公司发布检索模型，支持多语种检索并公开评测方法。','body':TEXT,
            'sources':[{'url':'https://example.com/a','title':'来源一','publishedAt':NOW.isoformat()},
                       {'url':'https://example.com/b','title':'来源二','publishedAt':NOW.isoformat()}],
            'publishedAt':NOW.isoformat(),'eventKey':'a'*64,'evidence':[{'sourceUrl':'https://example.com/a','quote':TEXT[:24]}]}
    calls=[]
    def run(self,prefs,existing,cancelled):
        calls.append((prefs,existing))
        yield {'type':'progress','stage':'planning','detail':'正在规划'}
        yield {'type':'result','articles':[] if existing else [output],'requested':prefs.max_items,'searched':2,'warnings':[]}
    monkeypatch.setattr(workbench.HotAgent,'run',run)
    with _client(tmp_path) as client:
        alice,bob=_login(client,'alice'),_login(client,'bob')
        path='/api/v1/workbench/hot-sync/stream'
        assert client.post(path).status_code==401
        client.put('/api/v1/workbench/hot-preferences',headers=alice,json={'topics':['医疗'],'maxItems':2})
        response=client.post(path,headers=alice)
        assert response.status_code==200,response.text
        events=[json.loads(line) for line in response.text.splitlines()]
        assert events[-1]['type']=='done' and events[-1]['imported']==1
        assert calls[-1][0].direction=='医疗'
        row=events[-1]['items'][0]
        assert row['body']==TEXT and len(row['data']['sources'])==2
        assert row['data']['evidence'][0]['sourceIndex']==0
        assert 'secret' not in response.text
        assert client.get('/api/v1/workbench/items?kind=hot',headers=bob).json()['items']==[]
        assert json.loads(client.post(path,headers=alice).text.splitlines()[-1])['imported']==0
        client.put('/api/v1/workbench/hot-preferences',headers=alice,json={'direction':'医疗', 'maxItems':None})
        assert json.loads(client.post(path,headers=alice).text.splitlines()[-1])['requested'] is None
        with workbench._hot_lock: workbench._hot_runs.add(calls[-1][1][0].user_id)
        try: assert client.post(path,headers=alice).status_code==409
        finally:
            with workbench._hot_lock: workbench._hot_runs.clear()
        def fail(self,*args):
            yield {'type':'progress','stage':'planning'}
            raise workbench.HotAgentError('热点Agent测试失败')
        monkeypatch.setattr(workbench.HotAgent,'run',fail)
        assert json.loads(client.post(path,headers=alice).text.splitlines()[-1])['type']=='error'
        assert len(client.get('/api/v1/workbench/items?kind=hot',headers=alice).json()['items'])==1
        assert not workbench._hot_runs


def test_unlimited_runs_one_search_and_preserves_all_batches_without_supplementing():
    searches=[]
    def search(query,**kwargs):
        searches.append((query,kwargs))
        return {'result':{'references':[ref(number) for number in range(20)]}}
    def complete(config,messages):
        data=json.loads(messages[1]['content']);system=messages[0]['content']
        if '搜索Agent' in system:
            assert data['direction']=='检索模型' and data['needed'] is None and data['queryCount']==1
            result={'queries':['检索模型新闻','模型额外搜索']}
        elif '事实校验Agent' in system: result={'approved':list(range(len(data['candidates'])))}
        else:
            assert data['needed'] is None
            result={'articles':[article(f"独立新闻事件{source['id']}",[source['id']]) for source in data['sources']]}
        return json.dumps(result,ensure_ascii=False),{}
    events=list(HotAgent(None,None,complete=complete,search_tool=search,now=NOW).run(HotPreferences(direction='检索模型',maxItems=None),[],threading.Event()))
    assert len(searches)==1 and len(events[-1]['articles'])==20
    assert events[-1]['requested'] is None and events[-1]['warnings']==[]
    assert not any(event.get('stage')=='supplementing' for event in events)


def test_direction_can_request_date_range_without_an_extra_preference_field():
    searches=[]
    def complete(config,messages):
        system=messages[0]['content']
        result={'queries':['最近一个月检索模型'],'lookbackDays':30} if '搜索Agent' in system else {'approved':[0]} if '事实校验Agent' in system else {'articles':[article('一个月内的新模型',[1])]}
        return json.dumps(result,ensure_ascii=False),{}
    def search(query,**kwargs):
        searches.append(kwargs)
        return {'result':{'references':[ref(1,date='2026-09-20 08:00:00')]}}
    result=list(HotAgent(None,None,complete=complete,search_tool=search,now=NOW).run(HotPreferences(direction='最近一个月的检索模型',maxItems=None),[],threading.Event()))[-1]
    assert len(result['articles'])==1 and searches[0]['freshness']=='month'
