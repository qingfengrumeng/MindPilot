import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { computed, ref, watch } from 'vue'
import { latestConversationMessageAt } from '../src/lib/conversationTime.js'

const source = readFileSync(new URL('../src/stores/chat.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export const useChatStore', 'const useChatStore')
const make = new Function('computed', 'ref', 'watch', 'defineStore', 'chatApi', 'documentsApi',
  'speechApi', 'backendEnabled', 'useUiStore', 'latestConversationMessageAt', 'setTimeout', 'clearTimeout',
  `${source}; return useChatStore()`)
const flush = () => new Promise(resolve => setImmediate(resolve))
function setup(api) {
  const timers = []
  const store = make(computed, ref, watch, (_, factory) => factory, api, {}, {}, true,
    () => ({}), latestConversationMessageAt, callback => { timers.push(callback); return timers.length }, () => {})
  store.conversations.value = [{ id: 'a', title: '首问', messages: 2 }]
  store.activeId.value = 'a'
  return { store, timers }
}

test('polling only observes the existing task and applies its final title once', async () => {
  let reads = 0
  const states = ['queued', 'running', 'completed']
  const { store, timers } = setup({ titleStatus: async () => ({ status: states[reads++], title: reads === 3 ? 'AI活动海报设计' : '首问' }) })
  store.observeTitle('a')
  store.observeTitle('a')
  await flush()
  assert.equal(reads, 1)
  timers.shift()()
  await flush()
  timers.shift()()
  await flush()
  assert.equal(store.conversations.value[0].title, 'AI活动海报设计')
  store.observeTitle('a')
  await flush()
  assert.equal(reads, 3)
  store.reset()
})

test('a failed task remains settled; subsequent messages cannot restart generation', async () => {
  let reads = 0
  const { store } = setup({ titleStatus: async () => { reads++; return { status: 'failed', title: '首问' } } })
  store.observeTitle('a')
  await flush()
  store.messages.value = [{ role: 'user', content: '后续问题' }, { role: 'assistant', content: '后续答案' }]
  store.observeTitle('a')
  await flush()
  assert.equal(reads, 1)
  assert.equal(store.conversations.value[0].title, '首问')
  store.reset()
})

test('observing before the first reply commits allows another read on completion', async () => {
  let reads = 0
  const { store } = setup({ titleStatus: async () => ({ status: ++reads === 1 ? 'idle' : 'completed', title: '简短标题' }) })
  store.observeTitle('a')
  await flush()
  store.observeTitle('a')
  await flush()
  assert.equal(reads, 2)
  store.reset()
})

test('old-account results are ignored after reset', async () => {
  let finish
  const { store } = setup({ titleStatus: () => new Promise(resolve => { finish = resolve }) })
  store.observeTitle('a')
  store.reset()
  store.conversations.value = [{ id: 'a', title: '新账户', messages: 2 }]
  finish({ status: 'completed', title: '旧账户标题' })
  await flush()
  assert.equal(store.conversations.value[0].title, '新账户')
  store.reset()
})
