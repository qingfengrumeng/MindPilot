"""Parallel Raw, Wiki and GraphRAG retrieval with provenance-aware fusion."""
from concurrent.futures import ThreadPoolExecutor

from app.core.model_runtime import require_runtime_model
from app.services.rerank_generation import rerank_texts
from app.services.wiki_retrieval import wiki_search
from app.services.graph_retrieval import graph_search
from app.tools.search_knowledge_base import hybrid_search


def fuse_results(raw, wiki, top_k=5, graph=None):
    merged = {}
    for origin, hits in (('raw', raw), ('wiki', wiki), ('graph', graph or [])):
        seen = set()
        for rank, hit in enumerate(hits, 1):
            key = (hit.get('documentId'), hit.get('page'), ' '.join(str(hit.get('text', '')).split()))
            if key in seen or not key[0] or not key[2]:
                continue
            seen.add(key)
            item = merged.setdefault(key, {**hit, 'fusionScore': 0, 'retrievalOrigins': []})
            item['fusionScore'] += 1 / (60 + rank)
            item['retrievalOrigins'].append(origin)
            if origin != 'raw':
                item.update({k: hit[k] for k in ('wikiId', 'wikiOverview', 'sourceSnapshot', 'sourcePageCount',
                                               'graphOverview', 'graphRelationId', 'graphPath') if k in hit})
    return sorted(merged.values(), key=lambda hit: hit['fusionScore'], reverse=True)[:top_k]


def retrieve_knowledge(query, settings, session_factory, user_id, dense_search, top_k=5):
    limit = max(1, min(top_k, 20))
    errors = []
    # Independent sessions in each engine; neither waits for the other to start.
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix='mindpilot-retrieve') as executor:
        futures = {
            'raw': executor.submit(hybrid_search, query, settings, session_factory, user_id,
                                   top_k=limit*2, dense_search=dense_search),
            'wiki': executor.submit(wiki_search, query, settings, session_factory, user_id, top_k=limit*2),
        }
        futures['graph'] = executor.submit(graph_search, query, settings, session_factory, user_id,
                                          top_k=limit*2, seed_futures=list(futures.values()))
        results = {}
        for origin, future in futures.items():
            try:
                results[origin] = future.result()
            except Exception:
                results[origin] = []
                errors.append(origin)
    graph_result = results['graph'] if isinstance(results['graph'], dict) else {}
    candidates = fuse_results(results['raw'], results['wiki'], limit*2, graph=graph_result.get('hits', []))
    try:
        config = require_runtime_model('reranker', settings.model_config_path)
    except RuntimeError:
        config = None
    if config and candidates:
        try:
            ranked = rerank_texts(config, query, [hit['text'] for hit in candidates], top_n=limit)
            if not ranked.get('results'):
                raise ValueError('Empty reranker output')
            candidates = [{**candidates[row['index']], 'rerankScore': row['relevanceScore']}
                          for row in ranked['results']]
        except Exception:
            errors.append('reranker')
    return {'hits': candidates[:limit], 'rawHits': results['raw'], 'wikiHits': results['wiki'],
            'graph': graph_result, 'errors': errors}
