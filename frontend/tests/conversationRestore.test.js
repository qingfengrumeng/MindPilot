import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { computed, ref, watch } from 'vue'
import { createPinia, defineStore } from 'pinia'
import { latestConversationMessageAt } from '../src/lib/conversationTime.js'

const source = (await readFile(new URL('../src/stores/chat.js', import.meta.url), 'utf8'))
  .replace(/^import[^\r\n]*\r?\n/gm, '').replace('export const useChatStore', 'const useChatStore')
const factory = new Function('computed', 'ref', 'watch', 'defineStore', 'chatApi', 'documentsApi', 'speechApi',
  'backendEnabled', 'useUiStore', 'useAuthStore', 'latestConversationMessageAt', 'sessionStorage', `${source};return useChatStore`)

const rows = [{ id: 'blank', title: '新会话', messages: 0 },
  { id: 'latest', title: '大模型定义', messages: 2 }, { id: 'poster', title: 'AI活动海报设计', messages: 2 }]
function fixture({ storage = new Map(), owner = 'alice', items = rows, blockedStorage = false } = {}) {
  const auth = { user: { id: owner } }, requests = []
  const api = { async list() { return { items } }, async messages(id) {
    requests.push(id)
    return { items: id === 'blank' ? [] : [{ id: `${id}-question`, role: 'user', content: id },
      { id: `${id}-answer`, role: 'assistant', content: '回复' }] }
  }, async latestAgentRun() { return { trace: null } } }
  const session = {
    getItem(key) { if (blockedStorage) throw Error('Storage unavailable'); return storage.get(key) ?? null },
    setItem(key, value) { if (blockedStorage) throw Error('Storage unavailable'); storage.set(key, value) },
  }
  const useStore = factory(computed, ref, watch, defineStore, api, {}, {}, false, () => ({}), () => auth,
    latestConversationMessageAt, session)
  return { chat: useStore(createPinia()), storage, auth, requests }
}

test('refresh restores the selected historical conversation even when a newer blank session is first', async () => {
  const first = fixture()
  await first.chat.loadConversations()
  await first.chat.loadMessages('poster')
  const refreshed = fixture({ storage: first.storage })
  await refreshed.chat.loadConversations()
  assert.equal(refreshed.chat.activeId, 'poster')
  assert.equal(refreshed.chat.activeConversation.title, 'AI活动海报设计')
  assert.equal(refreshed.chat.messages[0].content, 'poster')
  assert.deepEqual(refreshed.requests, ['poster'])
})

test('an intentionally selected empty conversation is also restored', async () => {
  const storage = new Map([['mindpilot:alice:active-conversation', 'blank']])
  const { chat } = fixture({ storage })
  await chat.loadConversations()
  assert.equal(chat.activeId, 'blank')
  assert.equal(chat.messages.length, 0)
})

test('deleted selections and unavailable storage fall back to a conversation with history', async () => {
  for (const options of [{ storage: new Map([['mindpilot:alice:active-conversation', 'deleted']]) }, { blockedStorage: true }]) {
    const { chat } = fixture(options)
    await chat.loadConversations()
    assert.equal(chat.activeId, 'latest')
    assert.equal(chat.messages[0].content, 'latest')
  }
})

test('account selections are isolated and logout reset retains the previous selection', async () => {
  const first = fixture()
  await first.chat.loadConversations()
  await first.chat.loadMessages('poster')
  first.chat.reset()
  assert.equal(first.storage.get('mindpilot:alice:active-conversation'), 'poster')
  const other = fixture({ storage: first.storage, owner: 'bob' })
  await other.chat.loadConversations()
  assert.equal(other.chat.activeId, 'latest')
  assert.equal(first.storage.get('mindpilot:alice:active-conversation'), 'poster')
  assert.equal(first.storage.get('mindpilot:bob:active-conversation'), 'latest')
})

test('empty lists remain empty and simultaneous initialization shares the restored load', async () => {
  const empty = fixture({ items: [] })
  await empty.chat.loadConversations()
  assert.equal(empty.chat.activeId, null)
  const f = fixture({ storage: new Map([['mindpilot:alice:active-conversation', 'poster']]) })
  await Promise.all([f.chat.loadConversations(), f.chat.loadConversations()])
  assert.equal(f.chat.activeId, 'poster')
  assert.deepEqual(f.requests, ['poster'])
})
