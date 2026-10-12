import json
import threading
from app.agents.hot_agent import HotAgent, source_batches
from app.api.routes.workbench import HotPreferences
from tests.test_hot_agent import NOW, TEXT, article, ref
from tests.test_workbench import _client, _login


def test_today_then_recent_days_and_articles_sorted_newest():
    searches=[]
    def search(query,**kwargs):
        searches.append(query)
        rows=[ref('today'),ref('yesterday',date='2026-10-10 10:00:00'),ref('old',date='2026-10-05 09:00:00')]
        return {'result':{'references':rows}}
    def complete(config,messages):
        data=json.loads(messages[1]['content']);system=messages[0]['content']
        if '搜索Agent' in system: result={'queries':[f"科技新闻第{data['round']}轮"]}
        elif '事实校验Agent' in system: result={'approved':list(range(len(data['candidates'])))}
        else: result={'articles':[article(source['title'],[source['id']]) for source in data['sources']]}
        return json.dumps(result,ensure_ascii=False),{}
    events=list(HotAgent(None,None,complete=complete,search_tool=search,now=NOW).run(HotPreferences(maxItems=3),[],threading.Event()))
    assert len(searches)==3
    assert '2026-10-11 今日新闻' in searches[0]
    assert '2026-10-08至2026-10-11' in searches[1]
    assert '2026-10-04至2026-10-11' in searches[2]
    assert [row['publishedAt'][:10] for row in events[-1]['articles']]==['2026-10-11','2026-10-10','2026-10-05']


def test_today_sufficient_does_not_search_older_days():
    calls=[]
    def complete(config,messages):
        system=messages[0]['content']
        result={'queries':['科技']} if '搜索Agent' in system else {'approved':[0]} if '事实校验Agent' in system else {'articles':[article('科技新闻报道',[1])]}
        return json.dumps(result,ensure_ascii=False),{}
    def search(query,**kwargs):calls.append(query);return {'result':{'references':[ref(1)]}}
    result=list(HotAgent(None,None,complete=complete,search_tool=search,now=NOW).run(HotPreferences(maxItems=1),[],threading.Event()))[-1]
    assert len(calls)==1 and len(result['articles'])==1


def test_related_roundup_has_detailed_points_with_source_mapping():
    sources=[ref(1,text=TEXT+'第一种技术的评测细节。'),ref(2,text=TEXT+'第二种技术的应用细节。')]
    def complete(config,messages):
        system=messages[0]['content'];data=json.loads(messages[1]['content'])
        if '搜索Agent' in system:result={'queries':['科技详细报道']}
        elif '事实校验Agent' in system:result={'approved':[0]}
        else:
            result={'articles':[{'title':'检索技术最新进展综述','summary':'汇总相关检索技术的研究与应用进展。','articleType':'roundup',
                'paragraphs':[{'heading':f'进展{source["id"]}','text':source['content'],'evidence':[{'sourceId':source['id'],'quote':source['content'][:24]}]} for source in data['sources']]}]}
        return json.dumps(result,ensure_ascii=False),{}
    result=list(HotAgent(None,None,complete=complete,search_tool=lambda *a,**k:{'result':{'references':sources}},now=NOW).run(HotPreferences(maxItems=None),[],threading.Event()))[-1]
    assert len(result['articles'])==1
    news=result['articles'][0]
    assert news['articleType']=='roundup' and len(news['sources'])==2 and len(news['body'])>600
    assert '1. 进展1（来源 1）' in news['body'] and '2. 进展2（来源 2）' in news['body']


def test_rich_source_cannot_be_reduced_to_a_few_sentences():
    def complete(config,messages):
        system=messages[0]['content']
        if '搜索Agent' in system:result={'queries':['科技']}
        elif '事实校验Agent' in system:result={'approved':[0]}
        else:
            result={'articles':[article('缩水的科技报道',[1])]}
            result['articles'][0]['paragraphs'][0]['text']='模型发布了新的技术，公开了相关评测方法，适用于知识库检索。'
        return json.dumps(result,ensure_ascii=False),{}
    result=list(HotAgent(None,None,complete=complete,search_tool=lambda *a,**k:{'result':{'references':[ref(1,text=TEXT*4)]}},now=NOW).run(HotPreferences(maxItems=None),[],threading.Event()))[-1]
    assert result['articles']==[]


def test_hot_list_api_uses_publication_time_across_pages(tmp_path):
    with _client(tmp_path) as client:
        headers=_login(client,'reader')
        for title,date in [('today','2026-10-11T12:00:00+08:00'),('old','2026-10-04'),('yesterday','2026-10-10')]:
            client.post('/api/v1/workbench/items',headers=headers,json={'kind':'hot','title':title,'data':{'publishedAt':date}})
        first=client.get('/api/v1/workbench/items?kind=hot&limit=2',headers=headers).json()
        second=client.get('/api/v1/workbench/items?kind=hot&limit=2&offset=2',headers=headers).json()
        assert [item['title'] for item in first['items']+second['items']]==['today','yesterday','old']


def test_short_draft_is_expanded_from_original_sources_before_review():
    organized=[]
    def complete(config,messages):
        system=messages[0]['content'];data=json.loads(messages[1]['content'])
        if '搜索Agent' in system:result={'queries':['科技']}
        elif '事实校验Agent' in system:result={'approved':[0]}
        else:
            organized.append(data)
            result={'articles':[article('展开后的科技报道',[1])]}
            if len(organized)==1:result['articles'][0]['paragraphs'][0]['text']='模型发布新技术，公开评测方法，面向知识检索。'
        return json.dumps(result,ensure_ascii=False),{}
    events=list(HotAgent(None,None,complete=complete,search_tool=lambda *a,**k:{'result':{'references':[ref(1)]}},now=NOW).run(HotPreferences(maxItems=None),[],threading.Event()))
    assert len(organized)==2 and organized[1]['sources'][0]['content']==TEXT
    assert any(event.get('stage')=='expanding' for event in events)
    assert events[-1]['articles'][0]['body']==TEXT


def test_long_sources_are_batched_without_dropping_content():
    sources=[{'id':i,'content':'内容'*8000} for i in range(20)]
    batches=list(source_batches(sources))
    assert [source['id'] for batch in batches for source in batch]==list(range(20))
    assert all(sum(len(source['content']) for source in batch)<=48000 for batch in batches)
