import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { computed, ref, watch } from 'vue'
import { createPinia, defineStore } from 'pinia'
import { latestConversationMessageAt } from '../src/lib/conversationTime.js'
import { createReplyControl } from '../src/lib/replyControl.js'

const source = (await readFile(new URL('../src/stores/chat.js', import.meta.url), 'utf8'))
  .replace(/^import[^\r\n]*\r?\n/gm, '').replace('export const useChatStore', 'const useChatStore')
const factory = new Function('computed', 'ref', 'watch', 'defineStore', 'chatApi', 'documentsApi', 'speechApi',
  'backendEnabled', 'useUiStore', 'useAuthStore', 'latestConversationMessageAt', 'createReplyControl', 'sessionStorage', `${source};return useChatStore`)
const tick = () => new Promise(resolve => setTimeout(resolve, 10))

function fixture() {
  const requests = [], controls = [], errors = []
  const api = {
    async latestAgentRun() { return { trace: null } },
    async messages() { return { items: [] } },
    async controlReply(id, streamId, action) { controls.push(action) },
    streamChatReply(id, payload, signal, event) {
      return new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true })
        requests.push({ id, payload, event, finish: resolve })
      })
    }
  }
  const useStore = factory(computed, ref, watch, defineStore, api, {}, {}, true,
    () => ({ toast: text => errors.push(text) }), () => ({ user: { id: 'alice' } }),
    latestConversationMessageAt, createReplyControl, { setItem() {} })
  const chat = useStore(createPinia())
  chat.loaded = true
  chat.activeId = 'chat'
  chat.conversations = [{ id: 'chat', title: 'test', messages: 0 }, { id: 'other', title: 'other', messages: 0 }]
  return { chat, requests, controls, errors }
}

test('partial reply pauses and resumes the same stream without duplicating the question', async () => {
  const { chat, requests, controls } = fixture()
  const sent = chat.send('question')
  await tick()
  await requests[0].event({ type: 'delta', text: 'first' })
  await chat.pauseOutput()
  assert.equal(chat.outputPaused, true)
  assert.equal(chat.messages.at(-1).outputPaused, true)
  const tail = requests[0].event({ type: 'delta', text: ' second' })
  await tick()
  assert.equal(chat.messages.at(-1).content, 'first')
  await chat.resumeOutput()
  await tail
  assert.equal(chat.messages.at(-1).content, 'first second')
  assert.equal(chat.messages.at(-1).outputPaused, undefined)
  assert.equal(requests.length, 1)
  assert.equal(chat.messages.filter(item => item.role === 'user').length, 1)
  requests[0].finish()
  assert.equal(await sent, true)
  assert.deepEqual(controls, ['pause', 'resume'])
  assert.equal(chat.generating, false)
})

test('thinking cancellation cannot resume and the next send remains independent', async () => {
  const { chat, requests, controls, errors } = fixture()
  const first = chat.send('question')
  await tick()
  await chat.pauseOutput()
  assert.equal(await first, false)
  assert.equal(chat.outputPaused, false)
  assert.equal(chat.generating, false)
  assert.equal(chat.messages.at(-1).outputStopped, true)
  await chat.resumeOutput()
  assert.equal(requests.length, 1)
  const second = chat.send('retry')
  await tick()
  assert.equal(chat.generating, true)
  await requests[1].event({ type: 'delta', text: 'answer' })
  requests[1].finish()
  assert.equal(await second, true)
  assert.deepEqual(controls, ['cancel'])
  assert.deepEqual(errors, [])
})

test('switching conversation cancels a paused stream and ignores its buffered tail', async () => {
  const { chat, requests } = fixture()
  const sent = chat.send('question')
  await tick()
  await requests[0].event({ type: 'delta', text: 'first' })
  await chat.pauseOutput()
  const tail = requests[0].event({ type: 'delta', text: ' stale' })
  const tailRejected = assert.rejects(tail, { name: 'AbortError' })
  await chat.loadMessages('other')
  await tailRejected
  assert.equal(await sent, false)
  assert.equal(chat.activeId, 'other')
  assert.deepEqual(chat.messages, [])
  assert.equal(chat.outputPaused, false)
})
