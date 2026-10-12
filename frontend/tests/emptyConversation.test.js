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

function fixture(rows = [], createGate = null) {
  const calls = [], session = { getItem: () => null, setItem() {} }
  const api = {
    async list() { return { items: rows.map(row => ({ ...row })) } },
    async messages(id) { calls.push(['messages', id]); return { items: rows.find(row => row.id === id)?.messages ? [{ role: 'user', content: '已有问题' }] : [] } },
    async latestAgentRun() { return { trace: null } },
    async create() { calls.push(['create']); await createGate; return { id: `new-${calls.filter(c => c[0] === 'create').length}`, title: '新会话', messages: 0, taskId: 'general' } },
    async remove() { throw new Error('New chat must never delete the reusable draft') }
  }
  const useStore = factory(computed, ref, watch, defineStore, api, {}, {}, false, () => ({}),
    () => ({ user: { id: 'owner' } }), latestConversationMessageAt, session)
  return { chat: useStore(createPinia()), calls }
}

test('restored empty conversations without transient draft flags are reused', async () => {
  const { chat, calls } = fixture([{ id: 'old-blank', title: '新会话', messages: 0 }, { id: 'history', title: '历史会话', messages: 2 }])
  await chat.loadConversations()
  assert.equal(chat.activeId, 'history')
  await chat.newChat()
  await chat.newChat()
  assert.equal(chat.activeId, 'old-blank')
  assert.equal(chat.messages.length, 0)
  assert.equal(calls.filter(c => c[0] === 'create').length, 0)
  assert.equal(calls.filter(c => c[0] === 'messages' && c[1] === 'old-blank').length, 1)
})

test('rapid clicks create a single draft, later clicks reuse the same id', async () => {
  const { chat, calls } = fixture()
  await Promise.all([chat.newChat(), chat.newChat(), chat.newChat()])
  await chat.newChat({ keepEmpty: true })
  assert.equal(calls.filter(c => c[0] === 'create').length, 1)
  assert.equal(chat.conversations.length, 1)
  assert.equal(chat.activeId, 'new-1')
})

test('named empty conversations and conversations with messages are preserved', async () => {
  const rows = [{ id: 'named', title: '我的任务', messages: 0 }, { id: 'history', title: '新会话', messages: 1 }]
  const { chat, calls } = fixture(rows)
  await chat.newChat()
  assert.equal(calls.filter(c => c[0] === 'create').length, 1)
  assert.deepEqual(new Set(chat.conversations.map(row => row.id)), new Set(['named', 'history', 'new-1']))
})

test('an outgoing account creation cannot overwrite the store after reset', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const { chat, calls } = fixture([], gate)
  const creating = chat.newChat()
  while (!calls.some(c => c[0] === 'create')) await new Promise(resolve => setImmediate(resolve))
  chat.reset(); release(); await creating
  assert.equal(chat.activeId, null)
  assert.deepEqual(chat.conversations, [])
})
