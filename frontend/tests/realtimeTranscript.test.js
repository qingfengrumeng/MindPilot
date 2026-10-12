import assert from 'node:assert/strict'
import test from 'node:test'
import { createRealtimeTranscript } from '../src/lib/realtimeTranscript.js'

function fixture(conversationId = null, greeting = '智能知识管家的自我介绍') {
  const events = [], stored = []
  const api = {
    async create() { events.push('create'); return { id: 'new-call' } },
    async addMessage(id, message) { events.push(`save:${message.role}`); stored.push({ id, ...message }) }
  }
  const chat = {
    async loadConversations() { events.push('reload-list') },
    async loadMessages(id) { events.push(`reload:${id}`) }
  }
  return { events, stored, transcript: createRealtimeTranscript({ api, chat, sessionId: 'call-1', conversationId, greeting: () => greeting }) }
}

test('silence and a local greeting do not create a conversation or store messages', async () => {
  const f = fixture()
  await f.transcript.append('assistant', '智能知识管家的自我介绍')
  await f.transcript.start('  \n')
  await f.transcript.finish()
  await f.transcript.finish()
  assert.deepEqual(f.events, [])
  assert.deepEqual(f.stored, [])
  assert.equal(f.transcript.conversationId, null)
})

test('silent calls preserve the existing empty or historical conversation', async () => {
  for (const id of ['empty-draft', 'historical']) {
    const f = fixture(id)
    await f.transcript.finish()
    assert.deepEqual(f.events, [])
    assert.equal(f.transcript.conversationId, id)
  }
})

test('the first real utterance creates one call and subsequent turns reuse it', async () => {
  const f = fixture()
  await Promise.all([f.transcript.start('什么是 RAG'), f.transcript.start('什么是 RAG')])
  await f.transcript.append('user', '什么是 RAG')
  await f.transcript.append('assistant', '检索增强生成。')
  await f.transcript.start('举个例子')
  await f.transcript.append('user', '举个例子')
  await f.transcript.append('assistant', '从本地资料中检索证据再作答。')
  await Promise.all([f.transcript.finish(), f.transcript.finish()])
  assert.equal(f.events.filter(event => event === 'create').length, 1)
  assert.deepEqual(f.stored.map(message => message.content), ['实时通话', '智能知识管家的自我介绍',
    '什么是 RAG', '检索增强生成。', '举个例子', '从本地资料中检索证据再作答。', '实时通话结束'])
  assert.ok(f.stored.every(message => message.id === 'new-call' && message.metadata.realtimeSessionId === 'call-1'))
  assert.deepEqual(f.events.slice(-2), ['reload-list', 'reload:new-call'])
})

test('spoken calls append to the current conversation and flush fallback messages before closing', async () => {
  const f = fixture('current', '')
  await f.transcript.start('你好')
  const question = f.transcript.append('user', '你好')
  const partialAnswer = f.transcript.append('assistant', '已经播出的部分回复')
  await f.transcript.finish()
  await Promise.all([question, partialAnswer])
  assert.equal(f.events.includes('create'), false)
  assert.deepEqual(f.stored.map(message => message.content), ['实时通话', '你好', '已经播出的部分回复', '实时通话结束'])
  assert.equal(f.events.at(-1), 'reload:current')
})
