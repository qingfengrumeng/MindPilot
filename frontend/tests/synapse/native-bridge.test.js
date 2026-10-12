import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (await readFile(new URL('../../src/lib/synapseBridge.js', import.meta.url), 'utf8')).replace(/^import[^\r\n]*\r?\n/gm, '').replace('export function', 'function')
const factory = new Function('chatApi', 'conversationMapApi', 'backendEnabled', 'demoState', 'persistDemoState', `${source}; return createSynapseBridge`)
const rows = [
  { id: 'u1', role: 'user', content: 'first question' }, { id: 'a1', role: 'assistant', content: 'first answer' },
  { id: 'u2', role: 'user', content: 'later question' }, { id: 'a2', role: 'assistant', content: 'later answer' },
]
function fixture(apiOverrides = {}) {
  const chat = { conversations: [{ id: 'root', title: 'Root', messages: 4 }], activeId: 'root', messages: [...rows], generating: false,
    get activeConversation() { return this.conversations.find(row => row.id === this.activeId) },
    async loadMessages(id) { this.activeId = id; this.messages = id === 'root' ? [...rows] : [] }, async rename() {} }
  const store = { loaded: true, board: { nodes: { root: { groupId: 'g' } }, groups: [{ id: 'g', title: 'Workspace' }], synapse: {} },
    ensureNode(id) { return this.board.nodes[id] ||= {} }, async save() {}, async createWorkspaceConversation() { return 'root' } }
  const emitted = [], branchCalls = []
  const api = { async messages(id) { return { items: id === 'root' ? [...rows] : [] } }, async agentRuns() { return { items: [{ id: 'run', trace: { stages: [{ id: 'tool', kind: 'tool', title: 'search', summary: 'found' }, { kind: 'output', detail: { answer: 'first answer' } }] } }] } }, async latestAgentRun() { return { trace: null } }, ...apiOverrides }
  const bridge = factory(api, { async branch(payload) { branchCalls.push(payload); return { id: 'child', title: 'Branch' } } }, true, {}, () => {})({ chat, conversationBoard: store, publish: (...args) => emitted.push(args), notify() {} })
  return { bridge, chat, store, emitted, branchCalls }
}

test('native projection keeps stable turn ids and attaches historical tool traces', async () => {
  const { bridge, chat, store } = fixture()
  try {
    const projection = (await bridge.api('/synapse/api/workspaces/conversation-map:root')).workspace
    assert.equal(projection.threads[0].messages[1].process[0].name, 'search')
    const questionSeq = store.board.nodes.root.synapseSequences.u2
    chat.messages = chat.messages.slice(2)
    await bridge.api('/synapse/api/workspaces/conversation-map:root')
    assert.equal(store.board.nodes.root.synapseSequences.u2, questionSeq)
    await assert.rejects(bridge.api('/synapse/api/workspaces/foreign'))
    await assert.rejects(bridge.api('/synapse/api/threads/foreign', 'DELETE'))
  } finally { await bridge.dispose() }
})

test('fork passes the exact historical assistant id and preserves the native workspace', async () => {
  const { bridge, store, branchCalls } = fixture()
  try {
    await bridge.api('/synapse/api/workspaces/conversation-map:root')
    const sourceSeq = store.board.nodes.root.synapseSequences.a1
    await assert.rejects(bridge.fork('root', store.board.nodes.root.synapseSequences.u1))
    await bridge.fork('root', sourceSeq)
    assert.equal(branchCalls[0].sourceMessageId, 'a1')
    assert.equal(store.board.nodes.child.synapseSeedLength, sourceSeq + 1)
    assert.equal(store.board.nodes.child.groupId, 'g')
  } finally { await bridge.dispose() }
})

test('each turn stores its own color and rejects cards from other conversations', async () => {
  const { bridge, store } = fixture()
  try {
    await bridge.api('/synapse/api/threads/root', 'PATCH', { cardId: 'root:turn:1', color: '#2563eb' })
    const thread = (await bridge.api('/synapse/api/workspaces/conversation-map:root')).workspace.threads[0]
    assert.equal(thread.cardColors['root:turn:1'], '#2563eb')
    assert.equal(thread.cardColors['root:turn:3'], undefined)
    assert.equal(store.board.nodes.root.color, undefined)
    await assert.rejects(bridge.api('/synapse/api/threads/root', 'PATCH', { cardId: 'foreign:turn:1', color: '#2563eb' }))
  } finally { await bridge.dispose() }
})

test('canvas actions persist only to the allowed account board key', async () => {
  const { bridge, store } = fixture()
  try {
    const actions = JSON.stringify({ hiddenCards: ['root:turn:1'], links: [{ id: 'edge', source: 'root:turn:1', target: 'root:turn:3' }] })
    bridge.persist('dsh-synapse:canvas-actions:v1', actions)
    bridge.persist('foreign-storage', 'bad')
    assert.equal(store.board.synapse['dsh-synapse:canvas-actions:v1'], actions)
    assert.equal(store.board.synapse['foreign-storage'], undefined)
    bridge.persist('dsh-synapse:canvas-actions:v1', null)
    assert.equal(store.board.synapse['dsh-synapse:canvas-actions:v1'], undefined)
    await assert.rejects(bridge.api('/synapse/api/threads/root', 'DELETE'))
  } finally { await bridge.dispose() }
})

test('right-click creation uses the current native workspace and rejects foreign workspaces', async () => {
  const { bridge, store } = fixture()
  try {
    let chosen
    store.createWorkspaceConversation = async id => { chosen = id; return 'root' }
    assert.equal((await bridge.createSession('conversation-map:root')).id, 'root')
    assert.equal(chosen, 'g')
    await assert.rejects(bridge.createSession('foreign'))
  } finally { await bridge.dispose() }
})

test('independent conversations have separate maps even in the same sidebar workspace', async () => {
  const { bridge, chat, store } = fixture()
  try {
    chat.conversations.unshift({ id: 'blank', title: '新会话', messages: 0 }, { id: 'other', title: 'Other', messages: 2 })
    store.board.nodes.blank = { groupId: 'g' }
    store.board.nodes.other = { groupId: 'g' }
    chat.activeId = 'blank'; chat.messages = []
    const maps = bridge.workspaces()
    assert.deepEqual(maps.find(item => item.id === 'conversation-map:blank').sessionIds, ['blank'])
    assert.deepEqual(maps.find(item => item.id === 'conversation-map:root').sessionIds, ['root'])
    assert.deepEqual((await bridge.api('/synapse/api/workspaces/conversation-map:blank')).workspace.threads, [])
    bridge.sync()
    delete store.board.nodes.blank.groupId; delete store.board.nodes.other.groupId; delete store.board.nodes.root.groupId
    assert.deepEqual(bridge.workspaces().map(item => item.sessionIds), [['blank'], ['other'], ['root']])
  } finally { await bridge.dispose() }
})

test('a realtime greeting without a user query keeps the map empty, including after restoring history', async () => {
  const greeting = [
    { id: 'start', role: 'system', content: '实时通话', metadata: { type: 'realtime_marker' } },
    { id: 'greeting', role: 'assistant', content: '我是你的智能知识管家，今天有什么需求吗？' },
    { id: 'end', role: 'system', content: '实时通话结束', metadata: { type: 'realtime_marker' } },
  ]
  const { bridge, chat } = fixture({ async messages() { return { items: [...greeting] } } })
  try {
    chat.messages = [...greeting]
    assert.deepEqual((await bridge.api('/synapse/api/workspaces/conversation-map:root')).workspace.threads, [])
    chat.messages = []
    assert.deepEqual((await bridge.api('/synapse/api/workspaces/conversation-map:root')).workspace.threads, [])
    chat.messages = [...greeting, { id: 'u-query', role: 'user', content: '什么是大模型？' }]
    const projected = (await bridge.api('/synapse/api/workspaces/conversation-map:root')).workspace
    assert.equal(projected.threads.length, 1)
    assert.equal(projected.threads[0].messages.at(-1).text, '什么是大模型？')
  } finally { await bridge.dispose() }
})

test('branches and sessions created within a map retain membership after reload', async () => {
  const { bridge, chat, store } = fixture()
  try {
    await bridge.api('/synapse/api/workspaces/conversation-map:root')
    await bridge.fork('root', store.board.nodes.root.synapseSequences.a1)
    assert.deepEqual(bridge.workspaces()[0].sessionIds, ['child', 'root'])
    store.createWorkspaceConversation = async groupId => {
      assert.equal(groupId, 'g')
      chat.conversations.unshift({ id: 'topic', title: 'Topic', messages: 0 })
      chat.activeId = 'topic'; chat.messages = []
      store.board.nodes.topic = { groupId }
      return 'topic'
    }
    await bridge.createSession('conversation-map:root')
    assert.equal(store.board.nodes.topic.synapseMapId, 'root')
    assert.deepEqual(bridge.workspaces()[0].sessionIds, ['topic', 'child', 'root'])
    const restored = factory({}, {}, false, {}, () => {})({ chat, conversationBoard: store, publish() {}, notify() {} })
    try { assert.deepEqual(restored.workspaces()[0].sessionIds, ['topic', 'child', 'root']) }
    finally { await restored.dispose() }
  } finally { await bridge.dispose() }
})

test('existing colored regions move to their source map and do not appear in a new conversation', async () => {
  const { bridge, chat, store } = fixture()
  try {
    chat.conversations.unshift({ id: 'blank', title: '新会话', messages: 0 })
    store.board.synapse['dsh-synapse:canvas-actions:v1'] = JSON.stringify({ regions: [{
      id: 'region', workspaceId: 'dsh:g', color: '#0d9488', roots: ['root:turn:1'], sessions: [], x: 100, y: 200,
    }] })
    bridge.sync()
    const region = JSON.parse(store.board.synapse['dsh-synapse:canvas-actions:v1']).regions[0]
    assert.equal(region.workspaceId, 'dsh:conversation-map:root')
    assert.deepEqual(region.roots, ['root:turn:1'])
    assert.notEqual(region.workspaceId, 'dsh:conversation-map:blank')
    const migrated = JSON.stringify(region)
    bridge.sync()
    assert.equal(JSON.stringify(JSON.parse(store.board.synapse['dsh-synapse:canvas-actions:v1']).regions[0]), migrated)
  } finally { await bridge.dispose() }
})


test('stream keeps the projected question id when committed messages arrive', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const { bridge, store, chat, emitted } = fixture({ async streamChatReply(_id, _payload, _signal, onEvent) {
    onEvent({ type: 'trace', trace: {} }); await gate
    onEvent({ type: 'delta', text: 'answer' })
    onEvent({ type: 'done', userMessage: { id: 'saved-u', role: 'user', content: 'new question' }, assistantMessage: { id: 'saved-a', role: 'assistant', content: 'answer' } })
  } })
  try {
    await bridge.send('root', 'new question')
    const temporary = bridge.running.get('root').messages.at(-1).id
    const expectedSeq = store.board.nodes.root.synapseSequences[temporary]
    await assert.rejects(bridge.send('root', 'duplicate'))
    release(); await new Promise(resolve => setTimeout(resolve, 0))
    assert.equal(store.board.nodes.root.synapseSequences['saved-u'], expectedSeq)
    assert.equal(bridge.running.size, 0)
    assert.equal(chat.messages.at(-1).content, 'answer')
    assert.ok(emitted.some(([type, value]) => type === 'synapse:live-reply' && value.running === false))
  } finally { release(); await bridge.dispose() }
})
