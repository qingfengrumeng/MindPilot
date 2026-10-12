import test from 'node:test'
import assert from 'node:assert/strict'
import { matchesModelSearch } from '../src/lib/modelSearch.js'

test('model search accepts partial, case insensitive, separated and fuzzy names', () => {
  for (const query of ['embedding', 'QWEN EMBED', 'qwen37embed', 'qwen_3.7 text', '']) {
    assert.equal(matchesModelSearch('qwen3.7-text-embedding', query), true)
  }
  assert.equal(matchesModelSearch('Qwen/Qwen3-Reranker-8B', 'qwen rerank 8'), true)
  assert.equal(matchesModelSearch('deepseek-chat', 'embedding'), false)
  assert.equal(matchesModelSearch('longanwen_v3.1 龙安温', '龙安温'), true)
  assert.equal(matchesModelSearch('longanwen_v3.1 龙安温', 'longwen31'), true)
})
