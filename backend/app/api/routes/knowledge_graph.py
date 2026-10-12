import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import CurrentContext
from app.services.graph_build import schedule_graph_build
from app.services.graph_data import current_graph
from app.services.graph_retrieval import graph_search

router = APIRouter(prefix='/knowledge-graph', tags=['knowledge-graph'])


class GraphQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=8000)


def output_graph(request, user_id):
    graph = current_graph(request.app.state.settings, request.app.state.session_factory, user_id)
    for edge in graph['semantic']['edges']:
        edge['evidence'] = [{key: value for key, value in proof.items() if key != 'rawText'} for proof in edge['evidence']]
    return graph


@router.get('')
def get_graph(request: Request, context: CurrentContext):
    return output_graph(request, context[0].id)


@router.post('/build', status_code=202)
def start_build(request: Request, context: CurrentContext):
    try:
        schedule_graph_build(request.app.state.settings, request.app.state.session_factory,
                             request.app.state.graph_executor, context[0].id)
    except RuntimeError:
        raise HTTPException(422, '请配置并启用文本模型，再构建知识图谱') from None
    return output_graph(request, context[0].id)


@router.post('/query')
def query_graph(payload: GraphQuestion, request: Request, context: CurrentContext):
    result = graph_search(payload.question, request.app.state.settings,
                          request.app.state.session_factory, context[0].id, top_k=10)
    return result


@router.get('/export')
def export_graph(request: Request, context: CurrentContext):
    graph = output_graph(request, context[0].id)
    return Response(json.dumps(graph, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="personal-knowledge-graph.json"', 'Cache-Control': 'no-store'})
