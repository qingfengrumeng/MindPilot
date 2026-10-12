<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Check,
  CheckCheck,
  ChevronDown,
  ChevronUp,
  FolderClosed,
  FolderOpen,
  FolderPlus,
  ListChecks,
  Map as MapIcon,
  MessageSquareText,
  MoreHorizontal,
  Pencil,
  Pin,
  Trash2,
  X
} from 'lucide-vue-next'
import ConfirmModal from './ConfirmModal.vue'
import { conversationActivityAt, formatConversationTime } from '@/lib/conversationTime'
import { useChatStore } from '@/stores/chat'
import { useConversationBoardStore } from '@/stores/conversationBoard'
import { useUiStore } from '@/stores/ui'

const emit = defineEmits(['navigate'])
const chat = useChatStore()
const conversationBoard = useConversationBoardStore()
const board = conversationBoard.board
const ui = useUiStore()
const route = useRoute()
const router = useRouter()
const menuId = ref(null)
const menuPosition = ref({ top: 0, left: 0 })
const renameTarget = ref(null)
const renameValue = ref('')
const deleteTarget = ref(null)
const workspaceMenuId = ref(null)
const workspaceMenuPosition = ref({ top: 0, left: 0 })
const workspaceEditor = ref(null)
const workspaceAction = ref(null)
const workspaceBusy = ref(false)
const draggingId = ref(null)
const dropTarget = ref(null)
const rowDropTarget = ref(null)
const openFolders = ref(new Set())
const expandedWorkspaces = ref(new Set())
const workspacePreviewLimit = 3

/** 批量管理状态 */
const batchMode = ref(false)
const selected = ref(new Set())
const batchDeleteOpen = ref(false)

function closeConversationMenu() {
  menuId.value = null
  workspaceMenuId.value = null
}

onMounted(() => {
  document.addEventListener('click', closeConversationMenu)
  conversationBoard.load().catch(error => ui.toast(error.message || '工作区加载失败', 'error'))
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeConversationMenu)
})

function timestampOf(item) {
  return new Date(conversationActivityAt(item)).getTime()
}

function startOfDay(time) {
  const date = new Date(time)
  date.setHours(0, 0, 0, 0)
  return date.getTime()
}

function sortConversations(items) {
  return [...items].sort((a, b) => {
    const aOrder = board.nodes[a.id]?.sidebarOrder
    const bOrder = board.nodes[b.id]?.sidebarOrder
    const aHasOrder = Number.isFinite(aOrder)
    const bHasOrder = Number.isFinite(bOrder)
    if (aHasOrder && bHasOrder) return aOrder - bOrder
    if (aHasOrder !== bHasOrder) return aHasOrder ? 1 : -1
    return timestampOf(b) - timestampOf(a)
  })
}

const standaloneConversations = computed(() => sortConversations(chat.conversations.filter(item =>
  !board.nodes[item.id]?.groupId || !board.groups.some(group => group.id === board.nodes[item.id].groupId))))

/** 分组顺序：置顶 → 今天 → 昨天 → 一周以内 → 其余按「2026年X月」。 */
const groupedConversations = computed(() => {
  // A manually ordered list can cross date boundaries; timestamps remain on each row.
  if (standaloneConversations.value.some(item => Number.isFinite(board.nodes[item.id]?.sidebarOrder))) {
    return [{ key: 'manual', label: '', items: standaloneConversations.value.filter(item => !item.pinned) }].filter(group => group.items.length)
  }
  const now = Date.now()
  const dayStart = startOfDay(now)
  const yesterdayStart = dayStart - 86400000
  const weekStart = dayStart - 6 * 86400000

  const buckets = { pinned: [], today: [], yesterday: [], week: [], months: new Map() }

  for (const item of standaloneConversations.value) {
    if (item.pinned) continue
    const ts = timestampOf(item)
    if (item.pinned || Number.isNaN(ts)) {
      buckets.pinned.push(item)
    } else if (ts >= dayStart) {
      buckets.today.push(item)
    } else if (ts >= yesterdayStart) {
      buckets.yesterday.push(item)
    } else if (ts >= weekStart) {
      buckets.week.push(item)
    } else {
      const date = new Date(ts)
      const key = `${date.getFullYear()}-${date.getMonth() + 1}`
      if (!buckets.months.has(key)) buckets.months.set(key, [])
      buckets.months.get(key).push(item)
    }
  }

  const byRecent = list => list.sort((a, b) => timestampOf(b) - timestampOf(a))
  const groups = []
  const push = (key, label, list) => {
    if (list.length) groups.push({ key, label, items: byRecent(list) })
  }

  push('pinned', '置顶', buckets.pinned)
  push('today', '今天', buckets.today)
  push('yesterday', '昨天', buckets.yesterday)
  push('week', '一周以内', buckets.week)
  const monthKeys = [...buckets.months.keys()].sort((a, b) => b.localeCompare(a))
  for (const key of monthKeys) {
    const [year, month] = key.split('-')
    push(`month-${key}`, `${year}年${Number(month)}月`, buckets.months.get(key))
  }
  return groups
})
const workspaceGroups = computed(() => board.groups.map((group, index) => ({ ...group, index,
  items: sortConversations(chat.conversations.filter(item => board.nodes[item.id]?.groupId === group.id))
    .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned))) }))
  .sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || a.index - b.index))
const workspaceMenuItem = computed(() => board.groups.find(group => group.id === workspaceMenuId.value) || null)
const activeWorkspaceId = computed(() => board.nodes[chat.activeId]?.groupId || null)
const sidebarEntries = computed(() => [
  ...workspaceGroups.value.filter(item => item.pinned).map(item => ({ kind: 'workspace', item })),
  ...standaloneConversations.value.filter(item => item.pinned).map(item => ({ kind: 'conversation', item })),
  ...workspaceGroups.value.filter(item => !item.pinned).map(item => ({ kind: 'workspace', item }))
])

function workspaceItems(workspace) {
  return expandedWorkspaces.value.has(workspace.id) ? workspace.items : workspace.items.slice(0, workspacePreviewLimit)
}

function workspaceHiddenCount(workspace) { return Math.max(0, workspace.items.length - workspacePreviewLimit) }

function toggleWorkspaceItems(id) {
  const next = new Set(expandedWorkspaces.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedWorkspaces.value = next
}

const allSelected = computed(
  () => chat.conversations.length > 0 && selected.value.size === chat.conversations.length
)
const menuItem = computed(() => chat.conversations.find(item => item.id === menuId.value) || null)

function toggleConversationMenu(event, item) {
  if (menuId.value === item.id) {
    menuId.value = null
    return
  }
  const rect = event.currentTarget.getBoundingClientRect()
  const menuWidth = 150
  const menuHeight = 132
  const gap = 7
  const openUpward = window.innerHeight - rect.bottom < menuHeight + 16
  menuPosition.value = {
    top: openUpward ? Math.max(10, rect.top - menuHeight - gap) : rect.bottom + gap,
    left: Math.min(window.innerWidth - menuWidth - 10, Math.max(10, rect.right - menuWidth))
  }
  menuId.value = item.id
}

async function activate(item) {
  await chat.loadMessages(item.id)
  menuId.value = null
  if (route.path !== '/') await router.push('/')
  emit('navigate')
}

function enterBatchMode() {
  batchMode.value = true
  selected.value = new Set()
}

function exitBatchMode() {
  batchMode.value = false
  selected.value = new Set()
}

function toggleSelect(id) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleSelectAll() {
  selected.value = allSelected.value ? new Set() : new Set(chat.conversations.map(item => item.id))
}

async function batchDelete() {
  await chat.removeMany([...selected.value])
  selected.value = new Set()
  batchMode.value = false
  batchDeleteOpen.value = false
  ui.toast('所选会话已删除')
}

function subLabel(item) { return formatConversationTime(conversationActivityAt(item)) }

async function toggleConversationPin(item) {
  menuId.value = null
  try {
    await chat.togglePin(item.id)
    const groupId = board.nodes[item.id]?.groupId
    const items = workspaceGroups.value.find(group => group.id === groupId)?.items || standaloneConversations.value
    if (!items.some(conversation => Number.isFinite(board.nodes[conversation.id]?.sidebarOrder))) return
    const ids = items.filter(conversation => conversation.id !== item.id)
    const firstUnpinned = ids.findIndex(conversation => !conversation.pinned)
    ids.splice(item.pinned ? 0 : firstUnpinned < 0 ? ids.length : firstUnpinned, 0, item)
    ids.forEach((conversation, index) => { conversationBoard.ensureNode(conversation.id).sidebarOrder = index })
    await conversationBoard.save()
  } catch (error) { ui.toast(error.message || '置顶操作失败', 'error') }
}

function openRename(item) {
  renameTarget.value = item
  renameValue.value = item.title
  menuId.value = null
}

function saveRename() {
  const value = renameValue.value.trim()
  if (!value) {
    ui.toast('会话名称不能为空', 'error')
    return
  }
  chat.rename(renameTarget.value.id, value)
  renameTarget.value = null
  ui.toast('会话名称已更新')
}

function removeConversation() {
  chat.remove(deleteTarget.value.id)
  deleteTarget.value = null
  ui.toast('会话已删除')
}

function openWorkspaceMenu(event, group) {
  event.preventDefault()
  event.stopPropagation()
  menuId.value = null
  const rect = event.currentTarget.getBoundingClientRect()
  const x = event.clientX || rect.right
  const y = event.clientY || rect.bottom
  workspaceMenuPosition.value = { left: Math.max(10, Math.min(x, window.innerWidth - 188)),
    top: Math.max(10, Math.min(y, window.innerHeight - 190)) }
  workspaceMenuId.value = group.id
}

function workspacePosition() {
  for (let index = 0; index < 500; index++) {
    const x = 80 + index % 2 * 720
    const y = 100 + Math.floor(index / 2) * 560
    if (!board.groups.some(group => !group.removed && x < group.x + group.width + 30 && x + 660 > group.x - 30 && y < group.y + group.height + 30 && y + 470 > group.y - 30)) return { x, y }
  }
  return { x: 80, y: 100 + board.groups.length * 560 }
}

function editWorkspace(kind, group = null) {
  workspaceMenuId.value = null
  workspaceEditor.value = { kind, id: group?.id || null, value: group?.title || '' }
}

async function saveWorkspace() {
  if (workspaceBusy.value) return
  const data = workspaceEditor.value
  const title = data?.value.trim()
  if (!title) { ui.toast('请输入工作区名称', 'error'); return }
  workspaceBusy.value = true
  try {
    await conversationBoard.load()
    if (data.kind === 'create') {
      const group = await conversationBoard.createWorkspace(title, workspacePosition())
      openFolders.value = new Set([...openFolders.value].filter(id => id !== group.id))
      if (route.path !== '/') await router.push('/')
      emit('navigate')
    } else {
      const group = board.groups.find(item => item.id === data.id)
      if (group) group.title = title
    }
    await conversationBoard.save()
    workspaceEditor.value = null
    ui.toast(data.kind === 'create' ? '工作区已创建' : '工作区已重命名')
  } catch (error) { ui.toast(error.message || '工作区保存失败', 'error') }
  finally { workspaceBusy.value = false }
}

function askWorkspaceAction(kind, group) {
  workspaceMenuId.value = null
  if (kind !== 'delete') { performWorkspaceAction({ kind, id: group.id }); return }
  workspaceAction.value = { kind, id: group.id, title: group.title, pinned: Boolean(group.pinned) }
}

async function confirmWorkspaceAction() {
  await performWorkspaceAction(workspaceAction.value)
}

async function performWorkspaceAction(action) {
  if (!action || workspaceBusy.value) return
  const group = board.groups.find(item => item.id === action.id)
  if (!group) { workspaceAction.value = null; return }
  workspaceBusy.value = true
  try {
    if (action.kind === 'create') {
      await chat.newChat({ keepEmpty: true })
      const node = conversationBoard.ensureNode(chat.activeId)
      const count = Object.values(board.nodes).filter(item => item.groupId === group.id).length
      const col = count % 2
      const row = Math.floor(count / 2)
      Object.assign(node, { groupId: group.id, x: group.x + 24 + col * 310, y: group.y + 56 + row * 210 })
      group.width = Math.max(group.width, 660)
      group.height = Math.max(group.height, 56 + (row + 1) * 210 + 24)
      const nextCollapsed = new Set(openFolders.value)
      nextCollapsed.add(group.id)
      openFolders.value = nextCollapsed
      await conversationBoard.save()
      if (route.path !== '/') await router.push('/')
      emit('navigate')
    } else if (action.kind === 'pin') {
      group.pinned = !group.pinned
      await conversationBoard.save()
      ui.toast(group.pinned ? '工作区已置顶' : '已取消置顶')
    } else if (action.kind === 'delete') {
      for (const node of Object.values(board.nodes)) if (node.groupId === group.id) node.groupId = null
      board.groups = board.groups.filter(item => item.id !== group.id)
      await conversationBoard.save()
      ui.toast('工作区已删除，会话保留在未分组中')
    }
    workspaceAction.value = null
  } catch (error) { ui.toast(error.message || '工作区操作失败', 'error') }
  finally { workspaceBusy.value = false }
}

function toggleWorkspace(id) {
  const next = new Set(openFolders.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  openFolders.value = next
  const expanded = new Set(expandedWorkspaces.value)
  expanded.delete(id)
  expandedWorkspaces.value = expanded
}

function startConversationDrag(event, id) {
  if (batchMode.value) { event.preventDefault(); return }
  closeConversationMenu()
  draggingId.value = id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', id)
}

function endConversationDrag() {
  draggingId.value = null
  dropTarget.value = null
  rowDropTarget.value = null
}

function dragOverConversation(event, item, groupId = null) {
  if (!draggingId.value || draggingId.value === item.id) return
  event.preventDefault()
  event.stopPropagation()
  event.dataTransfer.dropEffect = 'move'
  const rect = event.currentTarget.getBoundingClientRect()
  rowDropTarget.value = { id: item.id, after: event.clientY >= rect.top + rect.height / 2 }
  dropTarget.value = groupId || 'ungrouped'
}

function dragOverContainer(event, groupId = null) {
  if (!draggingId.value) return
  event.preventDefault()
  event.stopPropagation()
  event.dataTransfer.dropEffect = 'move'
  dropTarget.value = groupId || 'ungrouped'
  rowDropTarget.value = null
}

function leaveConversationRow(event, id) {
  if (!event.currentTarget.contains(event.relatedTarget) && rowDropTarget.value?.id === id) rowDropTarget.value = null
}

async function dropConversation(event, groupId = null, targetId = null) {
  event.preventDefault()
  event.stopPropagation()
  const id = draggingId.value || event.dataTransfer.getData('text/plain')
  const after = rowDropTarget.value?.id === targetId && rowDropTarget.value.after
  endConversationDrag()
  if (!chat.conversations.some(item => item.id === id) || id === targetId) return
  try {
    await conversationBoard.load()
    const node = conversationBoard.ensureNode(id)
    const sameWorkspace = (node.groupId || null) === groupId
    if (sameWorkspace && !targetId) return
    const destination = groupId ? workspaceGroups.value.find(group => group.id === groupId)?.items :
      [...standaloneConversations.value.filter(item => item.pinned), ...groupedConversations.value.flatMap(group => group.items)]
    if (!destination) return
    if (groupId && targetId) {
      const sourceItem = chat.conversations.find(item => item.id === id)
      const targetItem = destination.find(item => item.id === targetId)
      if (targetItem && Boolean(sourceItem.pinned) !== Boolean(targetItem.pinned)) await chat.togglePin(id)
    }
    const ids = destination.map(item => item.id).filter(itemId => itemId !== id)
    const targetIndex = targetId ? ids.indexOf(targetId) : -1
    if (targetId && targetIndex < 0) return
    const insertionIndex = targetIndex < 0 ? ids.length : targetIndex + Number(after)
    ids.splice(insertionIndex, 0, id)
    if (sameWorkspace && ids.every((itemId, index) => itemId === destination[index]?.id)) return
    const previous = board.groups.find(group => group.id === node.groupId)
    if (!sameWorkspace && groupId) {
      const group = board.groups.find(item => item.id === groupId)
      if (!group) return
      const count = Object.values(board.nodes).filter(item => item.groupId === groupId && item !== node).length
      Object.assign(node, { groupId, x: group.x + 24 + count % 2 * 310, y: group.y + 56 + Math.floor(count / 2) * 210 })
      group.width = Math.max(group.width, 660)
      group.height = Math.max(group.height, node.y + 210 - group.y)
    } else if (!sameWorkspace) {
      node.groupId = null
      if (previous) { node.x = previous.x + previous.width + 36; node.y = previous.y + 60 }
    }
    ids.forEach((itemId, index) => { conversationBoard.ensureNode(itemId).sidebarOrder = index })
    delete chat.conversations.find(item => item.id === id).emptyDraft
    if (groupId) {
      const nextCollapsed = new Set(openFolders.value)
      nextCollapsed.add(groupId)
      openFolders.value = nextCollapsed
      const itemIndex = workspaceGroups.value.find(group => group.id === groupId)?.items.findIndex(item => item.id === id)
      if (itemIndex >= workspacePreviewLimit) expandedWorkspaces.value = new Set([...expandedWorkspaces.value, groupId])
    }
    await conversationBoard.save()
  } catch (error) { ui.toast(error.message || '移动会话失败', 'error') }
}
</script>

<template>
  <section class="sidebar-conversations" :class="{ 'batch-mode': batchMode }" @click="menuId = null">
    <!-- 标题行：会话记录 + 数量 + 批量管理 -->
    <div v-if="!batchMode" class="conversation-section-title">
      <span>最近</span>
      <small>{{ chat.conversations.length }}</small>
      <div class="conversation-title-actions">
        <button class="conversation-title-btn workspace-create-btn" type="button" title="创建工作区" aria-label="创建工作区" @click.stop="editWorkspace('create')"><FolderPlus :size="18" /></button>
        <button class="conversation-title-btn map-button" type="button" :title="route.name === 'conversation-map' ? '退出会话地图' : '会话地图'" :aria-label="route.name === 'conversation-map' ? '退出会话地图' : '会话地图'" :aria-pressed="route.name === 'conversation-map'" @click.stop="router.push(route.name === 'conversation-map' ? ui.conversationMapReturnPath : '/conversation-map'); emit('navigate')">
          <MapIcon :size="17" />
        </button>
        <button class="conversation-title-btn" type="button" title="批量管理" @click="enterBatchMode">
          <ListChecks :size="16" />
        </button>
      </div>
    </div>

    <!-- 批量模式工具条 -->
    <div v-else class="conversation-batch-bar">
      <button class="conversation-batch-exit" type="button" title="退出批量管理" @click="exitBatchMode">
        <X :size="15" />
      </button>
      <span class="conversation-batch-count">已选 {{ selected.size }} 项</span>
      <div class="conversation-batch-actions">
        <button type="button" :title="allSelected ? '取消全选' : '全选'"
          :aria-label="allSelected ? '取消全选' : '全选'" :aria-pressed="allSelected"
          @click="toggleSelectAll"><CheckCheck :size="17" /></button>
        <button
          type="button"
          class="danger"
          title="删除所选会话"
          aria-label="删除所选会话"
          :disabled="!selected.size"
          @click="batchDeleteOpen = true"
        >
          <Trash2 :size="17" />
        </button>
      </div>
    </div>

    <div class="conversation-list">
      <div v-if="sidebarEntries.length" class="sidebar-workspaces">
        <template v-for="entry in sidebarEntries" :key="entry.item.id">
        <div v-for="workspace in entry.kind === 'workspace' ? [entry.item] : []" :key="workspace.id" class="sidebar-workspace" :data-workspace-id="workspace.id" :class="{ 'drop-active': dropTarget === workspace.id, 'active-workspace': activeWorkspaceId === workspace.id }" :style="{ '--workspace-color': workspace.color || '#7c3aed' }" @dragover="dragOverContainer($event, workspace.id)" @dragleave.self="dropTarget = null" @drop="dropConversation($event, workspace.id)">
          <div class="sidebar-workspace-heading" @contextmenu="openWorkspaceMenu($event, workspace)">
            <button type="button" class="sidebar-workspace-toggle" :aria-expanded="openFolders.has(workspace.id)" @click="toggleWorkspace(workspace.id)"><component :is="openFolders.has(workspace.id) ? FolderOpen : FolderClosed" class="workspace-folder-icon" :size="17" /><strong>{{ workspace.title }}</strong><Pin v-if="workspace.pinned" class="conversation-pin-marker workspace-pin-marker" :size="12" aria-label="已置顶" /><small>{{ workspace.items.length }}</small></button>
            <button type="button" class="sidebar-workspace-more" title="工作区操作" @click="openWorkspaceMenu($event, workspace)"><MoreHorizontal :size="17" /></button>
          </div>
          <div v-if="openFolders.has(workspace.id)" class="sidebar-workspace-items">
            <button v-for="item in workspaceItems(workspace)" :key="item.id" class="conversation-item workspace-conversation" :data-conversation-id="item.id" :class="{ active: item.id === chat.activeId, 'batch-selected': selected.has(item.id), dragging: draggingId === item.id, 'drop-before': rowDropTarget?.id === item.id && !rowDropTarget.after, 'drop-after': rowDropTarget?.id === item.id && rowDropTarget.after }" type="button" :draggable="!batchMode" @dragstart="startConversationDrag($event, item.id)" @dragend="endConversationDrag" @dragover="dragOverConversation($event, item, workspace.id)" @dragleave="leaveConversationRow($event, item.id)" @drop="dropConversation($event, workspace.id, item.id)" @click="batchMode ? toggleSelect(item.id) : activate(item)">
              <span class="conversation-leading"><span v-if="batchMode" class="conversation-check" :class="{ checked: selected.has(item.id) }"><Check v-if="selected.has(item.id)" :size="13" /></span><MessageSquareText v-else :size="15" /></span>
              <span class="conversation-copy"><strong>{{ item.title }}</strong></span><Pin v-if="item.pinned" class="conversation-pin-marker" :size="12" aria-label="已置顶" />
              <span v-if="!batchMode" class="conversation-trailing"><time class="conversation-time" :datetime="conversationActivityAt(item)">{{ subLabel(item) }}</time><span class="conversation-more" role="button" tabindex="0" title="会话操作" aria-label="会话操作" @click.stop="toggleConversationMenu($event, item)" @keydown.enter.stop="toggleConversationMenu($event, item)" @keydown.space.prevent.stop="toggleConversationMenu($event, item)"><MoreHorizontal :size="17" /></span></span>
            </button>
            <span v-if="!workspace.items.length" class="workspace-empty">拖入会话，或右键创建</span>
            <button v-if="workspaceHiddenCount(workspace)" type="button" class="workspace-show-more" :aria-expanded="expandedWorkspaces.has(workspace.id)" @click="toggleWorkspaceItems(workspace.id)"><component :is="expandedWorkspaces.has(workspace.id) ? ChevronUp : ChevronDown" :size="13" /><span>{{ expandedWorkspaces.has(workspace.id) ? '收起多余会话' : `展开其余 ${workspaceHiddenCount(workspace)} 个会话` }}</span></button>
          </div>
        </div>
            <button v-for="item in entry.kind === 'conversation' ? [entry.item] : []" :key="item.id" class="conversation-item pinned-standalone-conversation" :data-conversation-id="item.id" :class="{ active: item.id === chat.activeId, 'batch-selected': selected.has(item.id), dragging: draggingId === item.id, 'drop-before': rowDropTarget?.id === item.id && !rowDropTarget.after, 'drop-after': rowDropTarget?.id === item.id && rowDropTarget.after }" type="button" :draggable="!batchMode" @dragstart="startConversationDrag($event, item.id)" @dragend="endConversationDrag" @dragover="dragOverConversation($event, item)" @dragleave="leaveConversationRow($event, item.id)" @drop="dropConversation($event, null, item.id)" @click="batchMode ? toggleSelect(item.id) : activate(item)">
              <span class="conversation-leading"><span v-if="batchMode" class="conversation-check" :class="{ checked: selected.has(item.id) }"><Check v-if="selected.has(item.id)" :size="13" /></span><MessageSquareText v-else :size="15" /></span>
              <span class="conversation-copy"><strong>{{ item.title }}</strong></span><Pin v-if="item.pinned" class="conversation-pin-marker" :size="12" aria-label="已置顶" />
              <span v-if="!batchMode" class="conversation-trailing"><time class="conversation-time" :datetime="conversationActivityAt(item)">{{ subLabel(item) }}</time><span class="conversation-more" role="button" tabindex="0" title="会话操作" aria-label="会话操作" @click.stop="toggleConversationMenu($event, item)" @keydown.enter.stop="toggleConversationMenu($event, item)" @keydown.space.prevent.stop="toggleConversationMenu($event, item)"><MoreHorizontal :size="17" /></span></span>
            </button>
        </template>
      </div>
      <div class="standalone-conversations" :class="{ 'drop-active': dropTarget === 'ungrouped', 'is-dragging': draggingId }" @dragover="dragOverContainer($event)" @dragleave.self="dropTarget = null" @drop="dropConversation($event, null)">
        <div v-for="group in groupedConversations" :key="group.key" class="conversation-group">
          <p v-if="group.label" class="conversation-group-title">{{ group.label }}<small>{{ group.items.length }}</small></p>
          <button
            v-for="item in group.items"
            :key="item.id"
            class="conversation-item"
            :data-conversation-id="item.id"
            :class="{ active: item.id === chat.activeId, 'batch-selected': selected.has(item.id), dragging: draggingId === item.id, 'drop-before': rowDropTarget?.id === item.id && !rowDropTarget.after, 'drop-after': rowDropTarget?.id === item.id && rowDropTarget.after }"
            type="button"
            :draggable="!batchMode"
            @dragstart="startConversationDrag($event, item.id)"
            @dragend="endConversationDrag"
            @dragover="dragOverConversation($event, item)"
            @dragleave="leaveConversationRow($event, item.id)"
            @drop="dropConversation($event, null, item.id)"
            @click="batchMode ? toggleSelect(item.id) : activate(item)"
          >
            <span class="conversation-leading">
              <span v-if="batchMode" class="conversation-check" :class="{ checked: selected.has(item.id) }">
                <Check v-if="selected.has(item.id)" :size="13" />
              </span>
              <template v-else>
                <Pin v-if="item.pinned" :size="13" />
                <MessageSquareText v-else :size="15" />
              </template>
            </span>
            <span class="conversation-copy">
              <strong>{{ item.title }}</strong>
            </span>
            <span v-if="!batchMode" class="conversation-trailing">
              <time class="conversation-time" :datetime="conversationActivityAt(item)">{{ subLabel(item) }}</time>
              <span class="conversation-more" role="button" tabindex="0" title="会话操作" aria-label="会话操作" @click.stop="toggleConversationMenu($event, item)" @keydown.enter.stop="toggleConversationMenu($event, item)" @keydown.space.prevent.stop="toggleConversationMenu($event, item)"><MoreHorizontal :size="17" /></span>
            </span>
          </button>
          <div v-if="group.key === 'pinned' && groupedConversations.length > 1" class="conversation-pinned-divider" aria-hidden="true" />
        </div>
        <p v-if="draggingId && !groupedConversations.length" class="standalone-drop-hint">拖到这里成为独立会话</p>
      </div>
      <p v-if="!chat.conversations.length" class="conversation-empty">暂无会话记录</p>
    </div>
  </section>

  <Teleport to="body">
    <Transition name="conversation-menu-pop">
      <div
        v-if="menuItem"
        class="conversation-menu conversation-menu-floating"
        :style="{ top: `${menuPosition.top}px`, left: `${menuPosition.left}px` }"
        @click.stop
      >
        <button type="button" @click="openRename(menuItem)"><Pencil :size="16" />重命名</button>
        <button type="button" @click="toggleConversationPin(menuItem)">
          <Pin :size="16" />{{ menuItem.pinned ? '取消置顶' : '置顶' }}
        </button>
        <button type="button" class="danger" @click="deleteTarget = menuItem; menuId = null">
          <Trash2 :size="16" />删除
        </button>
      </div>
    </Transition>
  </Teleport>

  <Teleport to="body">
    <Transition name="conversation-menu-pop">
      <div v-if="workspaceMenuItem" class="conversation-menu conversation-menu-floating workspace-menu-floating" :style="{ top: `${workspaceMenuPosition.top}px`, left: `${workspaceMenuPosition.left}px` }" @click.stop>
        <button type="button" :disabled="workspaceBusy" @click="askWorkspaceAction('create', workspaceMenuItem)"><MessageSquareText :size="16" />创建会话</button>
        <button type="button" :disabled="workspaceBusy" @click="askWorkspaceAction('pin', workspaceMenuItem)"><Pin :size="16" />{{ workspaceMenuItem.pinned ? '取消置顶' : '置顶工作区' }}</button>
        <button type="button" @click="editWorkspace('rename', workspaceMenuItem)"><Pencil :size="16" />重命名</button>
        <button type="button" class="danger" @click="askWorkspaceAction('delete', workspaceMenuItem)"><Trash2 :size="16" />删除工作区</button>
      </div>
    </Transition>
  </Teleport>

  <ConfirmModal :open="!!workspaceAction" title="删除这个工作区？" message="删除后，工作区中的会话仍会保留，并移到独立会话列表；画布中的工作区也会删除。" :subject="workspaceAction?.title" confirm-text="删除工作区" danger @cancel="workspaceAction = null" @confirm="confirmWorkspaceAction" />

  <Transition name="modal">
    <div v-if="workspaceEditor" class="modal-mask" @click.self="workspaceEditor = null">
      <form class="modal-card rename-modal conversation-rename-modal" @submit.prevent="saveWorkspace">
        <button type="button" class="icon-btn modal-close" aria-label="关闭" @click="workspaceEditor = null"><X :size="19" /></button>
        <div class="rename-modal-head"><span class="dialog-feature-icon"><FolderPlus :size="21" /></span><div><span class="rename-kicker">会话管理</span><h3>{{ workspaceEditor.kind === 'create' ? '创建工作区' : '重命名工作区' }}</h3><p>把同一产品或项目的任务会话整理到一起。</p></div></div>
        <label class="rename-field"><span>工作区名称</span><div class="rename-input-wrap"><FolderClosed :size="18" /><input v-model="workspaceEditor.value" autofocus maxlength="80" placeholder="请输入工作区名称" /><small>{{ workspaceEditor.value.length }} / 80</small></div></label>
        <div class="modal-actions"><button type="button" class="btn secondary" @click="workspaceEditor = null">取消</button><button class="btn" type="submit">{{ workspaceEditor.kind === 'create' ? '创建工作区' : '保存名称' }}</button></div>
      </form>
    </div>
  </Transition>

  <ConfirmModal
    :open="!!deleteTarget"
    title="删除这条会话？"
    message="删除后，对话内容和相关分析记录将无法恢复。"
    :subject="deleteTarget?.title"
    subject-label="即将删除"
    confirm-text="删除会话"
    danger
    @cancel="deleteTarget = null"
    @confirm="removeConversation"
  />

  <ConfirmModal
    :open="batchDeleteOpen"
    title="删除所选会话？"
    message="将同时删除选中的全部会话及其对话内容，操作无法撤销。"
    :subject="`${selected.size} 条会话`"
    subject-label="即将删除"
    confirm-text="删除会话"
    danger
    @cancel="batchDeleteOpen = false"
    @confirm="batchDelete"
  />

  <Transition name="modal">
    <div v-if="renameTarget" class="modal-mask" @click.self="renameTarget = null">
      <form class="modal-card rename-modal conversation-rename-modal" @submit.prevent="saveRename">
        <button type="button" class="icon-btn modal-close" aria-label="关闭" @click="renameTarget = null">
          <X :size="19" />
        </button>
        <div class="rename-modal-head">
          <span class="dialog-feature-icon"><Pencil :size="21" /></span>
          <div>
            <span class="rename-kicker">会话管理</span>
            <h3>重命名会话</h3>
            <p>使用简洁明确的名称，方便之后快速查找。</p>
          </div>
        </div>
        <label class="rename-field">
          <span>会话名称</span>
          <div class="rename-input-wrap">
            <MessageSquareText :size="18" />
            <input v-model="renameValue" autofocus maxlength="40" placeholder="请输入会话名称" />
            <small>{{ renameValue.length }} / 40</small>
          </div>
        </label>
        <div class="modal-actions">
          <button type="button" class="btn secondary" @click="renameTarget = null">取消</button>
          <button class="btn" type="submit">保存名称</button>
        </div>
      </form>
    </div>
  </Transition>
</template>

<style scoped>
.sidebar-conversations{user-select:none}
.sidebar-workspace-toggle small,.workspace-show-more span,.conversation-pin-marker{background:transparent}
/* 标题行：标题靠左，批量操作靠右 */
.conversation-section-title{justify-content:flex-start}
.conversation-title-actions{margin-left:auto;display:flex;align-items:center;gap:4px}
.conversation-title-btn{
  width:34px;height:34px;display:grid;place-items:center;flex:0 0 34px;
  border:1px solid #c5a9e8;border-radius:10px;color:#450b8b;background:#e6d9f7;
  box-shadow:0 2px 7px rgba(76,11,155,.12);cursor:pointer;
}
.conversation-title-btn:hover{color:#380773;background:#dac5f4;border-color:#a97fdc}
.conversation-title-btn:focus-visible,.conversation-batch-exit:focus-visible{outline:2px solid #7c3aed;outline-offset:2px}
.conversation-title-btn svg{width:19px;height:19px;stroke-width:2.3}
.conversation-title-btn.map-button{border-color:transparent;background:transparent;box-shadow:none;color:#766783}
.conversation-title-btn.map-button:hover,.conversation-title-btn.map-button[aria-pressed="true"]{border-color:#d8c1f5;background:#f4edff;color:#6d28d9}
.conversation-title-btn.workspace-create-btn{border-color:transparent;background:transparent;box-shadow:none;color:#766783}.conversation-title-btn.workspace-create-btn:hover{border-color:#d8c1f5;background:#f4edff;color:#6d28d9}
.sidebar-workspaces{display:grid;gap:5px;margin-bottom:8px}.sidebar-workspace{min-width:0;border:1px solid transparent;border-radius:10px}.sidebar-workspace.drop-active{border-color:#aa7ceb;background:#f5edff;box-shadow:0 0 0 2px #a87bef2b}.sidebar-workspace-heading{display:flex;align-items:center;min-width:0}.sidebar-workspace-toggle{display:flex;align-items:center;gap:8px;min-width:0;flex:1;padding:8px 7px;border:0;border-radius:9px;background:transparent;color:#4b365c;text-align:left;cursor:pointer}.sidebar-workspace-toggle:hover{background:#f6f1fb}.sidebar-workspace-toggle strong{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;font-weight:700}.sidebar-workspace-toggle small{color:#a291b2;font-size:10px}.sidebar-workspace-more{display:grid;place-items:center;width:27px;height:27px;flex:none;border:0;border-radius:8px;background:transparent;color:#8b7b9e;opacity:0;cursor:pointer}.sidebar-workspace-heading:hover .sidebar-workspace-more,.sidebar-workspace-more:focus-visible{opacity:1}.sidebar-workspace-more:hover{background:#eee2fb;color:#6424ac}.sidebar-workspace-items{padding-left:13px;border-left:1px solid #dfd3ec;margin-left:14px}.sidebar-workspace-items .conversation-item{min-height:39px}.workspace-empty{display:block;padding:6px 8px;color:#aa9fb4;font-size:11px}.workspace-menu-floating{width:174px}

/* 批量工具条 */
.workspace-folder-icon{flex:none;color:color-mix(in srgb,var(--workspace-color) 55%,#b3a6c1);fill:color-mix(in srgb,var(--workspace-color) 5%,transparent);transition:color .15s,fill .15s}
.sidebar-workspace-heading{border-radius:9px;transition:background .15s}
.sidebar-workspace-heading:hover{background:color-mix(in srgb,var(--workspace-color) 9%,transparent)}
.sidebar-workspace-heading:hover .sidebar-workspace-toggle,.active-workspace .sidebar-workspace-toggle:hover{background:transparent}
.active-workspace .workspace-folder-icon{color:var(--workspace-color);fill:color-mix(in srgb,var(--workspace-color) 30%,white);stroke-width:2.3}
.workspace-show-more{display:flex;align-items:center;gap:5px;width:100%;padding:7px 9px;border:0;border-radius:7px;background:transparent;color:#94859f;font:inherit;font-size:11px;text-align:left;cursor:pointer}
.workspace-show-more:hover{background:transparent;color:#6d28d9}
.workspace-show-more:focus-visible{outline:2px solid #a879e6;outline-offset:1px}
.standalone-conversations{min-width:0;border:1px solid transparent;border-radius:9px}
.standalone-conversations.is-dragging{min-height:40px}
.standalone-conversations.drop-active{border-color:#aa7ceb;background:#f5edff;box-shadow:0 0 0 2px #a87bef2b}
.standalone-drop-hint{margin:0;padding:12px;color:#94859f;text-align:center;font-size:11px}
.conversation-trailing{display:grid;align-items:center;justify-items:end;flex:0 0 auto;min-width:34px;height:27px}
.conversation-time{grid-area:1/1;color:#a09aa7;font-size:10px;font-weight:400;white-space:nowrap;font-variant-numeric:tabular-nums;pointer-events:none}
.sidebar-conversations .conversation-item .conversation-more{grid-area:1/1;opacity:0;visibility:hidden;pointer-events:none;cursor:pointer}
.sidebar-conversations .conversation-item:hover .conversation-more,.sidebar-conversations .conversation-item:focus-visible .conversation-more,.sidebar-conversations .conversation-more:focus-visible{opacity:1;visibility:visible;pointer-events:auto}
.conversation-item:hover .conversation-time,.conversation-item:focus-visible .conversation-time,.conversation-item:has(.conversation-more:focus-visible) .conversation-time{visibility:hidden}
.conversation-more:focus-visible{outline:2px solid #a879e6;outline-offset:1px}
.conversation-item.dragging{cursor:grabbing;box-shadow:inset 0 0 0 1px #c4b5fd}
.conversation-item.drop-before::before,.conversation-item.drop-after::after{content:"";position:absolute;left:7px;right:7px;height:2px;border-radius:2px;background:#8b5cf6;box-shadow:0 0 0 1px #8b5cf61a;pointer-events:none;z-index:1}
.conversation-item.drop-before::before{top:-2px}
.conversation-item.drop-after::after{bottom:-2px}

/* 批量工具条 */
.conversation-batch-bar{display:flex;align-items:center;gap:7px;min-width:0;padding:0 4px 9px;color:#8b95a7;font-size:12px;white-space:nowrap}
.conversation-batch-exit{width:32px;height:32px;display:grid;place-items:center;flex:0 0 32px;border:1px solid #c5a9e8;border-radius:9px;color:#46286a;background:#ebe1f7;box-shadow:0 2px 6px rgba(76,11,155,.1);cursor:pointer}
.conversation-batch-exit:hover{color:#380773;background:#dcc9f3;border-color:#a97fdc}
.conversation-batch-exit svg{width:18px;height:18px;stroke-width:2.4}
.conversation-batch-count{min-width:0;flex:1;font-weight:700;color:#4b3566;white-space:nowrap}
.conversation-batch-actions{margin-left:auto;display:flex;align-items:center;flex:0 0 auto;gap:6px}
.conversation-batch-actions button{width:30px;height:30px;display:grid;place-items:center;flex:0 0 30px;padding:0;border:0;border-radius:9px;color:#5a4278;background:#eae1f5;cursor:pointer}
.conversation-batch-actions button:hover{color:#5611ab;background:#f1eafa}
.conversation-batch-actions button[aria-pressed="true"]{color:#7c3aed;background:#f3effe}
.conversation-batch-actions button.danger{color:#d4384f;background:#fdeef0}
.conversation-batch-actions button.danger:hover{color:#c32b43;background:#fbdde2}
.conversation-batch-actions button:disabled{opacity:.45;cursor:not-allowed}

/* 分组标题 */
.conversation-group{display:grid;gap:3px;margin-bottom:6px}
.conversation-group-title{display:flex;align-items:center;gap:6px;margin:2px 8px 3px;color:#9aa4b6;font-size:11px;font-weight:750;letter-spacing:.03em}
.conversation-group-title small{font-size:10px;font-weight:650;color:#beb3cb}
.conversation-pinned-divider{height:1px;margin:10px 8px 5px;background:linear-gradient(90deg,transparent,#bfa8dc 12%,#bfa8dc 88%,transparent)}

.conversation-pin-marker{flex:none;color:#9972ca;fill:#c6aceb;stroke-width:1.8;margin-right:-5px;transform:translateX(3px)}
.sidebar-workspace-heading{position:relative}
.sidebar-workspace-toggle{width:100%}
.sidebar-workspace-toggle small{flex:0 0 34px;min-width:34px;text-align:right}
.sidebar-workspace-more{position:absolute;right:7px;top:50%;transform:translateY(-50%)}
.sidebar-workspace-heading:hover .sidebar-workspace-toggle small,.sidebar-workspace-heading:focus-within .sidebar-workspace-toggle small{visibility:hidden}
.sidebar-workspace-heading:focus-within .sidebar-workspace-more{opacity:1}
.workspace-pin-marker{margin-right:-4px}

/* 批量选择 */
.conversation-check{width:20px;height:20px;display:grid;place-items:center;margin:auto;border:2px solid #896bad;border-radius:6px;color:#fff;background:#fff;box-shadow:0 0 0 2px rgba(76,11,155,.08);transition:.14s}
.conversation-item:hover .conversation-check{border-color:#7c3aed;background:#f3effe}
.conversation-check.checked,.conversation-item:hover .conversation-check.checked{border-color:#7c3aed;background:#7c3aed;box-shadow:0 0 0 2px rgba(124,58,237,.16)}
.conversation-item.batch-selected{background:#f3effe;color:#6d28d9}
</style>
