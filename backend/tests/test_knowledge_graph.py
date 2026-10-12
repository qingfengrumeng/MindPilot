import hashlib
import json
import time
from threading import Barrier
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import documents
from app.core.model_preferences import write_preferences
from app.db.models import Document, DocumentWikiCompilation, KnowledgeGraphIndex
from app.main import create_app
from app.services import graph_build, graph_retrieval, knowledge_fusion
from app.services.graph_data import current_graph, page_graph, wiki_records
from test_model_configs import settings_for, login


def test_all_three_retrievers_start_concurrently(tmp_path,monkeypatch):
    barrier=Barrier(3,timeout=3)
    hit={'documentId':'doc','page':1,'text':'One original fact'}
    def retrieve(*args,**kwargs):
        barrier.wait();return [hit]
    def graph(*args,**kwargs):
        barrier.wait();return {'hits':[dict(hit,graphRelationId='r1')]}
    monkeypatch.setattr(knowledge_fusion,'hybrid_search',retrieve)
    monkeypatch.setattr(knowledge_fusion,'wiki_search',retrieve)
    monkeypatch.setattr(knowledge_fusion,'graph_search',graph)
    result=knowledge_fusion.retrieve_knowledge('fact',settings_for(tmp_path),None,'owner',None)
    assert len(result['hits'])==1
    assert result['hits'][0]['retrievalOrigins']==['raw','wiki','graph']
    assert result['hits'][0]['graphRelationId']=='r1'


def configured(settings):
    write_preferences(settings.model_config_path, {'providers': {'deepseek': {
        'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-only',
        'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'fake-model'}}}}, 'active': {'text': 'deepseek'}})


def page(client, auth, title, text, link=''):
    uploaded = client.post('/api/v1/documents', headers=auth, files={'file': (title+'.txt', text.encode(), 'text/plain')}).json()
    with client.app.state.session_factory() as db:
        doc = db.get(Document, uploaded['id'])
        doc.title = title
        fingerprint = hashlib.sha256(text.encode()).hexdigest()
        db.add(DocumentWikiCompilation(document_id=doc.id, user_id=doc.user_id, status='done',
            markdown=f'# {title}\n\n{text} {link} [S1]\n\n## 原始来源\n- [S1] source',
            data_json={'sourceHash': fingerprint, 'sourcePageCount': 1,
                       'sources': [{'id':'S1','chunkId':'raw:'+fingerprint,'page':1,'text':text}]}))
        db.commit()
        return doc.id, doc.user_id, Path(doc.storage_path)


def fake_model(config, messages):
    data = json.loads(messages[-1]['content'])
    if isinstance(data, list):
        return json.dumps({'summary': data[0]['fact']+' [R1]'}), {}
    source = data['rawSources'][0]
    subject, predicate, target = ('Transformer','用于','Attention') if source['text'].startswith('Transformer') else (data['page'],'基于','Transformer')
    return json.dumps({'triples':[{'subject':{'name':subject,'type':'概念','aliases':[],'qualifier':''},
        'object':{'name':target,'type':'概念','aliases':[],'qualifier':''}, 'predicate':predicate,
        'sourceId':source['id'],'paragraphId':data['paragraphs'][0]['id'], 'quote':source['text'],'confidence':.9}]}), {}


def wait_build(client, auth):
    deadline = time.monotonic()+10
    while time.monotonic()<deadline:
        data=client.get('/api/v1/knowledge-graph',headers=auth).json()
        if data['build']['status'] in ('ready','failed'):
            return data
        time.sleep(.02)
    raise AssertionError('Build did not finish')


def test_page_links_resolve_alias_anchor_backlinks_and_report_ambiguous_targets():
    records=[{'id':'a','title':'BERT','sourceHash':'h','markdown':'# BERT\n\n[[Transformer#架构|架构]] [[Missing]] [S1]\n\n```\n[[NotALink]]\n```'},
             {'id':'b','title':'Transformer','sourceHash':'h','markdown':'# Transformer'},
             {'id':'c','title':'Other','sourceHash':'h','markdown':'---\naliases: [Transformer]\n---\n# Other'}]
    graph=page_graph(records[:2])
    assert graph['edges'][0]['target']=='b' and graph['edges'][0]['anchor']=='架构'
    assert graph['edges'][0]['sourceIds']==['S1']
    assert len(graph['issues'])==1 and graph['issues'][0]['target']=='Missing'
    paths=graph_retrieval.expand_pages({'wiki':graph},['b'])
    assert paths['a']==['b','a']
    assert any(i['kind']=='ambiguous' for i in page_graph(records)['issues'])


@pytest.mark.parametrize('sql', [
    'DELETE FROM entities', 'WITH x AS (SELECT 1) DELETE FROM entities',
    'SELECT * FROM users', 'SELECT * FROM sqlite_master',
    "SELECT load_extension('x')", "ATTACH DATABASE 'x' AS stolen", 'SELECT randomblob(100000000)',
    'SELECT 1; DELETE FROM entities', "SELECT X'FF' AS unsupported_blob", 'SELECT 1e999 AS unsupported_infinity',
])
def test_sql_cannot_modify_or_read_other_tables(sql):
    empty={'semantic':{'nodes':[],'edges':[]},'wiki':{'nodes':[],'edges':[]},'communities':[]}
    with pytest.raises(ValueError):
        graph_retrieval.execute_graph_sql(empty,sql)
    assert graph_retrieval.execute_graph_sql(empty,'SELECT COUNT(*) AS n FROM entities')==[{'n':0}]


def test_graph_build_retrieval_sql_cross_document_expansion_and_deletion(tmp_path, monkeypatch):
    settings=settings_for(tmp_path);configured(settings)
    calls=[]
    def model(*args):
        calls.append(args)
        return fake_model(*args)
    monkeypatch.setattr(graph_build,'complete_text',model)
    monkeypatch.setattr(graph_retrieval,'complete_text',lambda *args: ('{"sql":"SELECT relation_id FROM relations WHERE subject_name=:name","params":{"name":"BERT"}}',{}))
    monkeypatch.setattr(documents,'remove_document_vectors',lambda *args:None)
    with TestClient(create_app(settings)) as client:
        auth=login(client)
        bert,owner,source=page(client,auth,'BERT','BERT is based on Transformer.','[[Transformer]]')
        gpt,_,_=page(client,auth,'GPT','GPT is based on Transformer.','[[Transformer]]')
        transformer,_,_=page(client,auth,'Transformer','Transformer uses Attention.')
        assert client.get('/api/v1/knowledge-graph').status_code==401
        assert client.post('/api/v1/knowledge-graph/build',headers=auth).status_code==202
        data=wait_build(client,auth)
        assert data['build']['status']=='ready',data
        assert len(data['wiki']['nodes'])==3 and len(data['wiki']['edges'])==2
        assert len(data['semantic']['nodes'])==4 and len(data['semantic']['edges'])==3
        assert data['communities'] and data['communities'][0]['summary']
        assert all(edge['evidence'] and 'rawText' not in edge['evidence'][0] for edge in data['semantic']['edges'])
        snapshot=settings.data_dir/'knowledge_graph'/owner/'graph.json'
        assert snapshot.exists()
        count=len(calls)
        client.post('/api/v1/knowledge-graph/build',headers=auth)
        assert wait_build(client,auth)['build']['status']=='ready'
        assert len(calls)==count
        response=client.post('/api/v1/knowledge-graph/query',headers=auth,json={'question':'BERT relationship'})
        assert response.status_code==200,response.text
        result=response.json()
        assert result['rows'] and result['sql'].startswith('SELECT')
        assert {h['documentId'] for h in result['hits']}>={bert,gpt,transformer}
        assert all(len(path)<=3 for path in result['pagePaths'].values())
        fusion=knowledge_fusion.retrieve_knowledge('BERT relationship',settings,client.app.state.session_factory,owner,lambda *args,**kwargs:[])
        assert any('graph' in hit['retrievalOrigins'] for hit in fusion['hits'])
        export=client.get('/api/v1/knowledge-graph/export',headers=auth)
        assert export.status_code==200 and export.json()['semantic']['edges']
        client.post('/api/v1/auth/register',json={'username':'guest','password':'strong-password-123'})
        guest=client.post('/api/v1/auth/login',json={'username':'guest','password':'strong-password-123'}).json()['accessToken']
        other={'Authorization':'Bearer '+guest}
        assert client.get('/api/v1/knowledge-graph',headers=other).json()['semantic']['nodes']==[]
        assert client.post('/api/v1/knowledge-graph/query',headers=other,json={'question':'BERT'}).json()['hits']==[]
        source.write_text('Changed raw source')
        assert all(proof['documentId']!=bert for edge in current_graph(settings,client.app.state.session_factory,owner)['semantic']['edges'] for proof in edge['evidence'])
        assert client.delete(f'/api/v1/documents/{bert}',headers=auth).status_code==204
        persisted=json.loads(snapshot.read_text(encoding='utf-8'))
        assert bert not in persisted['pageExtractions']
        assert all(proof['documentId']!=bert for edge in persisted['relations'] for proof in edge['evidence'])


def test_false_relations_rejected_and_aliases_keep_qualifier_identity(tmp_path,monkeypatch):
    settings=settings_for(tmp_path);configured(settings)
    with TestClient(create_app(settings)) as client:
        auth=login(client)
        _,owner,_=page(client,auth,'BERT','BERT is based on Transformer.')
        record=wiki_records(client.app.state.session_factory,owner)[0]
        def fake_quote(*args):
            answer,usage=fake_model(*args)
            data=json.loads(answer);data['triples'][0]['quote']='A fabricated claim';return json.dumps(data),usage
        monkeypatch.setattr(graph_build,'complete_text',fake_quote)
        extraction=graph_build.extract_page(object(),record,'rules')
        assert extraction['triples']==[] and extraction['issues']
        entity=lambda name,qualifier,aliases=[]:{'name':name,'type':'组织','qualifier':qualifier,'aliases':aliases}
        triples=[{'subject':entity('Apple','US',['苹果公司']),'object':entity('Vendor','US'),'predicate':'依赖','confidence':.9,'evidence':{}},
                 {'subject':entity('苹果公司','US',['Apple']),'object':entity('Vendor','US'),'predicate':'依赖','confidence':.9,'evidence':{}},
                 {'subject':entity('Apple','Other'),'object':entity('Vendor','US'),'predicate':'依赖','confidence':.9,'evidence':{}}]
        nodes,edges=graph_build.assemble_entities({'page':{'triples':triples}})
        assert len(nodes)==3 and len(edges)==2


def test_graph_sql_statistics_reach_chat_and_restart_retains_snapshot(tmp_path,monkeypatch):
    from app.api.routes import conversations
    from starlette.requests import Request
    settings=settings_for(tmp_path);configured(settings)
    monkeypatch.setattr(graph_retrieval,'complete_text',lambda *args: ('{"sql":"SELECT COUNT(*) AS wiki_pages FROM wiki_pages","params":{}}',{}))
    monkeypatch.setattr(conversations,'search_documents',lambda *args,**kwargs:[])
    with TestClient(create_app(settings)) as client:
        auth=login(client)
        _,owner,_=page(client,auth,'BERT','BERT is based on Transformer.')
        result=client.post('/api/v1/knowledge-graph/query',headers=auth,json={'question':'当前图谱有多少页面'}).json()
        assert result['sqlStatus']=='executed' and result['rows']==[{'wiki_pages':1}]
        context,hits=conversations.knowledge_context(Request({'type':'http','app':client.app}),owner,'当前图谱有多少页面')
        assert '图谱只读SQL查询结果' in context and 'wiki_pages' in context
        with client.app.state.session_factory() as db:
            db.add(KnowledgeGraphIndex(user_id=owner,status='building',data_json={'manifest':{},'entities':[],'relations':[]}))
            db.commit()
    with TestClient(create_app(settings)) as client:
        auth=login(client)
        state=client.get('/api/v1/knowledge-graph',headers=auth).json()
        assert state['build']['status']=='failed' and '服务重启' in state['build']['error']


def test_summary_failure_keeps_verified_relation_overview(monkeypatch):
    monkeypatch.setattr(graph_build,'complete_text',lambda *args: (_ for _ in ()).throw(RuntimeError('Model down')))
    nodes=[{'id':'a','name':'BERT'},{'id':'b','name':'Transformer'}]
    relations=[{'id':'r','source':'a','target':'b','predicate':'基于','evidence':[{'quote':'BERT is based on Transformer.'}]}]
    communities=[{'id':'community','relationIds':['r'],'entityIds':['a','b']}]
    graph_build.summarize_communities(object(),communities,nodes,relations,[])
    assert communities[0]['summaryMethod']=='facts' and '[R1]' in communities[0]['summary']


def test_sql_execution_budget_stops_recursive_explosion():
    empty={'semantic':{'nodes':[],'edges':[]},'wiki':{'nodes':[],'edges':[]},'communities':[]}
    sql='WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x WHERE n<100000000) SELECT sum(n) FROM x'
    started=time.monotonic()
    with pytest.raises(ValueError):
        graph_retrieval.execute_graph_sql(empty,sql)
    assert time.monotonic()-started<2
