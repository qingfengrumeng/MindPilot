<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useAuthStore } from '@/stores/auth'
import { useConversationBoardStore } from '@/stores/conversationBoard'
import { useUiStore } from '@/stores/ui'
import { createSynapseBridge } from '@/lib/synapseBridge'

const props = defineProps({ deepThinking: Boolean, active: Boolean })
const emit = defineEmits(['close', 'open-message'])
const chat = useChatStore(), auth = useAuthStore(), boardStore = useConversationBoardStore(), ui = useUiStore()
const frame = ref(null), ready = ref(false)
const frameUrl = `${import.meta.env.BASE_URL}synapse/index.html`
const publish = (type, payload = {}) => frame.value?.contentWindow?.postMessage(JSON.parse(JSON.stringify({ source: 'dsh-synapse', type, ...payload })), location.origin)
const bridge = createSynapseBridge({ chat, conversationBoard: boardStore, publish, notify: message => ui.toast(message, 'error') })
async function initialize() { await boardStore.load(); if (!chat.loaded) await chat.loadConversations(); ready.value = true; bridge.sync() }
async function message(event) {
  if (event.origin !== location.origin || event.source !== frame.value?.contentWindow || event.data?.source !== 'dsh-synapse') return
  const data = event.data
  try {
    if (data.type === 'synapse:bootstrap') {
      await initialize()
      publish('synapse:bootstrap-result', { requestId: data.requestId, owner: auth.user?.id || auth.user?.username || 'demo', state: boardStore.board.synapse || {} })
    } else if (data.type === 'synapse:api') {
      publish('synapse:api-result', { requestId: data.requestId, value: await bridge.api(data.path, data.method, data.body) })
    } else if (data.type === 'synapse:request-current') { bridge.sync(); publish('synapse:theme', { dark: false }); publish('synapse:visibility', { active: props.active }) }
    else if (data.type === 'synapse:close') emit('close')
    else if (data.type === 'synapse:persist') bridge.persist(data.key, data.value)
    else if (data.type === 'synapse:create-session') publish('synapse:created-session', { requestId: data.requestId, session: await bridge.createSession(data.workspaceId) })
    else if (data.type === 'synapse:fork-session') publish('synapse:forked-session', { requestId: data.requestId, session: await bridge.fork(data.sessionId, data.atSeq) })
    else if (data.type === 'synapse:send-message') { const result = await bridge.send(data.sessionId, data.text, { deepThinking: props.deepThinking }); publish('synapse:message-sent', { requestId: data.requestId, ...result }) }
    else if (['synapse:open-session', 'synapse:activate-session'].includes(data.type)) {
      if (!chat.conversations.some(item => item.id === data.sessionId)) throw new Error('会话不存在')
      if (bridge.running.has(data.sessionId)) { chat.activeId = data.sessionId; chat.messages = bridge.running.get(data.sessionId).messages }
      else await chat.loadMessages(data.sessionId)
      chat.generating = bridge.running.has(data.sessionId)
      bridge.sync()
      if (data.type === 'synapse:open-session') { emit('open-message', { sessionId: data.sessionId, seq: data.seq }); emit('close') }
    }
  } catch (error) {
    if (data.type === 'synapse:api') publish('synapse:api-result', { requestId: data.requestId, error: error.message })
    else publish('synapse:bridge-error', { requestId: data.requestId, message: error.message || '地图操作失败' })
  }
}
watch(() => props.active, value => { if (ready.value) { publish('synapse:visibility', { active: value }); if (value) { bridge.sync(); publish('synapse:map-opened') } } })
watch(() => chat.conversations.map(item => `${item.id}:${item.title}`).join('|'), () => { if (ready.value) bridge.sync() })
watch(() => chat.activeId, () => { if (ready.value) { chat.generating = bridge.running.has(chat.activeId); bridge.sync() } })
watch(() => boardStore.board.groups.map(item => `${item.id}:${item.title}`).join('|'), () => { if (ready.value) bridge.sync() })
watch(() => Object.entries(boardStore.board.nodes).map(([id, item]) => `${id}:${item.groupId}:${item.synapseParentId}:${item.synapseMapId}`).join('|'), () => { if (ready.value) bridge.sync() })
onMounted(() => window.addEventListener('message', message))
onBeforeUnmount(() => { window.removeEventListener('message', message); bridge.dispose().catch(error => ui.toast(error.message, 'error')) })
</script>

<template>
  <section class="synapse-embedded" aria-label="对话地图">
    <iframe ref="frame" :src="frameUrl" aria-label="对话地图" />
  </section>
</template>

<style scoped>
.synapse-embedded{position:relative;flex:1;min-height:0;overflow:hidden}.synapse-embedded iframe{display:block;width:100%;height:100%;border:0;background:#fbf8ff}
</style>
