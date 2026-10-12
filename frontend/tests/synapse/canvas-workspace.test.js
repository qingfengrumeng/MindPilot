import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import test from 'node:test'

const source = await readFile(new URL('../../public/synapse/app.js', import.meta.url), 'utf8')
function fixture(api) {
  const state = { dshWorkspaces: [
    { id: 'conversation-map:old', title: 'Old', sessionIds: ['old'] },
    { id: 'conversation-map:blank', title: 'Blank', sessionIds: ['blank'] },
  ], currentDsh: { id: 'blank' }, workspace: { id: 'dsh:conversation-map:old', threads: [{ id: 'old', dshSessionId: 'old' }] },
    selectedDshWorkspaceId: 'conversation-map:old', workspaceLoad: 0, activeId: 'old', summaries: [],
    inspectorCardId: 'old:turn:1', draft: null }
  const context = vm.createContext({ state, api, resetCanvasCamera() {}, render() {}, canReplaceView: () => true,
    conversationCards: () => [], revealConversationThread() {}, loadThreadHistory: async () => {} })
  vm.runInContext(source.slice(source.indexOf('function currentDshWorkspace()'), source.indexOf('function focusDraftInput()')), context)
  return { state, context }
}

test('switching to an empty conversation clears old cards before its projection resolves and requests only its map', async () => {
  let resolve, requested
  const { state, context } = fixture(path => { requested = path; return new Promise(done => { resolve = done }) })
  const loading = context.openCurrentWorkspace()
  assert.equal(requested, '/synapse/api/workspaces/conversation-map:blank')
  assert.equal(state.workspace.id, 'dsh:conversation-map:blank')
  assert.equal(state.workspace.threads.length, 0)
  assert.equal(state.inspectorCardId, null)
  assert.equal(state.activeId, null)
  resolve({ workspace: { threads: [] } }); await loading
  assert.equal(state.workspace.threads.length, 0)
})

test('a delayed historical projection cannot overwrite the subsequently selected blank conversation', async () => {
  let finishOld
  const { state, context } = fixture(path => path.endsWith(':old')
    ? new Promise(done => { finishOld = done }) : Promise.resolve({ workspace: { threads: [] } }))
  const older = context.openDshWorkspace('conversation-map:old')
  await context.openDshWorkspace('conversation-map:blank')
  finishOld({ workspace: { threads: [{ id: 'old', dshSessionId: 'old' }] } }); await older
  assert.equal(state.workspace.id, 'dsh:conversation-map:blank')
  assert.equal(state.workspace.threads.length, 0)
})

test('summary bootstrap waits for the active conversation scope instead of opening the first historical map', async () => {
  const paths = []
  const { state, context } = fixture(async path => { paths.push(path); return { workspaces: [{ id: 'conversation-map:old' }] } })
  state.workspace = null; state.selectedDshWorkspaceId = null; state.dshWorkspaces = []
  await context.refreshSummaries()
  assert.deepEqual(paths, ['/synapse/api/workspaces'])
  assert.equal(state.workspace, null)
})
