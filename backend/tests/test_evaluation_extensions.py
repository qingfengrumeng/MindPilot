from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.rag_sample_dataset import sample_dataset
from app.services.rag_groundedness import dual_signal_metrics,lexical_support,sentences_for
from app.services.rag_evaluation import RunInput
from app.services import rag_evaluation
import asyncio
from app.services.rag_metrics import aggregate
from app.services import embedding_generation
from app.core.model_runtime import RuntimeModel
import json
import httpx
from app.api.routes.rag_evaluations import DatasetInput,validate_gold
from tests.test_model_configs import settings_for,login


def test_sample_has_large_valid_gold_and_grouped_paraphrases():
    dataset=sample_dataset()
    assert len(dataset['documents'])==12 and len(dataset['questions'])==144
    assert sum(len(p['text']) for d in dataset['documents'] for p in d['pages'])>50000
    parsed=DatasetInput(revision=1,**dataset)
    validate_gold(parsed.questions,dataset['documents'])
    for question in dataset['questions']:
        evidence=question['evidence'][0]
        doc=next(d for d in dataset['documents'] if d['id']==evidence['documentId'])
        text=next(p['text'] for p in doc['pages'] if p['page']==evidence['page'])
        assert text[evidence['start']:evidence['end']]==question['answer']
    groups={}
    for q in dataset['questions']:groups.setdefault(q['id'].rsplit('-',1)[0],set()).add(q['split'])
    assert all(len(splits)==1 for splits in groups.values())


def test_embedding_v4_splits_twenty_rows_into_two_ten_row_requests(monkeypatch):
    batches=[]
    def respond(request):
        values=json.loads(request.content)['input'];batches.append(values)
        assert len(values)<=10
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[float(value),1.]} for i,value in enumerate(values)],'usage':{'total_tokens':len(values)}})
    original=httpx.Client
    monkeypatch.setattr(embedding_generation.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(respond),**kwargs))
    result=embedding_generation.embed_texts(RuntimeModel('embedding','dashscope','https://example.com/v1','text-embedding-v4','test-key',2),[str(i) for i in range(20)])
    assert len(batches)==2 and [row['index'] for row in result['data']]==list(range(20))
    assert [row['embedding'][0] for row in result['data']]==list(range(20))
    assert result['usage']['totalTokens']==20


def test_short_verbatim_answers_are_supported_even_with_low_semantic_similarity():
    metrics,signals=dual_signal_metrics(['黄连，地榆。','凭空增加药物。'],['原文成分为黄连、地榆。'],[[0,1],[0,1]],[[1,0]])
    assert metrics['groundedness']==.5 and metrics['potentialHallucinationRate']==.5
    assert signals[0]['lexicalOverlap']==1 and signals[0]['sources']==[0]
    assert signals[1]['potentialHallucination']
    assert lexical_support('0.25克','规格为每片重0.25克。')==1
    assert dual_signal_metrics([],[],[],[])[0]['groundedness'] is None
    with pytest.raises(ValueError):dual_signal_metrics(['a'],['b'],[],[[1,0]])
    assert sentences_for('Cats sleep. Birds fly.\n第三句。')==['Cats sleep.','Birds fly.','第三句。']
    assert sentences_for('# 标题\n有事实。[0]\n来源：[0]')==['有事实。']
    assert aggregate([{'metrics':{'groundedness':1}},{'error':'failed','metrics':{'groundedness':0}},{'metrics':{}}])['metricCounts']['groundedness']==1


def test_independent_factual_judge_does_not_infer_correctness_from_similarity(monkeypatch):
    async def completion(*args):
        return json.dumps({'claims':[{'text':'错误数字','supported':False,'sources':[],'referenceSupported':False}],
            'referenceClaims':[{'text':'正确数字','covered':False}],
            'factualConsistency':0.,'consistencyVerdict':'inconsistent','consistencyReason':'答案中的数字与资料矛盾。'}),{}
    monkeypatch.setattr(rag_evaluation,'completion',completion)
    metrics,judgment=asyncio.run(rag_evaluation.judge_answer(None,{'query':'金额？','answer':'100元'},[{'text':'100元'}],'200元'))
    assert metrics['faithfulness']==0 and metrics['factualConsistency']==0
    assert judgment['consistencyVerdict']=='inconsistent'
    selection={'providerId':'test','model':'same-model'}
    with pytest.raises(ValueError):RunInput(revision=1,plans=[{'id':'p','name':'test','embedding':selection}],generator=selection,judge=selection)


def test_archive_is_persistent_owner_scoped_and_rejects_secrets(tmp_path):
    settings=settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        headers=login(client)
        prefix='/api/v1/model-evaluations/reports'
        value={'kind':'rag','title':'实验报告','result':{'plans':[],'metrics':{'groundedness':.8}}}
        assert client.post(prefix,json=value).status_code==401
        result=client.post(prefix,headers=headers,json=value)
        assert result.status_code==200
        report_id=result.json()['id']
        assert client.get(prefix,headers=headers).json()['items'][0]['id']==report_id
        assert client.get(prefix+'/'+report_id,headers=headers).json()['result']==value['result']
        bad=deepcopy(value);bad['result']['nested']={'apiKey':'do-not-store'}
        assert client.post(prefix,headers=headers,json=bad).status_code==422
        client.post('/api/v1/auth/register',json={'username':'other-user','password':'strong-password-123'})
        token=client.post('/api/v1/auth/login',json={'username':'other-user','password':'strong-password-123'}).json()['accessToken']
        other={'Authorization':'Bearer '+token}
        assert client.get(prefix,headers=other).json()['items']==[]
        assert client.get(prefix+'/'+report_id,headers=other).status_code==404
        assert client.delete(prefix+'/'+report_id,headers=other).status_code==404
        assert client.delete(prefix+'/'+report_id,headers=headers).status_code==200


def test_editing_gold_document_invalidates_spans_and_keeps_other_evidence(tmp_path):
    with TestClient(create_app(settings_for(tmp_path))) as client:
        headers=login(client);prefix='/api/v1/model-evaluations/rag'
        workspace=client.post(prefix,headers=headers).json()
        sample=client.get(prefix+'/samples/golden-dataset',headers=headers)
        assert sample.status_code==200
        workspace=client.post(f'{prefix}/{workspace["id"]}/import',headers=headers,json={'revision':workspace['revision'],**sample.json()}).json()
        assert len(workspace['questions'])==144
        document=workspace['documents'][0]
        pages=deepcopy(document['pages']);pages[0]['text']='已修改的黄金文档正文。'
        path=f'{prefix}/{workspace["id"]}/documents/{document["id"]}'
        payload={'revision':workspace['revision'],'name':'编辑后名称','pages':pages}
        result=client.put(path,headers=headers,json=payload)
        assert result.status_code==200,result.text
        updated=result.json()
        assert not updated['questions'][0]['evidence'] and not updated['questions'][0]['complete']
        assert updated['questions'][12]['evidence']
        assert client.put(path,headers=headers,json=payload).status_code==409
        assert client.get(f'{prefix}/{workspace["id"]}',headers=headers).json()['documents'][0]['pages'][0]['text']==pages[0]['text']
