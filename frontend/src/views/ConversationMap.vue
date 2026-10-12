<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Bot, CircleHelp, Eye, EyeOff, GitBranch, Link2, Map, Maximize2, MessageSquarePlus, Minus, MoreHorizontal, Plus, Redo2, Search, Send, Sparkles, Trash2, Undo2, X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import PageShell from '@/components/PageShell.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import MapSelect from '@/components/MapSelect.vue'
import { chatApi } from '@/api'
import { conversationMapApi } from '@/api/conversationMap'
import { backendEnabled } from '@/api/http'
import { conversationActivityAt, formatConversationTime } from '@/lib/conversationTime'
import { summaryText } from '@/lib/conversationSummary'
import { SKILLS } from '@/skills'
import { useChatStore } from '@/stores/chat'
import { useConversationBoardStore } from '@/stores/conversationBoard'
import { useUiStore } from '@/stores/ui'

const router = useRouter()
const chat = useChatStore()
const conversationBoard = useConversationBoardStore()
const ui = useUiStore()
const canvas = ref(null)
const board = conversationBoard.board
const previews = ref({})
const ready = ref(false)
const saving = ref(false)
const search = ref('')
const filter = ref('all')
const selected = ref(null)
const linkSource = ref(null)
const linkSide = ref(null)
const linkPointer = ref(null)
const menu = ref(null)
const importKind = ref(null)
const importSearch = ref('')
const deleteCardTarget = ref(null)
const editor = ref(null)
const deleteGroupTarget = ref(null)
const pendingMembership = ref(null)
const pendingDetach = ref(null)
const pendingLink = ref(null)
const linking = ref(false)
const dialog = ref(null)
const creatingConversation = ref(false)
const drag = ref(null)
const digestBusy = ref(new Set())
const helpOpen = ref(false)
const summaryHover = ref(null)
const summaryPopover = ref(null)
const undoHistory = ref([])
const redoHistory = ref([])
let saveTimer = null
let digestStopped = false
let statusTimer = null
let summaryCloseTimer = null
let pendingSave = Promise.resolve()

const conversations = computed(() => chat.conversations.filter(item => {
  const node = board.nodes[item.id]
  if (node?.removed || node?.hidden || board.groups.some(group => group.id === node?.groupId && (group.hidden || group.removed))) return false
  const hasFeatureDomain = Boolean(previews.value[item.id]?.hasFeatureDomain || (item.taskId && item.taskId !== 'general'))
  if (filter.value === 'plain' && hasFeatureDomain) return false
  if (filter.value === 'feature' && !hasFeatureDomain) return false
  if (filter.value === 'useful' && item.messages < 2) return false
  if (filter.value === 'waiting' && statusOf(item) !== 'waiting') return false
  const query = search.value.trim().toLowerCase()
  return !query || `${item.title} ${node?.digest?.summary || ''} ${previews.value[item.id]?.summary || ''}`.toLowerCase().includes(query)
}))
const visibleIds = computed(() => new Set(conversations.value.map(item => item.id)))
const visibleGroups = computed(() => board.groups.filter(group => !group.hidden && !group.removed))
const hiddenCount = computed(() => {
  const hiddenGroups = new Set(board.groups.filter(group => group.hidden && !group.removed).map(group => group.id))
  const cards = Object.values(board.nodes).filter(node => !node.removed && (node.hidden || hiddenGroups.has(node.groupId))).length
  return { groups: hiddenGroups.size, cards, total: hiddenGroups.size + cards }
})
const edges = computed(() => board.edges.filter(edge => visibleIds.value.has(edge.source) && visibleIds.value.has(edge.target) && sameRegion(edge.source, edge.target)))
const selectedGroup = computed(() => board.groups.find(group => group.id === selected.value && !group.removed) || null)
const importOptions = computed(() => {
  const query = importSearch.value.trim().toLowerCase()
  if (importKind.value === 'group') return board.groups.filter(group => !query || group.title.toLowerCase().includes(query))
    .map(group => ({ id: group.id, title: group.title, disabled: !group.removed, note: group.removed ? '可恢复原有布局与卡片' : '已在画布中' }))
  return chat.conversations.filter(item => !query || item.title.toLowerCase().includes(query))
    .map(item => {
      const node = board.nodes[item.id]
      const missingGroup = board.groups.find(group => group.id === node?.groupId && group.removed)
      return { id: item.id, title: item.title, disabled: Boolean(node && !node.removed) || Boolean(missingGroup),
        note: missingGroup ? '请先导入所属工作区' : node && !node.removed ? '已在画布中' : '可恢复原有卡片与连线' }
    })
})
const groupColors = ['#7c3aed', '#a855f7', '#2563eb', '#0ea5e9', '#0d9488', '#16a34a', '#84cc16', '#d97706', '#ea580c', '#db2777']
const portLabels = { top: '顶部', right: '右侧', bottom: '底部', left: '左侧' }
const relationLabels = { related: '关联', digest: '摘要注入', full: '完整注入' }
const filterOptions = [
  { id: 'all', label: '全部会话', description: '显示所有会话卡片' },
  { id: 'plain', label: '纯对话', description: '未调用功能域的聊天' },
  { id: 'feature', label: '功能会话', description: '曾调用任一功能域' },
  { id: 'useful', label: '有内容', description: '已有问答内容' },
  { id: 'waiting', label: '等待回复', description: '等待继续处理的会话' },
]
const createSkills = [{ id: '', label: '直接对话', description: '不指定功能域' }, ...SKILLS.map(item => ({ id: item.id, label: item.label, description: item.description }))]
// DeepSeek V4.1 Flash uses "deepseek-flash" as its API model identifier.
const modelOptions = [{ id: 'deepseek-flash', label: 'deepseek-v4.1-flash' }]

function statusOf(item) {
  if (chat.generating && chat.activeId === item.id) return 'running'
  return previews.value[item.id]?.status || (item.messages ? 'done' : 'idle')
}

function statusText(item) { return { running: '正在运行', waiting: '等待回复' }[statusOf(item)] }
function summaryOf(item) { return summaryText(nodeOf(item.id).digest?.summary || previews.value[item.id]?.summary) || '等待添加会话内容' }
function cancelSummaryClose() { clearTimeout(summaryCloseTimer) }
function hideSummary() { cancelSummaryClose(); summaryHover.value = null }
function scheduleSummaryClose() { cancelSummaryClose(); summaryCloseTimer = setTimeout(() => { summaryHover.value = null }, 180) }
async function showSummary(event, item) {
  const source = event.currentTarget
  cancelSummaryClose()
  const card = source.closest('.map-card').getBoundingClientRect()
  const canvasRect = canvas.value?.getBoundingClientRect()
  const limits = { left: Math.max(16, (canvasRect?.left || 0) + 12), right: Math.min(window.innerWidth - 16, (canvasRect?.right || window.innerWidth) - 12),
    top: Math.max(16, (canvasRect?.top || 0) + 12), bottom: Math.min(window.innerHeight - 16, (canvasRect?.bottom || window.innerHeight) - 12) }
  const width = Math.min(300, limits.right - limits.left)
  const left = Math.max(limits.left, Math.min(card.right + 14, limits.right - width))
  summaryHover.value = { id: item.id, text: summaryOf(item), left, top: Math.max(limits.top, card.top), width,
    maxHeight: Math.min(500, limits.bottom - limits.top), offset: false }
  await nextTick()
  if (summaryHover.value?.id === item.id && summaryPopover.value) {
    const height = summaryPopover.value.offsetHeight
    const overlapsCard = left < card.right + 8
    const below = card.bottom + 12
    const above = card.top - height - 12
    const preferredTop = overlapsCard && below + height <= limits.bottom ? below
      : overlapsCard && above >= limits.top ? above : card.top
    summaryHover.value.top = Math.max(limits.top, Math.min(preferredTop, limits.bottom - height))
    summaryHover.value.offset = Math.abs(summaryHover.value.top - card.top) > 12
  }
}

function nodeOf(id) { return board.nodes[id] || { x: 0, y: 0, digest: {} } }
function regionId(id) { return board.nodes[id]?.groupId || null }
function sameRegion(sourceId, targetId) { return regionId(sourceId) === regionId(targetId) }
function groupAt(point) {
  return [...board.groups].filter(group => !group.hidden && !group.removed && point.x >= group.x && point.x <= group.x + group.width && point.y >= group.y && point.y <= group.y + group.height)
    .sort((a, b) => a.width * a.height - b.width * b.height)[0] || null
}
function groupForNode(node) {
  return groupAt({ x: node.x + 140, y: node.y + 87 })
}
function expandGroupForNode(group, id) {
  const node = board.nodes[id]
  if (!group || !node) return
  const { width, height } = cardSize(id)
  const left = Math.min(group.x, node.x - 24)
  const top = Math.min(group.y, node.y - 52)
  const right = Math.max(group.x + group.width, node.x + width + 24)
  const bottom = Math.max(group.y + group.height, node.y + height + 24)
  group.x = left; group.y = top
  group.width = right - left; group.height = bottom - top
}
function fitGroupToCards(group) {
  if (!group) return
  const members = Object.entries(board.nodes).filter(([id, node]) => node.groupId === group.id && !node.removed && chat.conversations.some(item => item.id === id))
  if (!members.length) return
  const left = Math.min(...members.map(([, node]) => node.x - 24))
  const top = Math.min(...members.map(([, node]) => node.y - 52))
  const right = Math.max(...members.map(([id, node]) => node.x + cardSize(id).width + 24))
  const bottom = Math.max(...members.map(([id, node]) => node.y + cardSize(id).height + 24))
  group.x = left
  group.y = top
  group.width = Math.max(310, right - left)
  group.height = Math.max(240, bottom - top)
}
function centerWorld() {
  const rect = canvas.value?.getBoundingClientRect()
  return rect ? { x: (rect.width / 2 - board.viewport.x) / board.viewport.zoom, y: (rect.height / 2 - board.viewport.y) / board.viewport.zoom } : { x: 500, y: 300 }
}
function worldAt(clientX, clientY) {
  const rect = canvas.value.getBoundingClientRect()
  return { x: (clientX - rect.left - board.viewport.x) / board.viewport.zoom,
    y: (clientY - rect.top - board.viewport.y) / board.viewport.zoom }
}
function snapshot() { return { nodes: board.nodes, groups: board.groups, edges: board.edges, viewport: board.viewport } }
function cloneState() { return JSON.parse(JSON.stringify(snapshot())) }
function remember() {
  undoHistory.value.push(cloneState())
  if (undoHistory.value.length > 50) undoHistory.value.shift()
  redoHistory.value = []
}
function undo() {
  if (!undoHistory.value.length) return
  redoHistory.value.push(cloneState())
  Object.assign(board, undoHistory.value.pop())
  scheduleSave()
}
function redo() {
  if (!redoHistory.value.length) return
  undoHistory.value.push(cloneState())
  Object.assign(board, redoHistory.value.pop())
  scheduleSave()
}
function persist() {
  pendingSave = pendingSave.catch(() => {}).then(async () => {
    saving.value = true
    try { await conversationBoard.save(); return true }
    catch (error) { ui.toast(error.message || '会话地图保存失败', 'error'); return false }
    finally { saving.value = false }
  })
  return pendingSave
}
function scheduleSave() {
  if (!ready.value) return
  clearTimeout(saveTimer)
  saveTimer = setTimeout(persist, 500)
}
function ensureNodes() {
  let index = Object.keys(board.nodes).length
  let changed = false
  for (const item of chat.conversations) {
    if (board.nodes[item.id]) continue
    const col = index % 4
    const row = Math.floor(index / 4)
    board.nodes[item.id] = { x: 80 + col * 310, y: 110 + row * 220, digest: {}, hidden: false, groupId: null }
    index++
    changed = true
  }
  const ids = new Set(chat.conversations.map(item => item.id))
  for (const id of Object.keys(board.nodes)) if (!ids.has(id)) { delete board.nodes[id]; changed = true }
  for (const group of board.groups) {
    if (group.title === '新区域') { group.title = '新工作区'; changed = true }
  }
  for (const node of Object.values(board.nodes)) {
    if (!Object.hasOwn(node, 'groupId') || (node.groupId && !board.groups.some(group => group.id === node.groupId))) {
      node.groupId = groupForNode(node)?.id || null
      changed = true
    }
  }
  board.edges = board.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target))
  return changed
}
async function loadBoard() {
  try {
    await chat.loadConversations()
    const response = await conversationBoard.load()
    board.nodes ||= {}
    board.groups ||= []
    board.edges ||= []
    board.viewport ||= { x: 0, y: 0, zoom: 1 }
    previews.value = response.previews || {}
    const changed = ensureNodes()
    ready.value = true
    if (changed) scheduleSave()
    statusTimer = setInterval(async () => {
      try { previews.value = (await conversationMapApi.load()).previews || previews.value }
      catch { /* 临时网络故障不影响画布 */ }
    }, 5000)
    // 摘要逐条生成，避免个人本地模型被大量会话同时占满。
    for (const item of chat.conversations) {
      if (digestStopped) break
      if (item.messages && (!board.nodes[item.id]?.digest?.summary || board.nodes[item.id]?.digestSourceUpdatedAt !== item.updatedAt)) await refreshDigest(item.id, true)
    }
  } catch (error) { ui.toast(error.message || '会话地图加载失败', 'error') }
}
async function refreshDigest(id, quiet = false) {
  if (digestBusy.value.has(id) || !board.nodes[id]) return
  digestBusy.value = new Set([...digestBusy.value, id])
  try {
    const digest = await conversationMapApi.digest(id)
    if (digestStopped || !board.nodes[id]) return
    board.nodes[id].digest = digest
    board.nodes[id].digestSourceUpdatedAt = chat.conversations.find(item => item.id === id)?.updatedAt || null
    scheduleSave()
    if (!quiet) ui.toast('会话摘要已更新')
  } catch (error) { if (!quiet) ui.toast(error.message || '摘要生成失败', 'error') }
  finally { digestBusy.value = new Set([...digestBusy.value].filter(value => value !== id)) }
}

function onCanvasPointerDown(event) {
  if (event.button !== 0 || event.target.closest('button,input,select,textarea,.map-card,.map-group,.map-toolbar,.map-context-menu,.map-zoom,.map-footnote,.map-help,.map-link-hint')) return
  hideSummary()
  menu.value = null
  selected.value = null
  drag.value = { kind: 'pan', startX: event.clientX, startY: event.clientY,
    x: board.viewport.x, y: board.viewport.y }
  canvas.value.setPointerCapture(event.pointerId)
}
function startNodeDrag(event, id) {
  if (event.button !== 0 || event.target.closest('button')) return
  hideSummary()
  event.stopPropagation()
  selected.value = id
  event.currentTarget.focus({ preventScroll: true })
  menu.value = null
  remember()
  const node = nodeOf(id)
  drag.value = { kind: 'node', id, startX: event.clientX, startY: event.clientY, x: node.x, y: node.y, groupId: regionId(id) }
  event.currentTarget.setPointerCapture(event.pointerId)
}
function startLinkDrag(event, id, side) {
  if (event.button !== 0) return
  event.stopPropagation()
  linkSource.value = id
  linkSide.value = side
  linkPointer.value = worldAt(event.clientX, event.clientY)
  drag.value = { kind: 'link', id, side, startX: event.clientX, startY: event.clientY }
  canvas.value.setPointerCapture(event.pointerId)
}
function startGroupDrag(event, group) {
  if (event.button !== 0 || event.target.closest('button')) return
  event.stopPropagation()
  selected.value = group.id
  event.currentTarget.focus({ preventScroll: true })
  remember()
  const inside = Object.entries(board.nodes).filter(([id]) => regionId(id) === group.id)
  drag.value = { kind: 'group', id: group.id, startX: event.clientX, startY: event.clientY,
    x: group.x, y: group.y, inside: inside.map(([id, node]) => ({ id, x: node.x, y: node.y })) }
  event.currentTarget.setPointerCapture(event.pointerId)
}
function onPointerMove(event) {
  if (!drag.value) return
  const deltaX = event.clientX - drag.value.startX
  const deltaY = event.clientY - drag.value.startY
  if (drag.value.kind === 'pan') {
    board.viewport.x = drag.value.x + deltaX
    board.viewport.y = drag.value.y + deltaY
  } else if (drag.value.kind === 'node') {
    const node = board.nodes[drag.value.id]
    if (node) {
      node.x = Math.round((drag.value.x + deltaX / board.viewport.zoom) / 16) * 16
      node.y = Math.round((drag.value.y + deltaY / board.viewport.zoom) / 16) * 16
      if (node.groupId) expandGroupForNode(board.groups.find(group => group.id === node.groupId), drag.value.id)
    }
  } else if (drag.value.kind === 'group') {
    const group = board.groups.find(item => item.id === drag.value.id)
    if (group) {
      group.x = Math.round((drag.value.x + deltaX / board.viewport.zoom) / 16) * 16
      group.y = Math.round((drag.value.y + deltaY / board.viewport.zoom) / 16) * 16
      for (const item of drag.value.inside) {
        if (board.nodes[item.id]) {
          board.nodes[item.id].x = item.x + group.x - drag.value.x
          board.nodes[item.id].y = item.y + group.y - drag.value.y
        }
      }
    }
  } else if (drag.value.kind === 'resize') {
    const group = board.groups.find(item => item.id === drag.value.id)
    if (group) { group.width = Math.max(310, Math.round((drag.value.width + deltaX / board.viewport.zoom) / 16) * 16); group.height = Math.max(240, Math.round((drag.value.height + deltaY / board.viewport.zoom) / 16) * 16) }
  } else if (drag.value.kind === 'link') {
    linkPointer.value = worldAt(event.clientX, event.clientY)
  }
}
function endDrag(event) {
  if (!drag.value) return
  let needsMembershipConfirmation = false
  if (drag.value.kind === 'node' && drag.value.groupId) {
    fitGroupToCards(board.groups.find(group => group.id === drag.value.groupId))
  }
  if (drag.value.kind === 'node' && !drag.value.groupId) {
    const node = board.nodes[drag.value.id]
    const group = node && groupForNode(node)
    if (group) {
      pendingMembership.value = { id: drag.value.id, groupId: group.id, x: drag.value.x, y: drag.value.y }
      needsMembershipConfirmation = true
    }
  }
  if (drag.value.kind === 'resize') {
    const group = board.groups.find(item => item.id === drag.value.id)
    if (group) for (const id of Object.keys(board.nodes)) if (regionId(id) === group.id) expandGroupForNode(group, id)
  }
  if (drag.value.kind === 'link') {
    const current = drag.value
    const distance = Math.hypot(event.clientX - current.startX, event.clientY - current.startY)
    if (current.cancelled) { linkSource.value = null; linkSide.value = null; linkPointer.value = null }
    else if (distance > 10) {
      const hit = document.elementFromPoint(event.clientX, event.clientY)
      const targetId = hit?.closest('.map-card')?.dataset.conversationId
      if (targetId && targetId !== current.id) clickCard(targetId, hit.closest('.map-card-port')?.dataset.side || nearestSide(targetId, worldAt(event.clientX, event.clientY)))
      else if (!targetId) { linkSource.value = null; linkSide.value = null; newAt(worldAt(event.clientX, event.clientY), current.id, current.side) }
      else { linkSource.value = null; linkSide.value = null }
      linkPointer.value = null
    } else linkPointer.value = null
  }
  drag.value = null
  if (canvas.value?.hasPointerCapture(event.pointerId)) canvas.value.releasePointerCapture(event.pointerId)
  if (!needsMembershipConfirmation) scheduleSave()
}
function wheel(event) {
  event.preventDefault()
  hideSummary()
  const rect = canvas.value.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  const old = board.viewport.zoom
  const next = Math.max(.35, Math.min(2, old * (event.deltaY < 0 ? 1.1 : .9)))
  board.viewport.x = x - (x - board.viewport.x) * next / old
  board.viewport.y = y - (y - board.viewport.y) * next / old
  board.viewport.zoom = next
  scheduleSave()
}
function zoomBy(factor) {
  const rect = canvas.value.getBoundingClientRect()
  const old = board.viewport.zoom
  const next = Math.max(.35, Math.min(2, old * factor))
  board.viewport.x = rect.width / 2 - (rect.width / 2 - board.viewport.x) * next / old
  board.viewport.y = rect.height / 2 - (rect.height / 2 - board.viewport.y) * next / old
  board.viewport.zoom = next
  scheduleSave()
}
function fitBoard() {
  const entries = [
    ...conversations.value.map(item => ({ ...nodeOf(item.id), width: 280, height: cardSize(item.id).height })),
    ...visibleGroups.value.map(group => ({ x: group.x, y: group.y, width: group.width, height: group.height })),
  ]
  if (!entries.length) { board.viewport = { x: 0, y: 0, zoom: 1 }; scheduleSave(); return }
  const minX = Math.min(...entries.map(node => node.x)) - 80
  const minY = Math.min(...entries.map(node => node.y)) - 70
  const maxX = Math.max(...entries.map(node => node.x + node.width)) + 80
  const maxY = Math.max(...entries.map(node => node.y + node.height)) + 70
  const rect = canvas.value.getBoundingClientRect()
  const zoom = Math.max(.35, Math.min(1, Math.min(rect.width / (maxX - minX), rect.height / (maxY - minY))))
  board.viewport = { zoom, x: (rect.width - (maxX - minX) * zoom) / 2 - minX * zoom,
    y: (rect.height - (maxY - minY) * zoom) / 2 - minY * zoom }
  scheduleSave()
}
function newAt(point = centerWorld(), sourceId = null, sourcePort = null) {
  menu.value = null
  dialog.value = { sourceId, sourcePort, point, title: sourceId ? `继续：${chat.conversations.find(item => item.id === sourceId)?.title || '会话'}`.slice(0, 80) : '新会话', mode: sourceId ? 'digest' : 'none', skill: '', model: modelOptions[0].id, prompt: '', context: '', previewBusy: false, previewError: false }
  if (sourceId) refreshBranchPreview()
}
function onPromptKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    createConversation()
  }
}
async function refreshBranchPreview() {
  const data = dialog.value
  if (!data?.sourceId || data.mode === 'none') { if (data) { data.context = ''; data.previewError = false; data.previewBusy = false } return }
  const mode = data.mode
  data.previewBusy = true
  data.previewError = false
  try {
    const result = await conversationMapApi.branchPreview(data.sourceId, mode)
    if (dialog.value === data && data.mode === mode) data.context = result.context || ''
  } catch (error) { if (dialog.value === data && data.mode === mode) data.previewError = true; ui.toast(error.message || '继承内容预览失败', 'error') }
  finally { if (dialog.value === data && data.mode === mode) data.previewBusy = false }
}
async function createConversation() {
  const data = dialog.value
  if (!data || creatingConversation.value || data.previewBusy || data.previewError) return
  const title = data.title.trim()
  const prompt = data.prompt.trim()
  if (!title) { ui.toast('请输入会话标题', 'error'); return }
  if (!prompt) { ui.toast('请输入要发送的提示词', 'error'); return }
  creatingConversation.value = true
  try {
    const item = data.sourceId && backendEnabled
      ? await conversationMapApi.branch({ sourceId: data.sourceId, mode: data.mode, title, taskId: data.skill || 'general', context: data.context })
      : await chatApi.create({ title, taskId: data.skill || 'general' })
    chat.conversations.unshift(item)
    const point = data.point || centerWorld()
    board.nodes[item.id] = { x: Math.round(point.x / 16) * 16, y: Math.round(point.y / 16) * 16, digest: {}, hidden: false,
      groupId: data.sourceId ? regionId(data.sourceId) : null }
    if (!data.sourceId) board.nodes[item.id].groupId = groupForNode(board.nodes[item.id])?.id || null
    if (board.nodes[item.id].groupId) expandGroupForNode(board.groups.find(group => group.id === board.nodes[item.id].groupId), item.id)
    previews.value[item.id] = { summary: '新会话，尚无内容', nextStep: '', status: 'idle', hasFeatureDomain: Boolean(data.skill) }
    if (data.sourceId) board.edges.push({ id: crypto.randomUUID(), source: data.sourceId, target: item.id,
      ...choosePorts(data.sourceId, item.id, data.sourcePort), relation: data.mode === 'none' ? 'related' : data.mode,
      label: relationLabels[data.mode === 'none' ? 'related' : data.mode] })
    undoHistory.value = []
    redoHistory.value = []
    dialog.value = null
    scheduleSave()
    chat.queueMapMessage(item.id, prompt, data.skill)
    await router.push({ path: '/', query: { conversationId: item.id, ...(data.skill ? { skill: data.skill } : {}) } })
  } catch (error) { ui.toast(error.message || '会话创建失败', 'error') }
  finally { creatingConversation.value = false }
}
async function openConversation(id) {
  if (linkSource.value || pendingLink.value) return
  await chat.loadMessages(id)
  router.push({ path: '/', query: { conversationId: id } })
}
function openMenu(event, id = null) {
  event.preventDefault()
  event.stopPropagation()
  hideSummary()
  const point = worldAt(event.clientX, event.clientY)
  menu.value = { id, point, x: Math.max(8, Math.min(event.clientX, window.innerWidth - 220)), y: Math.max(8, Math.min(event.clientY, window.innerHeight - (id ? 330 : 260))) }
  selected.value = id
}
function openGroupMenu(event, id) {
  event.preventDefault()
  event.stopPropagation()
  menu.value = { kind: 'group', id, x: Math.min(event.clientX, window.innerWidth - 220), y: Math.min(event.clientY, window.innerHeight - 240) }
  selected.value = id
}
function addGroup(point = centerWorld()) {
  menu.value = null
  editor.value = { kind: 'group-create', value: '新工作区', point, color: groupColors[board.groups.length % groupColors.length] }
}
function setMapColor(kind, id, color) {
  if (!groupColors.includes(color)) return
  const item = kind === 'group' ? board.groups.find(group => group.id === id) : board.nodes[id]
  if (!item || item.color === color) return
  remember()
  item.color = color
  scheduleSave()
}
function editTitle(kind, id) {
  menu.value = null
  const item = kind === 'group' ? board.groups.find(group => group.id === id)
    : chat.conversations.find(conversation => conversation.id === id)
  editor.value = { kind, id, value: item?.title || '', color: item?.color }
}
async function saveTitle() {
  if (!editor.value?.value.trim()) return
  const { kind, id, value } = editor.value
  if (kind === 'group-create') {
    remember()
    const point = editor.value.point
    await conversationBoard.createWorkspace(value.trim(), { x: Math.round(point.x / 16) * 16, y: Math.round(point.y / 16) * 16, color: editor.value.color })
    scheduleSave()
  } else if (kind === 'group') {
    remember()
    const group = board.groups.find(item => item.id === id)
    if (group) { group.title = value.trim(); group.color = editor.value.color || group.color }
    scheduleSave()
  } else await chat.rename(id, value.trim())
  editor.value = null
}
function removeGroup(id) {
  const group = board.groups.find(item => item.id === id)
  if (!group) return
  remember()
  group.removed = true
  selected.value = null
  scheduleSave()
}
function confirmDeleteGroup() {
  if (deleteGroupTarget.value) removeGroup(deleteGroupTarget.value)
  deleteGroupTarget.value = null
}
function removeCardFromMap() {
  const node = board.nodes[deleteCardTarget.value]
  if (node) {
    remember()
    node.removed = true
    selected.value = null
    scheduleSave()
  }
  deleteCardTarget.value = null
}
function openImport(kind) {
  menu.value = null
  importSearch.value = ''
  importKind.value = kind
}
function importItem(id) {
  const option = importOptions.value.find(item => item.id === id)
  if (!option || option.disabled) return
  remember()
  if (importKind.value === 'group') {
    const group = board.groups.find(item => item.id === id)
    group.removed = false
    group.hidden = false
  } else {
    const node = conversationBoard.ensureNode(id)
    node.removed = false
    node.hidden = false
    if (node.groupId) expandGroupForNode(board.groups.find(group => group.id === node.groupId), id)
  }
  selected.value = id
  importKind.value = null
  scheduleSave()
}
function hideCard(id) { remember(); board.nodes[id].hidden = true; board.edges = board.edges.filter(edge => edge.source !== id && edge.target !== id); selected.value = null; menu.value = null; scheduleSave() }
function hideGroup(id) {
  const group = board.groups.find(item => item.id === id)
  if (!group) return
  remember(); group.hidden = true; selected.value = null; menu.value = null; scheduleSave()
}
function restoreCards() {
  if (!hiddenCount.value.total) return
  remember()
  Object.values(board.nodes).forEach(node => { node.hidden = false })
  board.groups.forEach(group => { group.hidden = false })
  scheduleSave()
}
function cancelMembership() {
  const pending = pendingMembership.value
  if (pending && board.nodes[pending.id]) Object.assign(board.nodes[pending.id], { x: pending.x, y: pending.y })
  pendingMembership.value = null
  scheduleSave()
}
function confirmMembership() {
  const pending = pendingMembership.value
  const node = pending && board.nodes[pending.id]
  const group = pending && board.groups.find(item => item.id === pending.groupId)
  if (node && group) { node.groupId = group.id; fitGroupToCards(group); scheduleSave() }
  pendingMembership.value = null
}
function confirmDetach() {
  const id = pendingDetach.value
  const node = board.nodes[id]
  const group = board.groups.find(item => item.id === node?.groupId)
  if (node && group) {
    remember()
    const { width, height } = cardSize(id)
    const center = { x: node.x + width / 2, y: node.y + height / 2 }
    const distances = [
      ['left', center.x - group.x], ['right', group.x + group.width - center.x],
      ['top', center.y - group.y], ['bottom', group.y + group.height - center.y],
    ].sort((a, b) => a[1] - b[1])
    const side = distances[0][0]
    if (side === 'left') node.x = group.x - width - 24
    if (side === 'right') node.x = group.x + group.width + 24
    if (side === 'top') node.y = group.y - height - 24
    if (side === 'bottom') node.y = group.y + group.height + 24
    for (let attempt = 0; attempt < board.groups.length + 1; attempt++) {
      const collision = board.groups.find(item => node.x < item.x + item.width && node.x + width > item.x && node.y < item.y + item.height && node.y + height > item.y)
      if (!collision) break
      if (side === 'left') node.x = collision.x - width - 24
      if (side === 'right') node.x = collision.x + collision.width + 24
      if (side === 'top') node.y = collision.y - height - 24
      if (side === 'bottom') node.y = collision.y + collision.height + 24
    }
    node.groupId = null
    fitGroupToCards(group)
    scheduleSave()
  }
  pendingDetach.value = null
}
function startLink(id) { linkSource.value = id; linkSide.value = null; menu.value = null; ui.toast('点击目标卡片，建立会话联系') }
function cardSize(id) {
  const card = document.querySelector(`.map-card[data-conversation-id="${CSS.escape(id)}"]`)
  return { width: card?.offsetWidth || 280, height: card?.offsetHeight || 148 }
}
function portPoint(id, side) {
  const node = nodeOf(id)
  const { width, height } = cardSize(id)
  if (side === 'top') return { x: node.x + width / 2, y: node.y }
  if (side === 'bottom') return { x: node.x + width / 2, y: node.y + height }
  if (side === 'left') return { x: node.x, y: node.y + height / 2 }
  return { x: node.x + width, y: node.y + height / 2 }
}
function nearestSide(id, point) {
  return ['top', 'right', 'bottom', 'left'].reduce((best, side) => {
    const anchor = portPoint(id, side)
    const distance = (anchor.x - point.x) ** 2 + (anchor.y - point.y) ** 2
    return distance < best.distance ? { side, distance } : best
  }, { side: 'left', distance: Infinity }).side
}
function autoSide(sourceId, targetId) {
  const source = nodeOf(sourceId)
  const target = nodeOf(targetId)
  const sourceSize = cardSize(sourceId)
  const targetSize = cardSize(targetId)
  const dx = target.x + targetSize.width / 2 - source.x - sourceSize.width / 2
  const dy = target.y + targetSize.height / 2 - source.y - sourceSize.height / 2
  return Math.abs(dx) / sourceSize.width >= Math.abs(dy) / sourceSize.height
    ? (dx >= 0 ? 'right' : 'left') : (dy >= 0 ? 'bottom' : 'top')
}
function edgeRelation(edge) {
  if (edge.relation === 'digest' || edge.relation === 'full' || edge.relation === 'related') return edge.relation
  if (edge.label?.includes('摘要')) return 'digest'
  if (edge.label?.includes('完整')) return 'full'
  return 'related'
}
function edgeLabel(edge) { return relationLabels[edgeRelation(edge)] }
function edgeBadgeWidth(edge) { return edgeRelation(edge) === 'related' ? 44 : 68 }
function portUsage(id, side) {
  return board.edges.reduce((count, edge) => {
    const sourcePort = edge.sourcePort || autoSide(edge.source, edge.target)
    const targetPort = edge.targetPort || nearestSide(edge.target, portPoint(edge.source, sourcePort))
    return count + Number(edge.source === id && sourcePort === side) + Number(edge.target === id && targetPort === side)
  }, 0)
}
function choosePorts(sourceId, targetId, preferredSource = null, preferredTarget = null) {
  const sides = ['top', 'right', 'bottom', 'left']
  const candidates = []
  for (const sourcePort of (preferredSource ? [preferredSource] : sides)) {
    for (const targetPort of (preferredTarget ? [preferredTarget] : sides)) {
      const source = portPoint(sourceId, sourcePort)
      const target = portPoint(targetId, targetPort)
      candidates.push({ sourcePort, targetPort,
        used: portUsage(sourceId, sourcePort) + portUsage(targetId, targetPort),
        distance: Math.hypot(target.x - source.x, target.y - source.y) })
    }
  }
  candidates.sort((a, b) => a.used - b.used || a.distance - b.distance)
  return { sourcePort: candidates[0].sourcePort, targetPort: candidates[0].targetPort }
}
function clickCard(id, targetSide = null) {
  if (!linkSource.value) { selected.value = id; return }
  if (linkSource.value === id) { linkSource.value = null; linkSide.value = null; return }
  if (!sameRegion(linkSource.value, id)) {
    ui.toast('不同工作区的会话无法建立联系，请先将卡片归入同一工作区', 'error')
  } else {
    pendingLink.value = { source: linkSource.value, target: id, ...choosePorts(linkSource.value, id, linkSide.value, targetSide) }
  }
  linkSource.value = null
  linkSide.value = null
}
async function applyLink(relation) {
  const data = pendingLink.value
  if (!data || linking.value) return
  if (!sameRegion(data.source, data.target)) { pendingLink.value = null; return }
  const duplicate = board.edges.some(edge => edgeRelation(edge) === relation &&
    (relation === 'related'
      ? (edge.source === data.source && edge.target === data.target) || (edge.source === data.target && edge.target === data.source)
      : edge.source === data.source && edge.target === data.target))
  if (duplicate) { ui.toast('这两个会话已有相同关系'); pendingLink.value = null; return }
  linking.value = true
  try {
    if (relation !== 'related') {
      if (!(await persist())) throw new Error('会话地图尚未保存，无法注入会话内容')
      await conversationMapApi.inject({ sourceId: data.source, targetId: data.target, mode: relation })
    }
    remember()
    board.edges.push({ id: crypto.randomUUID(), ...data, relation, label: relationLabels[relation] })
    pendingLink.value = null
    scheduleSave()
  } catch (error) { ui.toast(error.message || '建立会话关系失败', 'error') }
  finally { linking.value = false }
}
function removeEdge(id) {
  const edge = board.edges.find(item => item.id === id)
  if (!edge) return
  remember()
  board.edges = board.edges.filter(item => item.id !== id)
  if (edgeRelation(edge) !== 'related') ui.toast('连线已移除；已注入目标会话的上下文仍会保留')
  scheduleSave()
}
function edgeGeometry(edge) {
  const sourceSide = edge.sourcePort || autoSide(edge.source, edge.target)
  const start = portPoint(edge.source, sourceSide)
  const targetSide = edge.targetPort || nearestSide(edge.target, start)
  const end = portPoint(edge.target, targetSide)
  const directions = { top: [0, -1], right: [1, 0], bottom: [0, 1], left: [-1, 0] }
  const bend = Math.max(48, Math.min(180, Math.hypot(end.x - start.x, end.y - start.y) * .42))
  const [sx, sy] = directions[sourceSide]
  const [tx, ty] = directions[targetSide]
  const control1 = { x: start.x + sx * bend, y: start.y + sy * bend }
  const control2 = { x: end.x + tx * bend, y: end.y + ty * bend }
  return { path: `M ${start.x} ${start.y} C ${control1.x} ${control1.y}, ${control2.x} ${control2.y}, ${end.x} ${end.y}`,
    labelX: (start.x + 3 * control1.x + 3 * control2.x + end.x) / 8,
    labelY: (start.y + 3 * control1.y + 3 * control2.y + end.y) / 8 }
}
function closeHelpOnOutside(event) {
  if (helpOpen.value && !event.target.closest('.map-help,.map-help-trigger')) helpOpen.value = false
}
function keydown(event) {
  if (event.isComposing) return
  const editing = event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])')
  if ((event.ctrlKey || event.metaKey) && event.code === 'KeyZ' && !editing) {
    event.preventDefault()
    if (event.shiftKey) redo()
    else undo()
    return
  }
  if (event.key === 'Escape') { if (drag.value?.kind === 'link') drag.value.cancelled = true; menu.value = null; linkSource.value = null; linkSide.value = null; linkPointer.value = null; dialog.value = null; editor.value = null; importKind.value = null; helpOpen.value = false; deleteGroupTarget.value = null; deleteCardTarget.value = null }
  if (event.key !== 'Backspace' || event.repeat || editing) return
  if (dialog.value || editor.value || importKind.value || deleteGroupTarget.value || deleteCardTarget.value || pendingMembership.value || pendingDetach.value || pendingLink.value) return
  if (selected.value && board.edges.some(edge => edge.id === selected.value)) { event.preventDefault(); removeEdge(selected.value) }
  else if (visibleGroups.value.some(group => group.id === selected.value)) { event.preventDefault(); hideSummary(); menu.value = null; deleteGroupTarget.value = selected.value }
  else if (conversations.value.some(item => item.id === selected.value)) { event.preventDefault(); hideSummary(); menu.value = null; deleteCardTarget.value = selected.value }
}
onMounted(() => { window.addEventListener('keydown', keydown); document.addEventListener('pointerdown', closeHelpOnOutside, true); loadBoard() })
watch(() => chat.conversations.map(item => item.id).join('|'), () => {
  if (!ready.value) return
  if (ensureNodes()) {
    undoHistory.value = []
    redoHistory.value = []
    scheduleSave()
  }
})
onBeforeUnmount(() => {
  digestStopped = true
  hideSummary()
  clearTimeout(saveTimer)
  clearInterval(statusTimer)
  const pending = pendingMembership.value
  if (pending && board.nodes[pending.id]) Object.assign(board.nodes[pending.id], { x: pending.x, y: pending.y })
  if (ready.value) persist()
  window.removeEventListener('keydown', keydown)
  document.removeEventListener('pointerdown', closeHelpOnOutside, true)
})
</script>

<template>
  <PageShell title="会话地图" immersive>
    <section class="conversation-map-page">
      <header class="map-toolbar">
        <div class="map-heading"><span class="map-logo"><Map :size="21" /></span><div><strong>会话地图</strong><small>整理对话、连接思路、继续工作</small></div></div>
        <div class="map-search"><Search :size="17" /><input v-model="search" placeholder="搜索标题或摘要" aria-label="搜索会话" /></div>
        <MapSelect v-model="filter" class="map-filter" :options="filterOptions" label="筛选会话" />
        <button type="button" class="map-tool map-region-tool" title="创建工作区" @click="addGroup()"><Plus :size="16" />新建工作区</button>
        <button type="button" class="map-tool map-icon-tool map-restore-tool" :class="{ 'has-hidden': hiddenCount.total }"
          :aria-disabled="!hiddenCount.total" :aria-label="hiddenCount.total ? `恢复隐藏内容：${hiddenCount.groups} 个工作区、${hiddenCount.cards} 张卡片` : '没有隐藏的工作区或卡片'"
          :data-app-tooltip="hiddenCount.total ? `恢复隐藏内容 · ${hiddenCount.groups} 个工作区、${hiddenCount.cards} 张卡片` : '没有隐藏的工作区或卡片'"
          @click="restoreCards"><Eye :size="18" /><span v-if="hiddenCount.total" class="map-restore-count">{{ hiddenCount.total > 9 ? '9+' : hiddenCount.total }}</span></button>
        <button type="button" class="map-tool map-icon-tool" title="撤销（Ctrl+Z）" :disabled="!undoHistory.length" @click="undo"><Undo2 :size="16" /></button>
        <button type="button" class="map-tool map-icon-tool" title="重做（Ctrl+Shift+Z）" :disabled="!redoHistory.length" @click="redo"><Redo2 :size="16" /></button>
        <button type="button" class="map-tool primary" @click="newAt()"><MessageSquarePlus :size="17" />新建会话</button>
        <button type="button" class="map-tool map-back" title="返回上一页面" aria-label="返回上一页面" @click="router.push(ui.conversationMapReturnPath)"><ArrowLeft :size="17" /><span>返回</span></button>
      </header>

      <div ref="canvas" class="map-canvas" :class="{ 'is-panning': drag?.kind === 'pan', 'is-linking': !!linkSource }" @pointerdown="onCanvasPointerDown" @pointermove="onPointerMove" @pointerup="endDrag" @pointercancel="endDrag" @wheel="wheel" @contextmenu="openMenu($event)">
        <div v-if="!ready" class="map-empty">正在加载会话地图…</div>
        <div v-else-if="!chat.conversations.length" class="map-empty"><Map :size="42" /><strong>地图还是空的</strong><span>右键画布，新建第一条会话。</span></div>
        <div class="map-world" :style="{ transform: `translate(${board.viewport.x}px, ${board.viewport.y}px) scale(${board.viewport.zoom})` }">
          <div v-for="group in visibleGroups" :key="group.id" class="map-group" tabindex="0" @focus="selected = group.id" :class="{ selected: selected === group.id }" :style="{ left: `${group.x}px`, top: `${group.y}px`, width: `${group.width}px`, height: `${group.height}px`, '--group-color': group.color }" @pointerdown="startGroupDrag($event, group)" @contextmenu.stop.prevent="openGroupMenu($event, group.id)">
            <div class="map-group-title"><span class="map-group-dot" />{{ group.title }}<button type="button" title="工作区操作" @click.stop="openGroupMenu($event, group.id)"><MoreHorizontal :size="16" /></button><button type="button" title="删除工作区" @click.stop="deleteGroupTarget = group.id"><X :size="15" /></button></div>
            <span class="map-group-resize" title="拖动调整工作区大小" @pointerdown.stop="remember(); drag = { kind: 'resize', id: group.id, startX: $event.clientX, startY: $event.clientY, width: group.width, height: group.height }; canvas.setPointerCapture($event.pointerId)"></span>
          </div>
          <svg class="map-edge-layer" width="1" height="1" aria-label="会话关系连线">
            <path v-if="linkSource && linkSide && linkPointer" :d="`M ${portPoint(linkSource, linkSide).x} ${portPoint(linkSource, linkSide).y} L ${linkPointer.x} ${linkPointer.y}`" fill="none" stroke="#7c3aed" stroke-width="2" stroke-dasharray="5 5" />
            <g v-for="edge in edges" :key="edge.id" class="map-edge" @click.stop="selected = edge.id">
              <path :d="edgeGeometry(edge).path" fill="none" stroke="transparent" stroke-width="22" />
              <path :d="edgeGeometry(edge).path" fill="none" :stroke="selected === edge.id ? '#7c3aed' : '#a99ac5'" stroke-width="2" :marker-end="edgeRelation(edge) === 'related' ? undefined : 'url(#map-arrow)'" />
              <rect class="map-edge-badge" :class="{ injected: edgeRelation(edge) !== 'related' }" :x="edgeGeometry(edge).labelX - edgeBadgeWidth(edge) / 2" :y="edgeGeometry(edge).labelY - 10" :width="edgeBadgeWidth(edge)" height="20" rx="10" />
              <text class="map-edge-badge-text" :x="edgeGeometry(edge).labelX" :y="edgeGeometry(edge).labelY + 3" text-anchor="middle">{{ edgeLabel(edge) }}</text>
              <circle v-if="selected === edge.id" :cx="edgeGeometry(edge).labelX + edgeBadgeWidth(edge) / 2 + 14" :cy="edgeGeometry(edge).labelY" r="10" fill="#f4edff" @click.stop="removeEdge(edge.id)" />
              <text v-if="selected === edge.id" :x="edgeGeometry(edge).labelX + edgeBadgeWidth(edge) / 2 + 14" :y="edgeGeometry(edge).labelY + 4" text-anchor="middle" @click.stop="removeEdge(edge.id)">×</text>
            </g>
            <defs><marker id="map-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 0 L9 4.5 L0 9 Z" fill="#a99ac5" /></marker></defs>
          </svg>
          <article v-for="item in conversations" :key="item.id" class="map-card" tabindex="0" @focus="selected = item.id" :data-conversation-id="item.id" :class="{ selected: selected === item.id, 'map-card-running': statusOf(item) === 'running', 'map-card-waiting': statusOf(item) === 'waiting' }" :style="{ left: `${nodeOf(item.id).x}px`, top: `${nodeOf(item.id).y}px`, '--card-color': nodeOf(item.id).color || '#7c3aed' }" @pointerdown="startNodeDrag($event, item.id)" @click.stop="clickCard(item.id)" @dblclick.stop="openConversation(item.id)" @contextmenu="openMenu($event, item.id)">
            <div v-if="selected === item.id" class="map-inline-colors" aria-label="会话卡片背景颜色" @pointerdown.stop @click.stop><span>颜色</span><button v-for="color in groupColors" :key="color" type="button" :class="{ active: (nodeOf(item.id).color || '#7c3aed') === color }" :style="{ backgroundColor: color }" :aria-label="`卡片颜色 ${color}`" @click="setMapColor('card', item.id, color)" /></div>
            <div class="map-card-top"><span class="map-card-icon"><Bot :size="15" /></span><strong :title="item.title">{{ item.title }}</strong><button type="button" title="更多操作" @click.stop="openMenu($event, item.id)"><MoreHorizontal :size="17" /></button></div>
            <p class="map-card-summary" @mouseenter="showSummary($event, item)" @mouseleave="scheduleSummaryClose">{{ summaryOf(item) }}</p>
            <div class="map-card-bottom"><span>{{ formatConversationTime(conversationActivityAt(item)) }}</span><span v-if="statusOf(item) === 'running' || statusOf(item) === 'waiting'" class="map-status" :class="statusOf(item)"><i />{{ statusText(item) }}</span></div>
            <button v-for="side in ['top', 'right', 'bottom', 'left']" :key="side" class="map-card-port" :class="side" :data-side="side" type="button"
              :title="`${portLabels[side]}连接点：拖到其他卡片建立联系，拖到空白处创建分支`"
              :aria-label="`${portLabels[side]}连接点`"
              @pointerdown.stop="startLinkDrag($event, item.id, side)" @click.stop><Link2 :size="13" /></button>
          </article>
        </div>
        <div v-if="selectedGroup" class="map-inline-colors map-floating-colors" :style="{ left: `${board.viewport.x + selectedGroup.x * board.viewport.zoom}px`, top: `${board.viewport.y + selectedGroup.y * board.viewport.zoom - 41}px` }" aria-label="工作区背景颜色" @pointerdown.stop @click.stop><span>颜色</span><button v-for="color in groupColors" :key="color" type="button" :class="{ active: selectedGroup.color === color }" :style="{ backgroundColor: color }" :aria-label="`工作区颜色 ${color}`" @click="setMapColor('group', selectedGroup.id, color)" /></div>
        <div v-if="linkSource" class="map-link-hint"><Link2 :size="16" />拖到目标卡片建立联系，拖到空白处创建分支；也可直接点击目标卡片</div>
        <div class="map-zoom" @pointerdown.stop><button type="button" title="缩小" @click="zoomBy(.8)"><ZoomOut :size="17" /></button><span>{{ Math.round(board.viewport.zoom * 100) }}%</span><button type="button" title="放大" @click="zoomBy(1.25)"><ZoomIn :size="17" /></button><button type="button" title="适配画布" @click="fitBoard"><Maximize2 :size="16" /></button></div>
        <div class="map-footnote" @pointerdown.stop><span>{{ conversations.length }} 张卡片 · {{ visibleGroups.length }} 个工作区 · {{ edges.length }} 条联系</span><span>{{ saving ? '保存中…' : '已自动保存' }}</span><button type="button" class="map-help-trigger" title="使用提示" aria-label="使用提示" :aria-expanded="helpOpen" @click="helpOpen = !helpOpen"><CircleHelp :size="16" /></button></div>
        <div v-if="helpOpen" class="map-help" @pointerdown.stop><button type="button" title="关闭使用提示" @click="helpOpen = false"><X :size="15" /></button><strong>画布操作</strong><p>拖动卡片整理位置，工作区会随卡片扩展或收缩；拖动空白处平移，滚轮缩放。双击卡片打开智能问答；右键画布可新建或导入工作区、会话。拖动卡片四周的连接点可关联会话或创建分支。选中卡片或工作区后按Backspace（退格键）可从地图删除，侧栏记录仍会保留，可重新导入。</p></div>
      </div>
      <div v-if="menu" class="map-context-menu" :style="{ left: `${menu.x}px`, top: `${menu.y}px` }" @click.stop>
        <template v-if="menu.kind === 'group'">
          <button type="button" @click="editTitle('group', menu.id)"><MoreHorizontal :size="16" />编辑工作区</button>
          <button type="button" @click="hideGroup(menu.id)"><EyeOff :size="16" />隐藏工作区和卡片</button>
          <button type="button" class="map-menu-danger" @click="deleteGroupTarget = menu.id; menu = null"><Trash2 :size="16" />删除工作区</button>
        </template>
        <template v-else-if="menu.id">
          <button type="button" @click="openConversation(menu.id); menu = null"><MessageSquarePlus :size="16" />打开会话</button>
          <button type="button" @click="newAt({ x: nodeOf(menu.id).x + 340, y: nodeOf(menu.id).y + 40 }, menu.id)"><GitBranch :size="16" />基于此会话新建</button>
          <button type="button" @click="startLink(menu.id)"><Link2 :size="16" />建立联系</button>
          <button type="button" :disabled="digestBusy.has(menu.id)" @click="refreshDigest(menu.id); menu = null"><Sparkles :size="16" />更新AI摘要</button>
          <button type="button" @click="editTitle('conversation', menu.id)"><MoreHorizontal :size="16" />重命名</button>
          <button v-if="regionId(menu.id)" type="button" @click="pendingDetach = menu.id; menu = null"><Minus :size="16" />脱离当前工作区</button>
          <button type="button" @click="hideCard(menu.id)"><Minus :size="16" />从地图隐藏</button>
          <button type="button" class="map-menu-danger" @click="deleteCardTarget = menu.id; menu = null"><Trash2 :size="16" />从地图删除会话</button>
        </template>
        <template v-else><button type="button" @click="newAt(menu.point)"><MessageSquarePlus :size="16" />新建会话</button><button type="button" @click="addGroup(menu.point)"><Plus :size="16" />新建工作区</button><button type="button" @click="openImport('group')"><Map :size="16" />导入工作区</button><button type="button" @click="openImport('card')"><MessageSquarePlus :size="16" />导入会话</button><button type="button" @click="fitBoard(); menu = null"><Maximize2 :size="16" />适配画布</button><button type="button" class="map-menu-restore" :disabled="!hiddenCount.total" :title="hiddenCount.total ? `恢复 ${hiddenCount.groups} 个工作区和 ${hiddenCount.cards} 张卡片` : '没有隐藏的工作区或卡片'" @click="restoreCards(); menu = null"><Eye :size="16" />恢复隐藏内容<span v-if="hiddenCount.total" class="map-menu-count">{{ hiddenCount.total }}</span></button></template>
      </div>
      <div v-if="menu" class="map-menu-dismiss" @click="menu = null" />

      <div v-if="dialog" class="map-dialog-backdrop" @click.self="dialog = null"><form class="map-dialog" @submit.prevent="createConversation"><div class="map-dialog-head"><span><GitBranch v-if="dialog.sourceId" :size="22" /><MessageSquarePlus v-else :size="22" /></span><div><small>CONVERSATION MAP</small><h2>{{ dialog.sourceId ? '从会话创建分支' : '新建会话' }}</h2></div><button type="button" @click="dialog = null"><X :size="18" /></button></div>
        <label>会话标题<input v-model="dialog.title" maxlength="160" autofocus /></label>
        <label>选择功能<MapSelect v-model="dialog.skill" :options="createSkills" label="选择功能" /></label>
        <label>模型<MapSelect v-model="dialog.model" :options="modelOptions" label="选择模型" /></label>
        <template v-if="dialog.sourceId"><p class="map-dialog-source">来源：{{ chat.conversations.find(item => item.id === dialog.sourceId)?.title }}</p><span class="map-dialog-label">继承方式</span><div class="map-mode-tabs"><button type="button" :class="{ active: dialog.mode === 'none' }" @click="dialog.mode = 'none'; refreshBranchPreview()">不继承</button><button type="button" :class="{ active: dialog.mode === 'digest' }" @click="dialog.mode = 'digest'; refreshBranchPreview()">摘要注入</button><button type="button" :class="{ active: dialog.mode === 'full' }" @click="dialog.mode = 'full'; refreshBranchPreview()">完整对话</button></div><p class="map-dialog-help">{{ dialog.mode === 'full' ? '来源会话的完整对话将作为后续模型请求的背景。' : dialog.mode === 'digest' ? '将摘要、关键结论和下一步注入新会话。' : '只建立可视化联系，不注入对话内容。' }}</p><label v-if="dialog.mode !== 'none'">注入内容（可编辑）<textarea v-model="dialog.context" maxlength="60000" :placeholder="dialog.previewBusy ? '正在准备预览…' : '来源会话暂无内容'" @input="dialog.previewError = false" /></label></template>
        <label>提示词<textarea v-model="dialog.prompt" class="map-prompt" maxlength="60000" placeholder="输入想聊的内容，回车发送，Shift + 回车换行" @keydown="onPromptKeydown" /></label>
        <div class="map-dialog-actions"><button type="button" @click="dialog = null">取消</button><button type="submit" :disabled="creatingConversation || dialog.previewBusy || dialog.previewError || !dialog.prompt.trim()"><Send :size="17" />{{ creatingConversation ? '正在创建…' : '发送' }}</button></div>
      </form></div>
      <div v-if="editor" class="map-dialog-backdrop" @click.self="editor = null"><form class="map-dialog map-edit-dialog" @submit.prevent="saveTitle"><h2>{{ editor.kind === 'group-create' ? '创建工作区' : editor.kind === 'group' ? '编辑工作区' : '重命名会话' }}</h2><input v-model="editor.value" maxlength="160" autofocus /><div v-if="editor.kind === 'group' || editor.kind === 'group-create'" class="map-color-picker"><button v-for="color in groupColors" :key="color" type="button" :class="{ active: editor.color === color }" :style="{ background: color }" :title="`工作区颜色 ${color}`" @click="editor.color = color"></button></div><div class="map-dialog-actions"><button type="button" @click="editor = null">取消</button><button type="submit">{{ editor.kind === 'group-create' ? '创建' : '保存' }}</button></div></form></div>
      <div v-if="importKind" class="map-dialog-backdrop" @click.self="importKind = null"><div class="map-dialog map-import-dialog"><div class="map-import-head"><div><small>CONVERSATION MAP</small><h2>导入{{ importKind === 'group' ? '工作区' : '会话' }}</h2><p>导入后恢复原有位置、颜色和连线。</p></div><button type="button" title="关闭" @click="importKind = null"><X :size="18" /></button></div><label>搜索<input v-model="importSearch" autofocus :placeholder="`搜索${importKind === 'group' ? '工作区' : '会话'}名称`" /></label><div class="map-import-list"><button v-for="item in importOptions" :key="item.id" type="button" :disabled="item.disabled" @click="importItem(item.id)"><Map v-if="importKind === 'group'" :size="17" /><MessageSquarePlus v-else :size="17" /><span><strong>{{ item.title }}</strong><small>{{ item.note }}</small></span></button><p v-if="!importOptions.length">没有匹配的{{ importKind === 'group' ? '工作区' : '会话' }}</p></div></div></div>
      <div v-if="pendingLink" class="map-dialog-backdrop" @click.self="!linking && (pendingLink = null)"><section class="map-dialog map-relation-dialog" role="dialog" aria-modal="true" aria-label="选择会话关系">
        <div class="map-dialog-head"><span><Link2 :size="22" /></span><div><small>CONVERSATION MAP</small><h2>选择会话关系</h2></div><button type="button" aria-label="关闭" :disabled="linking" @click="pendingLink = null"><X :size="18" /></button></div>
        <p class="map-relation-direction">{{ chat.conversations.find(item => item.id === pendingLink.source)?.title }} <span>→</span> {{ chat.conversations.find(item => item.id === pendingLink.target)?.title }}</p>
        <div class="map-relation-options"><button type="button" :disabled="linking" @click="applyLink('related')"><Link2 :size="18" /><span><strong>关联</strong><small>只标记两条会话有关联，不注入内容，也不显示箭头</small></span></button>
          <button type="button" :disabled="linking" @click="applyLink('digest')"><Sparkles :size="18" /><span><strong>摘要注入</strong><small>将左侧来源会话摘要注入右侧目标会话</small></span></button>
          <button type="button" :disabled="linking" @click="applyLink('full')"><GitBranch :size="18" /><span><strong>完整对话注入</strong><small>将来源会话的完整对话注入目标会话</small></span></button></div>
        <div class="map-dialog-actions"><button type="button" :disabled="linking" @click="pendingLink = null">取消</button></div>
      </section></div>
      <ConfirmModal :open="!!deleteGroupTarget" title="从地图删除工作区？" message="只从地图移除工作区及其中的卡片；侧栏记录、布局和连线都会保留，可从右键菜单重新导入。" :subject="board.groups.find(group => group.id === deleteGroupTarget)?.title" confirm-text="从地图删除" danger @cancel="deleteGroupTarget = null" @confirm="confirmDeleteGroup" />
      <ConfirmModal :open="!!deleteCardTarget" title="从地图删除会话？" message="只从地图移除这张卡片；会话记录、原有位置、颜色和连线都会保留，可重新导入。" :subject="chat.conversations.find(item => item.id === deleteCardTarget)?.title" confirm-text="从地图删除" danger @cancel="deleteCardTarget = null" @confirm="removeCardFromMap" />
      <ConfirmModal :open="!!pendingMembership" title="将卡片移入工作区？" :message="`确认将《${chat.conversations.find(item => item.id === pendingMembership?.id)?.title || '会话'}》移入《${board.groups.find(group => group.id === pendingMembership?.groupId)?.title || '工作区'}》吗？跨工作区的连线将不再显示。`" confirm-text="移入工作区" @cancel="cancelMembership" @confirm="confirmMembership" />
      <ConfirmModal :open="!!pendingDetach" title="将卡片移出工作区？" :message="`确认将《${chat.conversations.find(item => item.id === pendingDetach)?.title || '会话'}》移出《${board.groups.find(group => group.id === regionId(pendingDetach))?.title || '工作区'}》吗？卡片会移到工作区外。`" confirm-text="移出工作区" @cancel="pendingDetach = null" @confirm="confirmDetach" />
    </section>
    <Teleport to="body"><div v-if="summaryHover" ref="summaryPopover" class="map-summary-popover" :class="{ 'is-offset': summaryHover.offset }" :style="{ left: `${summaryHover.left}px`, top: `${summaryHover.top}px`, width: `${summaryHover.width}px`, maxHeight: `${summaryHover.maxHeight}px` }" role="tooltip" @mouseenter="cancelSummaryClose" @mouseleave="scheduleSummaryClose"><strong>摘要信息</strong><p>{{ summaryHover.text }}</p></div></Teleport>
  </PageShell>
</template>

<style scoped>
.conversation-map-page{height:100%;min-height:0;display:flex;flex-direction:column;background:#faf8fd;color:#271636;font-family:inherit}
.map-toolbar{height:76px;flex:0 0 76px;display:flex;align-items:center;gap:10px;width:100%;min-width:0;padding:0 24px;background:#fff;border-bottom:1px solid #ebe6f2;z-index:2}
.map-heading{flex:0 0 auto;display:flex;align-items:center;gap:11px;min-width:0;margin-right:8px}.map-heading strong{display:block;font-size:18px;font-weight:750}.map-heading small{display:block;color:#9b91a8;font-size:11px;margin-top:2px;white-space:nowrap}.map-logo{width:42px;height:42px;flex:none;display:grid;place-items:center;border-radius:12px;background:#f2eafe;color:#7135d2}
.map-search{height:43px;min-width:180px;flex:1 1 320px;display:flex;align-items:center;gap:8px;padding:0 14px;border:1px solid #e8e1f0;border-radius:11px;background:#fbfafd;color:#9585aa}.map-search input{border:0;background:transparent;outline:0;width:100%;color:#342342;font:inherit;font-size:13px}.map-search input::placeholder{color:#aaa0b6}.map-filter{height:43px;flex:0 0 126px;border:1px solid #e8e1f0;border-radius:10px;background:#fff;color:#604e75;padding:0 9px;font:inherit;font-size:12px}.map-tool{height:43px;flex:0 0 auto;display:flex;align-items:center;justify-content:center;gap:6px;padding:0 14px;white-space:nowrap;border:1px solid #e8e1f0;border-radius:10px;background:#fff;color:#614775;font:inherit;font-size:12px;cursor:pointer}.map-tool:hover{background:#f5effe;color:#6d28d9}.map-icon-tool{width:43px;padding:0}.map-tool.primary{min-width:132px;background:#7c3aed;color:#fff;border-color:#7c3aed;font-weight:650}.map-tool.primary:hover{background:#6d28d9}.map-back{min-width:110px;gap:8px;border-color:#e1d3f4;background:#faf7ff;color:#6739a6;font-weight:650}.map-back:hover{border-color:#bfa5ef;background:#f0e8ff;color:#5525a2}
.map-tool:disabled{opacity:.4;cursor:not-allowed}.map-tool:disabled:hover{background:#fff;color:#614775}
.map-toolbar .map-filter{height:43px;flex:0 0 126px;min-width:0;padding:0;border:0;background:transparent}
.map-region-tool{border-color:#decaf7;background:#f7f1ff;color:#6d28b6;font-weight:650}.map-region-tool:hover{border-color:#bd99ef;background:#efe3ff}
.map-tool.map-restore-tool{position:relative;width:43px;padding:0;border-color:#e7dff0;background:#faf8fd;color:#a69ab6;box-shadow:inset 0 1px #fff;transition:background .16s,border-color .16s,box-shadow .16s,transform .16s}
.map-tool.map-restore-tool.has-hidden{border-color:#d7bdf4;background:linear-gradient(145deg,#f8f2ff,#eee2ff);color:#7231c7;box-shadow:inset 0 1px #fff,0 3px 9px #6e2bab1c}
.map-tool.map-restore-tool.has-hidden:hover{border-color:#b685eb;background:linear-gradient(145deg,#f4e8ff,#e6d2ff);box-shadow:0 5px 14px #7535bb30;transform:translateY(-1px)}
.map-tool.map-restore-tool:focus-visible{outline:2px solid #8b5cf6;outline-offset:2px}
.map-restore-count{position:absolute;top:-6px;right:-6px;display:grid;place-items:center;min-width:17px;height:17px;padding:0 3px;border:2px solid #fff;border-radius:999px;background:#7c3aed;color:#fff;font-size:9px;font-weight:700;line-height:1;box-shadow:0 2px 5px #4c1d9560}
.map-canvas{position:relative;flex:1;overflow:hidden;cursor:grab;background-color:#faf8fd;background-image:radial-gradient(#d9c9eb .8px,transparent .8px);background-size:20px 20px;touch-action:none}.map-canvas.is-panning{cursor:grabbing}.map-canvas.is-linking{cursor:crosshair}.map-world{position:absolute;left:0;top:0;transform-origin:0 0;width:1px;height:1px}.map-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;color:#9a8da8;pointer-events:none}.map-empty strong{font-size:18px;color:#513b67}
.map-group{position:absolute;z-index:0;border:1.5px dashed color-mix(in srgb,var(--group-color) 43%,white);border-radius:22px;background:color-mix(in srgb,var(--group-color) 5%,transparent);cursor:grab}.map-group.selected{border-style:solid}.map-group-title{height:38px;display:flex;align-items:center;gap:7px;padding:0 12px;color:var(--group-color);font-size:13px;font-weight:700}.map-group-dot{width:7px;height:7px;border-radius:50%;background:var(--group-color)}.map-group-title button{margin-left:auto;display:grid;place-items:center;border:0;background:transparent;color:var(--group-color);cursor:pointer}.map-group-title button+button{margin-left:0}.map-group-resize{position:absolute;bottom:3px;right:3px;width:20px;height:20px;cursor:nwse-resize;background:linear-gradient(135deg,transparent 55%,var(--group-color) 55%,var(--group-color) 60%,transparent 60%,transparent 74%,var(--group-color) 74%,var(--group-color) 79%,transparent 79%)}
.map-edge-layer{position:absolute;left:0;top:0;z-index:1;overflow:visible;pointer-events:none}.map-edge{pointer-events:stroke;cursor:pointer}.map-edge text,.map-edge circle,.map-edge rect{pointer-events:auto}.map-edge text{font-size:11px;fill:#75628a}
.map-edge-badge{fill:#fff;stroke:#e1d4ef;stroke-width:1;filter:drop-shadow(0 2px 4px #3d1b5c18)}.map-edge-badge.injected{fill:#f4ebff;stroke:#c9a9f5}.map-edge .map-edge-badge-text{fill:#674093;font-size:10px;font-weight:700;letter-spacing:.02em}
.map-card{position:absolute;z-index:2;width:280px;min-height:174px;padding:16px 16px 13px;border:1px solid #e7dfef;border-radius:15px;background:#fff;box-shadow:0 4px 16px rgba(52,26,82,.08),0 1px 3px rgba(52,26,82,.06);cursor:grab;user-select:none;transition:box-shadow .15s,border-color .15s}.map-card:hover,.map-card.selected{border-color:#b894f3;box-shadow:0 10px 26px rgba(97,46,160,.14)}.map-card:active{cursor:grabbing}.map-card-running{border-color:#96dab2}.map-card-waiting{border-color:#e9c88d}.map-card-top{display:flex;align-items:center;gap:7px;min-width:0}.map-card-top strong{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;color:#25172f}.map-card-top>button{display:grid;place-items:center;border:0;background:transparent;color:#9d90ae;cursor:pointer}.map-card-icon{display:grid;place-items:center;width:24px;height:24px;border-radius:7px;background:#f3edfc;color:#7c3aed}.map-card-summary{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;height:54px;margin:11px 0 4px;color:#756b7d;font-size:12px;line-height:1.5}.map-card-next{display:flex;gap:6px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;margin:0 0 8px;font-size:11px;color:#5b4970}.map-card-next span{flex:0 0 auto;color:#7c3aed;font-weight:700}.map-card-bottom{display:flex;align-items:center;justify-content:space-between;margin-top:10px;color:#aaa0b2;font-size:11px}.map-status{display:flex;align-items:center;gap:4px;color:#888092}.map-status i{width:6px;height:6px;border-radius:50%;background:#b3acbb}.map-status.running{color:#159451}.map-status.running i{background:#1ab96b;box-shadow:0 0 0 3px #ddfae8}.map-status.waiting{color:#bd7a17}.map-status.waiting i{background:#f2b43e}.map-card-port{position:absolute;top:72px;width:24px;height:24px;display:grid;place-items:center;border:1px solid #d9c4f5;border-radius:50%;background:#fff;color:#7c3aed;opacity:0;cursor:pointer}.map-card:hover .map-card-port,.map-card.selected .map-card-port,.is-linking .map-card-port{opacity:1}.map-card-port.left{left:-13px}.map-card-port.right{right:-13px}
.map-zoom{position:absolute;right:20px;bottom:42px;display:flex;align-items:center;gap:3px;padding:4px;border:1px solid #e9e1f0;border-radius:11px;background:#fff;box-shadow:0 3px 12px #35145214}.map-zoom button{width:30px;height:30px;display:grid;place-items:center;border:0;border-radius:7px;background:transparent;color:#755c8c;cursor:pointer}.map-zoom button:hover{background:#f4eefe}.map-zoom span{min-width:38px;text-align:center;color:#766b83;font-size:11px}.map-footnote{position:absolute;left:20px;bottom:12px;display:flex;align-items:center;gap:12px;color:#9a8fa7;font-size:11px}.map-footnote button{border:0;background:transparent;color:#8b75a6;cursor:pointer}.map-link-hint{position:absolute;top:18px;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:7px;padding:8px 14px;border:1px solid #cdb8ed;border-radius:9px;background:#fff;color:#6932bd;font-size:12px;box-shadow:0 3px 10px #42127522}.map-help{position:absolute;left:20px;bottom:44px;width:310px;padding:18px;border:1px solid #e2d4f4;border-radius:14px;background:#fff;box-shadow:0 12px 30px #3f1b651c;font-size:12px;line-height:1.7;color:#695778}.map-help button{float:right;border:0;background:transparent;color:#7c3aed;cursor:pointer}.map-help strong{color:#301847;font-size:14px}.map-help p{margin:8px 0 0}
.map-context-menu{position:fixed;z-index:31;display:grid;gap:2px;width:195px;padding:5px;border:1px solid #e7dfee;border-radius:12px;background:#fff;box-shadow:0 14px 34px #2f12402c}.map-context-menu button{height:34px;display:flex;align-items:center;gap:9px;padding:0 10px;border:0;border-radius:7px;background:transparent;color:#49365e;text-align:left;font:inherit;font-size:12px;cursor:pointer}.map-context-menu button:hover{background:#f4edfe;color:#6d28d9}.map-context-menu button:disabled{opacity:.45}.map-menu-dismiss{position:fixed;inset:0;z-index:30;background:transparent}
.map-context-menu:has(button:nth-child(4)) button{height:36px}.map-context-menu .map-menu-danger{color:#b74162}.map-context-menu .map-menu-danger:hover{background:#fff0f4;color:#a8244b}
.map-context-menu .map-menu-restore{margin-top:4px;border-top:1px solid #eee6f5;border-radius:0 0 7px 7px;color:#7132bd}.map-context-menu .map-menu-restore:not(:disabled):hover{background:#f2e9ff;color:#6324ac}.map-context-menu .map-menu-restore:disabled{color:#9f94ab;cursor:not-allowed}.map-context-menu .map-menu-restore:disabled:hover{background:transparent}.map-menu-count{display:grid;place-items:center;min-width:18px;height:18px;margin-left:auto;padding:0 4px;border-radius:999px;background:#eee0ff;color:#7132bd;font-size:10px;font-weight:700}
.map-import-dialog{width:min(480px,calc(100vw - 30px))}.map-import-head{display:flex;justify-content:space-between;gap:12px}.map-import-head small{color:#a185c8;font-size:10px;font-weight:700;letter-spacing:.14em}.map-import-head h2{margin:3px 0;color:#281638}.map-import-head p{margin:3px 0 0;color:#8b7b9a;font-size:12px}.map-import-head>button{align-self:flex-start;border:0;background:transparent;color:#8a7a9b;cursor:pointer}.map-import-list{display:grid;gap:5px;max-height:320px;overflow:auto}.map-import-list>button{display:flex;align-items:center;gap:11px;width:100%;padding:10px 12px;border:1px solid #e8def2;border-radius:10px;background:#fff;color:#7432c0;text-align:left;cursor:pointer}.map-import-list>button:not(:disabled):hover{border-color:#bda0e7;background:#faf6ff}.map-import-list>button:disabled{background:#f8f6fa;color:#b2a9bd;cursor:not-allowed}.map-import-list>button>span{display:grid;gap:3px;min-width:0}.map-import-list strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#3d2b50;font-size:13px}.map-import-list small{color:#92869d;font-size:11px}.map-import-list>p{padding:14px;color:#92869d;text-align:center;font-size:12px}
.map-dialog-backdrop{position:fixed;inset:0;z-index:40;display:grid;place-items:center;background:#20102b6b;backdrop-filter:blur(3px)}.map-dialog{width:min(460px,calc(100vw - 30px));display:grid;gap:15px;padding:24px;border:1px solid #e8def3;border-radius:19px;background:#fff;box-shadow:0 24px 70px #24102e35}.map-dialog-head{display:flex;align-items:center;gap:11px}.map-dialog-head>span{width:42px;height:42px;display:grid;place-items:center;border-radius:12px;background:#f2eafe;color:#7432d4}.map-dialog-head div{flex:1}.map-dialog-head small{font-size:10px;font-weight:700;letter-spacing:.14em;color:#a185c8}.map-dialog h2{margin:2px 0 0;color:#281638;font-size:20px}.map-dialog-head>button{align-self:flex-start;border:0;background:transparent;color:#8a7a9b;cursor:pointer}.map-dialog label{display:grid;gap:7px;color:#675777;font-size:12px;font-weight:700}.map-dialog input,.map-dialog select{height:43px;width:100%;padding:0 12px;border:1px solid #dfd2ed;border-radius:9px;background:#fff;color:#332044;font:inherit;font-size:13px;outline:none}.map-dialog input:focus,.map-dialog select:focus{border-color:#8b5cf6;box-shadow:0 0 0 3px #8b5cf620}.map-dialog-source{margin:0;color:#7a6c86;font-size:12px}.map-dialog-label{font-size:12px;font-weight:700;color:#675777}.map-mode-tabs{display:flex;gap:5px;padding:4px;border-radius:10px;background:#f6f2fa}.map-mode-tabs button{flex:1;padding:8px 4px;border:0;border-radius:8px;background:transparent;color:#7a6a89;font:inherit;font-size:12px;cursor:pointer}.map-mode-tabs button.active{background:#fff;color:#7131c7;box-shadow:0 1px 5px #45236e1b}.map-dialog-help{min-height:30px;margin:0;color:#91839e;font-size:11px;line-height:1.5}.map-dialog-actions{display:flex;justify-content:flex-end;gap:8px;padding-top:4px}.map-dialog-actions button{height:38px;display:flex;align-items:center;gap:6px;padding:0 15px;border:1px solid #e2d9ec;border-radius:9px;background:#fff;color:#59476b;font:inherit;font-size:12px;cursor:pointer}.map-dialog-actions button[type=submit]{border-color:#7c3aed;background:#7c3aed;color:#fff}.map-edit-dialog{gap:18px}
.map-dialog textarea{width:100%;min-height:98px;max-height:180px;resize:vertical;padding:10px 12px;border:1px solid #dfd2ed;border-radius:9px;background:#fcfaff;color:#463554;font:inherit;font-size:12px;line-height:1.5;outline:none}.map-dialog textarea:focus{border-color:#8b5cf6}.map-color-picker{display:flex;gap:10px}.map-color-picker button{width:24px;height:24px;border:2px solid #fff;border-radius:50%;box-shadow:0 0 0 1px #ddd2e8;cursor:pointer}.map-color-picker button.active{box-shadow:0 0 0 2px #32134c}
.map-dialog{max-height:calc(100vh - 36px);overflow-y:auto}.map-dialog textarea.map-prompt{min-height:120px;font-size:13px}.map-dialog-actions button[type=submit]:disabled{opacity:.55;cursor:not-allowed}
.map-relation-dialog{width:min(480px,calc(100vw - 30px))}.map-relation-direction{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:0;padding:10px 12px;border:1px solid #eee5f7;border-radius:10px;background:#faf7ff;color:#5c4670;font-size:12px}.map-relation-direction span{padding:0 5px;color:#7c3aed;font-weight:700}.map-relation-options{display:grid;gap:8px}.map-relation-options button{display:flex;align-items:center;gap:12px;width:100%;padding:12px;border:1px solid #e8def2;border-radius:11px;background:#fff;color:#6d3ba8;text-align:left;font:inherit;cursor:pointer}.map-relation-options button:hover{border-color:#bda0e7;background:#faf6ff}.map-relation-options button:disabled{opacity:.5;cursor:wait}.map-relation-options button>svg{flex:none}.map-relation-options strong{display:block;color:#3f2555;font-size:13px}.map-relation-options small{display:block;margin-top:3px;color:#8f819e;font-size:11px;line-height:1.5}
.map-color-picker{flex-wrap:nowrap;gap:6px}.map-color-picker button{flex:0 0 18px;width:18px;height:18px}.map-inline-colors{position:absolute;top:-41px;left:0;z-index:5;display:flex;align-items:center;gap:5px;width:max-content;max-width:calc(100vw - 40px);height:32px;padding:0 9px;border:1px solid #e9e0f1;border-radius:11px;background:#fff;box-shadow:0 7px 22px #32154826;cursor:default}.map-inline-colors span{margin-right:3px;color:#83768e;font-size:11px}.map-inline-colors button{flex:0 0 16px;width:16px;height:16px;padding:0;border:2px solid #fff;border-radius:50%;box-shadow:0 0 0 1px #d8d0de;cursor:pointer}.map-inline-colors button.active{box-shadow:0 0 0 2px #433248}
.map-floating-colors{z-index:10}
.map-group{background:color-mix(in srgb,var(--group-color) 6%,transparent)}.map-group.selected{border-color:var(--group-color);background:color-mix(in srgb,var(--group-color) 14%,transparent);box-shadow:0 0 0 2px color-mix(in srgb,var(--group-color) 40%,transparent),0 0 32px 8px color-mix(in srgb,var(--group-color) 26%,transparent),inset 0 0 28px color-mix(in srgb,var(--group-color) 9%,transparent)}
.map-card{border-color:color-mix(in srgb,var(--card-color) 20%,#e7dfef);background:color-mix(in srgb,var(--card-color) 5%,#fff 95%)}.map-card.selected{z-index:4;border-color:var(--card-color);background:color-mix(in srgb,var(--card-color) 10%,#fff 90%);box-shadow:0 0 0 2px color-mix(in srgb,var(--card-color) 38%,transparent),0 0 28px 6px color-mix(in srgb,var(--card-color) 30%,transparent),0 10px 25px #32145212}.map-card-icon{color:var(--card-color);background:color-mix(in srgb,var(--card-color) 12%,#fff 88%)}
.map-card{min-height:148px}.map-card-summary:hover{color:#59446b}.map-summary-popover{display:flex;flex-direction:column;max-height:500px;position:fixed;z-index:1200;box-sizing:border-box;width:min(300px,calc(100vw - 32px));padding:16px 18px;border:1px solid #d7c1f2;border-radius:15px;background:#fff;color:#4b365e;box-shadow:0 18px 48px #3920522e,0 4px 12px #3920521a;user-select:text}.map-summary-popover::before{content:"";position:absolute;top:30px;left:-7px;width:12px;height:12px;border-left:1px solid #d7c1f2;border-bottom:1px solid #d7c1f2;background:#fff;transform:rotate(45deg)}.map-summary-popover.is-left::before{left:auto;right:-7px;border:0;border-top:1px solid #d7c1f2;border-right:1px solid #d7c1f2}.map-summary-popover strong{flex-shrink:0;display:block;margin-bottom:8px;color:#6d28d9;font-size:12px;font-weight:750}.map-summary-popover p{min-height:0;overflow-y:auto;overscroll-behavior:contain;margin:0;color:#4b365e;font-size:13px;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere}
.map-summary-popover.is-offset::before{display:none}
.map-card-port{z-index:5;top:auto;transition:opacity .15s,box-shadow .15s,background .15s}.map-card-port:hover,.map-card-port:focus-visible{background:#f4edff;box-shadow:0 0 0 4px #b995ef44;outline:0}.map-card-port.left{top:50%;left:-13px;transform:translateY(-50%)}.map-card-port.right{top:50%;right:-13px;transform:translateY(-50%)}.map-card-port.top{top:-13px;left:50%;transform:translateX(-50%)}.map-card-port.bottom{bottom:-13px;left:50%;transform:translateX(-50%)}
@media(max-width:1250px){.map-toolbar{gap:8px;padding:0 14px}.map-heading{margin-right:0}.map-heading small{display:none}.map-search{min-width:150px}.map-filter{flex-basis:114px}.map-tool{padding:0 10px}.map-icon-tool{width:43px;padding:0}.map-tool.primary{min-width:116px}.map-back{min-width:96px}}
@media(max-width:980px){.map-toolbar{height:auto;min-height:76px;flex:0 0 auto;flex-wrap:wrap;gap:8px;padding:11px 14px}.map-toolbar::before{content:"";order:3;flex:0 0 100%;height:0}.map-heading{flex:0 0 auto}.map-search{flex:1 1 220px}.map-back{order:2;margin-left:auto}.map-filter{order:3;flex:1 1 120px}.map-toolbar>.map-tool:not(.map-back){order:4}.map-tool.primary{flex:1 1 130px}.map-icon-tool{flex:0 0 43px}}
@media(max-width:720px){.map-toolbar{padding:10px}.map-search{order:3;min-width:100%;flex-basis:100%}.map-filter{display:none}.map-heading strong{font-size:15px}.map-tool:not(.map-back){font-size:0}.map-tool svg{flex:0 0 auto}.map-tool.primary{min-width:43px}.map-back{min-width:43px;width:43px;padding:0}.map-back span{display:none}.map-card{width:280px}}
.map-dialog .map-select{font-weight:400}
@media(max-width:1250px){.map-toolbar .map-filter{flex-basis:114px}}
@media(max-width:980px){.map-toolbar .map-filter{flex:1 1 120px}}
@media(max-width:720px){.map-toolbar .map-filter{display:block;order:4;flex:1 1 120px}}
</style>
