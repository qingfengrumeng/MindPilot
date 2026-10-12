"""Owner-scoped Wiki navigation backed by immutable raw evidence snapshots."""
import hashlib
import re
from pathlib import Path

from sqlalchemy import select

from app.db.models import Document, DocumentWikiCompilation
from app.tools.bm25_search import _tokens


def wiki_search(query, settings, session_factory, user_id, top_k=5):
    terms = set(_tokens(query))
    if not terms:
        return []
    candidates = []
    with session_factory() as db:
        records = db.execute(select(Document, DocumentWikiCompilation).join(
            DocumentWikiCompilation, DocumentWikiCompilation.document_id == Document.id
        ).where(Document.user_id == user_id, DocumentWikiCompilation.user_id == user_id,
                DocumentWikiCompilation.status == 'done')).all()
        for document, wiki in records:
            data = wiki.data_json or {}
            try:
                fingerprint = hashlib.sha256(Path(document.storage_path).read_bytes()).hexdigest()
            except OSError:
                continue
            if fingerprint != data.get('sourceHash'):
                continue
            sources = {source['id']: source for source in data.get('sources', [])
                       if isinstance(source, dict) and source.get('id') and source.get('text')}
            # The provenance index is not a Wiki answer; don't match it as content.
            body = wiki.markdown.split('\n## 原始来源', 1)[0]
            for section in re.split(r'\n(?=#{2,4} )', body):
                matched = terms.intersection(_tokens(section))
                cited = list(dict.fromkeys(re.findall(r'\[(S\d+)\]', section)))
                if not matched or not cited:
                    continue
                score = len(matched) / len(terms)
                available = [sources[ref] for ref in cited if ref in sources]
                available.sort(key=lambda s: len(terms.intersection(_tokens(s['text']))), reverse=True)
                for source in available[:3]:
                    candidates.append({
                        'documentId': document.id, 'page': source.get('page'), 'text': source['text'],
                        'sourceSnapshot': fingerprint,
                        'sourcePageCount': data.get('sourcePageCount') or max((s.get('page') or 1 for s in sources.values()), default=1),
                        'wikiId': document.id, 'wikiOverview': section[:2200], 'wikiScore': score,
                        'retrievalOrigins': ['wiki'],
                    })
    candidates.sort(key=lambda hit: hit['wikiScore'], reverse=True)
    unique = {}
    for hit in candidates:
        key = (hit['documentId'], hit.get('page'), hit['text'])
        unique.setdefault(key, hit)
    return list(unique.values())[:top_k]
