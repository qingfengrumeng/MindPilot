import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import test from 'node:test'

async function fixture(cards = []) {
  const source = await readFile(new URL('../../public/synapse/app.js', import.meta.url), 'utf8')
  const code = source.slice(source.indexOf('function normalizeCanvasRegions('), source.indexOf('function hideCanvasCard('))
  const stored = new Map()
  const state = { workspace: { id: 'workspace-a', threads: [] }, regions: [], canvasCards: cards,
    hiddenCardIds: new Set(), links: [], draft: null, quickPhrases: [], quickPhraseEditorOpen: false,
    cardPositions: new Map(), canvasCardsById: new Map(cards.map(card => [card.id, card])) }
  const context = vm.createContext({ state, REGION_COLORS: ['#7c3aed', '#2563eb'], CARD_WIDTH: 280, CARD_HEIGHT: 300,
    CANVAS_ACTIONS_KEY: 'actions', localStorage: { setItem: (key, value) => stored.set(key, value) },
    conversationCards: () => cards, crypto: { randomUUID: () => 'new-region' }, render() {},
    draftPlacement: () => state.draft?.placement || null })
  vm.runInContext(code, context)
  const region = (id, roots, extra = {}) => ({ id, workspaceId: 'workspace-a', color: '#7c3aed', x: 0, y: 0, roots, sessions: [], ...extra })
  return { context, state, stored, region }
}

test('a topic region covers descendants and future branches but excludes unrelated topics', async () => {
  const cards = [{ id: 'a', parentId: null }, { id: 'b', parentId: 'a' }, { id: 'c', parentId: 'b' },
    { id: 'branch', parentId: 'a' }, { id: 'other', parentId: null }]
  const f = await fixture(cards)
  f.state.regions = [f.region('topic', ['a']), f.region('foreign', ['other'], { workspaceId: 'workspace-b' })]
  assert.deepEqual(JSON.parse(JSON.stringify([...f.context.regionMembership(cards)])), [['a', 'topic'], ['b', 'topic'], ['c', 'topic'], ['branch', 'topic']])
  cards.push({ id: 'future', parentId: 'branch' })
  assert.equal(f.context.regionMembership(cards).get('future'), 'topic')
})

test('a later topic root splits its own descendants and malformed cycles terminate', async () => {
  const cards = [{ id: 'a', parentId: null }, { id: 'b', parentId: 'a' }, { id: 'c', parentId: 'b' },
    { id: 'x', parentId: 'y' }, { id: 'y', parentId: 'x' }]
  const f = await fixture(cards)
  f.state.regions = [f.region('first', ['a']), f.region('second', ['b'])]
  assert.deepEqual(JSON.parse(JSON.stringify([...f.context.regionMembership(cards)])), [['a', 'first'], ['b', 'second'], ['c', 'second']])
})

test('sessions created in a region retain membership when the empty card becomes a real first turn', async () => {
  const f = await fixture()
  f.state.regions = [f.region('topic', [], { sessions: ['session'] })]
  for (const id of ['session:turn:empty', 'session:turn:1']) {
    const cards = [{ id, dshThreadId: 'session', turnIndex: 0 }, { id: 'followup', parentId: id, turnIndex: 1 }]
    assert.equal(f.context.regionMembership(cards).get('followup'), 'topic')
  }
})

test('bounds track visible card moves and drafts, while collapsed ancestors still establish membership', async () => {
  const cards = [{ id: 'a', parentId: null, position: { x: 10, y: 20 } },
    { id: 'b', parentId: 'a', position: { x: 400, y: 100 } }]
  const f = await fixture(cards)
  f.state.regions = [f.region('topic', ['a'])]
  f.state.canvasCards = [cards[1]]
  let view = f.context.canvasRegionViews()[0]
  assert.equal(view.x, 368)
  assert.equal(view.width, 344)
  cards[1].position.x = 800
  f.state.draft = { kind: 'continue', anchorId: 'b', placement: { parent: cards[1], position: { x: 1165, y: 100 } } }
  view = f.context.canvasRegionViews()[0]
  assert.equal(view.x, 768)
  assert.equal(view.width, 709)
})

test('nameless empty regions and colors survive reload alongside existing canvas actions', async () => {
  const f = await fixture()
  f.state.regionDialog = { point: { x: -100, y: -200 } }
  f.context.saveRegionColor('#2563eb')
  const saved = JSON.parse(f.stored.get('actions'))
  assert.equal(saved.regions[0].name, undefined)
  assert.equal(saved.regions[0].color, '#2563eb')
  f.state.regions = f.context.normalizeCanvasRegions(saved.regions)
  const view = f.context.canvasRegionViews()[0]
  assert.equal(view.empty, true)
  assert.equal(view.x, -100)
  assert.equal(view.height, 390)
  assert.equal(f.context.normalizeCanvasRegions([{ ...saved.regions[0], color: 'invalid' }]).length, 0)
})

test('group dragging moves hidden descendants and position aliases, preserving unrelated cards', async () => {
  const cards = [{ id: 'a', positionKey: 'a:index:0', parentId: null, position: { x: 10, y: 20 } },
    { id: 'b', positionKey: 'b:index:0', parentId: 'a', position: { x: 400, y: 100 } },
    { id: 'other', parentId: null, position: { x: 10, y: 500 } }]
  const f = await fixture(cards)
  f.state.regions = [f.region('topic', ['a'])]
  f.state.canvasCards = [cards[0], cards[2]]
  f.state.canvasCardsById.delete('b')
  const snapshot = f.context.regionDragSnapshot('topic')
  f.context.translateCanvasRegion(snapshot, 240, -120)
  assert.equal(cards[0].position.x, 250)
  assert.equal(f.state.cardPositions.get('b').x, 640)
  assert.equal(f.state.cardPositions.get('b:index:0').y, -20)
  assert.equal(cards[2].position.x, 10)
  assert.equal(f.state.cardPositions.has('other'), false)
  // Pointer moves use their initial snapshot rather than accumulating prior deltas.
  f.context.translateCanvasRegion(snapshot, 300, -80)
  assert.equal(cards[0].position.x, 310)
  assert.equal(f.state.cardPositions.get('b').x, 700)
})

test('an empty region can be dragged and its location survives persistence', async () => {
  const f = await fixture()
  f.state.regions = [f.region('empty', [], { x: -100, y: 50 })]
  const snapshot = f.context.regionDragSnapshot('empty')
  f.context.translateCanvasRegion(snapshot, -60, 120)
  f.context.persistCanvasActions()
  const saved = JSON.parse(f.stored.get('actions'))
  assert.equal(saved.regions[0].x, -160)
  assert.equal(saved.regions[0].y, 170)
})

test('the region draft moves with its parent while another topic retains its position', async () => {
  const cards = [{ id: 'a', parentId: null, position: { x: 10, y: 20 } },
    { id: 'b', parentId: 'a', position: { x: 400, y: 100 } }]
  const f = await fixture(cards)
  f.state.regions = [f.region('first', ['a']), f.region('second', ['b'])]
  f.state.draft = { kind: 'continue', anchorId: 'a', placement: { parent: cards[0], position: { x: 10, y: 362 } } }
  const snapshot = f.context.regionDragSnapshot('first')
  f.context.translateCanvasRegion(snapshot, 50, 70)
  assert.equal(f.state.draft.position.x, 60)
  assert.equal(f.state.draft.position.y, 432)
  assert.equal(cards[1].position.x, 400)
  assert.equal(cards[1].position.y, 100)
})
