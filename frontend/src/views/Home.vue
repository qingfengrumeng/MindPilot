<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AudioLines,
  Atom,
  Bot,
  Check,
  ExternalLink,
  Keyboard,
  LibraryBig,
  Mic,
  Network,
  NotebookText,
  PhoneCall,
  Paperclip,
  Send,
  Square,
  Play,
  Sparkles,
  X
} from 'lucide-vue-next'
import PageShell from '@/components/PageShell.vue'
import SynapseConversationMap from '@/components/SynapseConversationMap.vue'
import ChatMessage from '@/components/ChatMessage.vue'
import FollowUpQuestions from '@/components/FollowUpQuestions.vue'
import { createFollowupSession, fallbackFollowups } from '@/lib/followupSession'
import DrawingProcess from '@/components/DrawingProcess.vue'
import AgentMonitorPanel from '@/components/AgentMonitorPanel.vue'
import ConversationOutline from '@/components/ConversationOutline.vue'
import SkillPalette from '@/components/SkillPalette.vue'
import ComposerEditor from '@/components/ComposerEditor.vue'
import ComposerAttachments from '@/components/ComposerAttachments.vue'
import AttachmentPreview from '@/components/AttachmentPreview.vue'
import SkillInfoDialog from '@/components/SkillInfoDialog.vue'
import { SKILL_GROUPS, SKILLS, findSkill, skillsByGroup } from '@/skills'
import { chatApi, documentsApi, visualizationApi, wikiApi } from '@/api'
import { backendEnabled } from '@/api/http'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'
import { playMorphIn } from '@/lib/jarvisSound'
import { startLiveAsr } from '@/lib/liveAsr'
import { userMessageForSequence } from '@/lib/conversationNavigation'

const chat = useChatStore()
const auth = useAuthStore()
const conversationViewKey = computed(() => `mindpilot:${auth.user?.id || auth.user?.username || 'anonymous'}:conversation-view`)
function savedConversationView() {
  try { return sessionStorage.getItem(conversationViewKey.value) === 'map' ? 'map' : 'dialog' }
  catch { return 'dialog' }
}
const conversationView = ref(savedConversationView())
watch(conversationView, value => {
  try { sessionStorage.setItem(conversationViewKey.value, value) } catch { /* Storage can be unavailable. */ }
}, { flush: 'sync' })
watch(conversationViewKey, () => { conversationView.value = savedConversationView() }, { flush: 'sync' })
const mapInitialized = ref(false)
const mapNavigationSpace = ref(0)
const outlineAvailable = computed(() => chat.messages.some(item => item.role === 'user'))
let mapNavigationPending = false
let mapNavigationTop = null
async function openMapMessage({ sessionId, seq }) {
  mapNavigationPending = true
  followFeed.value = false
  conversationView.value = 'dialog'
  mapNavigationSpace.value = 0
  try {
    const { useConversationBoardStore } = await import('@/stores/conversationBoard')
    if (chat.activeId !== sessionId) return
    const boardStore = useConversationBoardStore()
    const message = userMessageForSequence(chat.messages, boardStore.board.nodes[sessionId]?.synapseSequences, seq)
    await nextTick()
    await navigateToQuestion(message?.id)
  } finally {
    followFeed.value = false
    mapNavigationPending = false
  }
}
async function navigateToQuestion(id) {
  if (!id) return
  mapNavigationPending = true
  followFeed.value = false
  mapNavigationSpace.value = 0
  try {
    await nextTick()
    const element = document.getElementById(`chat-message-${id}`)
    const container = feed.value
    if (!element || !container) return
    const top = Math.max(0, container.scrollTop + element.getBoundingClientRect().top - container.getBoundingClientRect().top - 20)
    // Short replies still need enough space below to align their question at the top.
    mapNavigationSpace.value = Math.max(0, top + container.clientHeight - container.scrollHeight)
    await nextTick()
    mapNavigationTop = top
    container.scrollTo({ top, behavior: 'instant' })
  } finally {
    followFeed.value = false
    mapNavigationPending = false
  }
}
const assistantStreaming = computed(() => chat.messages.some(item => /^local-assistant-\d+$/.test(String(item.id)) && Boolean(item.content)))
const ui = useUiStore()
const app = useAppStore()
const route = useRoute()
const router = useRouter()
const message = ref('')
const files = ref([])
const fileInput = ref()
const attachmentPreview = ref(null)
const previewUrls = new Set()
const freshFollowups = ref(null)
const followupSession=createFollowupSession({
  request:(conversationId,question)=>backendEnabled ? chatApi.suggestions(conversationId,question) : Promise.resolve({items:fallbackFollowups(question)}),
  onChange:value=>{freshFollowups.value=value}
})
watch(()=>chat.messages.filter(item=>item.role==='user').at(-1)?.id,id=>{
  if(!chat.generating || !String(id||'').startsWith('local-user-') || !chat.activeId)return
  const user=chat.messages.filter(item=>item.role==='user').at(-1)
  followupSession.begin(chat.activeId,id,user.transcript||user.content||'')
},{flush:'sync'})
watch(()=>[chat.generating,chat.messages.at(-1)?.id],()=>{
  const last=chat.messages.at(-1)
  if(chat.generating || chat.outputPaused || !freshFollowups.value || last?.role!=='assistant' || last.failed || String(last.id).startsWith('local-'))return
  const user=chat.messages.filter(item=>item.role==='user').at(-1)
  followupSession.finish(chat.activeId,last.id,user?.transcript||user?.content||'')
})
watch(() => chat.activeId, () => {
  message.value = ''
  files.value = []
  closeAttachmentPreview()
  for (const url of previewUrls) URL.revokeObjectURL(url)
  previewUrls.clear()
})
watch(()=>[chat.activeId,auth.user?.id],()=>followupSession.clear(),{flush:'sync'})
let sentPreviewUrl = null
let previewRequest = 0

function closeAttachmentPreview() {
  previewRequest += 1
  attachmentPreview.value = null
  if (sentPreviewUrl) URL.revokeObjectURL(sentPreviewUrl)
  sentPreviewUrl = null
}

function openComposerAttachment(file) {
  closeAttachmentPreview()
  attachmentPreview.value = file
}

async function openSentAttachment(file) {
  closeAttachmentPreview()
  const request = previewRequest
  if (!file.previewUrl?.startsWith('blob:')) {
    attachmentPreview.value = file
    return
  }
  try {
    const image = await fetch(file.previewUrl).then(response => response.blob())
    if (request !== previewRequest) return
    sentPreviewUrl = URL.createObjectURL(image)
    attachmentPreview.value = { ...file, previewUrl: sentPreviewUrl }
  } catch {
    if (request === previewRequest) attachmentPreview.value = file
  }
}
const attachmentBusy = computed(() => files.value.some(file => file.uploading))
const feed = ref()
const followFeed = ref(true)
const voiceMode = ref(false)
const deepThinking = ref(false)
const dictating = ref(false)
const recordingVoice = ref(false)
const voiceSeconds = ref(0)
const activeContext = ref(null)
let recordingTimer = null
let mediaRecorder = null
let mediaStream = null
let audioChunks = []
let liveDictation = null
let liveVoice = null
let liveDictationPrefix = ''
let voiceStartPending = false
let voiceStopRequested = false

/** 进入虚拟助手：先放「凝聚成形」的声效，再整页切到全息界面。 */
async function enterAssistant() {
  if (!chat.loaded) await chat.loadConversations()
  playMorphIn()
  router.push({ path: '/assistant', query: chat.activeId ? { conversationId: chat.activeId } : {} })
}

/** 从其他页面带入的上下文类型：资料 / Wiki 页面 / 可视化产物。 */
const contextKinds = {
  document: { label: '知识资料', to: '/documents', icon: LibraryBig },
  wiki: { label: 'LLM Wiki', to: '/wiki', icon: NotebookText },
  artifact: { label: '可视化产物', to: '/visualization', icon: Network }
}

/** 按 query 里的 context + id 取回上下文摘要，失败时静默忽略。 */
async function loadContext(kind, id) {
  if (!id) return null
  try {
    if (kind === 'document') {
      const document = await documentsApi.get(id)
      return {
        ...contextKinds.document,
        title: document.title,
        meta: `${document.typeLabel} · ${document.pages} 页 · ${app.domainLabel(document.domain)}`,
        content: `已载入《${document.title}》。你可以让我总结要点、定位具体章节、与库内其他资料对比，或把它整理进LLM Wiki。`
      }
    }
    if (kind === 'wiki') {
      const page = await wikiApi.get(id)
      const body = page?.body || []
      return {
        ...contextKinds.wiki,
        title: page.title,
        meta: `${page.typeLabel} · ${body.length} 个章节 · ${page.stale ? '内容待更新' : `更新于 ${page.updatedAt}`}`,
        content: `已载入Wiki页面「${page.title}」。你可以让我梳理脉络、补充缺失结论，或与关联页面做差异对比。`
      }
    }
    if (kind === 'artifact') {
      const result = await visualizationApi.artifacts()
      const artifact = (result.items || []).find(item => item.id === id)
      if (!artifact) return null
      return {
        ...contextKinds.artifact,
        title: artifact.title,
        meta: `${artifact.typeLabel} · ${artifact.nodes ?? 0} 个节点 · ${artifact.createdAt}`,
        content: `已载入可视化产物「${artifact.title}」。你可以让我解读结构、指出缺失的关联，或基于它生成新的视图。`
      }
    }
  } catch {
    // 上下文已失效（例如资料被删除）时不影响正常提问。
  }
  return null
}

const conversationTitle = computed(() => {
  const title = chat.activeConversation?.title?.trim()
  const characters = Array.from(title || '新会话')
  return characters.length > 10 ? `${characters.slice(0, 10).join('')}...` : characters.join('')
})

/* ------------------------------------------------------------------ *
 * 能力（技能）驱动：示例、/ 面板与输入框里的能力标识都取自同一份注册表
 * ------------------------------------------------------------------ */

/** 当前挂在输入框上的能力 id：有值时输入框首行出现能力标识，并带上它专属的系统提示词。 */
const activeSkillId = ref(null)
const workBusy = ref(false)

const infoSkill = ref(null)
const activeSkill = computed(() => findSkill(activeSkillId.value))
const featureTypes = computed(() => skillsByGroup('artifacts'))
const composerPlaceholder = computed(() => {
  // 只挂着标识、正文还空着：提示这里该写什么，提示词交给用户自己写。
  if (activeSkill.value) return `写下要让「${activeSkill.value.label}」处理的内容`
  return '输入问题直接提问，也可选择功能或输入 / 查看能力列表'
})
/** 占位符是 CSS 画的，读屏读不到，给输入框配一句等价的说明。 */
const composerLabel = computed(() => {
  const skill = activeSkill.value
  return skill ? `已载入「${skill.label}」，写下要让这条能力处理的内容` : composerPlaceholder.value
})

function isRealtimeMarker(item) {
  return item?.metadata?.type === 'realtime_marker' || item?.type === 'realtime_marker'
}

/* --- 输入框里的「/」能力面板 --- */

/**
 * 输入框以 / 开头即进入能力检索；面板内容全部由输入派生，不会和输入状态不同步。
 * 所有会话均可通过 / 选择能力。
 */
const paletteQuery = computed(() => {
  const value = message.value
  if (!value.startsWith('/')) return null
  const rest = value.slice(1)
  if (rest.includes('\n')) return null
  return rest.trim().toLowerCase()
})
const paletteOpen = computed(() => paletteQuery.value !== null)
const paletteResults = computed(() => {
  const query = paletteQuery.value
  if (query === null) return []
  if (!query) return SKILLS
  return SKILLS.filter(item =>
    `${item.label} ${item.description} ${item.sample} ${item.id}`.toLowerCase().includes(query)
  )
})
/** 按能力分组，并给每行一个跨组连续的序号，键盘上下移动直接用它。 */
const paletteGroups = computed(() => {
  let cursor = 0
  return SKILL_GROUPS
    .map(group => ({
      id: group.id,
      label: group.label,
      items: paletteResults.value
        .filter(item => item.group === group.id)
        .map(item => ({ ...item, flatIndex: cursor++ }))
    }))
    .filter(group => group.items.length)
})
const paletteFlat = computed(() => paletteGroups.value.flatMap(group => group.items))
const paletteIndex = ref(0)
watch(paletteQuery, () => { paletteIndex.value = 0 })

/* --- 输入框：标识按钮与可编辑正文分别管理 ---
 * 浏览器只能修改 ComposerEditor 内的正文，避免删除操作破坏 Vue 的标识节点。
 */

const editor = ref()

function caretOffset() { return editor.value?.caretOffset() || 0 }
function insertEditorText(text) { editor.value?.insert(text) }
function focusComposer() { nextTick(() => editor.value?.focus()) }

/**
 * 挂上一条能力：输入框首行出现它的标识。
 *
 * 两条入口铺的东西不一样：
 * - 点成果卡片（loadExample）把这条能力的完整示例落进框里——那是句能直接发出去的话，
 *   用户就着它改，或者直接回车；
 * - 从 / 面板挑（不铺示例）只给标识，提示词由用户自己写——面板里那段 / 查询只是手柄，
 *   选中后不留痕，上一条能力留下的原样示例也一并清掉，用户自己写过的内容不动。
 * 选用能力不改变当前会话。
 */
function activateSkill(item, { loadExample = true } = {}) {
  const previous = activeSkill.value
  if (paletteOpen.value) message.value = ''
  else if (previous && message.value === previous.example) message.value = ''
  activeSkillId.value = item.id
  if (loadExample && !message.value.trim()) message.value = item.example
  focusComposer()
}

/** 摘掉能力标识；输入框里还是原样示例时一并清空。 */
function clearSkill() {
  const current = activeSkill.value
  if (current && message.value === current.example) message.value = ''
  activeSkillId.value = null
  focusComposer()
}

/** 功能卡片：再点一次取消，点别的直接换过去。 */
function selectWorkType(item) {
  if (activeSkillId.value === item.id) clearSkill()
  else activateSkill(item)
}

function movePalette(step) {
  const total = paletteFlat.value.length
  if (!total) return
  paletteIndex.value = (paletteIndex.value + step + total) % total
}

function pickPalette(index) {
  const item = paletteFlat.value[index]
  // 面板只负责换工具，不铺示例：提示词留给用户自己写。
  if (item) activateSkill(item, { loadExample: false })
}

function onComposerKeydown(event) {
  if (paletteOpen.value) {
    if (event.key === 'ArrowDown') { event.preventDefault(); movePalette(1); return }
    if (event.key === 'ArrowUp') { event.preventDefault(); movePalette(-1); return }
    if (event.key === 'Enter') { event.preventDefault(); pickPalette(paletteIndex.value); return }
    if (event.key === 'Escape') { event.preventDefault(); message.value = ''; return }
  }
  // 标识是提示词开头的第一个 token：光标停在正文最前面时按退格，和删掉这段文字一样把它删掉。
  if (event.key === 'Backspace' && activeSkill.value && !event.isComposing) {
    if (window.getSelection()?.isCollapsed && caretOffset() === 0) {
      event.preventDefault()
      clearSkill()
      return
    }
  }
  // 换行交给输入框自己排版，插完仍然是纯文本。
  if (event.key === 'Enter' && event.shiftKey && !event.isComposing) {
    event.preventDefault()
    insertEditorText('\n')
    return
  }
  // 中文输入法组词时的回车用于选词，不能当作发送。
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    send()
  }
}

function scrollFeed(force = false) {
  if (mapNavigationPending) return
  if (force) { mapNavigationTop = null; mapNavigationSpace.value = 0; followFeed.value = true }
  if (!followFeed.value) return
  nextTick(() => {
    const feedElement = feed.value
    if (feedElement && followFeed.value && !mapNavigationPending) feedElement.scrollTop = feedElement.scrollHeight
  })
}

function onFeedScroll(event) {
  if (mapNavigationPending) return
  const element = event.target
  if (mapNavigationTop !== null && Math.abs(element.scrollTop - mapNavigationTop) < 1) return
  mapNavigationTop = null
  followFeed.value = element.scrollHeight - element.scrollTop - element.clientHeight < 64
}

const textFilePattern = /\.(txt|md|markdown|csv|json|log|yaml|yml|xml|html|css|js|jsx|ts|tsx|py|java|sql|sh)$/i
const imageTypes = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])

function fileSize(bytes) {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function removeFile(localId) {
  const index = files.value.findIndex(item => item.localId === localId)
  if (index < 0) return
  const [removed] = files.value.splice(index, 1)
  if (attachmentPreview.value?.localId === localId) closeAttachmentPreview()
  if (removed.previewUrl) {
    URL.revokeObjectURL(removed.previewUrl)
    previewUrls.delete(removed.previewUrl)
  }
}

async function addFiles(selected) {
  const pending = []
  for (const file of Array.from(selected || [])) {
    const fileLimit = activeSkill.value?.id === 'poster' ? 8 : 5
    if (files.value.length >= fileLimit) { ui.toast(`一次最多添加 ${fileLimit} 个附件`, 'warning'); break }
    const isImage = imageTypes.has(file.type)
    const isText = textFilePattern.test(file.name)
    if (!isImage && !isText) { ui.toast(`暂不支持“${file.name}”的文件格式`, 'warning'); continue }
    const imageLimit = activeSkill.value?.id === 'poster' ? 20 : 64
    if (isImage && file.size > imageLimit * 1024 * 1024) { ui.toast(`图片不能超过 ${imageLimit} MiB`, 'warning'); continue }
    if (isText && file.size > 150 * 1024) { ui.toast('文本附件不能超过150 KB', 'warning'); continue }
    const localId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    const item = { localId, name: file.name, size: fileSize(file.size), type: isImage ? 'image' : 'text', mimeType: file.type, uploading: true }
    if (isImage) {
      item.previewUrl = URL.createObjectURL(file)
      previewUrls.add(item.previewUrl)
    }
    files.value.push(item)
    pending.push((async () => {
      try {
        if (isImage) {
          const form = new FormData()
          form.append('file', file)
          const uploaded = activeSkill.value?.id === 'poster' ? await chatApi.uploadPosterAsset(form) : await chatApi.uploadFile(form)
          const current = files.value.find(entry => entry.localId === localId)
          if (current) Object.assign(current, { id: uploaded.id, previewId: uploaded.previewId, uploading: false })
        } else {
          const content = await file.text()
          if (!content.trim()) throw new Error('文本附件内容为空')
          if (content.length > 50000) throw new Error('文本附件不能超过50000个字符')
          const current = files.value.find(entry => entry.localId === localId)
          if (current) Object.assign(current, { content, uploading: false })
        }
      } catch (error) {
        removeFile(localId)
        ui.toast(error?.message || `“${file.name}”添加失败`, 'error')
      }
    })())
  }
  await Promise.all(pending)
}

function selectFiles(event) {
  const selected = Array.from(event.target.files || [])
  event.target.value = ''
  addFiles(selected)
}

function pasteLongText(text) {
  const stamp = new Date().toLocaleString('sv-SE').replace(/[ :]/g, '-')
  addFiles([new File([text], `粘贴内容-${stamp}.txt`, { type: 'text/plain' })])
}

async function stopDictation() {
  if (liveDictation) {
    const session = liveDictation
    liveDictation = null
    dictating.value = false
    try {
      const text = await session.stop()
      message.value = `${liveDictationPrefix}${liveDictationPrefix && text ? ' ' : ''}${text}`
    } catch (error) {
      ui.toast(error?.message || '语音转文字失败，请检查ASR配置', 'error')
    }
    return
  }
  dictating.value = false
}

async function toggleDictation() {
  if (dictating.value) return stopDictation()
  voiceMode.value = false
  if (!backendEnabled) {
    ui.toast('语音转文字需要连接后端ASR服务', 'error')
    return
  }
  try {
    liveDictationPrefix = message.value
    liveDictation = await startLiveAsr(text => {
      message.value = `${liveDictationPrefix}${liveDictationPrefix && text ? ' ' : ''}${text}`
    }, null, { requireSpeech: true })
    dictating.value = true
  } catch (error) {
    ui.toast(error?.message || '无法启动实时语音识别', 'error')
  }
}

function toggleVoiceMode() {
  stopDictation()
  voiceMode.value = !voiceMode.value
}

async function startVoiceRecording(event) {
  if (recordingVoice.value || voiceStartPending) return
  if (backendEnabled) {
    voiceStartPending = true
    voiceStopRequested = false
    event.currentTarget?.setPointerCapture?.(event.pointerId)
    try {
      liveVoice = await startLiveAsr()
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioChunks = []
      mediaRecorder = new MediaRecorder(mediaStream)
      mediaRecorder.addEventListener('dataavailable', value => { if (value.data?.size) audioChunks.push(value.data) })
      mediaRecorder.start()
      recordingVoice.value = true
      voiceSeconds.value = 0
      clearInterval(recordingTimer)
      recordingTimer = setInterval(() => {
        voiceSeconds.value = Math.min(60, voiceSeconds.value + 1)
        if (voiceSeconds.value >= 60) finishVoiceRecording()
      }, 1000)
      if (voiceStopRequested) finishVoiceRecording()
    } catch (error) {
      ui.toast(error?.message || '无法启动实时语音识别', 'error')
    } finally {
      voiceStartPending = false
    }
    return
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    event.currentTarget?.setPointerCapture?.(event.pointerId)
    audioChunks = []
    mediaRecorder = new MediaRecorder(mediaStream)
    mediaRecorder.addEventListener('dataavailable', value => {
      if (value.data?.size) audioChunks.push(value.data)
    })
    mediaRecorder.start()
    recordingVoice.value = true
    voiceSeconds.value = 0
    clearInterval(recordingTimer)
    recordingTimer = setInterval(() => {
      voiceSeconds.value = Math.min(60, voiceSeconds.value + 1)
      if (voiceSeconds.value >= 60) finishVoiceRecording()
    }, 1000)
  } catch {
    ui.toast('无法使用麦克风，请在浏览器设置中允许录音权限', 'error')
  }
}

async function finishVoiceRecording() {
  if (backendEnabled && voiceStartPending && !recordingVoice.value) {
    voiceStopRequested = true
    return
  }
  if (!recordingVoice.value) return
  recordingVoice.value = false
  clearInterval(recordingTimer)
  recordingTimer = null
  if (backendEnabled && liveVoice) {
    const session = liveVoice
    liveVoice = null
    const duration = Math.max(1, voiceSeconds.value)
    voiceSeconds.value = 0
    try {
      const text = await session.stop()
      if (!text) throw new Error('未识别到语音，请重试')
      const recorder = mediaRecorder
      const blob = await new Promise(resolve => {
        if (!recorder) return resolve(new Blob(audioChunks, { type: 'audio/webm' }))
        recorder.addEventListener('stop', () => resolve(new Blob(audioChunks, { type: recorder.mimeType || 'audio/webm' })), { once: true })
        recorder.stop()
      })
      mediaStream?.getTracks().forEach(track => track.stop())
      mediaRecorder = null
      mediaStream = null
      await chat.sendVoice(blob, duration, text)
      scrollFeed()
    } catch (error) {
      ui.toast(error?.message || '语音提问失败，请检查ASR配置', 'error')
    }
    return
  }
  const duration = Math.max(1, voiceSeconds.value)
  voiceSeconds.value = 0
  const recorder = mediaRecorder
  const blob = await new Promise(resolve => {
    recorder.addEventListener('stop', () => resolve(new Blob(audioChunks, { type: recorder.mimeType || 'audio/webm' })), { once: true })
    recorder.stop()
  })
  mediaStream?.getTracks().forEach(track => track.stop())
  mediaRecorder = null
  mediaStream = null
  await chat.sendVoice(blob, duration)
  scrollFeed()
}

function formatVoiceTime(value) {
  return `00:${String(value).padStart(2, '0')}`
}

/** 将这次请求落成一份真实产物，可在「知识可视化」里打开与导出。 */
async function generateArtifact(body, skill) {
  workBusy.value = true
  try {
    const artifact = await visualizationApi.generate({
      type: skill.artifactType,
      title: body.slice(0, 24) || skill.defaultTitle,
      domain: auth.user?.defaultDomain || 'personal_learning'
    })
    chat.messages.push({
      id: `work-${artifact.id}`,
      role: 'assistant',
      content: `已生成《${artifact.title}》（${artifact.typeLabel}）。产物保存在本地，可在「知识可视化」中打开、继续编辑或导出。`,
      createdAt: new Date().toISOString()
    })
    ui.toast(`《${artifact.title}》已生成，可在「知识可视化」中查看`)
    scrollFeed()
  } catch (error) {
    ui.toast(error?.message || '产物生成失败，请稍后重试', 'error')
  } finally {
    workBusy.value = false
  }
}

async function send() {
  if (chat.generating || attachmentBusy.value) return
  const content = message.value.trim()
  if (!content && !files.value.length) {
    // 只挂了标识、正文空着：这时的回车该说一句，而不是悄无声息。
    if (activeSkill.value) ui.toast(`写下要让「${activeSkill.value.label}」处理的内容，再发送`, 'error')
    return
  }
  const skill = activeSkill.value
  const attachments = [...files.value]
  const sendingConversationId = chat.activeId
  const sendingUserId = auth.user?.id
  // 框里那句话本身就是这次要处理的内容（卡片铺进来的完整示例也是原样发出）；
  // 只挂了附件没写要求时，以附件为对象。
  const outgoing = content
  message.value = ''
  activeSkillId.value = null
  files.value = []
  const sent = await chat.send(outgoing, attachments, skill, { attachments: attachments.map(file => ({
    id: file.id, name: file.name, type: file.type, content: file.content,
    previewId: file.previewId, previewUrl: file.previewUrl
  })) }, { deepThinking: deepThinking.value })
  if (!sent && !chat.generating && !message.value && auth.user?.id === sendingUserId &&
      (!sendingConversationId || chat.activeId === sendingConversationId)) {
    message.value = content
    files.value = attachments
    activeSkillId.value = skill?.id || null
  }
  scrollFeed()
  if (sent && !backendEnabled && skill?.artifactType) await generateArtifact(outgoing, skill)
}

async function sendFollowup(question) {
  if(chat.generating || chat.outputPaused || workBusy.value || attachmentBusy.value)return
  await chat.send(question,[],null,null,{deepThinking:deepThinking.value})
  scrollFeed()
}

function composerAction() {
  if (chat.outputPaused) return chat.resumeOutput()
  if (chat.generating) return chat.pauseOutput()
  return send()
}

onMounted(async () => {
  await app.load()
  if (!chat.loaded) await chat.loadConversations()
  if (route.query.conversationId && chat.conversations.some(item => item.id === String(route.query.conversationId))) {
    await chat.loadMessages(String(route.query.conversationId))
  }
  if (route.query.skill && findSkill(String(route.query.skill))) activeSkillId.value = String(route.query.skill)
  if (chat.activeId && !chat.latestTrace) await chat.loadLatestTrace()
  const pending = chat.takeMapMessage(String(route.query.conversationId || ''))
  if (pending && chat.activeId === pending.conversationId) {
    message.value = pending.content
    activeSkillId.value = findSkill(pending.skillId)?.id || null
    await send()
  }
})

watch(
  () => [route.query.context, route.query.id],
  async ([kind, id]) => {
    const loaded = await loadContext(kind, id)
    activeContext.value = loaded
    if (!loaded) return
    const marker = `context-${kind}-${id}`
    if (!chat.messages.some(item => item.contextSource === marker)) {
      chat.messages.push({ id: marker, role: 'assistant', content: loaded.content, contextSource: marker })
      scrollFeed()
    }
  },
  { immediate: true }
)

// 新消息总是定位到最新一轮；流式增长时持续跟随，手动上滑可暂时查看历史。
watch(
  () => chat.generating,
  value => scrollFeed(value),
  { flush: 'post' }
)

watch(
  () => chat.messages.length,
  () => scrollFeed(true),
  { flush: 'post' }
)

watch(
  () => chat.messages.at(-1)?.content,
  () => scrollFeed(),
  { flush: 'post' }
)

watch(
  () => chat.messages,
  () => scrollFeed(true),
  { flush: 'post' }
)

onBeforeUnmount(() => {
  followupSession.clear()
  closeAttachmentPreview()
  for (const url of previewUrls) URL.revokeObjectURL(url)
  previewUrls.clear()
  liveDictation?.cancel()
  liveVoice?.cancel()
  clearInterval(recordingTimer)
  if (mediaRecorder?.state === 'recording') mediaRecorder.stop()
  mediaStream?.getTracks().forEach(track => track.stop())
})
</script>

<template>
  <div class="home-root">
  <PageShell title="智能知识管家" immersive>
    <div class="chat-workspace">
    <section class="review-assistant-page" :class="{ 'has-messages': chat.messages.length, 'is-conversation-map': conversationView === 'map' }" :style="{ '--outline-space': conversationView === 'dialog' && outlineAvailable ? '20px' : '0px' }">
      <header class="assistant-topbar">
        <div>
          <strong class="assistant-conversation-title">{{ conversationTitle }}</strong>
          <span class="assistant-conversation-meta">
            <Bot :size="13" /><b>智能知识管家</b><i />
            <small>{{ conversationView === 'map' ? '梳理问答脉络，创建分支与追问' : '知识库问答与功能调用' }}</small>
          </span>
        </div>
      </header>
        <nav class="conversation-view-switch" aria-label="问答与地图视图切换"><button type="button" :class="{ active: conversationView === 'dialog' }" :aria-pressed="conversationView === 'dialog'" @click="conversationView = 'dialog'">智能问答</button><button type="button" :class="{ active: conversationView === 'map' }" :aria-pressed="conversationView === 'map'" @click="conversationView = 'map'">对话地图</button></nav>

      <button v-if="conversationView === 'dialog'" class="assistant-enter" type="button" @click="enterAssistant">
        <PhoneCall :size="17" />
        <span>实时通话</span>
      </button>

      <SynapseConversationMap v-if="mapInitialized || conversationView === 'map'" v-show="conversationView === 'map'" :active="conversationView === 'map'" :deep-thinking="deepThinking" @vue:mounted="mapInitialized = true" @close="conversationView = 'dialog'" @open-message="openMapMessage" />
      <template v-if="conversationView === 'dialog' && !chat.messages.length">
        <main class="assistant-welcome">
          <p class="assistant-recommendation-heading">为你推荐</p>

          <div class="assistant-work-types">
            <button
              v-for="item in featureTypes"
              :key="item.id"
              type="button"
              class="assistant-work-type"
              :class="{ active: activeSkillId === item.id }"
              :aria-pressed="activeSkillId === item.id"
              @click="selectWorkType(item)"
            >
              <span class="assistant-work-icon"><component :is="item.icon" :size="18" /></span>
              <span class="assistant-work-copy"><strong>{{ item.label }}</strong><small>{{ item.id === 'poster' ? '设计活动海报，导出HTML、PNG或PDF' : item.description }}</small></span>
              <Check v-if="activeSkillId === item.id" :size="15" class="assistant-work-check" />
            </button>
          </div>

        </main>
      </template>

      <template v-else-if="conversationView === 'dialog'">
        <div v-if="activeContext" class="assistant-context-card">
          <span><component :is="activeContext.icon" :size="19" /></span>
          <div>
            <small>当前分析内容 · {{ activeContext.label }}</small>
            <strong>{{ activeContext.title }}</strong>
            <p>{{ activeContext.meta }}</p>
          </div>
          <button @click="router.push(activeContext.to)">查看来源 <ExternalLink :size="14" /></button>
          <button class="context-close" title="移除上下文" @click="router.replace('/')"><X :size="16" /></button>
        </div>

        <section ref="feed" class="assistant-feed" :style="{ '--map-navigation-space': `${mapNavigationSpace}px` }" @scroll="onFeedScroll">
          <div class="messages assistant-messages">
            <template v-for="(item, index) in chat.messages" :key="item.id">
              <div v-if="isRealtimeMarker(item)" class="realtime-divider"><span>{{ item.content }}</span></div>
              <div v-else-if="item.regenerating" class="thinking" role="status">
                <span class="message-avatar"><Sparkles :size="17" /></span>
                <span class="thinking-label">{{ chat.agentStatus || '正在重新生成' }}</span>
                <span class="thinking-dots" aria-label="正在重新生成"><i /><i /><i /></span>
              </div>
              <ChatMessage v-else
                :message="item"
                @resend="chat.regenerate(item.id)"
                @open-attachment="openSentAttachment"
              />
              <FollowUpQuestions v-if="index===chat.messages.length-1 && item.id===freshFollowups?.replyId && item.role==='assistant' && item.content && !item.failed && !item.regenerating && !chat.generating && !chat.outputPaused && !item.contextSource" :items="freshFollowups.items" :disabled="workBusy||attachmentBusy" @choose="sendFollowup"/>
            </template>
            <div v-if="chat.generating && !assistantStreaming && !chat.regeneratingId" class="drawing-thinking-wrap">
              <div class="thinking">
                <span class="message-avatar"><Sparkles :size="17" /></span>
                <span class="thinking-label">{{ chat.agentStatus || '思考中' }}</span>
                <span class="thinking-dots" aria-label="思考中"><i /><i /><i /></span>
              </div>
              <DrawingProcess v-if="chat.drawingProgress.length" :steps="chat.drawingProgress" live />
            </div>
          </div>
        </section>

        <ConversationOutline :messages="chat.messages" :container="feed" @navigate="navigateToQuestion" />

      </template>

        <div v-if="conversationView === 'dialog'" class="composer-stack bottom" :class="{ 'palette-open': paletteOpen }">
          <SkillPalette
            v-if="paletteOpen"
            :groups="paletteGroups"
            :index="paletteIndex"
            :total="paletteFlat.length"
            @pick="item => activateSkill(item, { loadExample: false })"
            @hover="index => (paletteIndex = index)"
          />
          <form class="assistant-bottom-composer" @submit.prevent="composerAction">
          <ComposerAttachments :files="files" @preview="openComposerAttachment" @remove="removeFile" />

          <div class="composer-input-area">
            <ComposerEditor
                v-if="!voiceMode"
                ref="editor"
                v-model="message"
                :skill="activeSkill"
                :label="composerLabel"
                :placeholder="composerPlaceholder"
                @keydown="onComposerKeydown"
                @show-info="infoSkill = activeSkill"
                @paste-files="addFiles"
                @paste-long-text="pasteLongText"
              />
          </div>
          <div v-if="voiceMode" class="voice-hold-input compact">
            <button
              type="button"
              :class="{ recording: recordingVoice }"
              @pointerdown.prevent="startVoiceRecording"
              @pointerup.prevent="finishVoiceRecording"
              @pointercancel="finishVoiceRecording"
            >
              <span class="voice-capture-icon"><Mic :size="20" /></span>
              <span class="voice-capture-copy">
                <strong>{{ recordingVoice ? formatVoiceTime(voiceSeconds) : '按住说话' }}</strong>
                <small>{{ recordingVoice ? '松开发送语音' : '按住开始录音' }}</small>
              </span>
              <span class="voice-capture-wave">
                <i v-for="index in 13" :key="index" :style="{ animationDelay: `${index * 55}ms` }" />
              </span>
            </button>
          </div>

          <footer>
            <div class="composer-left-actions">
              <button type="button" title="添加资料" @click="fileInput.click()"><Paperclip :size="18" /></button>
              <button
                type="button"
                class="voice-mode-button"
                :class="{ active: voiceMode }"
                :title="voiceMode ? '切换到文字输入' : '切换到语音消息'"
                @click="toggleVoiceMode"
              >
                <Keyboard v-if="voiceMode" :size="18" />
                <AudioLines v-else :size="18" />
              </button>
              <button
                v-if="!voiceMode"
                type="button"
                class="dictation-button"
                :class="{ active: dictating }"
                :aria-pressed="dictating"
                :title="dictating ? '停止语音转文字' : '语音转文字'"
                @click="toggleDictation"
              >
                <Mic :size="18" />
              </button>
            </div>
            <div class="composer-voice-actions">
              <button
                v-if="!voiceMode"
                type="button"
                class="deep-thinking-toggle"
                :class="{ active: deepThinking }"
                :aria-pressed="deepThinking"
                :title="deepThinking ? '关闭深度思考' : '开启深度思考'"
                @click="deepThinking = !deepThinking"
              >
                <Atom :size="17" /><span>深度思考</span>
              </button>
              <button v-if="!voiceMode" class="assistant-send"
                :title="chat.outputPaused ? '继续输出' : chat.generating ? '暂停输出' : '发送'"
                :aria-label="chat.outputPaused ? '继续输出' : chat.generating ? '暂停输出' : '发送'"
                :disabled="!chat.generating && !chat.outputPaused && ((!message.trim() && !files.length) || workBusy || attachmentBusy)">
                <Play v-if="chat.outputPaused" :size="18" fill="currentColor" />
                <Square v-else-if="chat.generating" :size="16" fill="currentColor" />
                <Send v-else :size="17" />
              </button>
            </div>
          </footer>
          </form>
        </div>
      <input ref="fileInput" hidden type="file" accept="image/jpeg,image/png,image/gif,image/webp,.txt,.md,.markdown,.csv,.json,.log,.yaml,.yml,.xml,.html,.css,.js,.jsx,.ts,.tsx,.py,.java,.sql,.sh" multiple @change="selectFiles" />
      <AttachmentPreview v-if="attachmentPreview" :file="attachmentPreview" @close="closeAttachmentPreview" />
    </section>
      <AgentMonitorPanel v-if="conversationView === 'dialog'" :trace="chat.latestTrace" :generating="chat.generating" />
    </div>
  </PageShell>
  <SkillInfoDialog v-if="infoSkill" :skill="infoSkill" @close="infoSkill = null" />
  </div>
</template>

<style scoped>
/* AI 助手与右侧运行监控的横向布局：左侧内容区占满剩余宽度，监控面板固定宽度并可收起。 */
.chat-workspace{position:relative;display:flex;height:100%;min-height:0;overflow:hidden}
.chat-workspace .review-assistant-page{--conversation-header-top:27px;flex:1;min-width:0;height:100%}
.review-assistant-page .assistant-topbar{position:relative;width:calc(100% - 56px);max-width:none;min-height:62px}
.conversation-view-switch{position:absolute;left:50%;top:calc(var(--conversation-header-top) + 3px);transform:translateX(-50%);display:flex;align-items:center;gap:3px;padding:4px;border:1px solid #e8dcf6;border-radius:999px;background:#fcfaff;box-shadow:0 3px 12px #7c3aed08;z-index:21}
.conversation-view-switch button{padding:7px 14px;border:0;border-radius:999px;background:transparent;color:#a18aaf;font-size:12px;font-weight:600;white-space:nowrap;cursor:pointer}.conversation-view-switch button.active{background:#7c3aed;color:#fff;box-shadow:0 3px 8px #7c3aed24}.conversation-view-switch button:hover:not(.active){background:#f1e9fc;color:#7c3aed}.conversation-view-switch button:focus-visible{outline:2px solid #a78bfa;outline-offset:2px}
.review-assistant-page .assistant-topbar>div:first-child{max-width:calc(50% - 105px)}
@media(max-width:850px){.review-assistant-page .assistant-topbar{width:calc(100% - 92px)}.conversation-view-switch{left:auto;right:24px;transform:none}.review-assistant-page .assistant-topbar>div:first-child{max-width:calc(100% - 170px)}.chat-workspace .assistant-enter{display:none}}

/* 进入虚拟助手的入口：固定在内容区右上角，不压住顶栏身份与右侧运行监控面板。 */
.assistant-enter{
  position:absolute;top:22px;right:28px;z-index:20;
  display:inline-flex;align-items:center;gap:9px;height:40px;padding:0 16px;
  border:0;border-radius:12px;cursor:pointer;
  color:#fff;font-size:13px;font-weight:600;letter-spacing:.3px;
  background:linear-gradient(135deg,var(--brand-strong),var(--brand));
  box-shadow:0 6px 18px rgba(89,17,177,.32),inset 0 1px 0 rgba(255,255,255,.22);
  transition:transform .18s,box-shadow .18s,filter .18s;
}
.assistant-enter:hover{filter:brightness(1.05);transform:translateY(-1px);box-shadow:0 10px 24px rgba(89,17,177,.42),inset 0 1px 0 rgba(255,255,255,.22)}
.assistant-enter:active{transform:translateY(0)}
.realtime-divider{display:flex;align-items:center;gap:12px;margin:20px 0 14px;color:#764fa5;font-size:12px;letter-spacing:1.5px;font-weight:700}
.realtime-divider::before,.realtime-divider::after{content:"";height:1px;flex:1;background:linear-gradient(90deg,transparent,#be9ee5)}
.realtime-divider::after{background:linear-gradient(90deg,#be9ee5,transparent)}
.realtime-divider span{padding:5px 12px;border:1px solid #c4a8e7;border-radius:999px;background:#f1e8fb;white-space:nowrap}

.review-assistant-page .composer-voice-actions .deep-thinking-toggle{
  min-height:38px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:6px;
  padding:0 13px;
  border:1px solid #c5a8e8;
  border-radius:999px;
  color:#490898;
  background:#f6f1fc;
  font-size:13px;
  font-weight:600;
  white-space:nowrap;
  cursor:pointer;
  transition:background .18s,border-color .18s,color .18s,box-shadow .18s;
}
.review-assistant-page .composer-voice-actions .deep-thinking-toggle:hover{
  color:#3f0882;
  border-color:#9e75d1;
  background:#ede4f9;
}
.review-assistant-page .composer-voice-actions .deep-thinking-toggle.active{
  color:#fff;
  border-color:#5b21b6;
  background:#5b21b6;
  box-shadow:0 4px 12px rgba(91,33,182,.22);
}
.review-assistant-page .composer-voice-actions .deep-thinking-toggle.active:hover{
  color:#fff;
  border-color:#4c1d95;
  background:#4c1d95;
}
.review-assistant-page .composer-voice-actions .deep-thinking-toggle:focus-visible{
  outline:2px solid #490898;
  outline-offset:2px;
}
.review-assistant-page .composer-voice-actions{gap:16px}
.review-assistant-page .composer-voice-actions .assistant-send{
  height:40px;
  min-height:40px;
  padding:0;
  color:#fff;
  font-size:14px;
  font-weight:750;
  box-shadow:none;
}
.review-assistant-page .assistant-hero-composer .assistant-send{
  flex:0 0 86px;
  width:86px;
  min-width:86px;
}
.review-assistant-page .assistant-bottom-composer .assistant-send{
  flex:0 0 40px;
  width:40px;
  min-width:40px;
}
.review-assistant-page .composer-voice-actions .assistant-send:disabled{
  color:#fff;
  background:#b5a5c9;
}
.review-assistant-page .composer-voice-actions .assistant-send:disabled svg{
  color:inherit;
  stroke:currentColor;
}
@media(max-width:480px){
  .review-assistant-page .composer-voice-actions{gap:8px}
  .review-assistant-page .assistant-hero-composer .assistant-send{
    flex-basis:40px;
    width:40px;
    min-width:40px;
  }
  .review-assistant-page .assistant-hero-composer .assistant-send span{display:none}
  .review-assistant-page .composer-voice-actions .deep-thinking-toggle{padding:0 9px;font-size:12px}
}
.review-assistant-page .composer-left-actions .dictation-button{
  flex:0 0 38px;
  border-radius:50%;
}
.review-assistant-page .composer-left-actions .dictation-button.active,
.review-assistant-page .composer-left-actions .dictation-button.active:hover{
  position:relative;
  color:#fff;
  background:#ece0fb;
  box-shadow:none;
  animation:none;
}
.review-assistant-page .composer-left-actions .dictation-button.active::before{
  position:absolute;
  inset:5px;
  border-radius:50%;
  background:#570bb5;
  content:"";
}
.review-assistant-page .composer-left-actions .dictation-button.active svg{
  position:relative;
  z-index:1;
}
/* White/violet conversation skin; these scoped rules follow legacy chat styles. */
.review-assistant-page{background:#fff;color:#18181b}
.review-assistant-page .assistant-topbar{background:#fff;border-color:#ececee;box-shadow:none}
.review-assistant-page .assistant-topbar:after,.review-assistant-page .assistant-conversation-title:before{background:#7c3aed}
.review-assistant-page .assistant-conversation-title{color:#18181b;font-family:var(--font-display)}
.review-assistant-page .assistant-conversation-meta>svg{color:#7c3aed;background:#f3effe}
.review-assistant-page .assistant-welcome h1{color:#0a0a0a;background:none;-webkit-text-fill-color:#0a0a0a;animation:none;font-family:var(--font-display)}
.review-assistant-page .assistant-eyebrow{color:#7c3aed;font-family:var(--font-mono)}
.review-assistant-page .assistant-welcome-mark{color:#7c3aed;background:#f3effe;box-shadow:none}
.review-assistant-page .assistant-work-type{border-color:#ececee;background:#fff;border-radius:14px;box-shadow:0 1px 2px rgba(10,10,10,.04)}
.review-assistant-page .assistant-work-type:hover{border-color:#ddd0fb;box-shadow:0 8px 24px rgba(124,58,237,.08)}
.review-assistant-page .assistant-work-type.active{border-color:#a78bfa;box-shadow:0 0 0 3px #f3effe}
.review-assistant-page .assistant-work-icon{color:#7c3aed;background:#f3effe}
.review-assistant-page .assistant-work-type.active .assistant-work-icon{color:#fff;background:#7c3aed}
.review-assistant-page .assistant-work-copy strong{color:#27272a}
.review-assistant-page .assistant-work-copy small{color:#71717a}
.review-assistant-page .assistant-work-check{color:#7c3aed}
.review-assistant-page .assistant-hero-composer,.review-assistant-page .assistant-bottom-composer{color:#27272a;background:#fff;border:1px solid #dedbe7;box-shadow:0 8px 30px rgba(10,10,10,.06)}
.review-assistant-page .assistant-hero-composer:focus-within,.review-assistant-page .assistant-bottom-composer:focus-within{border-color:#a78bfa;box-shadow:0 0 0 3px #f3effe,0 8px 30px rgba(10,10,10,.05)}
.review-assistant-page .assistant-send:not(:disabled){color:#fff;background:#7c3aed;box-shadow:0 8px 24px rgba(124,58,237,.15)}
.review-assistant-page .assistant-send:not(:disabled):hover{background:#6d28d9}
.review-assistant-page .assistant-send:disabled{color:#a1a1aa;background:#f4f4f5}
.review-assistant-page .assistant-skill-tag svg,.review-assistant-page .composer-skill-chip{color:#7c3aed}
.review-assistant-page .assistant-skill-palette{border-color:#ddd0fb;background:#fff}
.review-assistant-page .assistant-skill-scroll button:hover,.review-assistant-page .assistant-skill-scroll button.highlighted{background:#f3effe}
.review-assistant-page .assistant-context-card{border-color:#e9ddff;background:#faf8ff}
.review-assistant-page .assistant-messages .thinking .message-avatar{color:#fff;background:#4c0b9b;border-color:#4c0b9b;box-shadow:0 8px 20px rgba(76,11,155,.2)}
.review-assistant-page .assistant-messages .thinking i{background:#7c3aed;box-shadow:none}
.review-assistant-page .assistant-messages .thinking-label{color:#6d28d9}
.review-assistant-page .chat-message.user .message-bubble{color:#fff;background:#7c3aed;border-color:#7c3aed;box-shadow:none}
.review-assistant-page .chat-message.assistant .message-prose,
.review-assistant-page .chat-message.assistant .message-bubble li{color:#3f3f46}
.review-assistant-page .chat-message.assistant .message-prose strong,
.review-assistant-page .chat-message.assistant .message-prose h2,
.review-assistant-page .chat-message.assistant .message-prose h3{color:#18181b}
.review-assistant-page .chat-message.assistant .message-prose h2,
.review-assistant-page .chat-message.assistant .message-prose h3{border-left-color:#7c3aed}
.review-assistant-page .chat-message.assistant .message-bubble blockquote,.review-assistant-page .chat-message.assistant .message-bubble code{color:#5b21b6;background:#f3effe}
.review-assistant-page .chat-message.assistant .message-sources{color:#52525b;border-color:#ececee;background:#fafafa}
.review-assistant-page .chat-message.assistant .message-sources button{color:#6d28d9;border-color:#e9ddff;background:#fff}
.review-assistant-page .chat-message.assistant .message-actions button:hover,.review-assistant-page .chat-message.assistant .message-actions button.active{color:#7c3aed;background:#f3effe}
.review-assistant-page .voice-hold-input>button{background:#fff;box-shadow:inset 0 0 0 1px #e9ddff,0 4px 15px rgba(124,58,237,.06)}
.review-assistant-page .voice-hold-input>button.recording{background:#f3effe;box-shadow:inset 0 0 0 1px #a78bfa}
.review-assistant-page .voice-capture-icon{color:#7c3aed;background:#f3effe;box-shadow:none}
.review-assistant-page .voice-hold-input>button.recording .voice-capture-icon{color:#fff;background:#7c3aed}
.review-assistant-page .voice-capture-copy strong,.review-assistant-page .voice-hold-input>button.recording .voice-capture-copy strong{color:#5b21b6}
.review-assistant-page .voice-capture-wave i{background:#c4b5fd}
.review-assistant-page .voice-hold-input>button.recording .voice-capture-wave i{background:#7c3aed}
.review-assistant-page .voice-message{color:#fff;background:#7c3aed;box-shadow:0 8px 20px rgba(124,58,237,.15)}
.review-assistant-page .voice-wave i{background:#fff}
.review-assistant-page .composer-left-actions .dictation-button.active,.review-assistant-page .composer-left-actions .dictation-button.active:hover{background:#f3effe}
.review-assistant-page .composer-left-actions .dictation-button.active::before{background:#7c3aed}
.review-assistant-page .assistant-topbar{
  max-width:calc(100% - 84px);
  margin:var(--conversation-header-top) var(--workspace-page-gutter,42px) 0;
}
.review-assistant-page .assistant-conversation-title{
  color:#25133b;font-family:var(--font-body);font-size:24px;line-height:1.25;
}
.review-assistant-page .assistant-conversation-meta{font-size:14px}
.review-assistant-page .assistant-conversation-meta{min-width:0;white-space:nowrap}
.review-assistant-page .assistant-conversation-meta>svg,
.review-assistant-page .assistant-conversation-meta>b,
.review-assistant-page .assistant-conversation-meta>i{flex-shrink:0}
.review-assistant-page .assistant-conversation-meta>small{min-width:0;overflow:hidden;text-overflow:ellipsis}
.review-assistant-page .assistant-feed{padding:28px var(--workspace-page-gutter,42px);padding-right:calc(var(--workspace-page-gutter,42px) + var(--outline-space,0px));padding-bottom:calc(72px + var(--map-navigation-space,0px))}
@media(max-width:900px){
  .review-assistant-page .assistant-topbar{max-width:calc(100% - 84px);margin-left:68px;margin-right:16px}
  .conversation-view-switch{left:calc(50% + 26px)}
  .review-assistant-page .assistant-feed{padding-right:calc(16px + var(--outline-space,0px));padding-left:16px}
}
@media(max-width:850px){
  .conversation-view-switch{left:auto}
}
@media(max-width:640px){
  .chat-workspace .review-assistant-page{--conversation-header-top:20px}
  .review-assistant-page .assistant-conversation-title{font-size:20px}
}
.review-assistant-page.is-conversation-map{background:#fbf8ff radial-gradient(#d5b9f5 1px,transparent 1px) 0 0/22px 22px}
.review-assistant-page.is-conversation-map .assistant-topbar{
  box-sizing:border-box;width:100%;max-width:none;margin:0;
  min-height:calc(var(--conversation-header-top) + 62px);
  padding:calc(var(--conversation-header-top) + 3px) var(--workspace-page-gutter,42px) 5px;
  background:transparent;border-bottom:1px solid #ececee;box-shadow:none;
}
@media(max-width:900px){
  .review-assistant-page.is-conversation-map .assistant-topbar{padding-left:68px;padding-right:16px}
}

/* Compact recommendations scroll independently of the shared bottom composer. */
.chat-workspace .review-assistant-page{min-height:0}
.review-assistant-page .assistant-welcome{
  flex:1;min-height:0;max-width:none;width:100%;margin:0;
  overflow-y:auto;padding:24px var(--workspace-page-gutter,42px) 18px;
  display:flex;flex-direction:column;
  text-align:left;background:none;
}
.assistant-recommendation-heading{
  width:min(900px,100%);margin:auto auto 14px;flex-shrink:0;color:#a1a1aa;
  font-size:13px;font-weight:400;line-height:1.5;
}
.review-assistant-page .assistant-work-types{
  display:flex;flex-direction:column;align-items:flex-start;gap:10px;
  width:min(900px,100%);margin:0 auto;flex-shrink:0;
}
.review-assistant-page .assistant-work-type{
  width:fit-content;max-width:100%;min-height:44px;gap:6px;
  padding:10px 14px;border:1px solid #ececee;border-radius:14px;
  background:#fff;box-shadow:none;transform:none;
}
.review-assistant-page .assistant-work-type:hover{
  border-color:#ddd0fb;background:#faf8ff;box-shadow:none;transform:none;
}
.review-assistant-page .assistant-work-type.active{
  border-color:#c4b5fd;background:#f7f3ff;box-shadow:none;
}
.review-assistant-page .assistant-work-type:focus-visible{outline:2px solid #a78bfa;outline-offset:3px}
.review-assistant-page .assistant-work-icon,
.review-assistant-page .assistant-work-type.active .assistant-work-icon{
  width:18px;height:18px;flex:0 0 18px;border-radius:0;
  color:#7c3aed;background:none;
}
.review-assistant-page .assistant-work-copy{display:block;min-width:0;line-height:1.6}
.review-assistant-page .assistant-work-copy strong{color:#7c3aed;font-size:14px;font-weight:500;margin-right:6px}
.review-assistant-page .assistant-work-copy small{color:#3f3f46;font-size:14px;line-height:inherit}
.review-assistant-page .assistant-work-check{position:static;flex-shrink:0;margin-left:4px}
@media(max-width:640px){
  .review-assistant-page .assistant-welcome{padding:24px 16px 20px}
  .review-assistant-page .assistant-work-type{padding:9px 12px;min-height:42px}
  .review-assistant-page .assistant-work-copy strong,
  .review-assistant-page .assistant-work-copy small{font-size:13px}
}
</style>
