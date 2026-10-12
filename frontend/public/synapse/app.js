const app = document.querySelector('#app')
if ('scrollRestoration' in history) history.scrollRestoration = 'manual'
const LEGACY_CARD_POSITIONS_KEY = 'dsh-synapse:card-positions'
const CARD_POSITIONS_KEY = 'dsh-synapse:card-positions:v4'
const CARD_WIDTH = 280
const CARD_HEIGHT = 300
const CARD_GAP_Y = 42
const INITIAL_CANVAS_ZOOM = .8
const COLLAPSED_CARDS_KEY = 'dsh-synapse:collapsed-cards:v1'
const QUICK_PHRASES_KEY = 'dsh-synapse:quick-phrases:v1'
const DEFAULT_QUICK_PHRASES = ['展开说明', '举例', '通俗易懂', '对比解释']
const MAX_QUICK_PHRASES = 12
const MAX_QUICK_PHRASE_LENGTH = 16
function normalizeQuickPhrases(value) {
  if (!Array.isArray(value)) return []
  const phrases = []
  for (const item of value) {
    const phrase = typeof item === 'string' ? item.trim().slice(0, MAX_QUICK_PHRASE_LENGTH) : ''
    if (phrase !== '' && !phrases.includes(phrase)) phrases.push(phrase)
    if (phrases.length === MAX_QUICK_PHRASES) break
  }
  return phrases
}
const savedQuickPhrases = (() => {
  try {
    const stored = localStorage.getItem(QUICK_PHRASES_KEY)
    return stored === null ? DEFAULT_QUICK_PHRASES : normalizeQuickPhrases(JSON.parse(stored))
  } catch { return DEFAULT_QUICK_PHRASES }
})()
const savedBranchAnchors = (() => {
  try {
    const value = JSON.parse(localStorage.getItem('dsh-synapse:branch-anchors') ?? '[]')
    return Array.isArray(value) ? value.filter(item => Array.isArray(item) && typeof item[0] === 'string' && typeof item[1] === 'string') : []
  } catch { return [] }
})()
const savedCardPositions = (() => {
  try {
    // Drop formats that were never persisted; the current key stores drags.
    localStorage.removeItem(LEGACY_CARD_POSITIONS_KEY)
    localStorage.removeItem('dsh-synapse:card-positions:v2')
    const stored = localStorage.getItem(CARD_POSITIONS_KEY)
    const value = JSON.parse(stored ?? localStorage.getItem('dsh-synapse:card-positions:v3') ?? '[]')
    const positions = Array.isArray(value) ? value.filter(item => Array.isArray(item) && typeof item[0] === 'string' && item[1] !== null && Number.isFinite(item[1].x) && Number.isFinite(item[1].y)) : []
    if (stored !== null) return positions
    // Expand existing vertical spacing once so taller cards retain their layout.
    const resized = positions.map(([id, position]) => [id, {
      x: position.x, y: 82 + (position.y - 82) * (CARD_HEIGHT + CARD_GAP_Y) / (210 + CARD_GAP_Y),
    }])
    localStorage.setItem(CARD_POSITIONS_KEY, JSON.stringify(resized))
    return resized
  } catch { return [] }
})()
const savedCollapsedCards = (() => {
  try {
    const value = JSON.parse(localStorage.getItem(COLLAPSED_CARDS_KEY) ?? '[]')
    return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []
  } catch { return [] }
})()
const CANVAS_ACTIONS_KEY = 'dsh-synapse:canvas-actions:v1'
const savedCanvasActions = (() => { try { const value = JSON.parse(localStorage.getItem(CANVAS_ACTIONS_KEY) || '{}'); return value && typeof value === 'object' ? value : {} } catch { return {} } })()
const REGION_COLORS = ['#7c3aed', '#2563eb', '#0ea5e9', '#0d9488', '#16a34a', '#d97706', '#ea580c', '#db2777']
const CAMERA_INSET_X = 56
const CAMERA_INSET_Y = 56
// Cards outside the viewport (plus this world-space margin) are not mounted
// into the DOM; the margin pre-mounts cards just before they scroll into view
// so panning never flashes empty space.
const VIEWPORT_MARGIN = 1400
const state = {
  summaries: [], workspace: null, activeId: null, selectedCardId: null, mode: 'canvas', zoom: INITIAL_CANVAS_ZOOM, currentDsh: null,
  dshWorkspaces: [], selectedDshWorkspaceId: null,
  historyBySession: new Map(), historyRequests: new Map(), pendingReplies: new Map(), pendingRpc: new Map(), liveReplies: new Map(),
  draft: null, error: '', workspaceLoad: 0, branchAnchors: new Map(savedBranchAnchors), cardPositions: new Map(savedCardPositions), collapsedCardIds: new Set(savedCollapsedCards), quickPhrases: savedQuickPhrases, quickPhraseEditorOpen: false,
  dragging: false, canvasGesture: false, canvasRefreshAfter: 0, canvasViewInitialized: false, canvasCamera: { x: 0, y: 0 }, mapCardSessionSwitches: new Set(),
  expandedMessageIds: new Set(),
  canvasCards: undefined, canvasCardsById: undefined, canvasGraph: undefined, mountedCardIds: new Set(), canvasNeedsFit: true, canvasAutoOverview: true, canvasOverviewSignature: null,
  inspectorCardId: null, inspectorOpening: false, inspectorScrollByCard: new Map(),
  hiddenCardIds: new Set(Array.isArray(savedCanvasActions.hiddenCards) ? savedCanvasActions.hiddenCards.filter(id => typeof id === 'string') : []),
  links: Array.isArray(savedCanvasActions.links) ? savedCanvasActions.links.filter(edge => edge && typeof edge.id === 'string' && typeof edge.source === 'string' && typeof edge.target === 'string' && edge.source !== edge.target) : [],
  regions: normalizeCanvasRegions(savedCanvasActions.regions), regionDialog: null, selectedRegionId: null,
  menu: null, linkSource: null, selectedLinkId: null, helpOpen: false, editCardId: null, deleteCardId: null,
}

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]))

function rememberBranchAnchor(sessionId, cardId) {
  state.branchAnchors.set(sessionId, cardId)
  try { localStorage.setItem('dsh-synapse:branch-anchors', JSON.stringify([...state.branchAnchors])) } catch { /* Private browsing may disable local storage. */ }
}

function persistCardPositions() {
  try { localStorage.setItem(CARD_POSITIONS_KEY, JSON.stringify([...state.cardPositions])) } catch { /* Private browsing may disable local storage. */ }
}

function persistCollapsedCards() {
  try { localStorage.setItem(COLLAPSED_CARDS_KEY, JSON.stringify([...state.collapsedCardIds])) } catch { /* Private browsing may disable local storage. */ }
}

function normalizeCanvasRegions(value) {
  if (!Array.isArray(value)) return []
  return value.filter(region => region && typeof region.id === 'string' && typeof region.workspaceId === 'string'
    && REGION_COLORS.includes(region.color) && Number.isFinite(region.x) && Number.isFinite(region.y))
    .map(region => ({ id: region.id, workspaceId: region.workspaceId, color: region.color, x: region.x, y: region.y,
      roots: Array.isArray(region.roots) ? region.roots.filter(id => typeof id === 'string') : [],
      sessions: Array.isArray(region.sessions) ? region.sessions.filter(id => typeof id === 'string') : [] }))
}
function currentCanvasRegions() {
  return state.regions.filter(region => region.workspaceId === state.workspace?.id)
}
function regionMembership(cards, regions = currentCanvasRegions()) {
  const byId = new Map(cards.map(card => [card.id, card]))
  const roots = new Map()
  for (const region of regions) {
    for (const id of region.roots) roots.set(id, region.id)
    for (const card of cards) {
      if (card.turnIndex === 0 && region.sessions.includes(card.dshSessionId || card.dshThreadId)) roots.set(card.id, region.id)
    }
  }
  const membership = new Map()
  for (const card of cards) {
    const visited = new Set()
    let cursor = card
    while (cursor && !visited.has(cursor.id)) {
      visited.add(cursor.id)
      if (roots.has(cursor.id)) { membership.set(card.id, roots.get(cursor.id)); break }
      cursor = byId.get(cursor.parentId)
    }
  }
  return membership
}
function canvasRegionViews(cards = state.canvasCards || []) {
  // Use the complete graph for membership, including collapsed or hidden ancestors.
  const all = conversationCards(state.workspace?.threads || [])
  const byId = new Map(cards.map(card => [card.id, card]))
  const membership = regionMembership(all)
  const placement = state.draft && state.draft.kind !== 'new' ? draftPlacement(cards) : null
  const draftRegion = state.draft?.regionId || membership.get(placement?.parent?.id || state.draft?.anchorId)
  return currentCanvasRegions().map(region => {
    const members = all.filter(card => membership.get(card.id) === region.id && byId.has(card.id))
      .map(card => ({ ...card, position: byId.get(card.id).position }))
    const boxes = members.map(card => ({ x: card.position.x, y: card.position.y, width: CARD_WIDTH, height: CARD_HEIGHT }))
    if (state.draft && draftRegion === region.id) {
      const position = state.draft.kind === 'new' ? state.draft.position : placement?.position
      const height = state.quickPhraseEditorOpen ? Math.max(CARD_HEIGHT, 263 + state.quickPhrases.length * 30) : CARD_HEIGHT
      if (position) boxes.push({ ...position, width: CARD_WIDTH, height })
    }
    if (!boxes.length) return { ...region, width: CARD_WIDTH + 64, height: CARD_HEIGHT + 90, empty: true }
    const x = Math.min(...boxes.map(box => box.x)) - 32, y = Math.min(...boxes.map(box => box.y)) - 58
    return { ...region, x, y, width: Math.max(...boxes.map(box => box.x + box.width)) - x + 32,
      height: Math.max(...boxes.map(box => box.y + box.height)) - y + 32, empty: false }
  })
}
function canvasRegionsHtml(cards) {
  return canvasRegionViews(cards).map(region => `<section class="canvas-region${state.selectedRegionId === region.id ? ' selected' : ''}" data-region-id="${escapeHtml(region.id)}" aria-label="主题区域" style="left:${region.x}px;top:${region.y}px;width:${region.width}px;height:${region.height}px;--region-color:${region.color}"><div class="region-toolbar"><span class="region-color-dot" aria-hidden="true"></span><button type="button" data-action="region-color" data-region="${escapeHtml(region.id)}" title="修改区域颜色" aria-label="修改区域颜色">${canvasIcon('edit')}</button><button type="button" data-action="region-remove" data-region="${escapeHtml(region.id)}" title="移除区域，保留会话" aria-label="移除区域，保留会话">${canvasIcon('minus')}</button></div></section>`).join('')
}
function syncCanvasRegions() {
  for (const region of canvasRegionViews()) {
    const element = app.querySelector(`[data-region-id="${selectorValue(region.id)}"]`)
    if (!element) continue
    element.style.left = `${region.x}px`; element.style.top = `${region.y}px`
    element.style.width = `${region.width}px`; element.style.height = `${region.height}px`
    element.classList.toggle('selected', state.selectedRegionId === region.id)
  }
}
function selectCanvasRegion(id) {
  if (id !== null) stopCanvasAutoOverview()
  state.selectedRegionId = id
  state.selectedCardId = null; state.selectedLinkId = null
  for (const element of app.querySelectorAll('.canvas-region')) element.classList.toggle('selected', element.dataset.regionId === id)
  for (const card of app.querySelectorAll('.thread-card.selected')) {
    card.classList.remove('selected'); card.querySelector('.card-color-palette')?.remove()
  }
}
function regionDragSnapshot(id) {
  const region = currentCanvasRegions().find(item => item.id === id)
  if (!region) return null
  const all = conversationCards(state.workspace?.threads || [])
  const membership = regionMembership(all)
  const placement = draftPlacement(state.canvasCards || [])
  const draftRegion = state.draft?.regionId || membership.get(placement?.parent?.id || state.draft?.anchorId)
  return { id, x: region.x, y: region.y,
    cards: all.filter(card => membership.get(card.id) === id).map(card => ({ id: card.id, positionKey: card.positionKey, position: { ...card.position } })),
    draft: draftRegion === id && state.draft ? { draft: state.draft, position: { ...(state.draft.kind === 'new' ? state.draft.position : placement?.position) } } : null }
}
function translateCanvasRegion(snapshot, dx, dy) {
  const region = currentCanvasRegions().find(item => item.id === snapshot.id)
  if (!region) return
  region.x = snapshot.x + dx; region.y = snapshot.y + dy
  for (const card of snapshot.cards) {
    const position = { x: card.position.x + dx, y: card.position.y + dy }
    state.cardPositions.set(card.id, position)
    if (card.positionKey) state.cardPositions.set(card.positionKey, position)
    const visible = state.canvasCardsById?.get(card.id)
    if (visible) visible.position = position
  }
  if (snapshot.draft && state.draft === snapshot.draft.draft) {
    state.draft.position = { x: snapshot.draft.position.x + dx, y: snapshot.draft.position.y + dy }
  }
}
function regionColorDialog() {
  const dialog = state.regionDialog
  if (!dialog) return ''
  return `<div class="canvas-dialog-backdrop"><div class="canvas-dialog region-dialog" role="dialog" aria-modal="true" aria-labelledby="region-dialog-title"><h2 id="region-dialog-title">${dialog.id ? '修改区域颜色' : '增加区域'}</h2><p>选择一种颜色${dialog.rootId ? '，此卡片及后续追问、分支会自动归入区域' : ''}。</p><div class="region-color-options">${REGION_COLORS.map(color => `<button type="button" data-action="choose-region-color" data-color="${color}" aria-label="${({ '#7c3aed': '紫色', '#2563eb': '蓝色', '#0ea5e9': '天蓝色', '#0d9488': '青色', '#16a34a': '绿色', '#d97706': '橙色', '#ea580c': '珊瑚色', '#db2777': '粉色' })[color]}" aria-pressed="${dialog.color === color}" style="--swatch-color:${color}"><span></span></button>`).join('')}</div><div><button type="button" data-action="cancel-dialog">取消</button></div></div></div>`
}
function saveRegionColor(color) {
  const dialog = state.regionDialog
  if (!dialog || !REGION_COLORS.includes(color)) return
  const existing = state.regions.find(region => region.id === dialog.id)
  if (existing) existing.color = color
  else state.regions.push({ id: crypto.randomUUID(), workspaceId: state.workspace.id, color,
    x: dialog.point.x, y: dialog.point.y, roots: dialog.rootId ? [dialog.rootId] : [], sessions: dialog.sessionId ? [dialog.sessionId] : [] })
  state.regionDialog = null
  persistCanvasActions(); render()
}
function persistCanvasActions() {
  localStorage.setItem(CANVAS_ACTIONS_KEY, JSON.stringify({ hiddenCards: [...state.hiddenCardIds], links: state.links, regions: state.regions }))
}
function hideCanvasCard(id) {
  state.hiddenCardIds.add(id)
  state.selectedCardId = null
  if (state.inspectorCardId === id) state.inspectorCardId = null
  state.menu = null; state.deleteCardId = null; state.linkSource = null
  persistCanvasActions(); render()
}
function restoreCanvasCards() {
  const ids = new Set(conversationCards(state.workspace?.threads || []).map(card => card.id))
  for (const id of ids) state.hiddenCardIds.delete(id)
  state.menu = null; persistCanvasActions(); render()
}
function fittedCanvasView(boxes, width, height, initialZoom = null) {
  if (!boxes.length || width <= 0 || height <= 0) return null
  const minX = Math.min(...boxes.map(box => box.x)), minY = Math.min(...boxes.map(box => box.y))
  const maxX = Math.max(...boxes.map(box => box.x + box.width)), maxY = Math.max(...boxes.map(box => box.y + box.height))
  const spanX = Math.max(1, maxX - minX), spanY = Math.max(1, maxY - minY)
  const paddingX = Math.min(50, width / 10), paddingY = Math.min(65, height / 10)
  // Start at a readable scale; only the explicit fit action shrinks the whole map.
  const zoom = initialZoom ?? Math.min(1, (width - paddingX * 2) / spanX, (height - paddingY * 2) / spanY)
  return { zoom, camera: { x: paddingX - minX * zoom,
    y: Math.max(paddingY - minY * zoom, height / 2 - (minY + maxY) / 2 * zoom) } }
}
function canvasFitGeometry() {
  const cards = state.canvasCards || []
  const viewport = app.querySelector('.canvas-viewport')
  if (!viewport) return null
  const regions = canvasRegionViews(cards)
  const boxes = [...cards.map(card => ({ ...card.position, width: CARD_WIDTH, height: CARD_HEIGHT })),
    ...regions.map(region => ({ x: region.x, y: region.y, width: region.width, height: region.height }))]
  const { width, height } = viewport.getBoundingClientRect()
  return { boxes, width, height, signature: JSON.stringify([width, height, boxes]) }
}
function stopCanvasAutoOverview() {
  state.canvasAutoOverview = false
  state.canvasNeedsFit = false
}
function fitCanvas({ renderAfter = true, initialZoom = null } = {}) {
  const geometry = canvasFitGeometry()
  if (!geometry) return false
  const fitted = fittedCanvasView(geometry.boxes, geometry.width, geometry.height, initialZoom)
  if (!fitted) return false
  if (renderAfter) stopCanvasAutoOverview()
  state.zoom = fitted.zoom
  state.canvasCamera = fitted.camera
  state.canvasNeedsFit = false
  state.canvasOverviewSignature = geometry.signature
  state.menu = null
  if (renderAfter) render()
  else {
    applyCanvasTransform()
    syncCanvasViewport()
    const label = app.querySelector('.canvas-controls span')
    if (label) label.textContent = `${Math.round(state.zoom * 100)}%`
  }
  return true
}
let initialCanvasFitFrame = 0
function scheduleInitialCanvasFit() {
  if (state.mode !== 'canvas') return
  if (state.canvasAutoOverview) {
    const geometry = canvasFitGeometry()
    if (geometry && geometry.width > 0 && geometry.height > 0 && geometry.signature !== state.canvasOverviewSignature) state.canvasNeedsFit = true
  }
  if (!state.canvasNeedsFit || initialCanvasFitFrame) return
  initialCanvasFitFrame = window.requestAnimationFrame(() => {
    initialCanvasFitFrame = 0
    if (state.canvasNeedsFit && state.mode === 'canvas') fitCanvas({ renderAfter: false, initialZoom: INITIAL_CANVAS_ZOOM })
  })
}
// The iframe can initialize while its parent is hidden. Fit only once a real
// viewport exists; subsequent dialog/map toggles retain the user's camera.

async function createCanvasSession(point) {
  if (state.draft) throw new Error('请先发送或取消当前草稿')
  stopCanvasAutoOverview()
  state.menu = null
  const session = await dshRpc('synapse:create-session', { workspaceId: state.selectedDshWorkspaceId || state.workspace?.id })
  state.draft = { kind: 'new', sessionId: session.id, position: point, text: '', sending: false }
  state.activeId = session.id
  render(); window.setTimeout(focusDraftInput, 0)
}
function canvasIcon(name) {
  // Match the Lucide icons used by the main conversation map.
  const mapIcons = {
    'zoom-out': '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35M8 11h6"/>',
    'zoom-in': '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35M11 8v6M8 11h6"/>',
    fit: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01"/>',
  }
  if (mapIcons[name]) return `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${mapIcons[name]}</svg>`
  const paths = { plus: '<path d="M8 3v10M3 8h10"/>', minus: '<path d="M3 8h10"/>', fit: '<path d="M6 2H2v4M10 2h4v4M2 10v4h4M14 10v4h-4"/>', link: '<path d="m6 10 4-4M5 11H4a3 3 0 0 1 0-6h3M11 5h1a3 3 0 0 1 0 6H9"/>', eye: '<path d="M1 8s2.5-4 7-4 7 4 7 4-2.5 4-7 4-7-4-7-4Z"/><circle cx="8" cy="8" r="2"/>', message: '<path d="M2 2h12v10H7l-4 3v-3H2Z"/>', edit: '<path d="m3 10 7-7 3 3-7 7H3Z"/>', trash: '<path d="M2 4h12M6 4V2h4v2M4 4v10h8V4M7 7v4M9 7v4"/>', help: '<circle cx="8" cy="8" r="6"/><path d="M6 6a2 2 0 1 1 3 2c-1 .5-1 1-1 2M8 12h.01"/>', layout: '<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>' }
  return `<svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.message}</svg>`
}
function mindPilotAvatar() {
  // Sparkles icon used by the native conversation interface (Lucide).
  return '<span class="map-assistant-avatar"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4M22 5h-4M4 17v2M5 18H3"/></svg></span>'
}
function mapThinkingIndicator() {
  return `<div class="map-thinking" role="status">${mindPilotAvatar()}<span>正在思考中</span><span class="map-thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>`
}
function canvasOverlays() {
  const cards = conversationCards(state.workspace?.threads || [])
  const hidden = cards.filter(card => state.hiddenCardIds.has(card.id)).length
  const visibleIds = new Set((state.canvasCards || []).map(card => card.id))
  const linkCount = state.links.filter(edge => visibleIds.has(edge.source) && visibleIds.has(edge.target)).length + (state.canvasCards || []).filter(card => visibleIds.has(card.parentId)).length
  const button = (action, text, icon, extra = '') => `<button type="button" data-action="${action}" ${extra}>${canvasIcon(icon)}${text}</button>`
  const menu = state.menu
  const card = menu?.cardId ? cards.find(item => item.id === menu.cardId) : null
  const cardActions = card ? `${button('menu-open', '打开会话', 'message')}${button('menu-continue', '继续追问', 'plus', card.canContinue ? '' : 'disabled')}${button('menu-branch', '基于此回答创建分支', 'link', Number.isInteger(card.answer?.sourceSeq) ? '' : 'disabled')}${button('menu-region', '增加区域', 'layout')}${button('menu-link', '建立关联', 'link')}${button('menu-rename', '重命名会话', 'edit')}${button('menu-hide', '从地图隐藏', 'minus')}${button('menu-delete', '从地图移除', 'trash', 'class="danger"')}` : ''
  const blankActions = `${button('menu-new', '新建会话', 'message')}${button('menu-region', '增加区域', 'layout')}${button('fit-canvas', '适配画布', 'fit')}${button('layout', '整理卡片', 'layout')}${button('restore-hidden', '恢复隐藏内容' + (hidden ? `（${hidden}）` : ''), 'eye', hidden ? '' : 'disabled')}`
  const regionActions = `${button('region-color', '修改区域颜色', 'edit', `data-region="${escapeHtml(menu?.regionId)}"`)}${button('region-remove', '移除区域，保留会话', 'minus', `data-region="${escapeHtml(menu?.regionId)}"`)}`
  const context = menu ? `<div class="canvas-menu" style="left:${menu.x}px;top:${menu.y}px">${menu.linkId ? button('remove-link', '删除关联', 'trash', 'class="danger"') : card ? cardActions : menu.regionId ? regionActions : blankActions}</div>` : ''
  const rename = state.editCardId ? cards.find(item => item.id === state.editCardId) : null
  const owner = rename ? state.workspace?.threads.find(thread => thread.id === rename.dshThreadId) : null
  const dialog = rename ? `<div class="canvas-dialog-backdrop"><form class="canvas-dialog" data-rename-thread="${rename.dshThreadId}"><h2>重命名会话</h2><input name="title" maxlength="160" value="${escapeHtml(owner?.title || '')}" required autofocus><div>${button('cancel-dialog', '取消', 'minus')}<button type="submit" class="primary">保存</button></div></form></div>` : state.deleteCardId ? `<div class="canvas-dialog-backdrop"><div class="canvas-dialog"><h2>从地图移除此卡片？</h2><p>会话记录会保留，可通过恢复隐藏内容重新显示。</p><div>${button('cancel-dialog', '取消', 'minus')}${button('confirm-hide', '移除卡片', 'trash', 'class="primary"')}</div></div></div>` : ''
  return `<div class="canvas-controls">${button('zoom-out', '', 'zoom-out', 'aria-label="缩小" title="缩小"')}<span>${Math.round(state.zoom * 100)}%</span>${button('zoom-in', '', 'zoom-in', 'aria-label="放大" title="放大"')}${button('fit-canvas', '', 'fit', 'aria-label="适配画布" title="适配画布"')}</div><div class="canvas-footnote"><span>${visibleIds.size} 张卡片 · ${linkCount} 条关联</span><span>已自动保存</span>${button('toggle-help', '', 'help', `aria-label="使用提示" title="画布操作提示" aria-expanded="${state.helpOpen}" aria-controls="canvas-help"`)}</div>${state.linkSource ? '<div class="canvas-link-hint">点击目标卡片建立关联，按 Esc 取消</div>' : ''}${state.helpOpen ? `<section class="canvas-help" id="canvas-help" aria-label="画布操作提示"><header><strong>画布操作</strong><button type="button" class="canvas-help-close" data-action="toggle-help" aria-label="关闭操作提示">×</button></header><dl><div><dt>移动与缩放</dt><dd>拖动卡片标题移动卡片；拖动画布空白处平移，滚轮缩放。</dd></div><div><dt>查看与编辑</dt><dd>单击选中卡片并修改颜色，双击查看详情。</dd></div><div><dt>新建与关联</dt><dd>右键画布新建会话；右键卡片建立关联、继续追问或隐藏。</dd></div><div><dt>移除与恢复</dt><dd><kbd>Backspace</kbd> 移除选中卡片，会话记录保留；右键画布恢复隐藏内容。</dd></div></dl></section>` : ''}${context}${dialog}${regionColorDialog()}`
}

// Render hints outside the canvas so card clipping and camera zoom cannot crop them.
let hintTimer = 0, hintTarget = null, hintBubble = null
function hideMapHint() {
  window.clearTimeout(hintTimer)
  hintTarget?.removeAttribute('aria-describedby')
  hintTarget = null
  hintBubble?.remove()
  hintBubble = null
}
function showMapHint(target, delay = 200) {
  if (hintTarget === target) return
  hideMapHint()
  if (target.matches(':disabled') || target.getAttribute('aria-expanded') === 'true') return
  hintTarget = target
  hintTimer = window.setTimeout(() => {
    if (!target.isConnected) { hideMapHint(); return }
    hintBubble = document.createElement('div')
    hintBubble.id = 'map-button-hint'
    hintBubble.className = 'map-button-hint'
    hintBubble.setAttribute('role', 'tooltip')
    hintBubble.textContent = target.dataset.tooltip
    document.body.append(hintBubble)
    target.setAttribute('aria-describedby', hintBubble.id)
    const rect = target.getBoundingClientRect(), box = hintBubble.getBoundingClientRect()
    const left = Math.max(8, Math.min(rect.left + rect.width / 2 - box.width / 2, window.innerWidth - box.width - 8))
    const above = rect.top >= box.height + 16
    const top = above ? rect.top - box.height - 10 : Math.min(rect.bottom + 10, window.innerHeight - box.height - 8)
    hintBubble.style.left = `${left}px`
    hintBubble.style.top = `${Math.max(8, top)}px`
    hintBubble.style.setProperty('--hint-arrow-x', `${Math.max(12, Math.min(rect.left + rect.width / 2 - left, box.width - 12))}px`)
    hintBubble.dataset.side = above ? 'above' : 'below'
  }, delay)
}
function positionCanvasHelp() {
  const help = app.querySelector('.canvas-help'), button = app.querySelector('.canvas-footnote [data-action="toggle-help"]'), viewport = app.querySelector('.canvas-viewport')
  if (!help || !button || !viewport) return
  const rect = viewport.getBoundingClientRect(), anchor = button.getBoundingClientRect()
  help.style.maxHeight = `${Math.max(80, anchor.top - rect.top - 24)}px`
  const left = Math.max(8, Math.min(anchor.left + anchor.width / 2 - rect.left - help.offsetWidth / 2, rect.width - help.offsetWidth - 8))
  help.style.left = `${left}px`
  help.style.bottom = `${rect.bottom - anchor.top + 12}px`
  help.style.setProperty('--help-arrow-x', `${anchor.left + anchor.width / 2 - rect.left - left}px`)
}
function prepareMapHints() {
  hideMapHint()
  for (const target of app.querySelectorAll('button[title]')) {
    target.dataset.tooltip = target.getAttribute('title')
    target.removeAttribute('title')
  }
  positionCanvasHelp()
}
function installMapHintEvents() {
  app.addEventListener('pointerover', event => {
    const target = event.target.closest('[data-tooltip]')
    if (target && !target.contains(event.relatedTarget)) showMapHint(target)
  })
  app.addEventListener('pointerout', event => {
    if (hintTarget && !hintTarget.contains(event.relatedTarget)) hideMapHint()
  })
  app.addEventListener('focusin', event => {
    const target = event.target.closest('[data-tooltip]')
    if (target) showMapHint(target, 0)
  })
  app.addEventListener('focusout', hideMapHint)
  document.addEventListener('pointerdown', hideMapHint)
  document.addEventListener('keydown', hideMapHint)
  document.addEventListener('scroll', hideMapHint, true)
  window.addEventListener('resize', () => { hideMapHint(); positionCanvasHelp() })
}

function persistQuickPhrases() {
  try { localStorage.setItem(QUICK_PHRASES_KEY, JSON.stringify(state.quickPhrases)) } catch { /* Private browsing may disable local storage. */ }
}

function rememberCardPosition(cardId, position, aliases = []) {
  state.cardPositions.set(cardId, { x: Math.round(position.x), y: Math.round(position.y) })
  for (const alias of aliases) state.cardPositions.set(alias, { x: Math.round(position.x), y: Math.round(position.y) })
  persistCardPositions()
}

function resetCardPositions() {
  state.cardPositions.clear()
  persistCardPositions()
  try {
    localStorage.removeItem(LEGACY_CARD_POSITIONS_KEY)
    localStorage.removeItem('dsh-synapse:card-positions:v2')
  } catch { /* Private browsing may disable local storage. */ }
}

function resetCanvasCamera() {
  state.zoom = INITIAL_CANVAS_ZOOM
  state.canvasAutoOverview = true
  state.canvasOverviewSignature = null
  state.canvasNeedsFit = true
  state.canvasViewInitialized = false
  state.canvasCamera = { x: 0, y: 0 }
}

async function api(path, options = {}) {
  return dshRpc('synapse:api', { path, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : undefined })
}
function post(type, payload = {}) {
  if (window.parent !== window) window.parent.postMessage({ source: 'dsh-synapse', type, ...payload }, window.location.origin)
}

function dshRpc(type, payload = {}) {
  if (window.parent === window) return Promise.reject(new Error('请从 MindPilot 页面打开 Synapse 后再操作会话'))
  const requestId = crypto.randomUUID()
  post(type, { requestId, ...payload })
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      state.pendingRpc.delete(requestId)
      reject(new Error('MindPilot 未在规定时间内响应'))
    }, 900_000)
    state.pendingRpc.set(requestId, { resolve, reject, timer })
  })
}

function settleRpc(requestId, value, error) {
  const pending = state.pendingRpc.get(requestId)
  if (pending === undefined) return
  state.pendingRpc.delete(requestId)
  window.clearTimeout(pending.timer)
  if (error === undefined) pending.resolve(value)
  else pending.reject(error instanceof Error ? error : new Error(String(error)))
}

function setError(error = '') { state.error = error instanceof Error ? error.message : error; render() }

function messagesFromEvents(events) {
  if (!Array.isArray(events)) return []
  return events.flatMap(event => {
    const content = event?.data?.message?.content ?? event?.data?.content
    const text = Array.isArray(content) ? content.filter(block => block?.type === 'text').map(block => block.text).filter(Boolean).join('\n') : ''
    if (event?.type === 'user/message' && text && !text.startsWith('Current runtime context. This snapshot supersedes earlier runtime-context snapshots.')) return [{ kind: 'user', text, at: event.time, sourceSeq: event.seq }]
    if (event?.type === 'assistant/message' && text) return [{ kind: 'assistant', text, at: event.time, sourceSeq: event.seq }]
    return []
  })
}

async function loadThreadHistory() {}

function canReplaceView() {
  return state.draft === null && state.editCardId === null && state.deleteCardId === null && state.regionDialog === null && !state.dragging && !state.canvasGesture && Date.now() >= state.canvasRefreshAfter && !document.activeElement?.matches('textarea,input')
}

function deferCanvasRefresh(delay = 700) {
  state.canvasRefreshAfter = Math.max(state.canvasRefreshAfter, Date.now() + delay)
}

function currentDshWorkspace() {
  const id = state.currentDsh?.id
  return typeof id === 'string' ? state.dshWorkspaces.find(workspace => workspace.sessionIds.includes(id)) : undefined
}

function selectedDshWorkspace() {
  return state.dshWorkspaces.find(workspace => workspace.id === state.selectedDshWorkspaceId)
}

function currentDshThread(threads = state.workspace?.threads ?? []) {
  const id = state.currentDsh?.id
  return typeof id === 'string' ? threads.find(thread => thread.dshSessionId === id) : undefined
}

async function threadsForDshWorkspace(workspace) {
  if (workspace.sessionIds.length === 0) return []
  const requested = new Set(workspace.sessionIds)
  const projection = await api(`/synapse/api/workspaces/${workspace.id}`)
  return projection.workspace.threads.filter(thread => requested.has(thread.dshSessionId))
}

async function openDshWorkspace(id, { renderAfter = true, preserveCanvasCamera = false } = {}) {
  if (state.workspace && state.workspace.id !== `dsh:${id}`) { state.menu = null; state.linkSource = null; state.selectedLinkId = null; state.editCardId = null; state.deleteCardId = null; state.regionDialog = null; state.selectedRegionId = null; state.draft = null; state.inspectorCardId = null; state.selectedCardId = null }
  const workspace = state.dshWorkspaces.find(item => item.id === id)
  if (workspace === undefined) return false
  const load = ++state.workspaceLoad
  state.selectedDshWorkspaceId = id
  const nextWorkspaceId = `dsh:${workspace.id}`
  if (state.workspace?.id !== nextWorkspaceId) {
    // Clear the previous conversation immediately, before loading the new map.
    if (!preserveCanvasCamera) resetCanvasCamera()
    state.workspace = { id: nextWorkspaceId, title: workspace.title, cwd: workspace.path, threads: [] }
    state.activeId = null
    if (renderAfter && canReplaceView()) render()
  }
  const threads = await threadsForDshWorkspace(workspace)
  if (load !== state.workspaceLoad) return true
  state.workspace = { id: nextWorkspaceId, title: workspace.title, cwd: workspace.path, threads }
  const currentThread = currentDshThread(state.workspace.threads)
  state.activeId = currentThread?.id ?? (state.workspace.threads.some(thread => thread.id === state.activeId) ? state.activeId : state.workspace.threads[0]?.id ?? null)
  if (currentThread !== undefined) revealConversationThread(conversationCards(state.workspace.threads), currentThread.id)
  if (renderAfter && canReplaceView()) render()
  await Promise.all(state.workspace.threads.map(thread => loadThreadHistory(thread, false)))
  if (renderAfter && load === state.workspaceLoad && canReplaceView()) render()
  return true
}

async function openCurrentWorkspace({ preserveCanvasCamera = false } = {}) {
  const workspace = currentDshWorkspace()
  if (workspace === undefined || workspace.id === state.selectedDshWorkspaceId) return false
  return openDshWorkspace(workspace.id, { preserveCanvasCamera })
}

async function refreshSummaries({ renderAfter = true } = {}) {
  const before = JSON.stringify(state.summaries)
  const body = await api('/synapse/api/workspaces')
  state.summaries = body.workspaces
  const changed = before !== JSON.stringify(state.summaries)
  const current = state.workspace?.id
  if (state.selectedDshWorkspaceId === null && current !== null && !state.summaries.some(item => item.id === current)) state.workspace = null
  const selected = selectedDshWorkspace()
  if (selected !== undefined && (changed || state.workspace === null)) await openDshWorkspace(selected.id, { renderAfter })
  else if (state.workspace === null) { await openCurrentWorkspace(); if (renderAfter && canReplaceView()) render() }
  else if (renderAfter && changed && canReplaceView()) render()
  return changed
}

async function openWorkspace(id, { renderAfter = true } = {}) {
  if (state.workspace && state.workspace.id !== id) { state.menu = null; state.linkSource = null; state.selectedLinkId = null; state.editCardId = null; state.deleteCardId = null; state.regionDialog = null; state.selectedRegionId = null; state.draft = null; state.inspectorCardId = null; state.selectedCardId = null }
  const load = ++state.workspaceLoad
  const body = await api(`/synapse/api/workspaces/${id}`)
  if (load !== state.workspaceLoad) return
  if (state.workspace?.id !== body.workspace.id) resetCanvasCamera()
  state.workspace = body.workspace
  state.activeId = state.workspace.threads.some(thread => thread.id === state.activeId) ? state.activeId : state.workspace.threads[0]?.id ?? null
  if (renderAfter && canReplaceView()) render()
  await Promise.all(state.workspace.threads.map(thread => loadThreadHistory(thread, false)))
  if (renderAfter && load === state.workspaceLoad && canReplaceView()) render()
}

async function refreshProjection() {
  const summariesChanged = await refreshSummaries({ renderAfter: false })
  if (!summariesChanged || state.workspace === null || !canReplaceView()) return summariesChanged
  if (state.selectedDshWorkspaceId !== null) await openDshWorkspace(state.selectedDshWorkspaceId)
  else await openWorkspace(state.workspace.id)
  return true
}

function focusDraftInput() {
  const input = document.querySelector('[data-draft] textarea')
  if (!(input instanceof HTMLTextAreaElement)) return
  // Native focus scrolling would move the viewport's controls with its content.
  // Reveal the editor by moving the camera instead, leaving the overlay fixed.
  const viewport = document.querySelector('.canvas-viewport')
  const card = input.closest('.draft-card')
  if (viewport && card) {
    const bounds = viewport.getBoundingClientRect(), rect = card.getBoundingClientRect()
    const target = rect.height > bounds.height - 90 ? input.getBoundingClientRect() : rect
    const shiftX = target.right > bounds.right - 20 ? bounds.right - 20 - target.right
      : target.left < bounds.left + 20 ? bounds.left + 20 - target.left : 0
    const shiftY = target.bottom > bounds.bottom - 76 ? bounds.bottom - 76 - target.bottom
      : target.top < bounds.top + 20 ? bounds.top + 20 - target.top : 0
    if (shiftX || shiftY) {
      state.canvasCamera.x += shiftX
      state.canvasCamera.y += shiftY
      applyCanvasTransform()
      syncCanvasViewport()
    }
  }
  input.focus({ preventScroll: true })
  input.setSelectionRange(input.value.length, input.value.length)
}

function openContinue(parent, anchorId = undefined, text = '') {
  if (parent.dshSessionId === null) return setError('该节点没有关联的 MindPilot 会话')
  state.activeId = parent.id
  state.quickPhraseEditorOpen = false
  stopCanvasAutoOverview()
  state.draft = { kind: 'continue', parentId: parent.id, anchorId, text, sending: false }
  if (text) {
    state.draft.text = text.length < 4000 ? text + ' ' : text
    state.draft.selectedRanges = [{ start: 0, end: text.length }]
  }
  render()
  window.setTimeout(focusDraftInput, 0)
}

function openBranch(parent, atSeq = undefined, anchorId = undefined) {
  if (parent.dshSessionId === null) return setError('该节点没有关联的 MindPilot 会话')
  state.activeId = parent.id
  state.quickPhraseEditorOpen = false
  stopCanvasAutoOverview()
  state.draft = { kind: 'branch', parentId: parent.id, atSeq, anchorId, text: '', sending: false }
  render()
  window.setTimeout(focusDraftInput, 0)
}

async function sendMessage(thread, text) {
  if (thread.dshSessionId === null) throw new Error('该节点没有关联的 MindPilot 会话')
  if (state.pendingReplies.has(thread.dshSessionId)) throw new Error('该会话正在回复，请稍后再发送')
  state.pendingReplies.set(thread.dshSessionId, { text, at: Date.now() })
  state.error = ''
  render()
  try {
    await dshRpc('synapse:send-message', { sessionId: thread.dshSessionId, text })
    void loadThreadHistory(thread)
  } catch (error) {
    state.pendingReplies.delete(thread.dshSessionId)
    render()
    throw error
  }
}

async function submitDraft() {
  const draft = state.draft
  const text = draft?.text.trim()
  if (draft === null || draft.sending || !text) return
  const sourceCards = state.workspace === null ? [] : conversationCards(state.workspace.threads)
  const draftPosition = draftPlacement(sourceCards)?.position
  draft.sending = true
  state.error = ''
  render()
  try {
    if (draft.kind === 'new') {
      await dshRpc('synapse:send-message', { sessionId: draft.sessionId, text })
      rememberCardPosition(`${draft.sessionId}:turn:1`, draft.position, [`${draft.sessionId}:turn-index:0`])
      state.draft = null
      await refreshProjection()
      render()
      return
    }
    const parent = state.workspace?.threads.find(thread => thread.id === draft.parentId)
    if (parent === undefined) throw new Error('来源会话不存在')
    if (draft.kind === 'continue') {
      const turns = sourceCards.filter(card => card.dshThreadId === parent.id)
      const nextIndex = turns[0]?.sourceSeq === undefined ? 0 : turns.length
      if (draftPosition) rememberCardPosition(`${parent.id}:turn-index:${nextIndex}`, draftPosition)
      state.draft = null
      await sendMessage(parent, text)
      return
    }
    const session = await dshRpc('synapse:fork-session', { sessionId: parent.dshSessionId, atSeq: draft.atSeq })
    if (draft.anchorId !== undefined) rememberBranchAnchor(session.id, draft.anchorId)
    const result = await api(`/synapse/api/threads/${parent.id}/branch`, { method: 'POST', body: JSON.stringify({ title: text.slice(0, 42), dshSessionId: session.id, dshSessionTitle: session.title, position: draftPosition }) })
    if (draftPosition) rememberCardPosition(`${result.thread.id}:turn:empty`, draftPosition, [`${result.thread.id}:turn-index:0`])
    if (state.workspace !== null && !state.workspace.threads.some(thread => thread.id === result.thread.id || thread.dshSessionId === result.thread.dshSessionId)) state.workspace.threads.push(result.thread)
    state.activeId = result.thread.id
    state.draft = null
    state.pendingReplies.set(result.thread.dshSessionId, { text, at: Date.now() })
    render()
    await dshRpc('synapse:send-message', { sessionId: result.thread.dshSessionId, text })
    void loadThreadHistory(result.thread)
    await refreshProjection()
  } catch (error) {
    if (draft.kind === 'branch') {
      state.pendingReplies.delete(state.workspace?.threads.find(thread => thread.id === state.activeId)?.dshSessionId)
      if (state.draft !== null) state.draft = { ...draft, sending: false }
    } else {
      state.draft = { ...draft, sending: false }
    }
    setError(error)
  }
}

function threadsById() { return new Map((state.workspace?.threads ?? []).map(thread => [thread.id, thread])) }
function persistedMessagesFor(thread) { return state.historyBySession.get(thread.dshSessionId) ?? thread.messages ?? [] }

function pendingUserIndex(messages, pending) {
  return messages.findLastIndex(message => message.kind === 'user' && message.text === pending.text && new Date(message.at).getTime() >= pending.at - 2_000)
}

function settlePendingReply(thread, messages) {
  const pending = state.pendingReplies.get(thread.dshSessionId)
  if (pending === undefined) return false
  const userIndex = pendingUserIndex(messages, pending)
  if (userIndex === -1 || !messages.slice(userIndex + 1).some(message => message.kind === 'assistant')) return false
  state.pendingReplies.delete(thread.dshSessionId)
  return true
}

function messagesFor(thread) {
  // A runtime-context snapshot is internal MindPilot state, never a user turn.
  // Filter here as well as during persistence so existing saved workspaces
  // immediately render one question and its answer as one card.
  const messages = persistedMessagesFor(thread).filter(message => !(message.kind === 'user' && typeof message.text === 'string' && message.text.trimStart().startsWith('Current runtime context. This snapshot supersedes earlier runtime-context snapshots.')))
  const pending = state.pendingReplies.get(thread.dshSessionId)
  if (pending === undefined) return messages
  if (settlePendingReply(thread, messages)) {
    state.liveReplies.delete(thread.dshSessionId)
    return messages
  }
  const liveReply = state.liveReplies.get(thread.dshSessionId)
  const liveAssistant = liveReply?.running ? { kind: 'assistant', text: liveReply.text, pending: true, at: new Date().toISOString() } : { kind: 'assistant', text: '', pending: true, at: new Date().toISOString() }
  const userIndex = pendingUserIndex(messages, pending)
  if (userIndex !== -1) return [...messages, liveAssistant]
  return [...messages, { kind: 'user', text: pending.text, pending: true, at: new Date(pending.at).toISOString() }, liveAssistant]
}

function latestMessage(thread, kind) { return [...messagesFor(thread)].reverse().find(message => message.kind === kind) }
function questionFor(thread) { return latestMessage(thread, 'user')?.text ?? thread.dshSessionTitle ?? '等待用户提问' }
function answerFor(thread) { return latestMessage(thread, 'assistant') ?? null }

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/~~([^~]+)~~/g, '<s>$1</s>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
}

const tableCells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim())

const isTableDelimiter = line => {
  const cells = tableCells(line)
  return cells.length > 0 && cells.every(cell => /^:?-+:?$/.test(cell))
}

function markdownBlock(text) {
  const lines = text.split('\n')
  const output = []
  for (let index = 0; index < lines.length;) {
    const line = lines[index]
    if (line.trim() === '') { index++; continue }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line)
    if (heading !== null) {
      const level = heading[1].length
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`)
      index++
      continue
    }
    const unordered = /^[-*+]\s+(.+)$/.exec(line)
    const ordered = /^\d+[.)]\s+(.+)$/.exec(line)
    if (unordered !== null || ordered !== null) {
      const matcher = unordered === null ? /^\d+[.)]\s+(.+)$/ : /^[-*+]\s+(.+)$/
      const items = []
      while (index < lines.length) {
        const item = matcher.exec(lines[index])
        if (item === null) break
        items.push(`<li>${inlineMarkdown(item[1])}</li>`)
        index++
      }
      output.push(`<${unordered === null ? 'ol' : 'ul'}>${items.join('')}</${unordered === null ? 'ol' : 'ul'}>`)
      continue
    }
    // GFM table: a leading-pipe header row followed by a |-delimiter row,
    // then any number of leading-pipe body rows.
    if (/^\s*\|/.test(line) && index + 1 < lines.length && isTableDelimiter(lines[index + 1])) {
      const header = line
      const body = []
      index += 2
      while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) {
        body.push(lines[index])
        index++
      }
      output.push(`<table><thead><tr>${tableCells(header).map(cell => `<th>${inlineMarkdown(cell)}</th>`).join('')}</tr></thead><tbody>${body.map(row => `<tr>${tableCells(row).map(cell => `<td>${inlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table>`)
      continue
    }
    const paragraph = []
    while (index < lines.length && lines[index].trim() !== '' && !/^(#{1,3})\s+/.test(lines[index]) && !/^[-*+]\s+/.test(lines[index]) && !/^\d+[.)]\s+/.test(lines[index])) paragraph.push(lines[index++])
    // A marker-only line such as PowerShell's "+ " diagnostic is neither a
    // list item nor paragraph content under the rules above. Consume it so
    // the parser always makes progress.
    if (paragraph.length === 0) paragraph.push(lines[index++])
    output.push(`<p>${paragraph.map(inlineMarkdown).join('<br>')}</p>`)
  }
  return output.join('')
}

// Markdown parsing is pure CPU and repeats for every card on every canvas
// rebuild; cache the rendered HTML by input text so stable answers are never
// re-parsed. Bounded: streaming partial texts churn keys, so evict oldest.
const markdownCache = new Map()
const MARKDOWN_CACHE_LIMIT = 5000
function renderMarkdown(text) {
  const key = String(text)
  const cached = markdownCache.get(key)
  if (cached !== undefined) return cached
  const parts = key.split(/```/)
  const rendered = parts.map((part, index) => index % 2 === 1
    ? `<pre><code>${escapeHtml(part.replace(/^\w*\n/, ''))}</code></pre>`
    : markdownBlock(part)).join('')
  if (markdownCache.size >= MARKDOWN_CACHE_LIMIT) markdownCache.delete(markdownCache.keys().next().value)
  markdownCache.set(key, rendered)
  return rendered
}

function overlapsCard(position, other) {
  return position.x < other.x + CARD_WIDTH && position.x + CARD_WIDTH > other.x
    && position.y < other.y + CARD_HEIGHT && position.y + CARD_HEIGHT > other.y
}

function firstAvailableCardPosition(position, occupied) {
  const candidate = { x: Math.round(position.x), y: Math.max(82, Math.round(position.y)) }
  while (true) {
    const collisions = occupied.filter(other => overlapsCard(candidate, other))
    if (collisions.length === 0) return candidate
    candidate.y = Math.max(...collisions.map(other => other.y + CARD_HEIGHT + CARD_GAP_Y))
  }
}

function nearbyCardPosition(anchor, occupied, kind = 'branch') {
  const stepX = 365, stepY = CARD_HEIGHT + CARD_GAP_Y
  const available = position => !occupied.some(other => overlapsCard(position, other))
  const at = (dx, dy) => ({ x: Math.round(anchor.x + dx * stepX), y: Math.round(anchor.y + dy * stepY) })
  const preferred = kind === 'continue' ? at(1, 0) : at(0, 1)
  if (available(preferred)) return preferred
  // Search around the source, rather than jumping below every colliding row.
  // Negative coordinates are valid on this infinite, camera-driven canvas.
  let best = null, bestDistance = Infinity
  for (let radius = 1; ; radius++) {
    for (let dy = radius; dy >= -radius; dy--) {
      for (let dx = -radius; dx <= radius; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dy)) !== radius) continue
        const distance = (dx * stepX) ** 2 + (dy * stepY) ** 2
        if (distance >= bestDistance) continue
        const position = at(dx, dy)
        if (available(position)) { best = position; bestDistance = distance }
      }
    }
    if (((radius + 1) * Math.min(stepX, stepY)) ** 2 > bestDistance) return best
  }
}

function connectorPath(fromPosition, toPosition) {
  return manualLinkGeometry(fromPosition, toPosition).path
}

function connectorPathFromElements(fromCard, toCard) {
  const from = { x: Number.parseFloat(fromCard.style.left), y: Number.parseFloat(fromCard.style.top) }
  const to = { x: Number.parseFloat(toCard.style.left), y: Number.parseFloat(toCard.style.top) }
  if (![from.x, from.y, to.x, to.y].every(Number.isFinite)) return null
  return connectorPath(from, to)
}

function selectorValue(value) {
  return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

// Connector paths are rebuilt together with the canvas DOM; cache the mapping
// from card id to its incident paths so dragging never scans the whole SVG.
let connectorPathsByCard = new Map()
function cacheCardConnectors() {
  connectorPathsByCard = new Map()
  const viewport = document.querySelector('.canvas-viewport')
  if (!(viewport instanceof HTMLElement)) return
  for (const path of viewport.querySelectorAll('.connectors path[data-from]')) {
    const fromId = path.getAttribute('data-from')
    const toId = path.getAttribute('data-to')
    if (fromId === null || toId === null) continue
    for (const id of [fromId, toId]) {
      const paths = connectorPathsByCard.get(id)
      if (paths === undefined) connectorPathsByCard.set(id, new Set([path]))
      else paths.add(path)
    }
  }
}

function refreshCardConnectors(cardId) {
  const paths = connectorPathsByCard.get(cardId)
  if (paths === undefined || paths.size === 0) return
  const byId = state.canvasCardsById
  if (byId === undefined) return
  for (const path of paths) {
    const fromId = path.getAttribute('data-from')
    const toId = path.getAttribute('data-to')
    if (fromId === null || toId === null) continue
    const fromCard = byId.get(fromId)
    const toCard = byId.get(toId)
    if (fromCard === undefined || toCard === undefined) continue
    // Data-driven endpoints: the counterpart card may be unmounted (outside
    // the viewport) but its position is still authoritative.
    path.setAttribute('d', connectorPath(fromCard.position, toCard.position))
  }
}

function initialCanvasCamera(cards) {
  const draft = draftPlacement(cards)
  // Focus the active conversation's latest turn, not its first: after many
  // rounds the canvas should open where work is happening, at the newest card.
  const activeCards = state.activeId === null || state.activeId === undefined ? [] : cards.filter(card => card.dshThreadId === state.activeId)
  const active = activeCards.at(-1)
  const focus = draft ?? active ?? cards[0]
  const position = focus?.position
  if (position === undefined) return { x: 0, y: 0 }
  return { x: CAMERA_INSET_X - position.x * state.zoom, y: CAMERA_INSET_Y - position.y * state.zoom }
}

function placeConversationCards(cards) {
  const saved = new Map(cards.flatMap(card => {
    if (card.positionLocked !== true) return []
    const position = state.cardPositions.get(card.id) ?? state.cardPositions.get(card.positionKey)
    return position === undefined ? [] : [[card.id, { x: position.x, y: position.y }]]
  }))
  const occupied = []
  for (const card of cards) {
    const position = saved.get(card.id)
    if (position !== undefined) {
      card.position = position
      continue
    }
    card.position = firstAvailableCardPosition(card.naturalPosition ?? card.position, occupied)
    occupied.push(card.position)
  }
  return cards
}

function layoutConversationGraph(cards, threads) {
  const byId = new Map(cards.map(card => [card.id, card]))
  const byThread = new Map()
  for (const card of cards) {
    const turns = byThread.get(card.dshThreadId) ?? []
    turns.push(card)
    byThread.set(card.dshThreadId, turns)
  }
  // Reserve dragged positions before choosing automatic lanes.
  const saved = new Map(cards.flatMap(card => {
    const position = state.cardPositions.get(card.id) ?? state.cardPositions.get(card.positionKey)
    return position === undefined ? [] : [[card.id, position]]
  }))
  const occupied = [...saved.values()]
  const placed = new Set(), visiting = new Set()
  const placeThread = threadId => {
    if (placed.has(threadId) || visiting.has(threadId)) return
    const turns = byThread.get(threadId)
    if (!turns?.length) return
    visiting.add(threadId)
    const parent = byId.get(turns[0].parentId)
    if (parent && parent.dshThreadId !== threadId) placeThread(parent.dshThreadId)
    const anchor = parent && placed.has(parent.dshThreadId) ? parent.position : null
    const start = { x: anchor?.x ?? 86, y: anchor ? anchor.y + CARD_HEIGHT + CARD_GAP_Y : 82 }
    let positions
    if (anchor) {
      // Keep the first branch turn close even when later turns need other slots.
      const localOccupied = [...occupied]
      positions = []
      turns.forEach((card, index) => {
        const previous = index === 0 ? anchor : positions[index - 1]
        const position = saved.get(card.id) ?? nearbyCardPosition(previous, localOccupied, index === 0 ? 'branch' : 'continue')
        if (!saved.has(card.id)) localOccupied.push(position)
        positions.push(position)
      })
    } else {
      // Choose a free lane for the whole conversation, so its follow-ups stay aligned.
      while (true) {
        positions = turns.map((card, index) => saved.get(card.id)
          ?? { x: start.x + index * 365, y: start.y })
        const collisions = positions.flatMap((position, index) => saved.has(turns[index].id)
          ? [] : occupied.filter(other => overlapsCard(position, other)))
        if (!collisions.length) break
        start.y = Math.max(start.y + CARD_HEIGHT + CARD_GAP_Y,
          ...collisions.map(other => other.y + CARD_HEIGHT + CARD_GAP_Y))
        // Keep dragged cards fixed and resolve automatic collisions locally.
        if (turns.some(card => saved.has(card.id))) {
          positions = positions.map((position, index) => saved.has(turns[index].id)
            ? position : firstAvailableCardPosition(position, occupied))
          break
        }
      }
    }
    turns.forEach((card, index) => {
      card.naturalPosition = positions[index]
      card.position = positions[index]
      if (!saved.has(card.id)) occupied.push(card.position)
    })
    placed.add(threadId)
    visiting.delete(threadId)
    for (const thread of threads) if (thread.parentId === threadId) placeThread(thread.id)
  }
  for (const thread of threads) if (thread.parentId == null) placeThread(thread.id)
  for (const thread of threads) placeThread(thread.id)
  return cards
}

function conversationCards(threads) {
  const cards = []
  const cardsByThread = new Map()
  for (const thread of threads) {
    const messages = messagesFor(thread)
    const turns = []
    for (let messageIndex = 0; messageIndex < messages.length; messageIndex++) {
      const question = messages[messageIndex]
      if (question.kind !== 'user' || !String(question.text || '').trim()) continue
      const replies = []
      const errors = []
      let processCount = 0
      for (let replyIndex = messageIndex + 1; replyIndex < messages.length; replyIndex++) {
        const reply = messages[replyIndex]
        if (reply.kind === 'user') break
        if (reply.kind === 'assistant') replies.push(reply)
        if (reply.kind === 'error') errors.push(reply)
        if (Array.isArray(reply.process)) processCount += reply.process.length
        else if (reply.kind === 'tool') processCount += 1
      }
      const answer = replies.at(-1) ?? null
      const error = errors.at(-1) ?? null
      const turnIndex = turns.length
      const id = `${thread.id}:turn:${question.sourceSeq ?? messageIndex}`
      const previous = turns.at(-1)
      const positionKey = `${thread.id}:turn-index:${turnIndex}`
      const naturalPosition = previous === undefined ? { x: 86, y: 82 } : { x: previous.naturalPosition.x + 365, y: previous.naturalPosition.y }
      const savedPosition = state.cardPositions?.get(id) ?? state.cardPositions?.get(positionKey)
      const positionLocked = savedPosition !== undefined
      const position = positionLocked ? savedPosition : naturalPosition
      turns.push({
        id,
        positionKey,
        dshThreadId: thread.id,
        sourceParentId: thread.parentId,
        parentId: null,
        sourceSeq: question.sourceSeq,
        turnIndex,
        naturalPosition,
        position,
        positionLocked,
        question: question.text,
        answer,
        error,
        processCount,
      })
    }
    const liveReply = state.liveReplies.get(thread.dshSessionId)
    const latestTurn = turns.at(-1)
    if (liveReply?.running && latestTurn !== undefined && (latestTurn.answer === null || latestTurn.answer.pending === true)) latestTurn.answer = { kind: 'assistant', text: liveReply.text, pending: true, at: new Date().toISOString() }
    if (turns.length === 0) continue
    turns.at(-1).canContinue = true
    cardsByThread.set(thread.id, turns)
    cards.push(...turns)
  }
  for (const card of cards) {
    const siblings = cardsByThread.get(card.dshThreadId)
    if (card.turnIndex > 0) card.parentId = siblings[card.turnIndex - 1].id
    else {
      const parentCards = cardsByThread.get(card.sourceParentId)
      const sourceThread = threads.find(thread => thread.id === card.dshThreadId)
      const firstChildQuestion = siblings?.[0]
      const seedLength = sourceThread?.sourceSeedLength ?? firstChildQuestion?.sourceSeq
      // A fork inherits every parent event before MindPilot's durable seed boundary.
      // The latest parent question below that boundary is the exact Turn where
      // this child was born. Canvas coordinates never participate in lineage.
      const inheritedTurn = Number.isSafeInteger(seedLength)
        ? parentCards?.filter(candidate => Number.isInteger(candidate.sourceSeq) && candidate.sourceSeq < seedLength).at(-1)
        : undefined
      card.parentId = state.branchAnchors.get(card.dshThreadId) ?? inheritedTurn?.id ?? null
    }
  }
  return layoutConversationGraph(cards, threads)
}

function conversationGraphView(cards, collapsedCardIds = state.collapsedCardIds) {
  const cardIds = new Set(cards.map(card => card.id))
  const childrenByParent = new Map()
  for (const card of cards) {
    if (card.parentId === null || !cardIds.has(card.parentId)) continue
    const children = childrenByParent.get(card.parentId) ?? []
    children.push(card.id)
    childrenByParent.set(card.parentId, children)
  }

  const hiddenIds = new Set()
  for (const rootId of collapsedCardIds) {
    if (!cardIds.has(rootId)) continue
    const visited = new Set([rootId])
    const visit = parentId => {
      for (const childId of childrenByParent.get(parentId) ?? []) {
        if (visited.has(childId)) continue
        visited.add(childId)
        hiddenIds.add(childId)
        visit(childId)
      }
    }
    visit(rootId)
  }

  // Persisted collapse roots must remain visible even if malformed metadata
  // contains a cycle where two collapsed nodes otherwise hide each other.
  for (const rootId of collapsedCardIds) hiddenIds.delete(rootId)

  // Post-order accumulation: each card's descendant count is 1 + the sum of
  // its children's subtree sizes, so the whole graph is O(n) instead of a BFS
  // from every card (O(n²) on deep chains). Malformed parent cycles are
  // detected through the DFS path: every member of a cycle reaches every other
  // member plus the union of their off-cycle subtrees, so when the cycle entry
  // pops last, all members are settled to (cycleSize - 1) + off-cycle total,
  // which matches the per-card BFS' unique-descendant count.
  const descendantCounts = new Map()
  const inStack = new Set()
  for (const card of cards) {
    if (descendantCounts.has(card.id)) continue
    const stack = [{ id: card.id, children: childrenByParent.get(card.id) ?? [], index: 0 }]
    const path = [card.id]
    let cycleEntry = null
    let cycleMembers = null
    let cycleOffCycleTotal = 0
    inStack.add(card.id)
    while (stack.length > 0) {
      const top = stack[stack.length - 1]
      if (top.index < top.children.length) {
        const childId = top.children[top.index++]
        if (descendantCounts.has(childId)) continue
        if (inStack.has(childId)) {
          // Back edge: the nodes from childId up to top.id form a cycle.
          cycleEntry = childId
          cycleMembers = new Set(path.slice(path.indexOf(childId)))
          cycleOffCycleTotal = 0
          continue
        }
        inStack.add(childId)
        path.push(childId)
        stack.push({ id: childId, children: childrenByParent.get(childId) ?? [], index: 0 })
      } else {
        stack.pop()
        path.pop()
        inStack.delete(top.id)
        let count = 0
        for (const childId of top.children) {
          if (cycleMembers !== null && cycleMembers.has(childId)) continue // ring edge; base count added below
          count += 1 + (descendantCounts.get(childId) ?? 0)
        }
        if (cycleMembers !== null && cycleMembers.has(top.id)) cycleOffCycleTotal += count
        if (cycleMembers !== null && top.id === cycleEntry) {
          // All cycle members have popped (the entry pops last in post-order);
          // settle them so ancestors popping next read the final counts.
          const base = cycleMembers.size - 1
          for (const id of cycleMembers) descendantCounts.set(id, base + cycleOffCycleTotal)
          cycleEntry = null
          cycleMembers = null
        } else {
          descendantCounts.set(top.id, count)
        }
      }
    }
  }

  return {
    cards: cards.filter(card => !hiddenIds.has(card.id)),
    childCounts: new Map(cards.map(card => [card.id, childrenByParent.get(card.id)?.length ?? 0])),
    descendantCounts,
  }
}

function revealConversationThread(cards, threadId) {
  const byId = new Map(cards.map(card => [card.id, card]))
  let changed = false
  for (const target of cards.filter(card => card.dshThreadId === threadId)) {
    const visited = new Set([target.id])
    let parentId = target.parentId
    while (parentId !== null && !visited.has(parentId)) {
      visited.add(parentId)
      if (state.collapsedCardIds.delete(parentId)) changed = true
      parentId = byId.get(parentId)?.parentId ?? null
    }
  }
  if (changed) persistCollapsedCards()
}

function manualLinkGeometry(from, to) {
  const dx = to.x - from.x, dy = to.y - from.y
  if (Math.abs(dx) >= Math.abs(dy)) {
    const direction = dx >= 0 ? 1 : -1
    const sx = from.x + (direction > 0 ? CARD_WIDTH : 0), sy = from.y + CARD_HEIGHT / 2
    const tx = to.x + (direction > 0 ? 0 : CARD_WIDTH), ty = to.y + CARD_HEIGHT / 2
    const bend = Math.max(36, Math.min(110, Math.abs(tx - sx) / 2)) * direction
    return { path: `M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`, x: (sx + tx) / 2, y: (sy + ty) / 2 }
  }
  const direction = dy >= 0 ? 1 : -1
  const sx = from.x + CARD_WIDTH / 2, sy = from.y + (direction > 0 ? CARD_HEIGHT : 0)
  const tx = to.x + CARD_WIDTH / 2, ty = to.y + (direction > 0 ? 0 : CARD_HEIGHT)
  const bend = Math.max(24, Math.min(110, Math.abs(ty - sy) / 2)) * direction
  return { path: `M ${sx} ${sy} C ${sx} ${sy + bend}, ${tx} ${ty - bend}, ${tx} ${ty}`, x: (sx + tx) / 2, y: (sy + ty) / 2 }
}
function canvasConnectors(cards) {
  const index = new Map(cards.map(card => [card.id, card]))
  const links = cards.map(card => {
    const parent = card.parentId === null ? null : index.get(card.parentId)
    if (parent === undefined || parent === null) return ''
    const active = card.dshThreadId === state.activeId && parent.dshThreadId === state.activeId ? ' active-connector' : ''
    return `<path class="${active.trim()}" data-from="${escapeHtml(parent.id)}" data-to="${escapeHtml(card.id)}" marker-end="url(#map-arrow${active ? '-active' : ''})" d="${connectorPath(parent.position, card.position)}"></path>`
  })
  const placement = draftPlacement(cards)
  if (placement !== null) {
    links.push(`<path class="draft-connector" data-from="${escapeHtml(placement.parent.id)}" data-to="draft" marker-end="url(#map-arrow-active)" d="${connectorPath(placement.parent.position, placement.position)}"></path>`)
  }
  for (const edge of state.links) {
    const from = index.get(edge.source), to = index.get(edge.target)
    if (!from || !to) continue
    const geometry = manualLinkGeometry(from.position, to.position)
    links.push(`<g class="manual-connector ${state.selectedLinkId === edge.id ? 'selected' : ''}" data-link-id="${escapeHtml(edge.id)}"><path class="connector-hit" data-from="${escapeHtml(edge.source)}" data-to="${escapeHtml(edge.target)}" d="${geometry.path}"/><path data-from="${escapeHtml(edge.source)}" data-to="${escapeHtml(edge.target)}" marker-end="url(#map-arrow${state.selectedLinkId === edge.id ? '-selected' : ''})" d="${geometry.path}"/><g transform="translate(${geometry.x},${geometry.y})"><rect x="-22" y="-10" width="44" height="20" rx="10"/><text text-anchor="middle" y="4">关联</text></g></g>`)
  }
  const arrows = [['map-arrow', '#a99ac5'], ['map-arrow-active', '#a78bfa'], ['map-arrow-selected', '#7c3aed']]
  return `<defs>${arrows.map(([id, color]) => `<marker id="${id}" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto" fill="${color}"><path d="M2 1L11 6L2 11L4.5 6Z"/></marker>`).join('')}</defs>${links.join('')}`
}

const CARD_COLORS = ['#7c3aed', '#a855f7', '#2563eb', '#0ea5e9', '#0d9488', '#16a34a', '#84cc16', '#d97706', '#ea580c', '#db2777']
function cardColorPalette(cardId, color) {
  return `<div class="card-color-palette" aria-label="卡片背景颜色"><span>颜色</span>${CARD_COLORS.map(value => `<button type="button" data-action="set-card-color" data-card="${escapeHtml(cardId)}" data-color="${value}" aria-label="卡片颜色 ${value}" aria-pressed="${value === color}" class="${value === color ? 'active' : ''}" style="background:${value}"></button>`).join('')}</div>`
}
function selectCanvasCard(cardId) {
  const selected = state.canvasCardsById?.get(cardId)
  if (selected === undefined) return
  stopCanvasAutoOverview()
  selectCanvasRegion(null)
  state.activeId = selected.dshThreadId
  state.selectedCardId = cardId
  for (const element of app.querySelectorAll('.thread-card[data-thread]')) {
    const active = element.dataset.cardId === cardId
    element.classList.toggle('selected', active)
    element.querySelector('.card-color-palette')?.remove()
    if (active) element.insertAdjacentHTML('afterbegin', cardColorPalette(cardId, element.style.getPropertyValue('--thread-color')))
  }
}
function conversationCard(card, graph) {
  const selected = card.id === state.selectedCardId ? 'selected' : ''
  const thread = state.workspace?.threads.find(item => item.id === card.dshThreadId)
  const color = thread?.cardColors?.[card.id] || thread?.color || '#7c3aed'
  const title = card.turnIndex === 0 ? thread?.title || card.question : card.question
  const source = card.parentId === null ? 'MindPilot 会话' : card.turnIndex === 0 ? 'MindPilot 分支' : '追问'
  const continueButton = card.canContinue === true
    ? `<button class="graph-continue-button" data-action="open-continue" data-thread="${card.dshThreadId}" data-card="${escapeHtml(card.id)}" aria-label="添加追问" title="添加追问"><svg aria-hidden="true" viewBox="0 0 16 16"><path d="M8 3.5v9M3.5 8h9"/></svg></button>`
    : ''
  const childCount = graph.childCounts.get(card.id) ?? 0
  const collapsed = state.collapsedCardIds.has(card.id)
  const foldLabel = collapsed ? '展开后续对话' : '折叠后续对话'
  const foldButton = childCount === 0 || card.canContinue === true ? '' : `<button class="graph-fold-button${collapsed ? ' collapsed' : ''}" data-action="toggle-card-children" data-card="${escapeHtml(card.id)}" aria-expanded="${collapsed ? 'false' : 'true'}" aria-label="${foldLabel}" title="${foldLabel}"><svg aria-hidden="true" viewBox="0 0 16 16"><path d="M3.5 8h9"/>${collapsed ? '<path d="M8 3.5v9"/>' : ''}</svg></button>`
  const branchButton = childCount === 0 || card.canContinue === true || !Number.isInteger(card.answer?.sourceSeq) ? '' : `<button class="graph-branch-button" data-action="open-branch" data-thread="${card.dshThreadId}" data-card="${escapeHtml(card.id)}" data-seq="${card.answer.sourceSeq}" aria-label="在新对话中分支" title="在新对话中分支"><svg aria-hidden="true" viewBox="0 0 16 16"><path fill-rule="evenodd" clip-rule="evenodd" d="M13.0762 1.37207C14.0846 1.37228 14.9021 2.19077 14.9023 3.19922C14.9022 4.20772 14.0847 5.02518 13.0762 5.02539C12.2967 5.02539 11.6325 4.53691 11.3701 3.84961H4.35547C4.79397 4.26458 5.15861 4.7644 5.41699 5.33496L7.10645 9.06738C7.88526 10.7875 9.55104 11.9228 11.4189 12.0371C11.7085 11.4109 12.3411 10.9756 13.0762 10.9756C14.0843 10.9759 14.9023 11.7936 14.9023 12.8018C14.9023 13.81 14.0843 14.6277 13.0762 14.6279C12.2534 14.6279 11.5574 14.0832 11.3291 13.335C8.9868 13.1879 6.89981 11.7612 5.92285 9.60352L4.23242 5.87109C3.67503 4.64033 2.44878 3.84961 1.09766 3.84961V2.54883C1.10665 2.54883 1.11601 2.54975 1.125 2.5498L11.3701 2.54883C11.6326 1.86151 12.2969 1.37207 13.0762 1.37207ZM13.0762 12.2764C12.7858 12.2764 12.5508 12.5114 12.5508 12.8018C12.5508 13.0921 12.7858 13.3281 13.0762 13.3281C13.3664 13.3279 13.6025 13.092 13.6025 12.8018C13.6025 12.5115 13.3664 12.2766 13.0762 12.2764ZM13.0762 2.67285C12.7855 2.67285 12.55 2.90861 12.5498 3.19922C12.5499 3.48987 12.7855 3.72559 13.0762 3.72559C13.3667 3.72538 13.6024 3.48975 13.6025 3.19922C13.6023 2.90874 13.3666 2.67306 13.0762 2.67285Z" fill="currentColor"/></svg></button>`
  return `<article class="thread-card ${selected}" data-drag-card="${escapeHtml(card.id)}" data-card-id="${escapeHtml(card.id)}" data-position-key="${escapeHtml(card.positionKey)}" data-thread="${card.dshThreadId}" style="left:${card.position.x}px;top:${card.position.y}px;--thread-color:${color}">
    ${selected ? cardColorPalette(card.id, color) : ''}
    ${continueButton}${foldButton}${branchButton}
    <div class="thread-card-head"><span class="card-bot-icon"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="7" width="14" height="12" rx="3"/><path d="M12 3v4M2 11v5M22 11v5M9 11v3M15 11v3M9 16h6"/></svg></span><strong class="thread-title">${escapeHtml(title)}</strong></div>
    <div class="thread-meta"><span>${source}</span><span>第 ${card.turnIndex + 1} 轮</span>${card.error === null ? '' : '<span class="card-error-status">失败</span>'}${card.processCount > 0 ? `<span class="card-process-count">工具 ${card.processCount}</span>` : ''}</div>
    <div class="thread-answer">${card.answer === null ? (card.error === null ? mapThinkingIndicator() : '') : card.answer.pending && card.answer.text === '' ? mapThinkingIndicator() : `${renderMarkdown(card.answer.text)}${card.answer.pending ? mapThinkingIndicator() : ''}`}${card.error === null ? '' : `<p class="thread-answer-error" title="${escapeHtml(card.error.text)}">本轮失败：${escapeHtml(card.error.text)}</p>`}</div>
    <footer><button class="card-open-dialog" type="button" data-action="open-dsh" data-thread="${card.dshThreadId}" data-seq="${Number.isInteger(card.sourceSeq) ? card.sourceSeq : ''}" title="在智能问答中打开" aria-label="在智能问答中打开">${openDialogIcon()}</button></footer>
  </article>`
}

function draftActions(draft) {
  const disabled = draft.sending ? 'disabled' : ''
  return `<div class="draft-actions"><button type="button" data-action="cancel-draft" ${disabled} aria-label="取消" title="取消"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4.5 4.5 7 7m0-7-7 7"/></svg></button><button class="primary" type="submit" ${disabled} aria-label="发送" title="发送"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 12.5v-9M4.5 7 8 3.5 11.5 7"/></svg></button></div>`
}

function quickPhraseEditor(draft) {
  const disabled = draft.sending ? 'disabled' : ''
  const phrases = state.quickPhrases.map((phrase, index) => `<div class="draft-quick-phrase-editor-row"><input data-quick-phrase-index="${index}" maxlength="${MAX_QUICK_PHRASE_LENGTH}" value="${escapeHtml(phrase)}" aria-label="快捷词 ${index + 1}" ${disabled}><button type="button" data-action="remove-quick-phrase" data-quick-phrase-index="${index}" aria-label="删除 ${escapeHtml(phrase)}" title="删除" ${disabled}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4.5 4.5 7 7m0-7-7 7"/></svg></button></div>`).join('')
  return `<section class="draft-quick-editor" aria-label="编辑快捷词"><div class="draft-quick-editor-head"><span>编辑快捷词</span><button class="draft-quick-editor-close" type="button" data-action="close-quick-phrase-editor" ${disabled}>完成</button></div><div class="draft-quick-editor-list">${phrases}</div><div class="draft-quick-phrase-add"><input maxlength="${MAX_QUICK_PHRASE_LENGTH}" placeholder="添加快捷词" aria-label="添加快捷词" ${disabled}><button class="primary" type="button" data-action="add-quick-phrase" aria-label="添加快捷词" title="添加快捷词" ${disabled}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3.5v9M3.5 8h9"/></svg></button></div></section>`
}

function draftQuickPhrases(draft) {
  const disabled = draft.sending ? 'disabled' : ''
  if (state.quickPhraseEditorOpen) return quickPhraseEditor(draft)
  const phrases = state.quickPhrases.map(phrase => `<button class="draft-quick-phrase" type="button" data-action="insert-quick-phrase" data-quick-phrase="${escapeHtml(phrase)}" ${disabled}>${escapeHtml(phrase)}</button>`).join('')
  return `<div class="draft-quick-phrases" aria-label="常用补充词">${phrases}<button class="draft-quick-phrase-add-button" type="button" data-action="open-quick-phrase-editor" aria-label="管理快捷词" title="管理快捷词" ${disabled}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3.5v9M3.5 8h9"/></svg></button></div>`
}

function draftRangesAfterEdit(previous, next, ranges = [], edit = null) {
  let start = 0, oldEnd = previous.length, newEnd = next.length
  const inserted = edit ? next.length - previous.length + edit.end - edit.start : -1
  if (edit && inserted >= 0 && previous.slice(0, edit.start) === next.slice(0, edit.start)
    && previous.slice(edit.end) === next.slice(edit.start + inserted)) {
    start = edit.start; oldEnd = edit.end; newEnd = edit.start + inserted
  } else {
    if (previous === next) return ranges
    while (start < oldEnd && start < newEnd && previous[start] === next[start]) start++
    while (oldEnd > start && newEnd > start && previous[oldEnd - 1] === next[newEnd - 1]) { oldEnd--; newEnd-- }
  }
  const delta = newEnd - oldEnd
  return ranges.flatMap(range => {
    const pieces = []
    if (range.start < start) pieces.push({ start: range.start, end: Math.min(range.end, start) })
    if (range.end > oldEnd) pieces.push({ start: Math.max(range.start, oldEnd) + delta, end: range.end + delta })
    return pieces.filter(piece => piece.end > piece.start)
  })
}
function updateDraftText(text, edit = null) {
  state.draft.selectedRanges = draftRangesAfterEdit(state.draft.text, text, state.draft.selectedRanges, edit)
  state.draft.text = text
}
function draftHighlightedText(draft) {
  let cursor = 0, html = ''
  for (const range of draft.selectedRanges || []) {
    html += escapeHtml(draft.text.slice(cursor, range.start))
    html += `<span class="draft-selected-text">${escapeHtml(draft.text.slice(range.start, range.end))}</span>`
    cursor = range.end
  }
  return html + escapeHtml(draft.text.slice(cursor)) + '\u200b'
}
function renderDraftInput(draft, placeholder) {
  return `<div class="draft-input-shell"><div class="draft-input-mirror" aria-hidden="true"><div>${draftHighlightedText(draft)}</div></div><textarea maxlength="4000" aria-label="${placeholder}" placeholder="${placeholder}" ${draft.sending ? 'disabled' : ''}>${escapeHtml(draft.text)}</textarea></div>`
}
function syncDraftHighlight(input = app.querySelector('[data-draft] textarea')) {
  if (!input || !state.draft) return
  const mirror = input.parentElement.querySelector('.draft-input-mirror>div')
  if (!mirror) return
  mirror.innerHTML = draftHighlightedText(state.draft)
  mirror.style.width = `${input.clientWidth}px`
  mirror.style.transform = `translate(${-input.scrollLeft}px,${-input.scrollTop}px)`
}
function insertQuickPhrase(phrase) {
  const input = document.querySelector('[data-draft] textarea')
  if (!(input instanceof HTMLTextAreaElement) || state.draft === null) return
  const start = input.selectionStart
  const end = input.selectionEnd
  const prefix = input.value.slice(0, start)
  const suffix = input.value.slice(end)
  const separator = prefix !== '' && !/\s$/.test(prefix) ? ' ' : ''
  const after = suffix !== '' && !/^\s/.test(suffix) ? ' ' : ''
  const text = `${prefix}${separator}${phrase}${after}${suffix}`
  if (text.length > input.maxLength) return setError('追问内容不能超过 4000 个字符')
  const caret = prefix.length + separator.length + phrase.length
  input.value = text
  updateDraftText(text)
  syncDraftHighlight(input)
  input.focus({ preventScroll: true })
  input.setSelectionRange(caret, caret)
}

function addQuickPhrase(value) {
  const phrase = value.trim().slice(0, MAX_QUICK_PHRASE_LENGTH)
  if (phrase === '') return false
  if (state.quickPhrases.includes(phrase)) return setError('这个快捷词已经存在')
  if (state.quickPhrases.length >= MAX_QUICK_PHRASES) return setError(`最多保留 ${MAX_QUICK_PHRASES} 个快捷词`)
  state.quickPhrases.push(phrase)
  persistQuickPhrases()
  return true
}

function updateQuickPhrase(index, value) {
  if (!Number.isInteger(index) || index < 0 || index >= state.quickPhrases.length) return
  const phrase = value.trim().slice(0, MAX_QUICK_PHRASE_LENGTH)
  if (phrase === '') {
    state.quickPhrases.splice(index, 1)
  } else if (state.quickPhrases.some((item, itemIndex) => itemIndex !== index && item === phrase)) {
    return setError('这个快捷词已经存在')
  } else {
    state.quickPhrases[index] = phrase
  }
  persistQuickPhrases()
  render()
}

function draftPlacement(cards) {
  const draft = state.draft
  if (draft?.kind === 'new') return null
  if (draft === null) return null
  const parent = draft.anchorId === undefined
    ? cards.filter(card => card.dshThreadId === draft.parentId).at(-1)
    : cards.find(card => card.id === draft.anchorId)
  if (parent === undefined) return null
  return { parent, position: draft.position || nearbyCardPosition(parent.position, cards.map(card => card.position), draft.kind) }
}

function draftCard(cards) {
  const draft = state.draft
  if (draft?.kind === 'new') return `<article class="thread-card draft-card" style="left:${draft.position.x}px;top:${draft.position.y}px;--thread-color:#7c3aed"><div class="thread-card-head"><strong>新会话</strong></div><form class="draft-branch-form" data-draft>${renderDraftInput(draft, '输入第一条消息…')}${draftActions(draft)}</form></article>`
  const placement = draftPlacement(cards)
  if (draft === null || placement === null) return ''
  const continuing = draft.kind === 'continue'
  return `<article class="thread-card draft-card" data-card-id="draft" style="left:${placement.position.x}px;top:${placement.position.y}px;--thread-color:#7c3aed">
    <div class="thread-card-head"><span class="topic-dot"></span><strong>${continuing ? '新的追问' : '新的分支'}</strong></div>
    <form class="draft-branch-form" data-draft>${draftQuickPhrases(draft)}${renderDraftInput(draft, continuing ? '输入追问' : '输入这个分支的新问题')}${draftActions(draft)}</form>
  </article>`
}

function selectionFollowupButton() {
  return `<button class="selection-followup" type="button" data-action="follow-selection" hidden aria-label="基于所选内容创建追问" title="基于所选内容追问"><svg aria-hidden="true" viewBox="0 0 16 16"><path d="M3 3.5h10v6.25H7.2L4 12.5V9.75H3Z"/><path d="M8 4.9v3.4M6.3 6.6h3.4"/></svg><span>追问</span></button>`
}

// Cards are mounted into the DOM only when they intersect the viewport
// (inflated by VIEWPORT_MARGIN) in world coordinates. The camera transform is
// translate(camera) scale(zoom), so screen = world * zoom + camera.
function visibleCardIds(cards) {
  const viewport = document.querySelector('.canvas-viewport')
  if (!(viewport instanceof HTMLElement)) return new Set(cards.map(card => card.id))
  const bounds = viewport.getBoundingClientRect()
  const left = (-state.canvasCamera.x - VIEWPORT_MARGIN) / state.zoom
  const right = (bounds.width - state.canvasCamera.x + VIEWPORT_MARGIN) / state.zoom
  const top = (-state.canvasCamera.y - VIEWPORT_MARGIN) / state.zoom
  const bottom = (bounds.height - state.canvasCamera.y + VIEWPORT_MARGIN) / state.zoom
  const visible = new Set()
  for (const card of cards) {
    const { x, y } = card.position
    if (x + CARD_WIDTH < left || x > right || y + CARD_HEIGHT < top || y > bottom) continue
    visible.add(card.id)
  }
  return visible
}

// Incrementally mount cards entering the viewport and unmount cards leaving
// it, without rebuilding the canvas. Called after pan/zoom/focus camera moves.
function syncCanvasViewport() {
  if (state.mode !== 'canvas' || state.canvasCards === undefined) return
  const layer = document.querySelector('.cards-layer')
  if (!(layer instanceof HTMLElement)) return
  const visible = visibleCardIds(state.canvasCards)
  for (const cardId of [...state.mountedCardIds]) {
    if (visible.has(cardId)) continue
    const element = layer.querySelector(`[data-card-id="${selectorValue(cardId)}"]`)
    if (element instanceof HTMLElement) element.remove()
    state.mountedCardIds.delete(cardId)
  }
  for (const card of state.canvasCards) {
    if (!visible.has(card.id) || state.mountedCardIds.has(card.id)) continue
    const wrapper = document.createElement('div')
    wrapper.innerHTML = conversationCard(card, state.canvasGraph)
    const element = wrapper.firstElementChild
    if (element instanceof HTMLElement) {
      layer.appendChild(element)
      const handle = element.matches('[data-drag-card]') ? element : element.querySelector('[data-drag-card]')
      if (handle instanceof HTMLElement) bindDragHandle(handle)
    }
    state.mountedCardIds.add(card.id)
  }
}

function renderCanvas() {
  const threads = state.workspace?.threads ?? []
  const allCards = conversationCards(threads)
  if (allCards.length === 0 && !state.draft && !currentCanvasRegions().length) { state.canvasCards = []; state.canvasCardsById = new Map(); state.canvasGraph = undefined; return `<div class="canvas-viewport"><section class="empty-canvas"><strong>当前会话还没有对话内容。</strong><p>点击开始对话，直接在地图中输入问题。</p><div><button class="primary" type="button" data-action="start-conversation">开始对话</button></div></section>${canvasOverlays()}</div>` }
  const graph = conversationGraphView(allCards)
  const cards = graph.cards.filter(card => !state.hiddenCardIds.has(card.id))
  state.canvasCards = cards
  state.canvasCardsById = new Map(cards.map(card => [card.id, card]))
  state.canvasGraph = graph
  if (state.inspectorCardId !== null && !state.canvasCardsById.has(state.inspectorCardId)) {
    state.inspectorCardId = null
    state.inspectorOpening = false
  }
  if (!state.canvasViewInitialized) {
    state.canvasCamera = initialCanvasCamera(cards)
    state.canvasViewInitialized = true
    // Position the map at its initial readable scale after the iframe is visible.
  }
  const visible = visibleCardIds(cards)
  state.mountedCardIds = new Set(visible)
  const mounted = cards.filter(card => visible.has(card.id))
  const inspector = state.inspectorCardId === null ? '' : renderCardInspector(state.canvasCardsById.get(state.inspectorCardId))
  return `<section class="canvas-view"><div class="canvas-viewport"><div class="canvas-content" style="transform:translate(${state.canvasCamera.x}px, ${state.canvasCamera.y}px) scale(${state.zoom})"><div class="regions-layer">${canvasRegionsHtml(cards)}</div><svg class="connectors">${canvasConnectors(cards)}</svg><div class="cards-layer">${mounted.map(card => conversationCard(card, graph)).join('')}${draftCard(cards)}</div></div>${canvasOverlays()}</div>${inspector}</section>`
}

function processSummary(text) {
  return text.replace(/\s+/g, ' ').trim().slice(0, 140) || '工具调用记录'
}

function processRecords(process, messageId) {
  const key = `${messageId}:process`
  const expanded = state.expandedMessageIds.has(key)
  const entries = process.map((entry, index) => {
    const entryKey = `${key}:${index}`
    const entryExpanded = state.expandedMessageIds.has(entryKey)
    const status = entry.error !== null ? '失败' : entry.result === null ? '等待结果' : '完成'
    const argumentsHtml = entry.arguments === null || entry.arguments === '' ? '' : `<pre class="process-args">${escapeHtml(entry.arguments)}</pre>`
    const outcomeHtml = entry.error !== null ? `<pre class="process-error">${escapeHtml(entry.error)}</pre>` : entry.result === null ? '' : `<pre class="process-result">${escapeHtml(entry.result)}</pre>`
    return `<div class="process-entry${entryExpanded ? ' expanded' : ''}"><button class="process-entry-fold" data-action="toggle-message" data-message="${escapeHtml(entryKey)}"><span class="process-entry-name">${escapeHtml(entry.name)}</span><span class="process-status${entry.error !== null ? ' process-status-error' : entry.result === null ? ' process-status-pending' : ' process-status-done'}">${status}</span></button>${entryExpanded ? `<div class="process-entry-body">${argumentsHtml}${outcomeHtml}</div>` : ''}</div>`
  }).join('')
  return `<section class="process-records${expanded ? ' expanded' : ''}"><button class="process-records-fold" data-action="toggle-message" data-message="${escapeHtml(key)}"><span>${expanded ? '收起过程记录' : '过程记录'}</span><span class="process-count">${process.length}</span></button>${expanded ? entries : ''}</section>`
}

function messagesForCard(card) {
  const thread = state.workspace?.threads.find(item => item.id === card.dshThreadId)
  if (thread === undefined) return { thread: null, messages: [] }
  const messages = messagesFor(thread)
  let turnIndex = -1
  let start = -1
  for (let index = 0; index < messages.length; index++) {
    if (messages[index].kind !== 'user') continue
    turnIndex += 1
    if (turnIndex === card.turnIndex) {
      start = index
      break
    }
  }
  if (start === -1) return { thread, messages: [] }
  const end = messages.findIndex((message, index) => index > start && message.kind === 'user')
  return { thread, messages: messages.slice(start, end === -1 ? undefined : end) }
}

function inspectorProcessEntries(messages) {
  const entries = []
  for (const message of messages) {
    if (Array.isArray(message.process)) {
      entries.push(...message.process.map(entry => ({ ...entry })))
      continue
    }
    if (message.kind === 'tool') {
      entries.push({ name: processSummary(message.text), arguments: message.text, result: null, error: null })
      continue
    }
    if (message.kind === 'tool-result') {
      const previous = entries.at(-1)
      if (previous !== undefined && previous.result === null && previous.error === null) previous.result = message.text
      else entries.push({ name: '工具结果', arguments: null, result: message.text, error: null })
    }
  }
  return entries
}

function openDialogIcon() {
  return '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h2l4 3v-3h1"/><path d="M7 8h8M7 12h4M15 16h7m-3-3 3 3-3 3"/></svg>'
}
function renderCardInspector(card) {
  if (card === undefined) return ''
  const { thread, messages } = messagesForCard(card)
  if (thread === null) return ''
  const process = inspectorProcessEntries(messages)
  const answer = card.answer === null
    ? card.error === null ? mapThinkingIndicator() : ''
    : `<article class="card-inspector-answer">${renderMarkdown(card.answer.text)}${card.answer.pending ? mapThinkingIndicator() : ''}</article>`
  const error = card.error === null ? '' : `<section class="card-inspector-error" role="alert"><strong>本轮未完成</strong><p>${escapeHtml(card.error.text)}</p></section>`
  const processRecordsHtml = process.length === 0 ? '' : processRecords(process, `${thread.id}:${card.id}:inspector`)
  const continueAction = card.canContinue === true ? `<button type="button" data-action="open-continue" data-thread="${thread.id}" data-card="${escapeHtml(card.id)}"><svg aria-hidden="true" viewBox="0 0 16 16"><path d="M2.5 3.5h11v7h-6l-3.5 2.5v-2.5h-1.5Z"/><path d="M8 5.5v3M6.5 7h3"/></svg>继续追问</button>` : ''
  const branch = Number.isInteger(card.answer?.sourceSeq)
    ? `<button type="button" data-action="open-branch" data-thread="${thread.id}" data-card="${escapeHtml(card.id)}" data-seq="${card.answer.sourceSeq}"><svg aria-hidden="true" viewBox="0 0 16 16"><circle cx="4" cy="3.5" r="1.5"/><circle cx="12" cy="3.5" r="1.5"/><circle cx="12" cy="12.5" r="1.5"/><path d="M5.5 3.5h2A2.5 2.5 0 0 1 10 6v5"/></svg>创建分支</button>`
    : ''
  const openDshAction = `<button class="primary" type="button" data-action="open-dsh" data-thread="${thread.id}" data-seq="${Number.isInteger(card.sourceSeq) ? card.sourceSeq : ''}" title="在智能问答中打开" aria-label="在智能问答中打开">${openDialogIcon()}打开问答</button>`
  return `<aside class="card-inspector${state.inspectorOpening ? ' is-opening' : ''}" aria-label="卡片详情" data-inspector-card="${escapeHtml(card.id)}">
    <header class="card-inspector-head"><div>
      <div class="card-inspector-eyebrow">${canvasIcon('message')}<span>对话详情</span></div>
      <h2>${escapeHtml(card.question)}</h2>
      <div class="card-inspector-meta"><span>第 ${card.turnIndex + 1} 轮</span>${card.error === null ? '' : '<span class="card-inspector-error-status">未完成</span>'}${process.length > 0 ? `<span>工具调用 ${process.length}</span>` : ''}</div>
    </div><button class="card-inspector-close" type="button" data-action="close-card-inspector" aria-label="关闭卡片详情" title="关闭"><svg aria-hidden="true" viewBox="0 0 16 16"><path d="m4.5 4.5 7 7m0-7-7 7"/></svg></button></header>
    <div class="card-inspector-scroll"><section class="card-inspector-response"><h3 class="map-assistant-identity">${mindPilotAvatar()}<span>MindPilot</span></h3>${error}${answer}</section>${processRecordsHtml}</div>
    <footer class="card-inspector-actions">${continueAction}${branch}${openDshAction}</footer></aside>`
}

function render() {
  if (state.mode === 'canvas' && state.inspectorCardId !== null) {
    const inspector = document.querySelector('.card-inspector-scroll')
    if (inspector instanceof HTMLElement) state.inspectorScrollByCard.set(state.inspectorCardId, inspector.scrollTop)
  }
  const inspectorScrollTop = state.mode === 'canvas' && state.inspectorCardId !== null ? state.inspectorScrollByCard.get(state.inspectorCardId) ?? null : null
  const cardScrollTops = new Map()
  if (state.mode === 'canvas') {
    // Key by the unique card id: every card of a session shares data-thread,
    // so keying on it would clobber sibling cards' scroll positions. Only
    // scrollable answers have a position worth preserving; reading the two
    // height properties shares the same forced layout as the scrollTop read.
    for (const answer of document.querySelectorAll('.thread-card[data-thread] .thread-answer')) {
      if (answer.scrollHeight <= answer.clientHeight) continue
      const card = answer.closest('.thread-card')
      if (card instanceof HTMLElement && typeof card.dataset.cardId === 'string') cardScrollTops.set(card.dataset.cardId, answer.scrollTop)
    }
  }
  const workspace = state.workspace
  const threads = workspace?.threads ?? []
  const view = renderCanvas()
  app.innerHTML = `<main class="synapse-shell"><section class="main-stage">${state.error ? `<div class="status-message" role="alert"><span>${escapeHtml(state.error)}</span><button data-action="dismiss-error" aria-label="Close">?</button></div>` : ''}${view}${selectionFollowupButton()}</section></main>`
  prepareMapHints()
  if (state.regionDialog) app.querySelector('.region-color-options button')?.focus({ preventScroll: true })
  syncDraftHighlight()
  installDragging()
  cacheCardConnectors()
  // The initial camera from renderCanvas is inset (viewport not laid out yet);
  // center it on the focused card once the canvas DOM is mounted.
  scheduleInitialCanvasFit()
  for (const [cardId, scrollTop] of cardScrollTops) {
    const answer = app.querySelector(`.thread-card[data-card-id="${CSS.escape(cardId)}"] .thread-answer`)
    if (answer instanceof HTMLElement) answer.scrollTop = scrollTop
  }
  if (inspectorScrollTop !== null) window.requestAnimationFrame(() => {
    const inspector = document.querySelector('.card-inspector-scroll')
    if (inspector instanceof HTMLElement) inspector.scrollTop = inspectorScrollTop
  })
  if (state.inspectorOpening) window.requestAnimationFrame(() => {
    document.querySelector('.card-inspector')?.classList.remove('is-opening')
    state.inspectorOpening = false
  })

}


let inspectorCloseTimer = 0
function openCardInspector(cardId) {
  if (inspectorCloseTimer !== 0) {
    window.clearTimeout(inspectorCloseTimer)
    inspectorCloseTimer = 0
  }
  state.inspectorOpening = state.inspectorCardId === null
  state.inspectorCardId = cardId
}

function closeCardInspector({ animate = true } = {}) {
  if (state.inspectorCardId === null) return
  if (inspectorCloseTimer !== 0) window.clearTimeout(inspectorCloseTimer)
  const cardId = state.inspectorCardId
  const inspector = document.querySelector('.card-inspector')
  if (!animate || !(inspector instanceof HTMLElement)) {
    state.inspectorCardId = null
    state.inspectorOpening = false
    render()
    return
  }
  inspector.classList.add('is-closing')
  inspectorCloseTimer = window.setTimeout(() => {
    inspectorCloseTimer = 0
    if (state.inspectorCardId !== cardId) return
    state.inspectorCardId = null
    state.inspectorOpening = false
    render()
  }, 180)
}

function applyCanvasTransform() {
  const content = document.querySelector('.canvas-content')
  if (content instanceof HTMLElement) content.style.transform = `translate(${state.canvasCamera.x}px, ${state.canvasCamera.y}px) scale(${state.zoom})`
}

function bindDragHandle(handle) {
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('button,textarea,input,select,form,.thread-answer,.card-color-palette')) return
    const cardId = event.currentTarget.dataset.dragCard
    const card = event.currentTarget.closest('.thread-card')
    if (cardId === undefined || !(card instanceof HTMLElement)) return
    event.preventDefault()
    const origin = { x: event.clientX, y: event.clientY, position: { x: Number.parseFloat(card.style.left), y: Number.parseFloat(card.style.top) } }
    const aliases = card.dataset.positionKey === undefined ? [] : [card.dataset.positionKey]
    let position = origin.position
    let stopped = false
    let frame = 0
    let moved = false
    // Coalesce pointermove updates to one DOM pass per animation frame so a
    // high report-rate pointer cannot queue a reflow per event.
    const apply = () => {
      frame = 0
      state.cardPositions.set(cardId, { x: Math.round(position.x), y: Math.round(position.y) })
      for (const alias of aliases) state.cardPositions.set(alias, { x: Math.round(position.x), y: Math.round(position.y) })
      // Keep the virtualized data object in sync so viewport visibility and
      // connector paths track the live drag position.
      const dataCard = state.canvasCardsById?.get(cardId)
      if (dataCard !== undefined) dataCard.position = { x: position.x, y: position.y }
      card.style.left = `${position.x}px`
      card.style.top = `${position.y}px`
      syncCanvasRegions()
      refreshCardConnectors(cardId)
      for (const group of app.querySelectorAll('.manual-connector')) {
        const edge = state.links.find(item => item.id === group.dataset.linkId)
        const from = state.canvasCardsById.get(edge?.source), to = state.canvasCardsById.get(edge?.target)
        if (from && to) {
          const geometry = manualLinkGeometry(from.position, to.position)
          group.querySelector('g').setAttribute('transform', `translate(${geometry.x},${geometry.y})`)
          for (const path of group.querySelectorAll('path')) path.setAttribute('d', geometry.path)
        }
      }
    }
    const move = moveEvent => {
      if (!moved && Math.hypot(moveEvent.clientX - origin.x, moveEvent.clientY - origin.y) <= 4) return
      if (!moved) { moved = true; state.dragging = true; selectCanvasCard(cardId) }
      position = { x: origin.position.x + (moveEvent.clientX - origin.x) / state.zoom, y: origin.position.y + (moveEvent.clientY - origin.y) / state.zoom }
      if (frame === 0) frame = window.requestAnimationFrame(apply)
    }
    const stop = () => {
      if (stopped) return
      stopped = true
      document.removeEventListener('pointermove', move)
      document.removeEventListener('pointerup', stop)
      document.removeEventListener('pointercancel', stop)
      if (frame !== 0) { window.cancelAnimationFrame(frame); frame = 0 }
      if (moved) { apply(); rememberCardPosition(cardId, position, aliases) }
      state.dragging = false
      deferCanvasRefresh(120)
      // No full render: only the dragged card's inline position and its
      // connectors changed; rebuilding the whole canvas on drop is the jank.
    }
    document.addEventListener('pointermove', move)
    document.addEventListener('pointerup', stop)
    document.addEventListener('pointercancel', stop)
  })
}

function installDragging() {
  for (const handle of document.querySelectorAll('[data-drag-card]')) bindDragHandle(handle)
}

function canvasViewport(target) {
  return target instanceof Element ? target.closest('.canvas-viewport') : null
}

function zoomCanvas(viewport, nextZoom, clientX, clientY) {
  stopCanvasAutoOverview()
  const zoom = Math.min(4, Math.max(.01, Math.round(nextZoom * 100) / 100))
  if (zoom === state.zoom) return
  const bounds = viewport.getBoundingClientRect()
  const localX = clientX - bounds.left
  const localY = clientY - bounds.top
  const worldX = (localX - state.canvasCamera.x) / state.zoom
  const worldY = (localY - state.canvasCamera.y) / state.zoom
  state.zoom = zoom
  state.canvasCamera = { x: localX - worldX * zoom, y: localY - worldY * zoom }
  const content = viewport.querySelector('.canvas-content')
  if (content instanceof HTMLElement) {
    // Drop the composited layer before zooming: a cached will-change raster
    // would be upscaled instead of re-rasterized, which was the original
    // zoom-blur bug. will-change re-applies via .is-panning on the next pan.
    content.style.willChange = 'auto'
    applyCanvasTransform()
    syncCanvasViewport()
    window.requestAnimationFrame(() => { content.style.willChange = '' })
  } else {
    applyCanvasTransform()
    syncCanvasViewport()
  }
  const label = document.querySelector('.canvas-controls span')
  if (label !== null) label.textContent = `${Math.round(state.zoom * 100)}%`
}

function zoomCanvasAtCenter(delta) {
  const viewport = document.querySelector('.canvas-viewport')
  if (!(viewport instanceof HTMLElement)) return
  const bounds = viewport.getBoundingClientRect()
  zoomCanvas(viewport, state.zoom + delta, bounds.left + bounds.width / 2, bounds.top + bounds.height / 2)
}

function focusActiveCard() {
  // Initial host syncs may select several sessions before bootstrap settles.
  // Keep the complete overview until the user interacts with the canvas.
  if (state.canvasAutoOverview) { scheduleInitialCanvasFit(); return }
  const viewport = document.querySelector('.canvas-viewport')
  if (!(viewport instanceof HTMLElement)) return
  const cards = state.canvasCards
  if (cards === undefined || cards.length === 0) return
  // Drafts win over the active conversation's latest turn; fall back to the
  // first card. Cards may be unmounted (outside the viewport), so the focus
  // target comes from the data model, never from DOM queries.
  const draft = state.draft === null ? undefined
    : draftPlacement(cards)
  const activeCards = state.activeId === null || state.activeId === undefined ? [] : cards.filter(card => card.dshThreadId === state.activeId)
  const card = draft ?? activeCards.at(-1) ?? cards[0]
  const { x: left, y: top } = card.position
  const bounds = viewport.getBoundingClientRect()
  state.canvasCamera = {
    x: bounds.width / 2 - (left + CARD_WIDTH / 2) * state.zoom,
    y: bounds.height / 2 - (top + CARD_HEIGHT / 2) * state.zoom,
  }
  applyCanvasTransform()
  syncCanvasViewport()
}

let selectionFollowup = null
let selectionFollowupFrame = 0

function hideSelectionFollowup() {
  if (selectionFollowupFrame !== 0) {
    window.cancelAnimationFrame(selectionFollowupFrame)
    selectionFollowupFrame = 0
  }
  selectionFollowup = null
  const button = app.querySelector('.selection-followup')
  if (button instanceof HTMLButtonElement) button.hidden = true
}

function selectionFollowupTarget(range) {
  const start = range.startContainer instanceof Element ? range.startContainer : range.startContainer.parentElement
  const end = range.endContainer instanceof Element ? range.endContainer : range.endContainer.parentElement
  if (!(start instanceof Element) || !(end instanceof Element)) return null
  const answer = start.closest('.thread-answer')
  if (answer instanceof HTMLElement && answer.contains(end)) {
    const card = answer.closest('.thread-card[data-thread]:not(.draft-card)')
    if (card instanceof HTMLElement && card.dataset.thread !== undefined) return { threadId: card.dataset.thread, cardId: card.dataset.cardId }
  }
  return null
}

function updateSelectionFollowup() {
  selectionFollowupFrame = 0
  const button = app.querySelector('.selection-followup')
  const selection = window.getSelection()
  if (!(button instanceof HTMLButtonElement) || selection === null || selection.rangeCount !== 1 || selection.isCollapsed) return hideSelectionFollowup()
  const text = selection.toString().trim()
  const range = selection.getRangeAt(0)
  const target = text === '' || text.length > 4000 ? null : selectionFollowupTarget(range)
  if (state.draft && (state.draft.sending || state.draft.text.trim() !== '' || state.draft.parentId !== target?.threadId
    || state.draft.anchorId !== undefined && state.draft.anchorId !== target?.cardId)) return hideSelectionFollowup()
  const rect = range.getBoundingClientRect()
  if (target === null || rect.width === 0 || rect.height === 0) return hideSelectionFollowup()
  selectionFollowup = { ...target, text }
  button.dataset.thread = target.threadId
  button.style.left = `${Math.min(window.innerWidth - 12, Math.max(76, rect.right))}px`
  button.style.top = `${Math.min(window.innerHeight - 38, Math.max(8, rect.bottom + 8))}px`
  button.hidden = false
}

function queueSelectionFollowup() {
  if (selectionFollowupFrame !== 0) return
  selectionFollowupFrame = window.requestAnimationFrame(updateSelectionFollowup)
}

app.addEventListener('pointerdown', event => {
  const regionElement = event.target.closest('.canvas-region')
  if (!regionElement || event.button !== 0 || event.target.closest('button')) return
  const viewport = canvasViewport(regionElement)
  const snapshot = regionDragSnapshot(regionElement.dataset.regionId)
  if (!viewport || !snapshot) return
  event.preventDefault()
  selectCanvasRegion(snapshot.id)
  state.menu = null; app.querySelector('.canvas-menu')?.remove()
  const origin = { x: event.clientX, y: event.clientY, zoom: state.zoom }
  let dx = 0, dy = 0, moved = false, frame = 0, stopped = false
  state.canvasGesture = true
  viewport.setPointerCapture(event.pointerId)
  const apply = () => {
    frame = 0
    translateCanvasRegion(snapshot, dx, dy)
    for (const card of snapshot.cards) {
      const element = app.querySelector(`.thread-card[data-card-id="${selectorValue(card.id)}"]`)
      const position = state.cardPositions.get(card.id)
      if (element) { element.style.left = `${position.x}px`; element.style.top = `${position.y}px` }
    }
    if (snapshot.draft && state.draft === snapshot.draft.draft) {
      const element = app.querySelector('.draft-card')
      if (element) { element.style.left = `${state.draft.position.x}px`; element.style.top = `${state.draft.position.y}px` }
    }
    syncCanvasRegions()
    const svg = app.querySelector('.connectors')
    if (svg) svg.innerHTML = canvasConnectors(state.canvasCards || [])
    syncCanvasViewport()
  }
  const move = moveEvent => {
    if (moveEvent.pointerId !== event.pointerId) return
    if (!moved && Math.hypot(moveEvent.clientX - origin.x, moveEvent.clientY - origin.y) <= 4) return
    moved = true; state.dragging = true; viewport.classList.add('is-region-dragging')
    dx = (moveEvent.clientX - origin.x) / origin.zoom
    dy = (moveEvent.clientY - origin.y) / origin.zoom
    if (!frame) frame = window.requestAnimationFrame(apply)
  }
  const stop = stopEvent => {
    if (stopEvent?.pointerId !== undefined && stopEvent.pointerId !== event.pointerId || stopped) return
    stopped = true
    document.removeEventListener('pointermove', move)
    document.removeEventListener('pointerup', stop)
    document.removeEventListener('pointercancel', stop)
    window.removeEventListener('blur', stop)
    if (frame) window.cancelAnimationFrame(frame)
    if (moved) { apply(); persistCardPositions(); persistCanvasActions(); cacheCardConnectors() }
    viewport.classList.remove('is-region-dragging')
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId)
    state.dragging = false; state.canvasGesture = false
    deferCanvasRefresh(120)
  }
  document.addEventListener('pointermove', move)
  document.addEventListener('pointerup', stop)
  document.addEventListener('pointercancel', stop)
  window.addEventListener('blur', stop)
})

app.addEventListener('pointerdown', event => {
  const viewport = canvasViewport(event.target)
  if (event.button !== 0 || event.target.closest('.canvas-region,.canvas-menu,.canvas-controls,.canvas-footnote,.canvas-help,.canvas-dialog-backdrop')) return
  if (!(viewport instanceof HTMLElement) || event.target instanceof Element && event.target.closest('.thread-card, button, textarea, select')) return
  stopCanvasAutoOverview()
  selectCanvasRegion(null)
  state.selectedCardId = null
  for (const card of app.querySelectorAll('.thread-card.selected')) { card.classList.remove('selected'); card.querySelector('.card-color-palette')?.remove() }
  event.preventDefault()
  const origin = { x: event.clientX, y: event.clientY, camera: { ...state.canvasCamera } }
  let pendingCamera = null
  let frame = 0
  state.canvasGesture = true
  viewport.classList.add('is-panning')
  viewport.setPointerCapture(event.pointerId)
  const apply = () => {
    frame = 0
    if (pendingCamera === null) return
    state.canvasCamera = pendingCamera
    pendingCamera = null
    applyCanvasTransform()
    syncCanvasViewport()
  }
  const move = moveEvent => {
    pendingCamera = {
      x: origin.camera.x + moveEvent.clientX - origin.x,
      y: origin.camera.y + moveEvent.clientY - origin.y,
    }
    if (frame === 0) frame = window.requestAnimationFrame(apply)
  }
  const stop = () => {
    viewport.classList.remove('is-panning')
    document.removeEventListener('pointermove', move)
    document.removeEventListener('pointerup', stop)
    document.removeEventListener('pointercancel', stop)
    if (frame !== 0) { window.cancelAnimationFrame(frame); frame = 0 }
    apply()
    state.canvasGesture = false
    deferCanvasRefresh(120)
  }
  document.addEventListener('pointermove', move)
  document.addEventListener('pointerup', stop)
  document.addEventListener('pointercancel', stop)
})

app.addEventListener('contextmenu', event => {
  if (event.target.closest('textarea,input,.card-inspector,.canvas-dialog')) return
  event.preventDefault()
  const card = event.target.closest('.thread-card[data-card-id]:not(.draft-card)')
  const edge = event.target.closest('[data-link-id]')
  const region = event.target.closest('[data-region-id]')
  const viewport = app.querySelector('.canvas-viewport')
  if (!viewport) return
  const rect = viewport.getBoundingClientRect()
  const point = { x: (event.clientX - rect.left - state.canvasCamera.x) / state.zoom, y: (event.clientY - rect.top - state.canvasCamera.y) / state.zoom }
  state.menu = { x: Math.max(8, Math.min(event.clientX - rect.left, rect.width - 220)), y: Math.max(8, Math.min(event.clientY - rect.top, rect.height - (card ? 344 : 224))), cardId: card?.dataset.cardId, linkId: edge?.dataset.linkId, regionId: region?.dataset.regionId, point }
  state.helpOpen = false
  if (card) selectCanvasCard(card.dataset.cardId)
  else if (region) selectCanvasRegion(region.dataset.regionId)
  render()
})

app.addEventListener('wheel', event => {
  const viewport = canvasViewport(event.target)
  if (!(viewport instanceof HTMLElement)) return
  const card = event.target instanceof Element ? event.target.closest('.thread-card') : null
  if (card instanceof HTMLElement) {
    // Over a card the wheel scrolls that card's own answer with the browser's
    // native wheel (OS-smooth, never a page jump per notch); the answer's
    // overscroll-behavior: contain stops the scroll chaining into the canvas.
    const answer = card.querySelector('.thread-answer')
    if (answer instanceof HTMLElement && answer.scrollHeight > answer.clientHeight) {
      deferCanvasRefresh()
      return
    }
    // A card with no scrollable answer swallows the wheel instead of zooming.
    event.preventDefault()
    deferCanvasRefresh()
    return
  }
  event.preventDefault()
  zoomCanvas(viewport, state.zoom + (event.deltaY < 0 ? .05 : -.05), event.clientX, event.clientY)
}, { passive: false })

// Track pointer-down so the card click handler can tell a plain click from a
// text-selection or drag gesture; acting on the latter would re-render and
// wipe the user's selection.
let pointerDownPosition = null
app.addEventListener('pointerdown', event => { pointerDownPosition = { x: event.clientX, y: event.clientY } })
app.addEventListener('pointerdown', event => {
  const button = event.target instanceof Element ? event.target.closest('.selection-followup') : null
  if (button instanceof HTMLButtonElement) event.preventDefault()
  else hideSelectionFollowup()
})
app.addEventListener('pointerup', queueSelectionFollowup)
app.addEventListener('scroll', hideSelectionFollowup, true)
document.addEventListener('selectionchange', queueSelectionFollowup)
installMapHintEvents()

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    event.preventDefault(); state.menu = null; state.linkSource = null; state.editCardId = null; state.deleteCardId = null; state.regionDialog = null; state.selectedRegionId = null; state.helpOpen = false
    if (state.inspectorCardId !== null) closeCardInspector({ animate: false }); else render()
  }
  if (event.key !== 'Backspace' || event.ctrlKey || event.metaKey || event.altKey || event.target instanceof Element && event.target.closest('input,textarea,select,[contenteditable="true"]')) return
  if (state.selectedLinkId) { event.preventDefault(); state.links = state.links.filter(edge => edge.id !== state.selectedLinkId); state.selectedLinkId = null; persistCanvasActions(); render() }
  else if (state.selectedCardId) { event.preventDefault(); state.deleteCardId = state.selectedCardId; render() }
})

document.addEventListener('pointerdown', event => {
  if (state.menu && !event.target.closest('.canvas-menu')) { state.menu = null; app.querySelector('.canvas-menu')?.remove() }
  if (state.helpOpen && !event.target.closest('.canvas-help,[data-action="toggle-help"]')) {
    state.helpOpen = false
    app.querySelector('.canvas-help')?.remove()
    app.querySelector('.canvas-footnote [data-action="toggle-help"]')?.setAttribute('aria-expanded', 'false')
  }
})

let cardActivationTimer = 0
function activateCardSession(thread) {
  if (thread.dshSessionId === null) return
  if (thread.dshSessionId !== state.currentDsh?.id) state.mapCardSessionSwitches.add(thread.dshSessionId)
  post('synapse:activate-session', { sessionId: thread.dshSessionId })
}
app.addEventListener('dblclick', event => {
  const card = event.target.closest('.thread-card[data-thread]:not(.draft-card)')
  if (!(card instanceof HTMLElement) || event.target.closest('button,textarea,input,select,form,.card-color-palette')) return
  window.clearTimeout(cardActivationTimer)
  const thread = state.workspace?.threads.find(item => item.id === card.dataset.thread)
  if (thread === undefined) return
  selectCanvasCard(card.dataset.cardId)
  openCardInspector(card.dataset.cardId)
  render()
  activateCardSession(thread)
})
app.addEventListener('click', async event => {
  const edge = event.target.closest('[data-link-id]')
  const region = event.target.closest('[data-region-id]')
  if (edge) { selectCanvasRegion(null); state.selectedLinkId = edge.dataset.linkId; state.selectedCardId = null; render(); return }
  const button = event.target.closest('[data-action]')
  if (!(button instanceof HTMLElement)) {
    if (region) { selectCanvasRegion(region.dataset.regionId); return }
    const card = event.target instanceof Element ? event.target.closest('.thread-card[data-thread]:not(.draft-card)') : null
    if (!(card instanceof HTMLElement) || event.target instanceof Element && event.target.closest('.node-handle, textarea, select, form')) return
    // A double-click selects a word and a drag selects a range; neither is a
    // select-click, so leave the selection intact instead of re-rendering.
    if (event.detail > 1) return
    if (pointerDownPosition !== null
      && Math.hypot(event.clientX - pointerDownPosition.x, event.clientY - pointerDownPosition.y) > 4) return
    const thread = state.workspace?.threads.find(item => item.id === card.dataset.thread)
    if (thread === undefined) return
    const cardId = card.dataset.cardId
    if (cardId === undefined) return
    if (state.linkSource) {
      const source = state.linkSource; state.linkSource = null
      if (source !== cardId && !state.links.some(edge => edge.source === source && edge.target === cardId || edge.source === cardId && edge.target === source)) {
        state.links.push({ id: crypto.randomUUID(), source, target: cardId }); persistCanvasActions()
      }
      selectCanvasCard(cardId); render(); return
    }
    state.selectedLinkId = null
    selectCanvasCard(cardId)
    state.error = ''
    window.clearTimeout(cardActivationTimer)
    // Bidirectional current-session sync: switch MindPilot's current session
    // without closing the map; the client confirms via synapse:current-session.
    cardActivationTimer = window.setTimeout(() => activateCardSession(thread), 300)
    return
  }
  const thread = state.workspace?.threads.find(item => item.id === button.dataset.thread)
  try {
    const action = button.dataset.action
    const menuCard = state.menu?.cardId ? state.canvasCardsById?.get(state.menu.cardId) : null
    const menuThread = menuCard ? state.workspace?.threads.find(item => item.id === menuCard.dshThreadId) : null
    if (action === 'start-conversation') {
      await createCanvasSession({ x: (CAMERA_INSET_X - state.canvasCamera.x) / state.zoom,
        y: (CAMERA_INSET_Y - state.canvasCamera.y) / state.zoom })
      return
    }
    if (action === 'menu-new') { await createCanvasSession(state.menu.point); return }
    if (action === 'menu-region') {
      const existing = menuCard && currentCanvasRegions().find(region => region.roots.includes(menuCard.id)
        || menuCard.turnIndex === 0 && region.sessions.includes(menuCard.dshThreadId))
      state.regionDialog = existing ? { id: existing.id, color: existing.color }
        : { rootId: menuCard?.id, sessionId: menuCard?.turnIndex === 0 ? menuCard.dshThreadId : null,
          point: menuCard ? { x: menuCard.position.x - 32, y: menuCard.position.y - 58 } : state.menu.point }
      state.menu = null; render(); return
    }
    if (action === 'choose-region-color') { saveRegionColor(button.dataset.color); return }
    if (action === 'region-color') {
      const region = currentCanvasRegions().find(item => item.id === button.dataset.region)
      if (region) { state.regionDialog = { id: region.id, color: region.color }; state.menu = null; render() }
      return
    }
    if (action === 'region-remove') {
      state.regions = state.regions.filter(region => region.id !== button.dataset.region)
      if (state.selectedRegionId === button.dataset.region) state.selectedRegionId = null
      state.menu = null; persistCanvasActions(); render(); return
    }
    if (action === 'menu-open' && menuThread) { state.menu = null; post('synapse:open-session', { sessionId: menuThread.dshSessionId, seq: menuCard.sourceSeq }); return }
    if (action === 'menu-continue' && menuThread) { state.menu = null; openContinue(menuThread, menuCard.id); return }
    if (action === 'menu-branch' && menuThread) { state.menu = null; openBranch(menuThread, menuCard.answer?.sourceSeq, menuCard.id); return }
    if (action === 'menu-link' && menuCard) { state.linkSource = menuCard.id; state.menu = null; render(); return }
    if (action === 'menu-rename' && menuCard) { state.editCardId = menuCard.id; state.menu = null; render(); window.setTimeout(() => app.querySelector('.canvas-dialog input')?.focus(), 0); return }
    if (action === 'menu-hide' && menuCard) { hideCanvasCard(menuCard.id); return }
    if (action === 'menu-delete' && menuCard) { state.deleteCardId = menuCard.id; state.menu = null; render(); return }
    if (action === 'confirm-hide' && state.deleteCardId) { hideCanvasCard(state.deleteCardId); return }
    if (action === 'cancel-dialog') { state.regionDialog = null; state.editCardId = null; state.deleteCardId = null; render(); return }
    if (action === 'restore-hidden') { restoreCanvasCards(); return }
    if (action === 'fit-canvas') { fitCanvas(); return }
    if (action === 'toggle-help') { state.helpOpen = !state.helpOpen; render(); return }
    if (action === 'remove-link') { const id = state.menu?.linkId; state.links = state.links.filter(edge => edge.id !== id); state.menu = null; state.selectedLinkId = null; persistCanvasActions(); render(); return }
    if (button.dataset.action === 'set-card-color') {
      const card = state.canvasCardsById?.get(button.dataset.card)
      const owner = state.workspace?.threads.find(item => item.id === card?.dshThreadId)
      if (owner === undefined || !CARD_COLORS.includes(button.dataset.color)) return
      const result = await api(`/synapse/api/threads/${owner.id}`, { method: 'PATCH', body: JSON.stringify({ cardId: card.id, color: button.dataset.color }) })
      Object.assign(owner, result.thread)
      render()
      return
    }
    if (button.dataset.action === 'follow-selection') {
      const followup = selectionFollowup
      hideSelectionFollowup()
      if (followup !== null && thread !== undefined && thread.id === followup.threadId) {
        if (state.draft === null) openContinue(thread, followup.cardId, followup.text)
        else if (!state.draft.sending && state.draft.text.trim() === '' && state.draft.parentId === thread.id) {
          state.draft.text = followup.text.length < 4000 ? followup.text + ' ' : followup.text
          state.draft.selectedRanges = [{ start: 0, end: followup.text.length }]
          render()
          window.setTimeout(focusDraftInput, 0)
        }
      }
      return
    }
    if (button.dataset.action === 'insert-quick-phrase' && button.dataset.quickPhrase !== undefined) insertQuickPhrase(button.dataset.quickPhrase)
    if (button.dataset.action === 'open-quick-phrase-editor') { state.quickPhraseEditorOpen = true; render() }
    if (button.dataset.action === 'close-quick-phrase-editor') { state.quickPhraseEditorOpen = false; render() }
    if (button.dataset.action === 'add-quick-phrase') {
      const editor = button.closest('.draft-quick-phrase-add')
      const input = editor?.querySelector('input')
      if (input instanceof HTMLInputElement && addQuickPhrase(input.value)) {
        render()
        window.setTimeout(() => document.querySelector('.draft-quick-phrase-add input')?.focus(), 0)
      }
    }
    if (button.dataset.action === 'remove-quick-phrase') {
      const index = Number(button.dataset.quickPhraseIndex)
      if (Number.isInteger(index) && index >= 0 && index < state.quickPhrases.length) {
        state.quickPhrases.splice(index, 1)
        persistQuickPhrases()
        render()
      }
    }
    if (button.dataset.action === 'close') post('synapse:close')
    if (button.dataset.action === 'close-card-inspector') { closeCardInspector(); return }
    if (button.dataset.action === 'open-current' && state.currentDsh !== null) post('synapse:open-session', { sessionId: state.currentDsh.id })
    if (button.dataset.action === 'toggle-card-children' && button.dataset.card !== undefined) {
      const cardId = button.dataset.card
      const collapsing = !state.collapsedCardIds.has(cardId)
      if (collapsing && state.workspace !== null) {
        const allCards = conversationCards(state.workspace.threads)
        const nextCollapsed = new Set(state.collapsedCardIds).add(cardId)
        const visibleCards = conversationGraphView(allCards, nextCollapsed).cards
        const visibleIds = new Set(visibleCards.map(card => card.id))
        const draftParentId = draftPlacement(allCards)?.parent.id
        if (draftParentId !== undefined && !visibleIds.has(draftParentId)) return setError('请先完成或取消正在编辑的追问或分支')
        if (state.activeId !== null && !visibleCards.some(card => card.dshThreadId === state.activeId)) return setError('当前会话位于这个后续分支中，请先切换会话')
      }
      collapsing ? state.collapsedCardIds.add(cardId) : state.collapsedCardIds.delete(cardId)
      persistCollapsedCards()
      render()
      window.setTimeout(() => document.querySelector(`[data-action="toggle-card-children"][data-card="${selectorValue(cardId)}"]`)?.focus(), 0)
    }
    if (button.dataset.action === 'open-continue' && thread !== undefined) openContinue(thread, button.dataset.card)
    if (button.dataset.action === 'open-branch' && thread !== undefined) {
      const requestedSeq = Number(button.dataset.seq)
      if (button.dataset.card !== undefined && !Number.isInteger(requestedSeq)) return setError('请等待这张卡片的最终回答后再创建分支')
      const fallbackSeq = latestMessage(thread, 'assistant')?.sourceSeq
      openBranch(thread, Number.isInteger(requestedSeq) ? requestedSeq : fallbackSeq, button.dataset.card)
    }
    if (button.dataset.action === 'cancel-draft') { state.draft = null; state.quickPhraseEditorOpen = false; render() }
    if (button.dataset.action === 'toggle-message' && button.dataset.message !== undefined) { state.expandedMessageIds.has(button.dataset.message) ? state.expandedMessageIds.delete(button.dataset.message) : state.expandedMessageIds.add(button.dataset.message); render() }
    if (button.dataset.action === 'open-dsh' && thread?.dshSessionId !== null) post('synapse:open-session', { sessionId: thread.dshSessionId, seq: button.dataset.seq !== '' && Number.isInteger(Number(button.dataset.seq)) ? Number(button.dataset.seq) : undefined })
    if (button.dataset.action === 'zoom-in') zoomCanvasAtCenter(.1)
    if (button.dataset.action === 'zoom-out') zoomCanvasAtCenter(-.1)
    if (button.dataset.action === 'dismiss-error') { state.error = ''; render() }
    if (button.dataset.action === 'layout' && state.workspace !== null) {
      state.menu = null
      resetCardPositions()
      resetCanvasCamera()
      render()
    }
  } catch (error) { setError(error) }
})

app.addEventListener('change', event => {
  const quickPhrase = event.target instanceof Element ? event.target.closest('[data-quick-phrase-index]') : null
  if (quickPhrase instanceof HTMLInputElement) {
    updateQuickPhrase(Number(quickPhrase.dataset.quickPhraseIndex), quickPhrase.value)
    return
  }
})
const draftCompositions = new WeakSet()
app.addEventListener('compositionstart', event => {
  if (event.target instanceof HTMLTextAreaElement && event.target.closest('[data-draft]')) draftCompositions.add(event.target)
})
app.addEventListener('compositionend', event => { draftCompositions.delete(event.target) })
app.addEventListener('keydown', event => {
  const input = event.target
  if (!(input instanceof HTMLTextAreaElement) || !input.closest('[data-draft]')
    || event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229 || draftCompositions.has(input)) return
  event.preventDefault()
  if (!state.draft || state.draft.sending) return
  updateDraftText(input.value)
  void submitDraft()
})
app.addEventListener('beforeinput', event => {
  const input = event.target
  if (input instanceof HTMLTextAreaElement && input.closest('[data-draft]') && state.draft) {
    state.draft.pendingEdit = { start: input.selectionStart, end: input.selectionEnd }
  }
})
app.addEventListener('input', event => {
  const input = event.target
  if (input instanceof HTMLTextAreaElement && input.closest('[data-draft]') && state.draft !== null) {
    updateDraftText(input.value, state.draft.pendingEdit)
    delete state.draft.pendingEdit
    syncDraftHighlight(input)
  }
})
app.addEventListener('scroll', event => {
  if (event.target instanceof HTMLTextAreaElement && event.target.closest('[data-draft]')) syncDraftHighlight(event.target)
}, true)
app.addEventListener('submit', event => {
  const form = event.target
  if (!(form instanceof HTMLFormElement)) return
  if (form.dataset.renameThread) {
    event.preventDefault()
    const title = form.elements.title.value.trim()
    if (!title) return
    const id = form.dataset.renameThread
    void api(`/synapse/api/threads/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }).then(result => {
      const thread = state.workspace?.threads.find(item => item.id === id)
      if (thread) Object.assign(thread, result.thread)
      state.editCardId = null; render()
    }).catch(setError)
    return
  }
  if (form.matches('[data-draft]')) { event.preventDefault(); void submitDraft(); return }

})

window.addEventListener('message', event => {
  if (event.source !== window.parent || event.origin !== window.location.origin || event.data?.source !== 'dsh-synapse') return
  const data = event.data
  if (data.type === 'synapse:visibility') { window.__synapseVisible = data.active === true }
  if (data.type === 'synapse:map-opened') {
    // Do NOT reset the camera here: toggling dialog<->map for the same
    // session must keep the user's viewport. A fresh canvas (canvasView
    // not initialized) positions its own cards after mounting; a real session switch
    // re-centers in the current-session handler below.
    state.mode = 'canvas'
    render()
    window.requestAnimationFrame(() => post('synapse:map-ready'))
  }
  if (data.type === 'synapse:theme') {
    document.documentElement.dataset.theme = data.dark === true ? 'dark' : 'light'
  }
  if (data.type === 'synapse:workspaces') {
    state.dshWorkspaces = Array.isArray(data.workspaces) ? data.workspaces.filter(workspace => typeof workspace?.id === 'string' && typeof workspace.title === 'string' && Array.isArray(workspace.sessionIds)) : []
    const current = currentDshWorkspace()
    if (current !== undefined && current.id !== state.selectedDshWorkspaceId) void openDshWorkspace(current.id).catch(setError)
    else if (state.selectedDshWorkspaceId !== null) void openDshWorkspace(state.selectedDshWorkspaceId).catch(setError)
    else if (canReplaceView()) render()
  }
  if (data.type === 'synapse:current-session') {
    const previousId = state.currentDsh?.id
    state.currentDsh = data.session
    if (!data.session) {
      state.workspaceLoad++
      state.workspace = null; state.selectedDshWorkspaceId = null; state.activeId = null
      state.draft = null; state.inspectorCardId = null; state.selectedCardId = null; state.selectedRegionId = null
      state.menu = null; state.regionDialog = null; state.editCardId = null; state.deleteCardId = null
      resetCanvasCamera(); render()
      return
    }
    const preserveCanvasCamera = previousId !== data.session?.id && state.mapCardSessionSwitches.delete(data.session?.id)
    const thread = currentDshThread()
    if (thread !== undefined) {
      const preserveSelectedCard = state.activeId === thread.id
      state.activeId = thread.id
      if (!preserveSelectedCard) {
        state.selectedCardId = null
        state.inspectorCardId = null
        state.inspectorOpening = false
      }
      if (state.workspace !== null) revealConversationThread(conversationCards(state.workspace.threads), thread.id)
    }
    if (previousId !== data.session?.id) {
      // A real session switch: re-center on the new session's latest turn,
      // whether it lives in the same workspace (openCurrentWorkspace returns
      // false) or a different one (it resets the camera itself).
      void openCurrentWorkspace({ preserveCanvasCamera }).then(opened => {
        if (!opened && canReplaceView()) {
          render()
          if (previousId != null && !state.canvasNeedsFit) {
            if (!preserveCanvasCamera) focusActiveCard()
          }
        }
      }).catch(setError)
    }
    else if (canReplaceView()) render()
  }
  if (data.type === 'synapse:live-reply' && typeof data.sessionId === 'string') {
    const thread = state.workspace?.threads.find(item => item.dshSessionId === data.sessionId)
    if (thread !== undefined) {
      if (data.running === true) {
        state.liveReplies.set(data.sessionId, { running: true, text: typeof data.text === 'string' ? data.text : '' })
        // Streaming: patch the live card's answer in place instead of
        // rebuilding the whole canvas on every chunk; a full render reconciles
        // at stream end. The detail view is single-thread, so keep its cheap
        // throttled full render.
        if (state.mode === 'canvas') scheduleLiveCardUpdate(data.sessionId)
        else if (canReplaceView()) scheduleLiveRender()
      } else {
        state.liveReplies.delete(data.sessionId)
        if (canReplaceView() || state.pendingReplies.has(data.sessionId)) render()
      }
    }
  }
  if (data.type === 'synapse:api-result') settleRpc(data.requestId, data.value, data.error)
  if (data.type === 'synapse:forked-session' || data.type === 'synapse:created-session' || data.type === 'synapse:message-sent') settleRpc(data.requestId, data.session ?? data)
  if (data.type === 'synapse:bridge-error') { settleRpc(data.requestId, undefined, new Error(data.message)); if (data.requestId === undefined) setError(data.message) }
})

if (typeof ResizeObserver === 'function') {
  const canvasSizeObserver = new ResizeObserver(scheduleInitialCanvasFit)
  canvasSizeObserver.observe(app)
}
post('synapse:request-current')
refreshSummaries().catch(setError)
let polling = false
let liveRenderTimer = 0
let liveCardFrame = 0
let liveCardSessionId = null
function scheduleLiveCardUpdate(sessionId) {
  // Coalesce streaming chunks to one DOM patch per animation frame.
  liveCardSessionId = sessionId
  if (liveCardFrame !== 0) return
  liveCardFrame = window.requestAnimationFrame(() => {
    liveCardFrame = 0
    if (liveCardSessionId === null) return
    const id = liveCardSessionId
    liveCardSessionId = null
    applyLiveReplyToCard(id)
  })
}
function applyLiveReplyToCard(sessionId) {
  if (state.mode !== 'canvas') return
  // Never patch cards mid-gesture: the reflow would compete with the drag or
  // pan frame; the next live-reply chunk re-applies after the gesture ends.
  if (state.dragging || state.canvasGesture) return
  const thread = state.workspace?.threads.find(item => item.dshSessionId === sessionId)
  if (thread === undefined) return
  const live = state.liveReplies.get(sessionId)
  if (live?.running !== true) return
  const cards = app.querySelectorAll(`.thread-card[data-thread="${CSS.escape(thread.id)}"]`)
  const card = cards[cards.length - 1]
  if (!(card instanceof HTMLElement)) return
  const answer = card.querySelector('.thread-answer')
  if (!(answer instanceof HTMLElement)) return
  const text = live.text
  answer.innerHTML = text.trim() === ''
    ? mapThinkingIndicator()
    : `${renderMarkdown(text)}${mapThinkingIndicator()}`
}
function scheduleLiveRender() {
  if (liveRenderTimer !== 0 || !canReplaceView()) return
  liveRenderTimer = window.setTimeout(() => {
    liveRenderTimer = 0
    if (canReplaceView()) render()
  }, 120)
}
async function pollProjection() {
  if (polling || document.hidden || window.__synapseVisible === false || !canReplaceView()) return
  polling = true
  try {
    await refreshProjection()
  } finally { polling = false }
}
window.setInterval(() => { void pollProjection() }, 1_000)
