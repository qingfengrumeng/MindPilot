"""A light, provenance-bound graph: live Wiki links and JSON/SQLite semantic index."""
import hashlib
import json
import re
from pathlib import Path
from collections import Counter, defaultdict

from sqlalchemy import select

from app.db.models import Document, DocumentWikiCompilation, KnowledgeGraphIndex

RELATION_TYPES = ('基于', '属于', '提出', '改进', '用于', '导致', '对比', '依赖', '包含', '关联', '发布', '发生于')
ENTITY_TYPES = ('人物', '组织', '产品', '概念', '事件', '地点')


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def normalized(value):
    return re.sub(r'\s+', '', str(value)).casefold()


def wiki_records(session_factory, user_id):
    records = []
    with session_factory() as db:
        rows = db.execute(select(Document, DocumentWikiCompilation).join(
            DocumentWikiCompilation, Document.id == DocumentWikiCompilation.document_id
        ).where(Document.user_id == user_id, DocumentWikiCompilation.user_id == user_id,
                DocumentWikiCompilation.status == 'done')).all()
        for doc, wiki in rows:
            data = wiki.data_json or {}
            try:
                fingerprint = hashlib.sha256(Path(doc.storage_path).read_bytes()).hexdigest()
            except OSError:
                continue
            if fingerprint != data.get('sourceHash'):
                continue
            body = wiki.markdown.split('\n## 原始来源', 1)[0]
            records.append({'id': doc.id, 'title': doc.title, 'markdown': body,
                            'sourceHash': fingerprint, 'version': stable_id(body, fingerprint),
                            'sources': data.get('sources', []), 'pages': data.get('sourcePageCount', doc.pages) or 1})
    return sorted(records, key=lambda page: page['id'])


def page_graph(records):
    names = defaultdict(set)
    nodes = []
    for page in records:
        heading = re.search(r'^#\s+(.+)$', page['markdown'], re.M)
        aliases = [page['title'], re.sub(r'\.(pdf|txt|md|markdown)$', '', page['title'], flags=re.I)]
        if heading:
            aliases.append(heading[1].strip())
        frontmatter = re.match(r'^---\s*\n(.*?)\n---', page['markdown'], re.S)
        if frontmatter:
            alias_line = re.search(r'^aliases:\s*\[(.*?)\]', frontmatter[1], re.M)
            if alias_line:
                aliases.extend(item.strip().strip('"\'') for item in alias_line[1].split(','))
        for alias in aliases:
            names[normalized(alias)].add(page['id'])
        nodes.append({'id': page['id'], 'name': page['title'], 'type': 'Wiki页面', 'documentId': page['id'],
                      'sourceHash': page['sourceHash'], 'aliases': list(dict.fromkeys(aliases))})
    edges, issues = [], []
    seen = set()
    for page in records:
        body = re.sub(r'```.*?```', '', page['markdown'], flags=re.S)
        for paragraph_no, paragraph in enumerate(body.split('\n\n'), 1):
            for match in re.finditer(r'(?<!\\)\[\[([^\]\n]{1,200})\]\]', paragraph):
                target, _, label = match[1].partition('|')
                target, _, anchor = target.partition('#')
                targets = names.get(normalized(target), set())
                resolved = len(targets) == 1
                target_id = next(iter(targets)) if resolved else 'unresolved:' + stable_id(target)
                if not resolved:
                    issue = {'kind': 'ambiguous' if targets else 'broken', 'documentId': page['id'], 'target': target}
                    if issue not in issues:
                        issues.append(issue)
                    if not any(node['id'] == target_id for node in nodes):
                        nodes.append({'id': target_id, 'name': target, 'type': '未解析页面', 'unresolved': True})
                key = (page['id'], target_id, anchor)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({'id': stable_id(*key), 'source': page['id'], 'target': target_id,
                              'predicate': '链接', 'label': label or target, 'anchor': anchor,
                              'resolved': resolved, 'paragraph': paragraph_no,
                              'sourceIds': re.findall(r'\[(S\d+)\]', paragraph)})
    return {'nodes': nodes, 'edges': edges, 'issues': issues}


def communities_for(nodes, relations):
    """Deterministic label propagation on the undirected semantic projection."""
    neighbors = defaultdict(Counter)
    for edge in relations:
        neighbors[edge['source']][edge['target']] += 1
        neighbors[edge['target']][edge['source']] += 1
    labels = {node['id']: node['id'] for node in nodes}
    for _ in range(20):
        changed = False
        for node_id in sorted(labels, key=lambda key: (-len(neighbors[key]), key)):
            votes = Counter()
            for neighbor, weight in neighbors[node_id].items():
                votes[labels[neighbor]] += weight
            if votes:
                winner = min(votes, key=lambda label: (-votes[label], label))
                if winner != labels[node_id]:
                    labels[node_id] = winner
                    changed = True
        if not changed:
            break
    groups = defaultdict(list)
    for node_id, label in labels.items():
        groups[label].append(node_id)
    lookup = {node['id']: node for node in nodes}
    result = []
    for ids in groups.values():
        ids = sorted(ids)
        edges = [edge for edge in relations if edge['source'] in ids and edge['target'] in ids]
        if not edges:
            continue
        prominent = sorted(ids, key=lambda node: (-len(neighbors[node]), node))[:3]
        result.append({'id': stable_id('community', ids), 'title': ' · '.join(lookup[node]['name'] for node in prominent),
                       'entityIds': ids, 'relationIds': [edge['id'] for edge in edges],
                       'method': 'label-propagation'})
    return sorted(result, key=lambda group: -len(group['relationIds']))


def current_graph(settings, session_factory, user_id):
    records = wiki_records(session_factory, user_id)
    valid = {page['id']: page for page in records}
    with session_factory() as db:
        index = db.get(KnowledgeGraphIndex, user_id)
        data = dict(index.data_json or {}) if index else {}
        status = {'status': index.status if index else 'empty', 'stage': index.stage if index else '',
                  'completed': index.completed if index else 0, 'total': index.total if index else 0,
                  'error': index.error_message if index else ''}
    relations = []
    for edge in data.get('relations', []):
        evidence = [proof for proof in edge.get('evidence', [])
                    if proof.get('documentId') in valid
                    and valid[proof['documentId']]['sourceHash'] == proof.get('sourceHash')
                    and valid[proof['documentId']]['version'] == proof.get('wikiVersion')]
        if evidence:
            relations.append({**edge, 'evidence': evidence})
    entity_ids = {edge[key] for edge in relations for key in ('source', 'target')}
    entities = [node for node in data.get('entities', []) if node['id'] in entity_ids]
    communities = communities_for(entities, relations)
    saved = {group['id']: group for group in data.get('communities', [])}
    node_names = {node['id']: node['name'] for node in entities}
    relation_map = {edge['id']: edge for edge in relations}
    for group in communities:
        previous = saved.get(group['id']) or {}
        selected = [relation_map[key] for key in group['relationIds'][:30]]
        if previous.get('version') == stable_id(selected):
            group.update({key: previous[key] for key in ('summary', 'summaryMethod') if key in previous})
        else:
            group['summary'] = '\n'.join(f'- {node_names[edge["source"]]} — {edge["predicate"]} → {node_names[edge["target"]]}' for edge in selected[:8])
            group['summaryMethod'] = 'facts'
    manifest = {page['id']: page['version'] for page in records}
    return {'wiki': page_graph(records), 'semantic': {'nodes': entities, 'edges': relations,
            'issues': [issue for issue in data.get('issues', []) if issue.get('documentId') in valid]},
            'communities': communities, 'build': status,
            'stale': data.get('manifest', {}) != manifest,
            'version': stable_id(manifest, relations), 'recordCount': len(records)}
