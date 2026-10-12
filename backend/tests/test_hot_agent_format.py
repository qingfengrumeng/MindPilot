import json
import pytest
from pydantic import ValidationError
from app.agents.hot_agent import HotAgent, HotAgentError, Plan, Digest, Review, parse_agent_json


@pytest.mark.parametrize('text',[
    '{"queries":["科技新闻"]}',
    '```json\n{"queries":["科技新闻"]}\n```',
    '以下是查询：\n{"queries":["科技新闻"]}\n已完成。',
    '<think>规划中</think>\n{"queries":["科技新闻"]}',
])
def test_json_wrappers_keep_valid_payload(text):
    assert parse_agent_json(text,Plan).queries==['科技新闻']


def test_format_retry_supplies_schema_and_issues_preserving_sources():
    calls=[]
    def complete(config,messages):
        calls.append(messages)
        return ('{"queries":[]}' if len(calls)==1 else '{queries:["科技"]}' if len(calls)==2 else '{"queries":["科技新闻"],"lookbackDays":7}'),{}
    result=HotAgent(None,None,complete=complete)._json('搜索Agent',{'direction':'科技'},Plan)
    assert result.queries==['科技新闻'] and len(calls)==3
    assert 'JSON Schema' in calls[0][0]['content']
    assert calls[1][1]['content']==calls[0][1]['content']
    assert json.loads(calls[1][-1]['content'])['issues'][0]['field']=='queries'


def test_invalid_shape_never_becomes_empty_success_and_failure_is_bounded():
    for schema in [Digest,Review]:
        with pytest.raises(ValidationError):parse_agent_json('{}',schema)
    calls=[]
    def complete(config,messages):
        calls.append(messages);return '{}',{}
    with pytest.raises(HotAgentError,match='内容整理阶段'):
        HotAgent(None,None,complete=complete)._json('整理Agent',{'sources':[]},Digest)
    assert len(calls)==3


def test_repair_does_not_relax_evidence_types_or_parse_nested_invalid_payload():
    invalid={'articles':[{'title':'新闻标题','summary':'这是足够长度的真实摘要','paragraphs':[{'text':'这是足够长度的正文信息','evidence':[{'sourceId':'1','quote':'这是逐字引用的原始内容'}]}]}]}
    with pytest.raises(ValidationError):parse_agent_json(json.dumps(invalid,ensure_ascii=False),Digest)
    with pytest.raises(ValueError):parse_agent_json('{"queries":["新闻"]}{"queries":["其他新闻"]}',Plan)
