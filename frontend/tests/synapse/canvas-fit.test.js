import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import test from 'node:test'

const source = await readFile(new URL('../../public/synapse/app.js', import.meta.url), 'utf8')
function fixture() {
  let rect = { width: 1200, height: 760 }, frame = null, paints = 0
  const cards = [{ id: 'a', position: { x: -6000, y: 3000 } }, { id: 'b', position: { x: 8000, y: 4500 } }]
  const state = { canvasCards: cards, canvasNeedsFit: true, canvasAutoOverview: true,
    mode: 'canvas', zoom: 1, canvasCamera: { x: 0, y: 0 } }
  const label = {}
  const context = vm.createContext({ state, CARD_WIDTH: 280, CARD_HEIGHT: 300, INITIAL_CANVAS_ZOOM: .8,
    app: { querySelector: selector => selector === '.canvas-viewport' ? { getBoundingClientRect: () => rect } : label },
    canvasRegionViews: () => [{ x: -6032, y: 2942, width: 14344, height: 1890 }],
    applyCanvasTransform: () => { paints++ }, syncCanvasViewport() {}, render() {},
    window: { requestAnimationFrame: callback => { frame = callback; return 1 } } })
  const code = source.slice(source.indexOf('function fittedCanvasView('), source.indexOf('async function createCanvasSession('))
  vm.runInContext(code, context)
  vm.runInContext(source.slice(source.indexOf('function focusActiveCard()'), source.indexOf('let selectionFollowup =')), context)
  return { context, state, cards, setRect: value => { rect = value }, paintCount: () => paints,
    runFrame: () => { const callback = frame; frame = null; callback?.() } }
}

test('widely separated saved cards and regions fit against the left margin without changing their positions', () => {
  const f = fixture()
  const original = JSON.stringify(f.cards)
  assert.equal(f.context.fitCanvas({ renderAfter: false }), true)
  assert.ok(f.state.zoom < .25)
  const { x, y } = f.state.canvasCamera, zoom = f.state.zoom
  for (const box of [...f.cards.map(card => ({ ...card.position, width: 280, height: 300 })), { x: -6032, y: 2942, width: 14344, height: 1890 }]) {
    assert.ok(box.x * zoom + x >= 49)
    assert.ok((box.x + box.width) * zoom + x <= 1151)
    assert.ok(box.y * zoom + y >= 64)
    assert.ok((box.y + box.height) * zoom + y <= 696)
  }
  assert.equal(JSON.stringify(f.cards), original)
  assert.equal(f.state.canvasNeedsFit, false)
})

test('a hidden iframe defers fitting until visible and later toggles preserve manual camera changes', () => {
  const f = fixture()
  f.setRect({ width: 0, height: 0 })
  f.context.scheduleInitialCanvasFit(); f.runFrame()
  assert.equal(f.state.canvasNeedsFit, true)
  assert.equal(f.paintCount(), 0)
  f.setRect({ width: 1200, height: 760 })
  f.context.scheduleInitialCanvasFit(); f.runFrame()
  assert.equal(f.state.canvasNeedsFit, false)
  assert.equal(f.state.zoom, .8)
  f.state.canvasCamera.x = 987
  f.context.scheduleInitialCanvasFit(); f.runFrame()
  assert.equal(f.state.canvasCamera.x, 987)
  assert.equal(f.paintCount(), 1)
})

test('small visible viewports and an empty canvas produce valid fitting decisions', () => {
  const { context } = fixture()
  assert.equal(context.fittedCanvasView([], 1200, 760), null)
  assert.equal(context.fittedCanvasView([{ x: 1, y: 1, width: 280, height: 300 }], 0, 0), null)
  const fitted = context.fittedCanvasView([{ x: 1, y: 1, width: 280, height: 300 }], 200, 180)
  assert.ok(fitted.zoom > 0 && fitted.zoom < 1)
  assert.ok(Number.isFinite(fitted.camera.x) && Number.isFinite(fitted.camera.y))
  assert.ok(Math.abs(fitted.camera.x + fitted.zoom - 20) < 1e-9)
})

test('late bootstrap session sync cannot replace the complete overview with single-card focus', () => {
  const f = fixture()
  f.context.scheduleInitialCanvasFit(); f.runFrame()
  const camera = JSON.stringify(f.state.canvasCamera)
  f.state.activeId = 'late-restored-session'
  f.context.focusActiveCard(); f.runFrame()
  assert.equal(JSON.stringify(f.state.canvasCamera), camera)
  assert.equal(f.paintCount(), 1)
})

test('initial view stays at 80 percent and anchors visible content to the left after resizing or later cards arrive', () => {
  const f = fixture()
  f.context.scheduleInitialCanvasFit(); f.runFrame()
  assert.equal(f.state.zoom, .8)
  assert.ok(Math.abs(-6032 * f.state.zoom + f.state.canvasCamera.x - 50) < 1e-9)
  assert.ok(Math.abs(2942 * f.state.zoom + f.state.canvasCamera.y - 65) < 1e-9)
  f.setRect({ width: 800, height: 760 })
  f.context.scheduleInitialCanvasFit(); f.runFrame()
  assert.equal(f.state.zoom, .8)
  f.cards.push({ id: 'late-card', position: { x: 20000, y: 3000 } })
  f.context.scheduleInitialCanvasFit(); f.runFrame()
  assert.equal(f.state.zoom, .8)
  assert.equal(f.paintCount(), 3)
  // Users can still fit the entire large map explicitly.
  f.context.fitCanvas()
  assert.ok(f.state.zoom < .25)
  assert.equal(f.state.canvasAutoOverview, false)
})

test('user interaction ends automatic overview and cancels pending fitting', () => {
  const f = fixture()
  f.context.scheduleInitialCanvasFit()
  f.context.stopCanvasAutoOverview()
  f.state.canvasCamera = { x: 777, y: 888 }
  f.runFrame()
  f.setRect({ width: 800, height: 760 })
  f.context.scheduleInitialCanvasFit(); f.runFrame()
  assert.equal(f.state.canvasCamera.x, 777)
  assert.equal(f.state.canvasCamera.y, 888)
  assert.equal(f.paintCount(), 0)
})
