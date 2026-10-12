<script setup>
/**
 * AI 管家全息界面。
 *
 * 整页接管：不走 PageShell，进入就是一个沉浸的全息助理场景。
 * 实时 ASR、流式 LLM 与流式 TTS 组成语音对话；进入页面后自动尝试开启麦克风。
 *
 * 布局：
 *   - 中央：进入页面后直接进入虚拟助手对话；
 *   - 底部：常驻的「接收语音」动态形象，聆听时波动变化；
 *   - 左上：实时字幕面板（AI ↔ 人的对话），常驻展开，可拖拽调宽；
 *   - 右上：Agent 实时监控面板，常驻展开，可拖拽调宽；
 *   - 两块面板延伸到页面底部，内容在面板内部滚动，中间保留全息形象与语音动态。
 *
 * 兼容性注意：全屏定位用显式 left/top/width/height 而非 inset 简写，
 * 并给背景一个纯色兜底，避免旧内核浏览器里全屏层塌缩成白屏。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { Activity, Bot, Compass, MessageSquare, MessageSquareText, UserRound } from 'lucide-vue-next'
import { playListenStart, playListenStop, playMechanicalShutdown } from '@/lib/jarvisSound'
import AssistantParticles from '@/components/AssistantParticles.vue'
import { chatApi, speechApi } from '@/api'
import { useChatStore } from '@/stores/chat'
import { startLiveAsr } from '@/lib/liveAsr'
import { createMp3Output } from '@/lib/streamMp3'
import { createRealtimeTranscript } from '@/lib/realtimeTranscript'

const router = useRouter()
const route = useRoute()
const chat = useChatStore()
const realtimeSessionId = `voice-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

/**
 * 底部语音球的外壳网格：一组过球心的大圆，各自绕不同轴摆一个角度。
 * 单看每个圆都是正圆，叠在一起再自转，就是一个球面网格。
 */
const VOICE_RINGS = [
  'rotateY(0deg)',
  'rotateY(36deg)',
  'rotateY(72deg)',
  'rotateY(108deg)',
  'rotateY(144deg)',
  'rotateX(90deg)',
  'rotateZ(45deg) rotateX(55deg)',
  'rotateZ(-45deg) rotateX(55deg)',
  'rotateZ(20deg) rotateY(50deg) rotateX(35deg)',
  'rotateZ(-70deg) rotateY(30deg) rotateX(60deg)',
  'rotateZ(60deg) rotateY(75deg) rotateX(25deg)',
  'rotateZ(-15deg) rotateY(110deg) rotateX(45deg)',
  'rotateZ(80deg) rotateX(70deg)',
  'rotateZ(-30deg) rotateY(140deg) rotateX(20deg)'
]

/** 收到声音后才出现的那几圈乱线，角度故意错开，让壳看着像被声音搅乱了。 */
const VOICE_SPARKS = [
  'rotateZ(12deg) rotateY(28deg) rotateX(64deg)',
  'rotateZ(-52deg) rotateY(96deg) rotateX(18deg)',
  'rotateZ(38deg) rotateY(150deg) rotateX(52deg)',
  'rotateZ(-24deg) rotateY(62deg) rotateX(78deg)',
  'rotateZ(70deg) rotateY(118deg) rotateX(30deg)',
  'rotateZ(-8deg) rotateY(8deg) rotateX(42deg)'
]

const GREETING_TEXT = '我是你的智能知识管家思雅，英文名字叫Sarsa，今天你有什么需求吗？随时为你效劳。'

// 分布在球面前后不同深度的粒子，沿径向错峰向外散开。
const VOICE_PARTICLE_COUNT = 96
const VOICE_PARTICLES = Array.from({ length: VOICE_PARTICLE_COUNT }, (_, index) => {
  const y = 1 - 2 * (index + .5) / VOICE_PARTICLE_COUNT
  const angle = index * 2.39996323
  const radius = Math.sqrt(1 - y * y)
  const x = Math.cos(angle) * radius
  const z = Math.sin(angle) * radius
  const reach = 108 + (index % 7) * 5
  return {
    '--px': `${x * 45}px`, '--py': `${y * 45}px`, '--pz': `${z * 45}px`,
    '--ex': `${x * reach}px`, '--ey': `${y * reach * .68}px`, '--ez': `${z * reach}px`,
    '--particle-size': `${1.5 + (index % 4) * .55}px`,
    '--particle-duration': `${1.4 + (index % 7) * .13}s`,
    '--particle-delay': `${-(index * .173) % 2.2}s`
  }
})

const listening = ref(false)
const speaking = ref(false)
const awake = ref(true)
const voiceEnabled = ref(false)
const voiceStatus = ref('正在聆听，请说话')
const interimText = ref('')
const micError = ref('')

/** 实时字幕：{ id, role: 'human' | 'ai' | 'system', text, time } */
const subtitles = ref([])
/** Agent 步骤：{ id, label, detail, status: 'active' | 'done', time } */
const agentSteps = ref([])

/** 中央时钟。 */
const now = ref(new Date())

/** 面板宽度（拖拽内缘调整，常驻展开不折叠）。 */
const leftWidth = ref(360)
const rightWidth = ref(380)
const panelWidth = width => `min(${width}px, max(220px, calc(50vw - 300px)))`
const leftPanelStyle = computed(() => ({ width: panelWidth(leftWidth.value) }))
const rightPanelStyle = computed(() => ({ width: panelWidth(rightWidth.value) }))

const subList = ref()
const agentList = ref()
const followSubtitles = ref(true)
const followAgent = ref(true)
function nearBottom(element) {
  return element.scrollHeight - element.scrollTop - element.clientHeight < 40
}

const panelScroll = reactive({
  subtitles: { top: 0, size: 1, overflow: false },
  agent: { top: 0, size: 1, overflow: false },
})
let panelResizeObserver = null
let activeScrollDrag = null

function panelElement(kind) {
  return kind === 'subtitles' ? subList.value : agentList.value
}

function updatePanelScroll(kind) {
  const element = panelElement(kind)
  if (!element) return
  const maxScroll = Math.max(0, element.scrollHeight - element.clientHeight)
  const size = Math.max(0.16, Math.min(1, element.clientHeight / Math.max(element.scrollHeight, 1)))
  panelScroll[kind] = {
    top: maxScroll ? (element.scrollTop / maxScroll) * (1 - size) : 0,
    size,
    overflow: maxScroll > 1,
  }
}

function onPanelScroll(kind, event) {
  if (kind === 'subtitles') followSubtitles.value = nearBottom(event.target)
  else followAgent.value = nearBottom(event.target)
  updatePanelScroll(kind)
}

function scrollSubtitles(force = false) {
  if (force) followSubtitles.value = true
  if (!followSubtitles.value) return
  nextTick(() => {
    const element = subList.value
    if (!element || !followSubtitles.value) return
    element.scrollTop = element.scrollHeight
    updatePanelScroll('subtitles')
  })
}

function movePanelScrollbar(kind, event) {
  const element = panelElement(kind)
  const rail = event.currentTarget
  if (!element || !panelScroll[kind].overflow) return
  const rect = rail.getBoundingClientRect()
  const thumbHeight = rect.height * panelScroll[kind].size
  const travel = rect.height - thumbHeight
  if (travel <= 0) return
  const offset = activeScrollDrag?.offset ?? thumbHeight / 2
  const progress = Math.max(0, Math.min(1, (event.clientY - rect.top - offset) / travel))
  element.scrollTop = progress * (element.scrollHeight - element.clientHeight)
}

function startPanelScrollbarDrag(kind, event) {
  if (!panelScroll[kind].overflow) return
  const rail = event.currentTarget
  const thumb = rail.querySelector('.panel-scroll-thumb')
  activeScrollDrag = {
    pointerId: event.pointerId,
    offset: thumb?.contains(event.target)
      ? event.clientY - thumb.getBoundingClientRect().top
      : thumb?.getBoundingClientRect().height / 2 || 0,
  }
  rail.setPointerCapture(event.pointerId)
  movePanelScrollbar(kind, event)
  event.preventDefault()
}

function dragPanelScrollbar(kind, event) {
  if (activeScrollDrag?.pointerId === event.pointerId) movePanelScrollbar(kind, event)
}

function endPanelScrollbarDrag(event) {
  if (activeScrollDrag?.pointerId !== event.pointerId) return
  if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  activeScrollDrag = null
}

const timeText = computed(() => {
  const d = now.value
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, '0')).join(':')
})
const dateText = computed(() => {
  const d = now.value
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
})
const weekdayText = computed(() => '星期' + '日一二三四五六'[now.value.getDay()])

const liveSubtitle = computed(() => (listening.value && interimText.value ? interimText.value : ''))
watch(liveSubtitle, () => scrollSubtitles())

/** 底部语音球是不是收到了声音：正在识别到人说话，或者助手正在回话。
 * 只是「麦克风开着」不算 —— 那样它就会一直抖，看不出「安静」和「有声」的区别。 */
const particleSpeaking = computed(() => speaking.value && !listening.value && !liveSubtitle.value.trim())
const voiceActive = computed(() => listening.value || !!liveSubtitle.value.trim())

let asrSession = null
let asrStarting = false
let realtimeTranscript = null
const activeTurns = new Set()
let finishPromise = null
let pendingTurn = null
let greetingSaved = false
let replyAbort = null
let speechAbort = null
let speechAudio = null
let speechOutput = null
let greetingAudioPromise = null
let greetingAudioController = null
let greetingAudioUrl = null
let turnVersion = 0
let disposed = false
let clockTimer = null
let subSeq = 0
let stepSeq = 0

function stamp() {
  const d = new Date()
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map(n => String(n).padStart(2, '0')).join(':')
}

function pushSubtitle(role, text) {
  const id = ++subSeq
  subtitles.value = [...subtitles.value, { id, role, text, time: stamp() }].slice(-80)
  scrollSubtitles(true)
  return id
}

function saveRealtimeMessage(role, content) {
  return realtimeTranscript.append(role, content)
}

function showGreetingSubtitle() {
  if (greetingSaved) return
  greetingSaved = true
  pushSubtitle('ai', GREETING_TEXT)
}

function updateSubtitle(id, text) {
  subtitles.value = subtitles.value.map(item => item.id === id ? { ...item, text } : item)
  scrollSubtitles()
}

function pushAgentStep(label, detail) {
  agentSteps.value = [...agentSteps.value, { id: ++stepSeq, label, detail, status: 'active', time: stamp() }].slice(-80)
  nextTick(() => {
    if (agentList.value && followAgent.value) agentList.value.scrollTop = agentList.value.scrollHeight
  })
}

function completeStep(label) {
  agentSteps.value = agentSteps.value.map(s =>
    s.label === label && s.status === 'active' ? { ...s, status: 'done' } : s
  )
}

function showAssistant() {
  if (!awake.value) {
    awake.value = true
    pushAgentStep('语音对话', 'AI管家已进入对话态')
    pushSubtitle('system', 'AI管家已进入对话态')
  }

}

async function playCachedAudio(url, version, onPlaying) {
  const controller = new AbortController()
  const audio = new Audio(url)
  speechAbort = controller
  speechAudio = audio
  try {
    await new Promise((resolve, reject) => {
      audio.onplaying = () => {
        if (version === turnVersion && !disposed) onPlaying?.()
        audio.onplaying = null
      }
      audio.onended = resolve
      audio.onerror = () => reject(new Error('语音播放失败'))
      controller.signal.addEventListener('abort', resolve, { once: true })
      audio.play().catch(reject)
    })
  } finally {
    if (speechAudio === audio) {
      speechAudio = null
      speechAbort = null
    }
  }
}

function prepareGreetingAudio() {
  if (greetingAudioUrl || greetingAudioPromise || disposed) return greetingAudioPromise
  const controller = new AbortController()
  greetingAudioController = controller
  const pending = speechApi.greeting(controller.signal)
    .then(response => response.blob())
    .then(blob => {
      if (controller.signal.aborted || disposed) return null
      greetingAudioUrl = URL.createObjectURL(blob)
      return greetingAudioUrl
    })
    .catch(() => null)
    .finally(() => {
      if (greetingAudioController === controller) greetingAudioController = null
      if (greetingAudioPromise === pending) greetingAudioPromise = null
    })
  greetingAudioPromise = pending
  return greetingAudioPromise
}

function clearGreetingAudio() {
  greetingAudioController?.abort()
  greetingAudioController = null
  if (greetingAudioUrl) URL.revokeObjectURL(greetingAudioUrl)
  greetingAudioUrl = null
  greetingAudioPromise = null
}

async function playGreeting() {
  const version = ++turnVersion
  speaking.value = true
  voiceStatus.value = 'AI管家正在回应'
  try {
    const url = greetingAudioUrl || await prepareGreetingAudio()
    if (disposed || version !== turnVersion) return
    if (!url) {
      await playSpeechSegment(GREETING_TEXT, version, signal => speechApi.greeting(signal), showGreetingSubtitle)
      return
    }
    await playCachedAudio(url, version, showGreetingSubtitle)
  } catch (error) {
    if (!disposed && version === turnVersion) {
      micError.value = error?.message || '语音播放失败'
    }
  } finally {
    if (version === turnVersion) {
      speechAbort = null
      speechAudio = null
      speaking.value = false
      clearGreetingAudio()

      if (voiceEnabled.value && !disposed) await startListening()
      else if (!disposed) voiceStatus.value = '麦克风已关闭 · 点击语音球或按空格开启'
    }
  }
}

async function startListening() {
  if (!voiceEnabled.value || asrSession || asrStarting || disposed) return
  asrStarting = true
  voiceStatus.value = '连接实时语音识别…'
  try {
    const session = await startLiveAsr(text => {
      interimText.value = text
      if (speaking.value && text.trim().length >= 2) {
        replyAbort?.abort()
        stopSpeech()
      }
    }, () => { finishUtterance() }, { silenceMs: 2000 })
    if (!voiceEnabled.value || disposed) { session.cancel(); return }
    asrSession = session
    listening.value = true
    voiceStatus.value = '正在聆听，请说话'
    playListenStart()
  } catch (error) {
    voiceEnabled.value = false
    micError.value = error?.message || '无法启动实时语音识别'
    voiceStatus.value = '麦克风连接失败 · 点击语音球重试'
  } finally {
    asrStarting = false
  }
}

function stopListening() {
  const wasListening = Boolean(asrSession || listening.value)
  asrSession?.cancel()
  asrSession = null
  listening.value = false
  interimText.value = ''
  if (wasListening) playListenStop()
}

function stopSpeech() {
  speechAbort?.abort()
  speechAbort = null
  speechAudio?.pause()
  speechOutput?.cleanup()
  speechOutput = null
  speechAudio = null
  speaking.value = false
}

function toggleVoice() {
  if (voiceEnabled.value) {
    voiceEnabled.value = false
    stopListening()
    voiceStatus.value = speaking.value
      ? '麦克风已关闭 · 继续播报'
      : '麦克风已关闭 · 点击语音球或按空格开启'
  } else {
    voiceEnabled.value = true
    micError.value = ''
    startListening()
  }
}

function onSpaceToggle(event) {
  if (event.code !== 'Space' || event.defaultPrevented || event.repeat || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return
  const target = event.target
  if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return
  event.preventDefault()
  toggleVoice()
}

async function finishUtterance() {
  const session = asrSession
  if (!session || !voiceEnabled.value) return
  asrSession = null
  listening.value = false
  voiceStatus.value = '正在确认语音…'
  playListenStop()
  try {
    if (speaking.value) {
      replyAbort?.abort()
      stopSpeech()
    }
    const text = (await session.stop()).trim()
    interimText.value = ''
    if (disposed || finishPromise) return
    if (!text) { await startListening(); return }
    pushSubtitle('human', text)
    const turnPromise = answerVoice(text)
    activeTurns.add(turnPromise)
    try {
      await turnPromise
    } finally {
      activeTurns.delete(turnPromise)
    }
  } catch (error) {
    if (voiceEnabled.value && !disposed) {
      micError.value = error?.message || '语音识别失败'
      await startListening()
    }
  }
}

async function playSpeechSegment(text, version, request = signal => speechApi.synthesize(text, signal), onPlaying) {
  if (!text.trim() || version !== turnVersion || disposed) return
  const controller = new AbortController()
  const audio = new Audio()
  const output = createMp3Output(audio, controller.signal)
  speechAbort = controller
  speechAudio = audio
  speechOutput = output
  speaking.value = true
  voiceStatus.value = '正在播报回复'
  let failPlayback
  const playback = new Promise((resolve, reject) => {
    failPlayback = reject
    audio.onplaying = () => {
      if (version === turnVersion && !disposed) onPlaying?.()
      audio.onplaying = null
    }
    audio.onended = resolve
    audio.onerror = () => reject(new Error('音频播放失败'))
    controller.signal.addEventListener('abort', () => reject(new DOMException('已取消', 'AbortError')), { once: true })
  })
  playback.catch(() => {})
  try {
    const response = await request(controller.signal)
    await output.consume(response, () => { audio.play().catch(failPlayback) })
    await playback
  } finally {
    output.cleanup()
    if (speechOutput === output) {
      speechAbort = null
      speechAudio = null
      speechOutput = null
    }
  }
}

async function answerVoice(text) {
  const version = ++turnVersion
  const controller = new AbortController()
  replyAbort = controller
  speaking.value = true
  if (voiceEnabled.value && !disposed) startListening()
  voiceStatus.value = '正在处理你的请求…'
  pushAgentStep('理解意图', text)
  let subtitleId = null
  let spokenText = ''
  let answer = ''
  const turn = { user: text, spoken: '', persisted: false }
  pendingTurn = turn
  let pendingSpeech = ''
  let speechQueue = Promise.resolve()
  let speechFailure = null
  let prefetchCount = 0
  const queueSpeech = segment => {
    if (!segment.trim()) return
    // 最多预热两段，避免长回答瞬间打开过多合成连接。
    const prepared = prefetchCount < 2 ? speechApi.synthesize(segment, controller.signal) : null
    if (prepared) { prefetchCount++; prepared.catch(() => {}) }
    speechQueue = speechQueue.then(async () => {
      if (speechFailure || controller.signal.aborted || version !== turnVersion) return
      try {
        await playSpeechSegment(segment, version, prepared ? () => prepared : undefined, () => {
          spokenText += segment
          turn.spoken = spokenText
          if (subtitleId === null) subtitleId = pushSubtitle('ai', spokenText)
          else updateSubtitle(subtitleId, spokenText)
        })
      } finally {
        if (prepared) prefetchCount--
      }
    }).catch(error => {
      if (!controller.signal.aborted && !speechFailure) speechFailure = error
    })
  }
  try {
    await realtimeTranscript.start(text)
    await realtimeTranscript.flush()
    completeStep('理解意图')
    pushAgentStep('生成回复', 'DeepSeek正在逐句回答')
    await chatApi.streamReply(realtimeTranscript.conversationId, text, controller.signal, event => {
      if (event.type === 'tool_start') {
        pushAgentStep(event.label || '工具调用', event.detail || '正在执行工具')
      }
      if (event.type === 'tool_end') {
        completeStep(event.label || '工具调用')
      }
      if (event.type === 'delta') {
        answer += event.text || ''
        pendingSpeech += event.text || ''
        let boundary = pendingSpeech.search(/[。！？.!?]/)
        if (boundary < 0 && pendingSpeech.length >= 16) boundary = pendingSpeech.search(/[，,；;：:]/)
        if (boundary < 0 && pendingSpeech.length >= 32) boundary = 31
        while (boundary >= 0) {
          queueSpeech(pendingSpeech.slice(0, boundary + 1))
          pendingSpeech = pendingSpeech.slice(boundary + 1)
          boundary = pendingSpeech.search(/[。！？.!?]/)
          if (boundary < 0 && pendingSpeech.length >= 16) boundary = pendingSpeech.search(/[，,；;：:]/)
          if (boundary < 0 && pendingSpeech.length >= 32) boundary = 31
        }
      }
      if (event.type === 'done') turn.persisted = true
    }, { realtimeSessionId })
    queueSpeech(pendingSpeech)
    completeStep('生成回复')
    await speechQueue
    if (speechFailure) throw speechFailure
  } catch (error) {
    if (!controller.signal.aborted && version === turnVersion) {
      ++turnVersion
      controller.abort()
      stopSpeech()
      replyAbort = null


      micError.value = error?.message || '语音对话失败，请检查模型配置'
      if (subtitleId === null) pushSubtitle('system', '回复失败，请重试。')
      if (voiceEnabled.value && !disposed) await startListening()
    }
  } finally {
    if (!turn.persisted) {
      saveRealtimeMessage('user', turn.user).catch(() => {})
      if (turn.spoken) saveRealtimeMessage('assistant', turn.spoken).catch(() => {})
    }
    if (pendingTurn === turn) pendingTurn = null
    if (version === turnVersion) {
      replyAbort = null
      speaking.value = false
      if (voiceEnabled.value && !disposed) await startListening()
      else if (!disposed) voiceStatus.value = '麦克风已关闭 · 点击语音球或按空格开启'
    }
  }
}

/** 拖拽面板内缘调整宽度（左面板拉右缘，右面板拉左缘）。 */
function startResize(side, e) {
  const startX = e.clientX
  const startW = Math.round(e.currentTarget.closest('.jarvis-panel')?.getBoundingClientRect().width || (side === 'left' ? leftWidth.value : rightWidth.value))
  const move = ev => {
    const dx = ev.clientX - startX
    const w = side === 'left' ? startW + dx : startW - dx
    const clamped = Math.max(220, Math.min(560, Math.round(w)))
    if (side === 'left') leftWidth.value = clamped
    else rightWidth.value = clamped
  }
  const up = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  e.preventDefault()
}

async function finalizeRealtimeSession() {
  if (finishPromise) return finishPromise
  finishPromise = (async () => {
    voiceEnabled.value = false
    stopListening()
    replyAbort?.abort()
    stopSpeech()
    await Promise.allSettled([...activeTurns])
    await realtimeTranscript.finish()
  })()
  return finishPromise
}

async function exit() {
  playMechanicalShutdown()
  const conversationId = realtimeTranscript.conversationId
  router.push({ path: '/', query: conversationId ? { conversationId } : {} })
}

onBeforeRouteLeave(async () => {
  try {
    await finalizeRealtimeSession()
  } catch (error) {
    micError.value = error?.message || '实时通话记录保存失败'
  }
})

onMounted(() => {
  realtimeTranscript = createRealtimeTranscript({
    api: chatApi, chat, sessionId: realtimeSessionId,
    conversationId: typeof route.query.conversationId === 'string' ? route.query.conversationId : chat.activeId,
    greeting: () => greetingSaved ? GREETING_TEXT : ''
  })
  window.addEventListener('keydown', onSpaceToggle)
  voiceEnabled.value = true
  showAssistant()
  prepareGreetingAudio()
  playGreeting()
  panelResizeObserver = new ResizeObserver(() => {
    scrollSubtitles()
    updatePanelScroll('subtitles')
    updatePanelScroll('agent')
  })
  for (const element of [subList.value, agentList.value]) {
    if (element) {
      panelResizeObserver.observe(element)
      if (element.firstElementChild) panelResizeObserver.observe(element.firstElementChild)
    }
  }
  updatePanelScroll('subtitles')
  updatePanelScroll('agent')
  clockTimer = window.setInterval(() => {
    now.value = new Date()
  }, 1000)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onSpaceToggle)
  panelResizeObserver?.disconnect()
  panelResizeObserver = null
  activeScrollDrag = null
  disposed = true
  voiceEnabled.value = false
  ++turnVersion
  stopListening()
  replyAbort?.abort()
  stopSpeech()
  clearGreetingAudio()

  window.clearInterval(clockTimer)
})
</script>

<template>
  <div class="jarvis" :class="{ 'is-listening': listening, 'is-speaking': particleSpeaking, 'is-awake': awake }">
    <!-- 背景层：网格、辉光、星点、扫描线 -->
    <div class="jarvis-bg" aria-hidden="true">
      <div class="jarvis-grid" />
      <div class="jarvis-glow glow-a" />
      <div class="jarvis-glow glow-b" />
      <div class="jarvis-stars">
        <i v-for="star in 26" :key="star" :style="{ left: `${(star * 37) % 100}%`, top: `${(star * 53) % 100}%`, animationDelay: `${(star % 9) * 0.6}s` }" />
      </div>
      <div class="jarvis-scan" />
    </div>

    <!-- 四周HUD边框：分布于屏幕四周的边框效果 -->
    <div class="jarvis-frame" aria-hidden="true">
      <span class="frame-corner fc-tl" /><span class="frame-corner fc-tr" />
      <span class="frame-corner fc-bl" /><span class="frame-corner fc-br" />
      <span class="frame-side fs-top" /><span class="frame-side fs-bottom" />
      <span class="frame-side fs-left" /><span class="frame-side fs-right" />
      <span class="frame-border" />
    </div>

    <!-- 顶栏 -->
    <header class="jarvis-strip">
      <!-- 品牌标：用MindPilot自己的Compass，配色跟本页的青色芯片统一 -->
      <span class="jarvis-brand">
        <span class="brand-mark"><Compass :size="19" /></span>
        <span class="brand-copy">
          <strong>MindPilot</strong>
          <small>智能知识管家 · 实时通话</small>
        </span>
      </span>
      <span class="strip-live" aria-hidden="true"><i /></span>
      <!-- 不挂title：按钮上已经写着「返回聊天界面」了，再挂title只会被全局
           AppTooltip接走、在按钮下面弹一个重复的气泡。无障碍语义走aria-label。 -->
      <button class="jarvis-exit" type="button" aria-label="返回聊天界面" @click="exit">
        <MessageSquare :size="17" />
        <span>返回聊天界面</span>
      </button>
    </header>

    <!-- 左上：对话内容面板（常驻展开，不可收缩） -->
    <aside class="jarvis-panel panel-left" :style="leftPanelStyle">
      <header class="panel-head">
        <span class="panel-icon"><MessageSquareText :size="15" /></span>
        <span class="panel-title">对话内容</span>
        <span class="panel-count"><b v-if="subtitles.length">{{ subtitles.length }}</b></span>
      </header>
      <div ref="subList" class="panel-body" tabindex="0" aria-label="对话内容" @scroll="onPanelScroll('subtitles', $event)">
        <ul class="subtitle-list">
          <li v-if="!subtitles.length && !liveSubtitle" class="subtitle-empty">请说话开始对话</li>
          <li v-for="sub in subtitles" :key="sub.id" class="subtitle-item" :class="sub.role">
            <span class="sub-meta">
              <b v-if="sub.role === 'system'">系统</b>
              <span v-else class="sub-role-icon" role="img" :aria-label="sub.role === 'human' ? '用户' : '智能知识管家'">
                <UserRound v-if="sub.role === 'human'" :size="14" />
                <Bot v-else :size="14" />
              </span>
              <i>{{ sub.time }}</i>
            </span>
            <p>{{ sub.text }}</p>
          </li>
          <li v-if="liveSubtitle" class="subtitle-item human is-live">
            <span class="sub-meta"><span class="sub-role-icon" role="img" aria-label="用户"><UserRound :size="14" /></span><i>实时</i></span>
            <p>{{ liveSubtitle }}</p>
          </li>
        </ul>
      </div>
      <div class="panel-scrollbar" :class="{ 'is-idle': !panelScroll.subtitles.overflow }" aria-hidden="true"
        @pointerdown="startPanelScrollbarDrag('subtitles', $event)"
        @pointermove="dragPanelScrollbar('subtitles', $event)"
        @pointerup="endPanelScrollbarDrag($event)" @pointercancel="endPanelScrollbarDrag($event)">
        <span class="panel-scroll-thumb" :style="{ top: `${panelScroll.subtitles.top * 100}%`, height: `${panelScroll.subtitles.size * 100}%` }" />
      </div>
      <div class="panel-resizer" @pointerdown="startResize('left', $event)" title="拖拽调整宽度" />
    </aside>

    <!-- 右上：Agent实时监控面板（常驻展开，不可收缩） -->
    <aside class="jarvis-panel panel-right" :style="rightPanelStyle">
      <header class="panel-head">
        <span class="panel-icon"><Activity :size="15" /></span>
        <span class="panel-title">Agent监控</span>
        <span class="panel-live"><i />LIVE</span>
      </header>
      <div ref="agentList" class="panel-body" tabindex="0" aria-label="Agent运行记录" @scroll="onPanelScroll('agent', $event)">
        <ul class="agent-list">
          <li v-if="!agentSteps.length" class="agent-empty">Agent空闲，等待语音输入…</li>
          <li v-for="step in agentSteps" :key="step.id" class="agent-step" :class="step.status">
            <span class="agent-step-dot" />
            <div><b>{{ step.label }}</b><p>{{ step.detail }}</p></div>
            <i>{{ step.time }}</i>
          </li>
        </ul>
      </div>
      <div class="panel-scrollbar" :class="{ 'is-idle': !panelScroll.agent.overflow }" aria-hidden="true"
        @pointerdown="startPanelScrollbarDrag('agent', $event)"
        @pointermove="dragPanelScrollbar('agent', $event)"
        @pointerup="endPanelScrollbarDrag($event)" @pointercancel="endPanelScrollbarDrag($event)">
        <span class="panel-scroll-thumb" :style="{ top: `${panelScroll.agent.top * 100}%`, height: `${panelScroll.agent.size * 100}%` }" />
      </div>
      <div class="panel-resizer" @pointerdown="startResize('right', $event)" title="拖拽调整宽度" />
    </aside>

    <!-- 中央：时间显示 / 虚拟助手形象 -->
    <main class="jarvis-stage">
      <Transition name="center" mode="out-in">
        <div class="jarvis-figure">
          <div class="figure-stage">
            <AssistantParticles :speaking="particleSpeaking" :listening="!!liveSubtitle" />
            <span class="fig-plinth" aria-hidden="true" />
            <span class="fig-scanline" aria-hidden="true" />
          </div>
        </div>
      </Transition>
    </main>

    <!-- 底部：常驻的接收语音形象。
         一个网壳球包着中心光核：没收到声音时壳是规整的球面网格、慢慢自转，
         收到声音后网格开始翻搅、变亮，光核也更刺眼。 -->
    <footer class="jarvis-voice">
      <p class="voice-status" role="status">{{ voiceStatus }}</p>
      <button class="voice-figure" :class="{ active: voiceActive, 'mic-on': voiceEnabled, 'mic-off': !voiceEnabled }"
        type="button" :aria-pressed="voiceEnabled"
        :aria-label="voiceEnabled ? '关闭麦克风，按空格也可切换' : '开启麦克风，按空格也可切换'"
        @click="toggleVoice">
        <span class="vo-halo" aria-hidden="true" />
        <span class="vo-particles" aria-hidden="true">
          <i v-for="(particle, index) in VOICE_PARTICLES" :key="index" :style="particle" />
        </span>
        <span class="vo-sphere" aria-hidden="true">
          <span class="vo-mesh">
            <i v-for="(ring, i) in VOICE_RINGS" :key="'vr' + i" :style="{ transform: ring }" />
          </span>
          <span class="vo-spark">
            <i
              v-for="(ring, i) in VOICE_SPARKS"
              :key="'vs' + i"
              :style="{ transform: ring, '--sd': (i * -0.17).toFixed(2) + 's' }"
            />
          </span>
        </span>
        <span class="vo-core" aria-hidden="true"><i /><i /><i /></span>
      </button>
      <p v-if="micError" class="voice-alert">{{ micError }}</p>
    </footer>
  </div>
</template>

<style scoped>
/* ------------------------------------------------------------------
 * AI 管家全息界面：深空底、青色全息视觉、HUD 元素，整体只在本页生效。
 * 全屏层用显式 left/top/width/height 定位，另给纯色背景兜底，
 * 避免旧内核浏览器（不支持 inset 简写）里全屏层塌缩成白屏。
 * ------------------------------------------------------------------ */
.jarvis{
  --cyan:#a967f9;
  --cyan-soft:#8e38f8;
  --cyan-dim:rgba(169,103,249,.28);
  --violet:#b88eeb;
  position:fixed;
  left:0;top:0;
  width:100%;height:100%;
  z-index:300;
  overflow:hidden;
  color:#eddfff;
  background-color:#220744;
  background-image:
    radial-gradient(circle at 50% 44%,rgba(126,34,238,.22),rgba(34,211,238,0) 48%),
    radial-gradient(circle at 50% 118%,rgba(142,56,248,.18),rgba(56,189,248,0) 56%),
    linear-gradient(180deg,#220744 0%,#350b68 52%,#200640 100%);
  font-family:var(--font-body);
  user-select:none;
  -webkit-user-select:none;
}

/* ---- 背景层 ---- */
.jarvis-bg{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}
.jarvis-grid{
  position:absolute;left:-2px;top:-2px;right:-2px;bottom:-2px;
  background-image:linear-gradient(rgba(169,103,249,.06) 1px,rgba(103,232,249,0) 1px),linear-gradient(90deg,rgba(169,103,249,.06) 1px,rgba(103,232,249,0) 1px);
  background-size:52px 52px;
  -webkit-mask-image:radial-gradient(circle at 50% 46%,#000 0%,rgba(0,0,0,0) 74%);
  mask-image:radial-gradient(circle at 50% 46%,#000 0%,rgba(0,0,0,0) 74%);
  animation:grid-drift 24s linear infinite;
}
@keyframes grid-drift{to{transform:translateY(52px)}}
.jarvis-glow{position:absolute;border-radius:50%;filter:blur(60px)}
.glow-a{width:560px;height:560px;left:50%;top:42%;margin:-280px 0 0 -280px;background:radial-gradient(circle,rgba(142,56,248,.22),rgba(56,189,248,0) 68%)}
.glow-b{width:380px;height:380px;right:6%;bottom:4%;background:radial-gradient(circle,rgba(169,103,249,.14),rgba(103,232,249,0) 70%)}
.jarvis-stars{position:absolute;left:0;top:0;width:100%;height:100%}
.jarvis-stars i{
  position:absolute;width:2px;height:2px;border-radius:50%;
  background:#ca9fff;box-shadow:0 0 8px rgba(169,103,249,.9);
  opacity:.7;animation:star-twinkle 4.4s ease-in-out infinite;
}
@keyframes star-twinkle{0%,100%{opacity:.18}50%{opacity:.9}}
.jarvis-scan{
  position:absolute;left:0;right:0;height:120px;top:-130px;
  background:linear-gradient(180deg,rgba(103,232,249,0),rgba(169,103,249,.09),rgba(103,232,249,0));
  animation:scan-move 7s linear infinite;
}
@keyframes scan-move{to{transform:translateY(calc(100vh + 260px))}}

/* ---- 四周 HUD 边框 ---- */
.jarvis-frame{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:1}
.frame-border{position:absolute;left:16px;top:16px;right:16px;bottom:16px;border:1px solid rgba(169,103,249,.13);border-radius:8px}
.frame-corner{position:absolute;width:54px;height:54px;border:2px solid rgba(169,103,249,.55);filter:drop-shadow(0 0 7px rgba(142,56,248,.55))}
.fc-tl{left:16px;top:16px;border-right:0;border-bottom:0;border-radius:8px 0 0 0}
.fc-tr{right:16px;top:16px;border-left:0;border-bottom:0;border-radius:0 8px 0 0}
.fc-bl{left:16px;bottom:16px;border-right:0;border-top:0;border-radius:0 0 0 8px}
.fc-br{right:16px;bottom:16px;border-left:0;border-top:0;border-radius:0 0 8px 0}
.frame-side{position:absolute;background:linear-gradient(90deg,rgba(103,232,249,0),rgba(169,103,249,.5),rgba(103,232,249,0))}
.fs-top{left:24%;right:24%;top:16px;height:1px}
.fs-bottom{left:24%;right:24%;bottom:16px;height:1px}
.fs-left{left:16px;top:26%;bottom:26%;width:1px;background:linear-gradient(180deg,rgba(103,232,249,0),rgba(169,103,249,.5),rgba(103,232,249,0))}
.fs-right{right:16px;top:26%;bottom:26%;width:1px;background:linear-gradient(180deg,rgba(103,232,249,0),rgba(169,103,249,.5),rgba(103,232,249,0))}
/* 上下两条边原来的刻度短线（ticks）已按需求去掉，只留长渐变边线 */

/* ---- 顶栏 ----
 * 左边是品牌标（徽记 + 两行中文名，用产品自己的 Compass），右边是带文字的退出按钮。
 * 中间原来有一条把两端连起来的渐隐横线，已去掉：它和四周 HUD 边框的上边线在屏幕
 * 上方并成上下两条平行的横线，上层那条（HUD 边框）才是要留的，这条是第二层。
 * 横线原本兼着 flex:1 撑开两端的作用，撤掉之后改由线尾那颗呼吸灯 margin-left:auto
 * 把「呼吸灯 + 退出按钮」这一组顶到右边，和原来的排布一致。
 * 文案只留中文，原来右侧那串英文状态字（HOLOGRAM ACTIVE / STANDBY）已去掉。
 */
.jarvis-strip{position:absolute;top:0;left:0;right:0;z-index:5;display:flex;align-items:center;gap:16px;padding:26px var(--workspace-page-gutter,42px)}
.strip-live{display:inline-flex;align-items:center;justify-content:center;width:10px;height:10px;border-radius:50%;border:1px solid rgba(169,103,249,.35);margin-left:auto}
.strip-live i{width:5px;height:5px;border-radius:50%;background:var(--cyan);box-shadow:0 0 10px var(--cyan);animation:status-blink 1.6s ease-in-out infinite}
/* 品牌标：徽记沿用面板里的 .panel-icon 芯片语言，右侧两行字一主一辅 */
.jarvis-brand{display:flex;align-items:center;gap:11px;flex:0 0 auto}
.jarvis-brand .brand-mark{
  width:42px;height:42px;flex:0 0 42px;border-radius:14px;display:grid;place-items:center;
  color:#bf8bff;background:rgba(142,56,248,.12);
  border:1px solid rgba(169,103,249,.34);
  box-shadow:0 0 18px rgba(142,56,248,.22),inset 0 1px 0 rgba(234,216,255,.14);
}
.brand-copy{display:grid;gap:2px;line-height:1.15}
.brand-copy strong{font-size:15px;font-weight:600;letter-spacing:.06em;color:#f2e8ff}
.brand-copy small{font-size:11px;letter-spacing:.1em;color:rgba(190,155,232,.72)}
.jarvis-exit{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;
  height:42px;flex:0 0 auto;padding:0 16px;
  border:1px solid rgba(169,103,249,.32);border-radius:14px;
  color:#dcbfff;background:rgba(142,56,248,.08);transition:.2s;
  font-size:13px;letter-spacing:.08em;white-space:nowrap;
  -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);
}
.jarvis-exit:hover{background:rgba(142,56,248,.2);border-color:rgba(169,103,249,.6);color:#f3eaff;box-shadow:0 0 20px rgba(142,56,248,.35)}
.jarvis-exit:focus-visible{outline:2px solid rgba(169,103,249,.7);outline-offset:2px}

/* ---- 左右浮动面板 ----
 * 卡片式的框：描边只画在四个角上，四条边的中段不画线。
 * 做法是整圈 1px 描边裁到 border-box，但底下只垫四道径向光——圆心钉在角上，
 * 前 34px 是等亮的平台、到 54px 衰减干净。中段离角太远，落到平台外，
 * 于是只剩四个角各一段「直角带弧」的亮线，边中段是空的。
 * 卡片与背景的边界靠底色拉开（比背景亮一档的深蓝）+ 一圈很淡的外发光，
 * 所以角标线可以压得很暗，轮廓依然清楚。
 */
.jarvis-panel{
  /* 左右面板等高延伸，底部留出更宽的呼吸空间。 */
  position:absolute;top:100px;bottom:60px;z-index:4;min-height:0;
  display:flex;flex-direction:column;
  border:1px solid transparent;border-radius:22px;
  background-image:
    /* 1. 卡片底色：比背景亮一档的深蓝，卡片轮廓由它撑出来 */
    linear-gradient(180deg,rgba(46,13,86,.95) 0%,rgba(38,10,73,.94) 55%,rgba(32,8,62,.93) 100%),
    /* 2-5. 四个角的角标线：先一段等亮，再收干净 */
    radial-gradient(circle at 0 0,rgba(220,191,255,.48) 0,rgba(220,191,255,.48) 34px,rgba(139,240,255,0) 54px),
    radial-gradient(circle at 100% 0,rgba(220,191,255,.44) 0,rgba(220,191,255,.44) 34px,rgba(139,240,255,0) 54px),
    radial-gradient(circle at 0 100%,rgba(220,191,255,.32) 0,rgba(220,191,255,.32) 34px,rgba(103,232,249,0) 54px),
    radial-gradient(circle at 100% 100%,rgba(220,191,255,.32) 0,rgba(220,191,255,.32) 34px,rgba(103,232,249,0) 54px);
  background-origin:border-box;
  background-clip:padding-box,border-box,border-box,border-box,border-box;
  box-shadow:
    0 22px 48px rgba(1,4,10,.5),
    0 0 34px rgba(142,56,248,.2),
    inset 0 1px 0 rgba(234,216,255,.06);
  overflow:hidden;
}
.panel-left{left:40px}
.panel-right{right:40px}
.panel-head{position:relative;display:flex;align-items:center;gap:10px;padding:13px 15px;flex:0 0 auto}
/* 头部下方那条分隔线：由左向右渐隐 */
.panel-head::after{content:'';position:absolute;left:15px;right:15px;bottom:0;height:1px;background:linear-gradient(90deg,rgba(220,191,255,.32),rgba(169,103,249,.12) 58%,rgba(103,232,249,0))}
.panel-icon{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;color:#bf8bff;background:rgba(142,56,248,.12);border:1px solid rgba(169,103,249,.32);box-shadow:0 0 12px rgba(142,56,248,.18)}
.panel-title{font-size:13px;font-weight:700;letter-spacing:2.6px;color:#f3eaff;text-shadow:0 0 14px rgba(169,103,249,.35)}
.panel-count{margin-left:auto;display:inline-flex;align-items:center;gap:7px;font-size:11px;color:rgba(182,125,252,.6);font-variant-numeric:tabular-nums}
.panel-count::after{content:'';width:8px;height:8px;border-radius:50%;background:#bf8bff;box-shadow:0 0 10px #a967f9,0 0 22px rgba(142,56,248,.6);animation:status-blink 1.8s ease-in-out infinite}
.panel-live{margin-left:auto;display:inline-flex;align-items:center;gap:7px;font-size:10px;letter-spacing:1.8px;color:rgba(182,125,252,.6)}
.panel-live i{width:8px;height:8px;border-radius:50%;background:#bf8bff;box-shadow:0 0 10px #a967f9,0 0 22px rgba(142,56,248,.6);animation:status-blink 1.8s ease-in-out infinite}
.panel-body{flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding:14px 23px 14px 12px;overscroll-behavior:contain;scrollbar-width:none}
.panel-body:focus-visible{outline:1px solid rgba(169,103,249,.5);outline-offset:-2px}
.panel-body::-webkit-scrollbar{display:none}
.panel-scrollbar{position:absolute;top:30%;bottom:30%;right:9px;width:14px;border-radius:99px;touch-action:none;cursor:pointer}
.panel-scrollbar::before{content:'';position:absolute;inset:0 4px;border-radius:99px;background:rgba(169,103,249,.11)}
.panel-scroll-thumb{position:absolute;left:4px;right:4px;min-height:20px;border-radius:99px;background:rgba(183,129,250,.72);box-shadow:0 0 9px rgba(169,103,249,.3);transition:background .2s}
.panel-scrollbar:hover .panel-scroll-thumb{background:#cca5fc}
.panel-scrollbar.is-idle{opacity:0;pointer-events:none}
/* 拖拽把手放在面板内侧：面板开了 overflow:hidden，放外面会被裁掉 */
.panel-resizer{position:absolute;top:14px;bottom:14px;width:8px;cursor:ew-resize}
.panel-left .panel-resizer{right:0}
.panel-right .panel-resizer{left:0}
.panel-resizer:hover,.panel-resizer:active{background:rgba(169,103,249,.16)}

/* 实时对话：AI 靠左，用户靠右，系统消息居中。 */
.subtitle-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:18px}
.subtitle-empty{font-size:12px;color:rgba(182,125,252,.45);text-align:center;padding:18px 6px}
.subtitle-item{display:flex;flex-direction:column;align-items:flex-start;gap:6px;max-width:88%;align-self:flex-start;min-width:0}
.subtitle-item.human{align-self:flex-end;align-items:flex-end}
.subtitle-item.human .sub-meta{flex-direction:row-reverse}
.subtitle-item.system{align-self:center;align-items:center;max-width:100%;text-align:center;margin:2px 0}
.sub-meta{display:flex;align-items:center;gap:8px}
.sub-role-icon{position:relative;display:grid;place-items:center;width:23px;height:23px;flex:0 0 23px;border:1px solid rgba(191,139,255,.3);border-radius:8px;background:rgba(142,56,248,.12);color:#d7b7ff;box-shadow:inset 0 1px 0 rgba(234,216,255,.08)}
.subtitle-item.human .sub-role-icon{border-color:rgba(182,125,252,.32);background:rgba(126,34,238,.14);color:#eee0ff}
.sub-meta b{font-size:10px;font-weight:700;letter-spacing:1.6px;color:#bf8bff;text-shadow:0 0 10px rgba(169,103,249,.45)}
.subtitle-item.system .sub-meta b{color:rgba(182,125,252,.5);text-shadow:none}
.sub-meta i{font-style:normal;font-size:10px;color:rgba(182,125,252,.38);font-variant-numeric:tabular-nums}
.subtitle-item p{margin:0;max-width:100%;padding:10px 12px;border:1px solid rgba(169,103,249,.22);border-radius:3px 14px 14px 14px;background:rgba(142,56,248,.09);font-size:13.5px;line-height:1.7;font-weight:400;color:#f8f2ff;overflow-wrap:anywhere;white-space:pre-wrap;text-align:left}
.subtitle-item.human p{border-radius:14px 3px 14px 14px;background:rgba(126,34,238,.13);border-color:rgba(169,103,249,.27)}
.subtitle-item.system p{padding:0 4px;border:0;background:none;font-size:12px;font-weight:400;color:rgba(182,125,252,.6);text-align:center}
.subtitle-item.is-live p{color:rgba(248,242,255,.62)}
.subtitle-item.is-live .sub-role-icon::after{content:'';position:absolute;right:-2px;top:-2px;width:5px;height:5px;border-radius:50%;background:#bf8bff;box-shadow:0 0 8px #a967f9;animation:status-blink .9s ease-in-out infinite}

/* ---- Agent 监控面板内容 ----
 * 只留执行步骤时间线：顶部原来那条「正在聆听」状态条和遥测读数栏已去掉，
 * 状态文案在底部语音区还有一份，不重复占位。
 */
.agent-list{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.agent-empty{font-size:12px;color:rgba(182,125,252,.45);text-align:center;padding:16px 6px}
.agent-step{display:flex;align-items:flex-start;gap:9px;padding:8px 10px;border-radius:10px;border:1px solid rgba(169,103,249,.1);background:rgba(142,56,248,.04)}
.agent-step.active{border-color:rgba(169,103,249,.4);background:rgba(142,56,248,.1)}
.agent-step-dot{width:7px;height:7px;border-radius:50%;margin-top:4px;flex:0 0 7px;background:rgba(182,125,252,.4)}
.agent-step.active .agent-step-dot{background:var(--cyan);box-shadow:0 0 10px var(--cyan);animation:status-blink .8s ease-in-out infinite}
.agent-step div{flex:1;min-width:0}
.agent-step b{display:block;font-size:12px;color:#eddfff;font-weight:600}
.agent-step p{margin:2px 0 0;font-size:11px;color:rgba(182,125,252,.55);line-height:1.45;word-break:break-word}
.agent-step>i{font-style:normal;font-size:10px;color:rgba(182,125,252,.35);font-variant-numeric:tabular-nums}

/* ---- 中央舞台 ---- */
.jarvis-stage{
  position:absolute;left:0;top:0;right:0;bottom:0;z-index:2;
  display:flex;align-items:center;justify-content:center;
  /* 左右留出浮动面板的宽度，中央形象才不会被压住 */
  padding:104px 360px 132px;pointer-events:none;
}
.center-enter-active,.center-leave-active{transition:opacity .35s,transform .35s}
.center-enter-from{opacity:0;transform:scale(.9) translateY(6px)}
.center-leave-to{opacity:0;transform:scale(1.04) translateY(-6px)}

/* 时间显示 */
.jarvis-clock{text-align:center;display:grid;gap:8px;justify-items:center}
.clock-week{font-size:14px;letter-spacing:6px;color:#d8b9ff;text-shadow:0 0 16px rgba(169,103,249,.5);text-transform:uppercase;margin:0}
.clock-time{
  margin:0;font-size:clamp(56px,9vw,108px);font-weight:200;line-height:1;
  letter-spacing:2px;color:#f3eaff;font-variant-numeric:tabular-nums;
  text-shadow:0 0 30px rgba(169,103,249,.45),0 0 90px rgba(142,56,248,.3);
}
.clock-date{margin:0;font-size:16px;letter-spacing:3px;color:#c39cf3;text-shadow:0 0 12px rgba(142,56,248,.35)}
.clock-wake{margin:26px 0 0;font-size:14px;font-weight:600;letter-spacing:2px;color:#e0c7ff;text-shadow:0 0 14px rgba(169,103,249,.55)}
.clock-demo{margin:8px 0 0;font-size:12px;letter-spacing:2px;color:#b88eeb}

/* 虚拟助手形象 */
.jarvis-figure{display:grid;gap:16px;justify-items:center}
.figure-stage{position:relative;width:420px;height:420px;display:grid;place-items:center}

/* 地面上的一圈基座光台 */
.fig-plinth{
  position:absolute;left:50%;bottom:30px;width:400px;height:80px;margin-left:-200px;
  border-radius:50%;border:1px solid rgba(169,103,249,.42);
  background:radial-gradient(ellipse at center,rgba(142,56,248,.3),rgba(56,189,248,0) 70%);
  transform:rotateX(74deg);filter:blur(.4px);
}
/* 向外扩散的脉冲环 */
.fig-pulse{
  position:absolute;left:50%;top:50%;width:260px;height:260px;margin:-130px 0 0 -130px;
  border-radius:50%;border:1px solid rgba(169,103,249,.45);
  animation:fig-pulse 3.6s ease-out infinite;
}
.fig-pulse.p2{animation-delay:1.2s}
.fig-pulse.p3{animation-delay:2.4s}
@keyframes fig-pulse{
  0%{transform:scale(.55);opacity:.85}
  100%{transform:scale(1.9);opacity:0}
}
.jarvis.is-speaking .fig-pulse{animation-duration:1.6s}

/* 环绕的卫星光点 */
.fig-orbit{position:absolute;left:50%;top:50%;border-radius:50%;border:1px dashed rgba(182,125,252,.16)}
.fig-orbit i{position:absolute;left:50%;top:-3px;width:6px;height:6px;margin-left:-3px;border-radius:50%;background:#dcbfff;box-shadow:0 0 12px #a967f9}
.fig-orbit.o1{width:352px;height:352px;margin:-176px 0 0 -176px;transform:rotateX(70deg);animation:spin 9s linear infinite}
.fig-orbit.o2{width:430px;height:430px;margin:-215px 0 0 -215px;transform:rotateX(66deg) rotateY(18deg);animation:spin-rev 15s linear infinite}
.fig-orbit.o2 i{background:#a5b4fc;box-shadow:0 0 12px #818cf8}
/* 环绕线条：三圈斜斜套在球外面的细轨道，圈本身固定，跑动的是圈上那颗光点。
 * 倾斜角必须写进关键帧里 —— 关键帧里的 transform 会整条替换元素的静态值，
 * 只写 rotate(360deg) 的话每帧都会把倾斜抹掉，环就变成一个正圆了。 */
.fig-halo{position:absolute;left:50%;top:50%;border-radius:50%;border:1px solid rgba(182,125,252,.22)}
.fig-halo i{position:absolute;left:50%;top:-3px;width:6px;height:6px;margin-left:-3px;border-radius:50%;background:#ead8ff;box-shadow:0 0 12px #a967f9,0 0 26px rgba(142,56,248,.8)}
.fig-halo.h1{width:336px;height:336px;margin:-168px 0 0 -168px;animation:halo-a 22s linear infinite}
.fig-halo.h2{width:374px;height:374px;margin:-187px 0 0 -187px;animation:halo-b 30s linear infinite}
.fig-halo.h3{width:400px;height:400px;margin:-200px 0 0 -200px;border-color:rgba(165,180,252,.16);animation:halo-c 38s linear infinite}
@keyframes halo-a{from{transform:rotateX(74deg) rotateZ(12deg) rotate(0deg)}to{transform:rotateX(74deg) rotateZ(12deg) rotate(360deg)}}
@keyframes halo-b{from{transform:rotateX(58deg) rotateZ(-30deg) rotate(360deg)}to{transform:rotateX(58deg) rotateZ(-30deg) rotate(0deg)}}
@keyframes halo-c{from{transform:rotateY(70deg) rotateX(24deg) rotate(0deg)}to{transform:rotateY(70deg) rotateX(24deg) rotate(360deg)}}

/* 核心向上下延伸的光柱 */
.core-beam{
  position:absolute;left:50%;top:50%;width:2px;height:340px;margin:-170px 0 0 -1px;
  background:linear-gradient(180deg,rgba(103,232,249,0),rgba(169,103,249,.55),rgba(169,103,249,.55),rgba(103,232,249,0));
  filter:blur(.5px);opacity:.65;
}
/* 扫过全息体的光带 */
.fig-scanline{
  position:absolute;left:50%;top:50%;width:400px;height:2px;margin:-1px 0 0 -200px;
  background:linear-gradient(90deg,rgba(103,232,249,0),rgba(220,191,255,.85),rgba(103,232,249,0));
  filter:blur(.6px);animation:fig-scan 3.4s ease-in-out infinite;
}
@keyframes fig-scan{0%,100%{transform:translateY(-140px);opacity:.15}50%{transform:translateY(140px);opacity:.75}}

.jarvis-orb{position:relative;width:400px;height:400px;perspective:1000px;animation:orb-enter .9s cubic-bezier(.2,.8,.2,1) both}
@keyframes orb-enter{0%{opacity:0;transform:scale(.55)}60%{opacity:1}100%{opacity:1;transform:scale(1)}}
.jarvis-orb::before{
  content:"";position:absolute;left:-46px;top:-46px;right:-46px;bottom:-46px;border-radius:50%;
  background:radial-gradient(circle,rgba(142,56,248,.15),rgba(142,56,248,.06) 42%,rgba(56,189,248,0) 72%);
  filter:blur(6px);transition:.6s;
}
.jarvis.is-listening .jarvis-orb::before{left:-66px;top:-66px;right:-66px;bottom:-66px;background:radial-gradient(circle,rgba(142,56,248,.34),rgba(56,189,248,0) 68%)}
.jarvis.is-speaking .jarvis-orb::before{background:radial-gradient(circle,rgba(169,103,249,.42),rgba(103,232,249,0) 70%)}

.jarvis-gyro{position:absolute;left:0;top:0;width:100%;height:100%;transform-style:preserve-3d;animation:gyro-tumble 16s linear infinite}
.jarvis-gyro i{position:absolute;left:0;top:0;width:100%;height:100%;border-radius:50%;border:1px solid rgba(169,103,249,.32)}
.jarvis-gyro i:nth-child(1){transform:rotateY(0deg)}
.jarvis-gyro i:nth-child(2){transform:rotateY(72deg)}
.jarvis-gyro i:nth-child(3){transform:rotateY(144deg)}
.jarvis-gyro i:nth-child(4){transform:rotateY(216deg)}
@keyframes gyro-tumble{from{transform:rotateX(64deg) rotateY(0deg)}to{transform:rotateX(64deg) rotateY(360deg)}}

.jarvis-ring-flat{position:absolute;left:0;top:0;width:100%;height:100%;border-radius:50%;border:1px solid rgba(169,103,249,.18);animation:spin 18s linear infinite}
.jarvis-ring-flat i{position:absolute;left:50%;top:-4px;width:8px;height:8px;margin-left:-4px;border-radius:50%;background:#dcbfff;box-shadow:0 0 12px #a967f9,0 0 28px rgba(142,56,248,.9)}

.jarvis-ring-tilt{position:absolute;left:8%;top:50%;width:84%;height:84%;margin-top:-42%;border-radius:50%;border:1px solid rgba(182,125,252,.28);transform:rotateX(76deg);animation:spin-rev 40s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes spin-rev{to{transform:rotate(-360deg)}}
/* 各处状态灯的呼吸，面板 / 顶栏 / 字幕 / Agent 步骤都在用 */
@keyframes status-blink{0%,100%{opacity:.35}50%{opacity:1}}

.jarvis-core{position:absolute;left:0;top:0;width:100%;height:100%;display:grid;place-items:center}
/* ---- AI 管家核心 ----
 * 虚拟助手形象：一颗真的在自转的线框球，里面裹着一颗发白的光核。
 * 线框是真 3D —— 6 条经线是绕 Y 轴每隔 30° 排开的整圆，7 条纬线是抬到对应高度的
 * 圆，半径与高度全部由 --jg-r 推出来，改这一个变量整颗球就等比缩放。
 * 球体不填色，只有线：光晕垫在底下、线压在上面，正面背面的线都看得见，
 * 这正是全息线框该有的通透感；最外面再补一道亮边，把球的轮廓勾出来。
 * 球心不是光球，是 .jg-head 里的三维管家头像（ButlerAvatar.vue 画出来的 canvas）
 * —— 线框要压在头像后面，所以 .jg-spin 排在 .jg-head 前面，靠 DOM 顺序而不是 z-index。
 */
.jg{position:absolute;width:280px;height:280px;--jg-r:140px;perspective:900px;animation:core-pulse 3.6s ease-in-out infinite}
.jg-glow{
  position:absolute;left:50%;top:50%;width:190%;height:190%;margin:-95% 0 0 -95%;border-radius:50%;
  background:radial-gradient(circle,rgba(142,56,248,.12) 0%,rgba(142,56,248,.13) 52%,rgba(126,34,238,.05) 72%,rgba(56,189,248,0) 86%);
  filter:blur(8px);
}
/* 头像：球心是一颗真的三维管家头 —— ButlerAvatar.vue 里的 three.js canvas。
 * 这里只负责给它一个盒子：canvas 自己铺满盒子，相机取景固定在组件里，
 * 所以改 --head-w 就等于整体缩放。
 * 盒子做成 1 : 1.31 的竖长方形，因为三维形象不只是一颗头，上面顶着天线、
 * 下面连着领口和领结；按正方形给会把天线截掉。
 * 居中靠 left/top:50% + 负 margin，不用 translate —— 底下的 face-hover 关键帧
 * 会整个顶掉元素自己的 transform，写 translate 的话头像会被动画顶出球心。
 * 眼带的明灭快慢不在这里管：那是三维材质的不透明度，由组件按 listening /
 * speaking 两个 prop 自己插值，CSS 插不进 canvas 里去。 */
.jg-head{
  position:absolute;left:50%;top:50%;
  --head-w:calc(var(--jg-r) * 1.34);
  width:var(--head-w);height:calc(var(--head-w) * 1.31);
  margin:calc(var(--head-w) * -.655) 0 0 calc(var(--head-w) * -.5);
  animation:face-hover 6.4s ease-in-out infinite;
}
@keyframes face-hover{0%,100%{transform:translateY(-4px)}50%{transform:translateY(4px)}}
.jg-spin{position:absolute;left:0;top:0;width:100%;height:100%;transform-style:preserve-3d;animation:jg-rotate 34s linear infinite}
.jg-spin > span{position:absolute;left:0;top:0;width:100%;height:100%;transform-style:preserve-3d}
.jg-spin i{position:absolute;left:0;top:0;width:100%;height:100%;border-radius:50%;border:1px solid rgba(203,160,255,.34)}
/* 经线：6 条整圆绕 Y 轴每隔 30° 排开，合起来就是一整圈 */
.jg-mer i:nth-child(2){transform:rotateY(30deg)}
.jg-mer i:nth-child(3){transform:rotateY(60deg)}
.jg-mer i:nth-child(4){transform:rotateY(90deg)}
.jg-mer i:nth-child(5){transform:rotateY(120deg)}
.jg-mer i:nth-child(6){transform:rotateY(150deg)}
/* 纬线：抬到 ±0.5 / ±0.866 / ±0.966 个半径高处的小圆，最大的一条是赤道 */
.jg-par i{left:50%;top:50%;border-color:rgba(217,186,255,.28)}
.jg-par i:nth-child(1){width:100%;height:100%;margin:-50% 0 0 -50%;transform:rotateX(90deg)}
.jg-par i:nth-child(2){width:86.6%;height:86.6%;margin:-43.3% 0 0 -43.3%;transform:rotateX(90deg) translateZ(calc(var(--jg-r) * .5))}
.jg-par i:nth-child(3){width:86.6%;height:86.6%;margin:-43.3% 0 0 -43.3%;transform:rotateX(90deg) translateZ(calc(var(--jg-r) * -.5))}
.jg-par i:nth-child(4){width:50%;height:50%;margin:-25% 0 0 -25%;transform:rotateX(90deg) translateZ(calc(var(--jg-r) * .866))}
.jg-par i:nth-child(5){width:50%;height:50%;margin:-25% 0 0 -25%;transform:rotateX(90deg) translateZ(calc(var(--jg-r) * -.866))}
.jg-par i:nth-child(6){width:26%;height:26%;margin:-13% 0 0 -13%;transform:rotateX(90deg) translateZ(calc(var(--jg-r) * .966))}
.jg-par i:nth-child(7){width:26%;height:26%;margin:-13% 0 0 -13%;transform:rotateX(90deg) translateZ(calc(var(--jg-r) * -.966))}
/* 球的轮廓：贴着赤道大圆的一道亮边 */
.jg-rim{
  position:absolute;left:0;top:0;width:100%;height:100%;border-radius:50%;
  border:1px solid rgba(217,186,255,.34);
  box-shadow:inset 0 0 36px rgba(169,103,249,.3),0 0 34px rgba(142,56,248,.28);
}
@keyframes jg-rotate{from{transform:rotateY(0deg)}to{transform:rotateY(360deg)}}
.jarvis.is-listening .jg{animation-duration:1.6s}
.jarvis.is-listening .jg-spin{animation-duration:14s}
/* 回话时整颗球微微胀大一圈，头跟着等比放大 —— 尺寸仍由 --jg-r 一处推出来 */
.jarvis.is-speaking .jg{animation-duration:1.5s;width:300px;height:300px;--jg-r:150px}
.jarvis.is-speaking .jg-spin{animation-duration:9s}
@keyframes core-pulse{0%,100%{transform:scale(1);opacity:.92}50%{transform:scale(1.07);opacity:1}}

/* ---- 底部接收语音动态形象 ----
 * 一个网壳球包着一颗光核。壳由十几圈过球心的大圆叠出来（单看每圈都是正圆，
 * 角度错开后就是一个球面网格），整体慢慢翻滚 —— 这是「待机」的样子：规整、安静。
 * 收到声音后壳开始搅动、线变亮，另外几圈乱线浮出来，光核也更刺眼。
 */
.jarvis-voice{position:absolute;left:0;right:0;bottom:0;z-index:3;display:grid;gap:10px;justify-items:center;padding:0 20px 30px;pointer-events:none}
.voice-status{margin:0;color:rgba(224,198,255,.75);font-size:12px;letter-spacing:.5px}
.voice-figure{position:relative;width:280px;height:150px;display:grid;place-items:center;perspective:460px;pointer-events:auto;appearance:none;border:0;padding:0;background:transparent;color:inherit;font:inherit;cursor:pointer;-webkit-tap-highlight-color:transparent}
.voice-figure:focus-visible{outline:none}
.voice-figure:focus-visible::after{content:"";position:absolute;left:50%;top:50%;width:112px;height:112px;margin:-56px 0 0 -56px;border:1px solid rgba(218,191,250,.68);border-radius:50%;box-shadow:0 0 14px rgba(188,145,240,.2);pointer-events:none}
.voice-figure.mic-on:hover .vo-halo{background:radial-gradient(circle,rgba(169,103,249,.36),rgba(56,189,248,0) 70%)}
.vo-halo{
  position:absolute;left:50%;top:50%;width:168px;height:168px;margin:-84px 0 0 -84px;border-radius:50%;
  background:radial-gradient(circle,rgba(142,56,248,.26),rgba(56,189,248,0) 68%);
  filter:blur(9px);transition:.6s;
}
.voice-figure.mic-on .vo-halo{width:236px;height:236px;margin:-118px 0 0 -118px;background:radial-gradient(circle,rgba(142,56,248,.24),rgba(142,56,248,.08) 48%,rgba(56,189,248,0) 72%)}
.voice-figure.mic-on.active .vo-halo{width:282px;height:282px;margin:-141px 0 0 -141px;background:radial-gradient(circle,rgba(169,103,249,.34),rgba(169,103,249,.1) 49%,rgba(103,232,249,0) 74%)}

.vo-particles{position:absolute;inset:0;transform-style:preserve-3d;opacity:0;transition:opacity .65s ease-out;pointer-events:none}
.voice-figure.active .vo-particles{opacity:1;transition-duration:.2s}
.vo-particles i{position:absolute;left:50%;top:50%;width:var(--particle-size);height:var(--particle-size);margin:-1px 0 0 -1px;border-radius:50%;background:#e1c8ff;box-shadow:0 0 6px #a967f9,0 0 14px #8e38f86b;opacity:0;animation:vo-particle-out var(--particle-duration) ease-out infinite;animation-delay:var(--particle-delay);animation-play-state:paused}
.voice-figure.active .vo-particles i{animation-play-state:running}
@keyframes vo-particle-out{
  0%{transform:translate3d(var(--px),var(--py),var(--pz)) scale(.35);opacity:0}
  18%{opacity:.95}
  65%{opacity:.55}
  100%{transform:translate3d(var(--ex),var(--ey),var(--ez)) scale(.15);opacity:0}
}
@media(prefers-reduced-motion:reduce){.vo-particles i{animation:none;transform:translate3d(var(--px),var(--py),var(--pz));opacity:.45}.vo-particles{transition:none}}

/* 壳：.vo-sphere 负责整体翻滚，.vo-mesh 里的每一圈只负责自己的朝向 */
.vo-sphere{position:relative;width:98px;height:98px;transform-style:preserve-3d;animation:vo-tumble 15s linear infinite}
.vo-mesh{position:absolute;left:0;top:0;width:100%;height:100%;transform-style:preserve-3d}
.vo-mesh i{
  position:absolute;left:0;top:0;width:100%;height:100%;border-radius:50%;
  border:1px solid rgba(182,125,252,.32);
  transition:border-color .5s,box-shadow .5s;
}
/* 乱线：待机时完全不出现，有声音了才浮上来，并自己绕一个斜轴慢慢搅动 */
.vo-spark{
  position:absolute;left:0;top:0;width:100%;height:100%;
  transform-style:preserve-3d;opacity:0;transition:opacity .5s;
  animation:vo-stir 6s linear infinite;
}
.vo-spark i{
  position:absolute;left:0;top:0;width:100%;height:100%;border-radius:50%;
  border:1px solid rgba(217,186,255,.5);
  animation:vo-quiver 1.5s ease-in-out infinite;
  animation-delay:var(--sd);
}
@keyframes vo-tumble{from{transform:rotateX(-20deg) rotateY(0deg)}to{transform:rotateX(-20deg) rotateY(360deg)}}
@keyframes vo-stir{from{transform:rotate3d(1,0,1,0deg)}to{transform:rotate3d(1,0,1,360deg)}}
@keyframes vo-quiver{0%,100%{opacity:.3;border-color:rgba(217,186,255,.35)}50%{opacity:1;border-color:rgba(245,236,255,.85)}}

/* 中心光核 + 两圈往外扩散的涟漪 */
.vo-core{position:absolute;left:50%;top:50%;width:24px;height:24px;margin:-12px 0 0 -12px}
.vo-core i{position:absolute;left:50%;top:50%;border-radius:50%;transform:translate(-50%,-50%)}
/* 光核：直接铺满 .vo-core，不靠 translate 居中 ——
 * core-pulse 会重写 transform，一旦沾上 translate 就会被动画顶掉，球就偏出去了。 */
.vo-core i:nth-child(1){
  left:0;top:0;width:100%;height:100%;transform:none;
  background:radial-gradient(circle at 40% 36%,#fff,#bf8bff 42%,#7e22ee 74%);
  box-shadow:0 0 18px rgba(142,56,248,.9),0 0 46px rgba(126,34,238,.45);
  animation:core-pulse 3.4s ease-in-out infinite;
}
.vo-core i:nth-child(2){width:44px;height:44px;border:1px solid rgba(169,103,249,.42);animation:vo-ripple 3.6s ease-out infinite}
.vo-core i:nth-child(3){width:44px;height:44px;border:1px solid rgba(169,103,249,.3);animation:vo-ripple 3.6s ease-out infinite;animation-delay:1.8s}
@keyframes vo-ripple{
  0%{transform:translate(-50%,-50%) scale(.6);opacity:.9}
  100%{transform:translate(-50%,-50%) scale(1.55);opacity:0}
}

/* 收到声音：转得更快、壳更亮、乱线浮出来、光核跳得更急 */
.voice-figure.active .vo-sphere{animation-duration:5.5s}
.voice-figure.active .vo-mesh i{border-color:rgba(217,186,255,.58);box-shadow:0 0 8px rgba(169,103,249,.35)}
.voice-figure.active .vo-spark{opacity:1}
.voice-figure.active .vo-core i:nth-child(1){animation-duration:1.1s}

/* 关闭后固定正面球形轮廓，仅保留浅冰蓝色网格与中心核。 */
.voice-figure.mic-off .vo-halo,.voice-figure.mic-off .vo-particles,.voice-figure.mic-off .vo-spark{opacity:0}
.voice-figure.mic-off .vo-sphere{animation:none;transform:rotateX(0deg) rotateY(0deg)}
.voice-figure.mic-off .vo-mesh i{border-color:rgba(215,191,245,.5);box-shadow:none}
.voice-figure.mic-off .vo-core i:nth-child(1){background:radial-gradient(circle at 40% 36%,#fbf8ff,#e5d6f8 45%,#bf9ee8 78%);box-shadow:none;animation:none}
.voice-figure.mic-off .vo-core i:nth-child(2),.voice-figure.mic-off .vo-core i:nth-child(3){opacity:0;animation:none}
.voice-figure.mic-off:focus-visible::after{box-shadow:none}

.voice-alert{margin:0;font-size:12px;letter-spacing:1px;color:rgba(252,165,165,.85)}

/* ---- 响应式 ---- */
@media(max-width:1500px){
  .jarvis-stage{padding:100px 340px 132px}
}
@media(max-width:1180px){
  .jarvis-stage{padding:96px 320px 132px}
}
@media(max-width:980px){
  .jarvis-panel{display:none}
  .jarvis-frame{display:none}
  .jarvis-stage{padding:96px 20px 140px}
}
@media(max-width:640px){
  .jarvis-strip{padding:20px 18px;gap:10px}
  .strip-live{display:none}
  .brand-copy small{display:none}
  .jarvis-brand .brand-mark{width:38px;height:38px;flex:0 0 38px;border-radius:12px}
  .jarvis-exit{height:38px;padding:0 12px;border-radius:12px;font-size:12px}
  .jarvis-frame{display:none}
  .clock-time{font-size:clamp(44px,14vw,64px)}
  .figure-stage{width:280px;height:280px}
  .jarvis-orb{width:250px;height:250px}
  .jg{width:186px;height:186px;--jg-r:93px}
  .jarvis.is-speaking .jg{width:200px;height:200px;--jg-r:100px}
  .fig-halo.h1{width:220px;height:220px;margin:-110px 0 0 -110px}
  .fig-halo.h2{width:248px;height:248px;margin:-124px 0 0 -124px}
  .fig-halo.h3{width:268px;height:268px;margin:-134px 0 0 -134px}
  .fig-orbit.o1{width:220px;height:220px;margin:-110px 0 0 -110px}
  .fig-orbit.o2{width:268px;height:268px;margin:-134px 0 0 -134px}
  .fig-plinth{width:250px;height:50px;margin-left:-125px}
  .fig-scanline{width:250px;height:2px;margin:-1px 0 0 -125px}
  .core-beam{height:212px;margin:-106px 0 0 -1px}
  .voice-figure{width:260px;height:140px}
  .vo-sphere{width:82px;height:82px}
}

/* Realtime call: an atmospheric violet stage with readable, translucent panels. */
.jarvis{
  --cyan:#b493ff;--cyan-soft:#d4c2ff;--cyan-dim:rgba(180,147,255,.32);--violet:#a78bfa;
  color:#f5f1ff;background:#0a0920;
  background-image:
    radial-gradient(ellipse 38% 44% at 50% 46%,rgba(107,70,211,.32),transparent 80%),
    radial-gradient(ellipse 52% 62% at 51% 112%,rgba(52,64,149,.3),transparent 82%),
    radial-gradient(ellipse 33% 42% at 93% 14%,rgba(79,48,148,.2),transparent 85%),
    linear-gradient(145deg,#0a0920 0%,#151034 53%,#090b24 100%);
  font-family:var(--font-body);
}
.jarvis-bg::before{
  content:'';position:absolute;inset:3% 22%;border-radius:50%;
  background:repeating-radial-gradient(ellipse at 50% 50%,transparent 0 75px,rgba(188,159,255,.075) 76px,transparent 77px 128px);
  -webkit-mask-image:radial-gradient(ellipse,#000 14%,transparent 73%);
  mask-image:radial-gradient(ellipse,#000 14%,transparent 73%);
}
.jarvis-bg::after{
  content:'';position:absolute;left:28%;right:28%;bottom:-18%;height:48%;border-radius:50%;
  background:radial-gradient(ellipse,rgba(112,81,241,.23),transparent 69%);filter:blur(40px);
}
.jarvis-grid{
  background-image:linear-gradient(rgba(178,153,255,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(178,153,255,.055) 1px,transparent 1px);
  background-size:64px 64px;opacity:.8;
}
.glow-a{background:radial-gradient(circle,rgba(133,93,255,.25),transparent 68%)}
.glow-b{background:radial-gradient(circle,rgba(93,106,228,.19),transparent 70%)}
.jarvis-stars i{background:#ddccff;box-shadow:0 0 9px rgba(199,175,255,.85)}
.jarvis-scan{background:linear-gradient(180deg,transparent,rgba(171,143,255,.045),transparent)}
.frame-border{border-color:rgba(187,164,255,.17)}
.frame-corner{border-color:rgba(190,158,255,.66);filter:drop-shadow(0 0 8px rgba(159,117,255,.5))}
.frame-side,.fs-left,.fs-right{background:linear-gradient(90deg,transparent,rgba(170,139,255,.4),transparent)}
.jarvis-brand .brand-mark,.panel-icon{
  color:#d8c7ff;background:rgba(149,110,255,.15);border-color:rgba(202,182,255,.31);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.12),0 0 18px rgba(132,86,237,.15);
}
.brand-copy strong,.panel-title{color:#f8f5ff;text-shadow:0 0 20px rgba(191,164,255,.2)}
.brand-copy small,.panel-count,.panel-live{color:#b9aed6}
.jarvis-exit{
  color:#eee4ff;background:rgba(40,30,82,.44);border-color:rgba(204,181,255,.34);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.1),0 8px 22px rgba(4,3,18,.16);
  -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
}
.jarvis-exit:hover{color:#fff;background:rgba(99,68,164,.4);border-color:rgba(213,193,255,.65);box-shadow:0 0 24px rgba(148,105,255,.2)}
.strip-live{border-color:rgba(204,181,255,.5)}
.jarvis-panel{
  border:1px solid rgba(214,196,255,.27);
  background:
    linear-gradient(145deg,rgba(127,95,212,.14),transparent 34%),
    linear-gradient(165deg,rgba(29,24,66,.64),rgba(13,14,40,.55) 72%,rgba(40,30,83,.5));
  background-clip:padding-box;background-origin:padding-box;
  -webkit-backdrop-filter:blur(24px) saturate(155%);backdrop-filter:blur(24px) saturate(155%);
  box-shadow:0 26px 60px rgba(3,3,19,.33),0 0 32px rgba(132,94,238,.12),inset 0 1px 0 rgba(255,255,255,.14),inset 0 0 38px rgba(150,117,255,.045);
}
.panel-head::after{background:linear-gradient(90deg,rgba(213,191,255,.42),rgba(177,143,255,.15) 65%,transparent)}
.panel-count::after,.panel-live i{background:#c9aaff;box-shadow:0 0 12px rgba(194,156,255,.7)}
.panel-body:focus-visible{outline-color:#b8a0ff}
.panel-scrollbar::before{background:rgba(203,181,255,.12)}
.panel-scroll-thumb,.panel-scrollbar:hover .panel-scroll-thumb{background:rgba(206,183,255,.7);box-shadow:0 0 10px rgba(169,128,255,.3)}
.panel-resizer:hover,.panel-resizer:active{background:rgba(172,131,255,.12)}
.subtitle-empty,.agent-empty,.sub-meta i,.agent-step>i{color:#b4a9d0}
.sub-role-icon,.subtitle-item.human .sub-role-icon{
  color:#d9c7ff;background:rgba(133,93,224,.2);border-color:rgba(200,172,255,.3);box-shadow:inset 0 1px 0 rgba(255,255,255,.08);
}
.sub-meta b{color:#d3baff;text-shadow:none}
.subtitle-item.system .sub-meta b{color:#b4a9d0}
.subtitle-item p{color:#f5f0ff;background:rgba(224,211,255,.09);border-color:rgba(220,204,255,.16)}
.subtitle-item.human p{color:#fff;background:rgba(120,76,225,.48);border-color:rgba(202,176,255,.38)}
.subtitle-item.system p{color:#b4a9d0}
.subtitle-item.is-live p{color:#e7ddff}
.subtitle-item.is-live .sub-role-icon::after{background:#c7a5ff;box-shadow:0 0 8px #ad80ff}
.agent-step{background:rgba(198,176,255,.065);border-color:rgba(206,185,255,.13)}
.agent-step.active{background:rgba(142,102,241,.2);border-color:rgba(203,178,255,.42)}
.agent-step-dot{background:#b99ae9}
.agent-step b{color:#f3ecff}
.agent-step p{color:#c1b7d6}
.clock-week,.clock-date,.clock-demo,.clock-wake{color:#d7c4ff;text-shadow:0 0 16px rgba(169,127,255,.25)}
.clock-time{color:#fff;text-shadow:0 0 35px rgba(178,143,255,.35);font-family:var(--font-display)}
.voice-status{color:#ddd1f6;text-shadow:0 1px 12px rgba(29,12,72,.8)}
.vo-halo,.voice-figure.mic-on .vo-halo,.voice-figure.mic-on.active .vo-halo{background:radial-gradient(circle,rgba(158,113,255,.35),rgba(124,74,230,.11) 50%,transparent 72%)}
.vo-mesh i,.voice-figure.active .vo-mesh i{border-color:rgba(193,156,255,.66);box-shadow:0 0 9px rgba(163,113,255,.28)}
.vo-spark i{border-color:rgba(193,156,255,.7)}
.vo-core i:nth-child(1){background:radial-gradient(circle at 38% 34%,#fff,#d7c4ff 39%,#8053ed 76%);box-shadow:0 0 22px rgba(181,136,255,.7),0 0 52px rgba(128,76,248,.38)}
.vo-core i:nth-child(2),.vo-core i:nth-child(3){border-color:rgba(192,154,255,.6)}
.vo-particles i{background:#d5bbff;box-shadow:0 0 8px #c69fff,0 0 18px rgba(165,111,255,.48)}
.voice-figure.mic-off .vo-mesh i{border-color:rgba(184,164,223,.4)}
.voice-figure.mic-off .vo-core i:nth-child(1){background:radial-gradient(circle at 40% 36%,#fff,#d8c5ff 45%,#8a66da 78%)}
.jarvis :deep(.particle-fallback){color:#e7d9ff;border-color:rgba(194,156,255,.6);background:radial-gradient(circle,rgba(134,79,239,.26),transparent 72%)}
</style>
