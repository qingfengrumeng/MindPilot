import { reactive, ref } from 'vue'
import { defineStore } from 'pinia'
import { conversationMapApi } from '@/api/conversationMap'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'

const emptyBoard = () => ({ nodes: {}, groups: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 }, synapse: {} })

/** The sidebar and canvas edit the same board so workspace membership cannot drift. */
export const useConversationBoardStore = defineStore('conversation-board', () => {
  const board = reactive(emptyBoard())
  const loaded = ref(false)
  const previews = ref({})
  let loading = null
  let saving = Promise.resolve()
  let owner = null
  let epoch = 0

  function currentOwner() {
    const user = useAuthStore().user
    return user?.id || user?.username || 'demo'
  }

  function resetForOwner() {
    const nextOwner = currentOwner()
    if (owner === nextOwner) return
    owner = nextOwner
    epoch++
    loading = null
    saving = Promise.resolve()
    Object.assign(board, emptyBoard())
    previews.value = {}
    loaded.value = false
  }

  async function load() {
    resetForOwner()
    if (loaded.value) return { state: board, previews: previews.value }
    if (loading) return loading
    const version = epoch
    loading = conversationMapApi.load().then(result => {
      if (version === epoch) {
        Object.assign(board, emptyBoard(), result.state || {})
        previews.value = result.previews || {}
        loaded.value = true
      }
      return result
    }).finally(() => { if (version === epoch) loading = null })
    return loading
  }

  function save() {
    resetForOwner()
    const chat = useChatStore()
    if (chat.loaded) {
      const ids = new Set(chat.conversations.map(item => item.id))
      for (const id of Object.keys(board.nodes)) if (!ids.has(id)) delete board.nodes[id]
      board.edges = board.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target))
    }
    const state = JSON.parse(JSON.stringify(board))
    saving = saving.catch(() => {}).then(() => conversationMapApi.save(state))
    return saving
  }

  function ensureNode(id, groupId = null) {
    if (!board.nodes[id]) {
      const index = Object.keys(board.nodes).length
      board.nodes[id] = { x: 80 + index % 4 * 310, y: 110 + Math.floor(index / 4) * 220,
        digest: {}, hidden: false, removed: false, groupId }
    }
    return board.nodes[id]
  }

  async function createWorkspace(title, options = {}) {
    await load()
    const group = { id: crypto.randomUUID(), title, x: options.x ?? 80, y: options.y ?? 100,
      width: 660, height: 300, color: options.color || '#7c3aed', hidden: false, removed: false, pinned: false }
    board.groups.push(group)
    try { await createWorkspaceConversation(group.id); return group }
    catch (error) { board.groups = board.groups.filter(item => item.id !== group.id); throw error }
  }

  async function createWorkspaceConversation(groupId = null, { reuseBlank = false } = {}) {
    await load()
    const chat = useChatStore()
    if (!chat.loaded) await chat.loadConversations()
    if (reuseBlank && chat.activeId && !chat.messages.length && (board.nodes[chat.activeId]?.groupId || null) === groupId) return chat.activeId
    await chat.newChat({ keepEmpty: Boolean(groupId) })
    const node = ensureNode(chat.activeId)
    const group = board.groups.find(item => item.id === groupId)
    if (group) {
      const count = Object.values(board.nodes).filter(item => item.groupId === groupId).length
      const row = Math.floor(count / 2)
      Object.assign(node, { groupId, x: group.x + 24 + count % 2 * 310, y: group.y + 56 + row * 210 })
      group.width = Math.max(group.width, 660)
      group.height = Math.max(group.height, 56 + (row + 1) * 210 + 24)
    }
    await save()
    return chat.activeId
  }

  return { board, loaded, previews, load, save, ensureNode, createWorkspace, createWorkspaceConversation }
})
