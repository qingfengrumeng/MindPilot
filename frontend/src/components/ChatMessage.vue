<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  Check,
  Copy,
  FileText,
  Image as ImageIcon,
  Pause,
  Play,
  RotateCcw,
  Sparkles,
  User,
  Volume2,
  Wand2
} from 'lucide-vue-next'
import { findSkill } from '@/skills'
import { chatApi, speechApi } from '@/api'
import { backendEnabled } from '@/api/http'
import { useUiStore } from '@/stores/ui'
import { createMp3Output } from '@/lib/streamMp3'
import CodeBlock from '@/components/CodeBlock.vue'
import DiagramCard from '@/components/DiagramCard.vue'
import PosterCard from '@/components/PosterCard.vue'

const props = defineProps({ message: Object })
const hasDiagram = computed(() => Boolean(props.message.diagram || props.message.metadata?.diagram))
const hasPoster = computed(() => Boolean(props.message.poster || props.message.metadata?.poster))
const ui = useUiStore()
const emit = defineEmits(['resend', 'open-attachment'])
const copied = ref(false)
const hoveredWebSource = ref(null)
const webTooltipPosition = ref({ left: 0, top: 0, width: 340 })
const feedback = ref({ key: '', text: '' })
const playing = ref(false)
const reading = ref(false)
const readingPaused = ref(false)
const transcriptVisible = ref(false)
const transcribing = ref(false)
const loadedPreviewUrls = ref({})
const ownedPreviewUrls = new Set()
const pendingPreviewIds = new Set()
let previewMounted = true

watch(() => props.message.attachments, async attachments => {
  if (!backendEnabled) return
  for (const file of attachments || []) {
    if (file.type !== 'image' || !file.previewId || file.previewUrl ||
        loadedPreviewUrls.value[file.previewId] || pendingPreviewIds.has(file.previewId)) continue
    pendingPreviewIds.add(file.previewId)
    try {
      const blob = await chatApi.previewImage(file.previewId)
      const url = URL.createObjectURL(blob)
      if (previewMounted) {
        ownedPreviewUrls.add(url)
        loadedPreviewUrls.value = { ...loadedPreviewUrls.value, [file.previewId]: url }
      } else URL.revokeObjectURL(url)
    } catch {
      // The attachment card remains visible if its local preview is unavailable.
    } finally {
      pendingPreviewIds.delete(file.previewId)
    }
  }
}, { immediate: true })

function filePreviewUrl(file) { return file.previewUrl || loadedPreviewUrls.value[file.previewId] }
function openAttachment(file) { emit('open-attachment', { ...file, previewUrl: filePreviewUrl(file) }) }
let playTimer = null
let transcriptTimer = null
let feedbackTimer = null
let copyTimer = null
let speechAudio = null
let speechAbort = null
let speechOutput = null
// 语音条播放与 AI 朗读必须分开；消息流更新会替换用户消息组件，不能影响语音条。
let voiceAudio = null
const readerToken = Symbol('message-reader')

function stopReading() {
  speechAbort?.abort()
  speechOutput?.cleanup()
  speechAudio = null
  speechAbort = null
  speechOutput = null
  reading.value = false
  readingPaused.value = false
}

function handleOtherMessageReading(event) {
  if (event.detail !== readerToken) stopReading()
}

window.addEventListener('mindpilot:message-reading', handleOtherMessageReading)

async function toggleReading() {
  if (!backendEnabled) {
    ui.toast('语音朗读需要启动本地后端', 'warning')
    return
  }

  if (reading.value) {
    speechAudio?.pause()
    reading.value = false
    readingPaused.value = true
    return
  }
  if (readingPaused.value && speechAudio) {
    reading.value = true
    readingPaused.value = false
    speechAudio.play().catch(() => {
      ui.toast('音频播放失败，请检查浏览器音频设置', 'error')
      stopReading()
    })
    return
  }

  const content = (props.message.content || '')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_#>]/g, '')
    .trim()
  if (!content) return

  window.dispatchEvent(new CustomEvent('mindpilot:message-reading', { detail: readerToken }))
  stopReading()
  const controller = new AbortController()
  const audio = new Audio()
  const output = createMp3Output(audio, controller.signal)
  speechAbort = controller
  speechAudio = audio
  speechOutput = output
  reading.value = true
  audio.onended = () => { if (speechAudio === audio) stopReading() }
  if (output.streaming) audio.play().catch(() => {})
  try {
    const response = await speechApi.synthesize(content, controller.signal)
    if (!controller.signal.aborted) await output.consume(response, () => {
      if (reading.value && audio.paused) audio.play().catch(() => {})
    })
  } catch (error) {
    if (!controller.signal.aborted) {
      ui.toast(/[\u4e00-\u9fff]/.test(error?.message || '') ? error.message : '语音合成失败，请检查TTS配置', 'error')
      stopReading()
    }
  }
}

function showFeedback(key, text) {
  clearTimeout(feedbackTimer)
  feedback.value = { key, text }
  feedbackTimer = setTimeout(() => { feedback.value = { key: '', text: '' } }, 2400)
}

const citationEntries = computed(() => (props.message.citations || props.message.metadata?.citations || [])
  .map((citation, index) => typeof citation === 'object' && citation?.documentId
    ? { ...citation, evidenceNumber: Number(citation.evidenceNumber || index + 1), page: Number(citation.page) > 0 ? Number(citation.page) : null }
    : null)
  .filter(Boolean))

function safeHttpUrl(value) {
  try {
    const parsed = new URL(String(value || ''))
    return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : ''
  } catch { return '' }
}

const webSourceEntries = computed(() => (props.message.webSources?.length
  ? props.message.webSources : props.message.metadata?.webSources || [])
  .map(source => {
    const number = Number(source?.sourceNumber)
    const url = safeHttpUrl(source?.url)
    if (!Number.isInteger(number) || number < 1 || !url) return null
    return { sourceNumber: number, title: String(source.title || new URL(url).hostname),
      url, date: String(source.date || ''), icon: safeHttpUrl(source.icon) }
  }).filter(Boolean))

function webCitationPattern() { return /[〔【\[]\s*网页\s*(\d+)\s*[〕】\]]/g }
function escapeHtml(value) {
  return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}
function formattedSourceDate(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}))?/)
  return match ? `${match[1]}年${match[2]}月${match[3]}日${match[4] ? `${match[4]}时` : ''}` : String(value || '')
}
function showWebSource(event) {
  const link = event.target.closest?.('a[data-web-source]')
  if (!link || !event.currentTarget.contains(link)) return
  const source = webSourceEntries.value.find(item => item.sourceNumber === Number(link.dataset.webSource))
  if (!source) return
  const rect = link.getBoundingClientRect()
  const width = Math.min(360, window.innerWidth - 24)
  webTooltipPosition.value = {
    width, left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
    top: rect.bottom + 170 > window.innerHeight ? Math.max(8, rect.top - 160) : rect.bottom + 8
  }
  hoveredWebSource.value = source
}
function hideWebSource(event) {
  const link = event.target.closest?.('a[data-web-source]')
  if (!link || !link.contains(event.relatedTarget)) hoveredWebSource.value = null
}
function fallbackWebIcon(event) {
  if (event.target.matches?.('.web-source-icon img')) {
    event.target.replaceWith(document.createTextNode('↗'))
  }
}

function citationPattern() {
  return /[（(]?\s*资料\[(\d+)\]\s*[,，]\s*页码\s*\d+\s*[）)]?|[〔【\[]\s*证据\s*(\d+)\s*[〕】\]]|[（(]?\s*文档\s*(\d+)\s*[,，、·]\s*第?(\d+)页\s*[）)]?/g
}

function matchingCitation(match) {
  return match[3]
    ? citationEntries.value.find(item => item.documentNumber === Number(match[3]) && item.page === Number(match[4]))
    : citationEntries.value.find(item => item.evidenceNumber === Number(match[1] || match[2]))
}

const referencedCitations = computed(() => {
  const content = props.message.content || ''
  const result = []
  for (const match of content.matchAll(citationPattern())) {
    const citation = matchingCitation(match)
    if (citation) result.push(citation)
  }
  return result
})

const documentLegend = computed(() => {
  const seen = new Set()
  return referencedCitations.value.filter(item => {
    if (seen.has(item.documentId)) return false
    seen.add(item.documentId)
    return true
  }).map(item => {
    const origins = new Set(referencedCitations.value.filter(citation => citation.documentId === item.documentId)
      .flatMap(citation => citation.retrievalOrigins || []))
    return { documentId: item.documentId, filename: item.filename || item.title || '文件名未提供',
      originLabel: origins.has('graph') ? ['raw','wiki','graph'].filter(key=>origins.has(key)).map(key=>({raw:'RAG',wiki:'Wiki',graph:'GraphRAG'}[key])).join(' + ') : origins.has('wiki') ? origins.has('raw') ? 'Wiki + RAG' : 'Wiki → 原文' : '' }
  })
})
const attachmentOnly = computed(() => props.message.role === 'user' &&
  !String(props.message.content || '').trim() && Boolean(props.message.attachments?.length))

function inlineFormat(value) {
  const escaped = escapeHtml(value)
  const styled = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/`(.*?)`/g, '<code>$1</code>')
  return styled.replace(webCitationPattern(), (_match, number) => {
    const source = webSourceEntries.value.find(item => item.sourceNumber === Number(number))
    if (!source) return _match
    const icon = source.icon ? `<img src="${escapeHtml(source.icon)}" alt="" loading="lazy">` : '↗'
    return `<a class="web-source-link" data-web-source="${source.sourceNumber}" href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer"><span class="web-source-icon">${icon}</span><span class="web-source-label">${escapeHtml(source.title)}</span></a>`
  }).replace(citationPattern(), '')
}

function formatText(content) {
  if (!content) return ''
  const lines = content.split('\n')
  const output = []
  let listType = ''
  const closeList = () => {
    if (listType) output.push(`</${listType}>`)
    listType = ''
  }
  lines.forEach((line, index) => {
    const value = line.trim()
    if (!value) {
      const next = lines.slice(index + 1).find(item => item.trim())?.trim() || ''
      const nextType = /^\d+[.、．)]\s+/.test(next) ? 'ol' : /^[-*]\s+/.test(next) ? 'ul' : ''
      if (nextType !== listType) closeList()
      return
    }
    const ordered = value.match(/^\d+[.、．)]\s+(.*)$/)
    const unordered = value.match(/^[-*]\s+(.*)$/)
    if (ordered || unordered) {
      const nextType = ordered ? 'ol' : 'ul'
      if (listType !== nextType) {
        closeList()
        listType = nextType
        output.push(`<${nextType}>`)
      }
      output.push(`<li>${inlineFormat((ordered || unordered)[1])}</li>`)
      return
    }
    closeList()
    if (value.startsWith('### ')) output.push(`<h3>${inlineFormat(value.slice(4))}</h3>`)
    else if (value.startsWith('## ')) output.push(`<h2>${inlineFormat(value.slice(3))}</h2>`)
    else if (value.startsWith('> ')) output.push(`<blockquote>${inlineFormat(value.slice(2))}</blockquote>`)
    else output.push(`<p>${inlineFormat(value)}</p>`)
  })
  closeList()
  return output.join('')
}

const contentSegments = computed(() => {
  const content = props.message.content || ''
  if (props.message.role !== 'assistant') return [{ type: 'text', html: formatText(content) }]
  const segments = []
  const textLines = []
  const codeLines = []
  let language = ''
  let inCode = false

  const flushText = () => {
    if (textLines.length) segments.push({ type: 'text', html: formatText(textLines.join('\n')) })
    textLines.length = 0
  }
  const flushCode = () => {
    segments.push({ type: 'code', code: codeLines.join('\n'), language })
    codeLines.length = 0
  }

  for (const line of content.split(/\r?\n/)) {
    if (!inCode) {
      const opening = line.match(/^ {0,3}```\s*([^`\s]*)[^`]*$/)
      if (opening) {
        flushText()
        language = opening[1] || ''
        inCode = true
      } else textLines.push(line)
    } else if (/^ {0,3}```\s*$/.test(line)) {
      flushCode()
      inCode = false
      language = ''
    } else codeLines.push(line)
  }
  if (inCode) flushCode()
  flushText()
  return segments
})

const voiceWidth = computed(() => `${Math.min(360, 118 + (props.message.duration || 1) * 8)}px`)
const voiceWave = computed(() => props.message.wave || Array.from({ length: 18 }, (_, index) => 30 + (index * 19) % 55))
/** 消息上挂着能力时，标识取注册表里的图标；能力下线的历史消息退回通用图标。 */
const skillIcon = computed(() => findSkill(props.message.skill?.id)?.icon || Wand2)

function formatDuration(value) {
  return `00:${String(value || 0).padStart(2, '0')}`
}

function toggleVoicePlay() {
  if (!props.message.audioUrl) {
    playing.value = !playing.value
    clearTimeout(playTimer)
    if (playing.value) playTimer = setTimeout(() => { playing.value = false }, Math.max(1, props.message.duration) * 1000)
    return
  }
  if (playing.value) {
    voiceAudio?.pause()
    playing.value = false
    return
  }
  const audio = new Audio(props.message.audioUrl)
  voiceAudio = audio
  playing.value = true
  audio.onended = () => { playing.value = false; if (voiceAudio === audio) voiceAudio = null }
  audio.onerror = () => { playing.value = false; if (voiceAudio === audio) voiceAudio = null; ui.toast('语音播放失败', 'error') }
  audio.play().catch(() => { playing.value = false; if (voiceAudio === audio) voiceAudio = null })
}

function toggleTranscript() {
  if (transcriptVisible.value) {
    transcriptVisible.value = false
    return
  }
  transcribing.value = true
  clearTimeout(transcriptTimer)
  transcriptTimer = setTimeout(() => {
    transcribing.value = false
    transcriptVisible.value = true
  }, 520)
}

async function copy() {
  await navigator.clipboard?.writeText(props.message.content || '')
  copied.value = true
  showFeedback('copy', '消息已复制')
  clearTimeout(copyTimer)
  copyTimer = setTimeout(() => { copied.value = false }, 1500)
}

onBeforeUnmount(() => {
  hoveredWebSource.value = null
  previewMounted = false
  for (const url of ownedPreviewUrls) URL.revokeObjectURL(url)
  stopReading()
  window.removeEventListener('mindpilot:message-reading', handleOtherMessageReading)
  clearTimeout(playTimer)
  clearTimeout(transcriptTimer)
  clearTimeout(feedbackTimer)
  clearTimeout(copyTimer)
})
</script>

<template>
  <article :id="`chat-message-${message.id}`" class="chat-message" :class="[message.role, { 'attachment-only': attachmentOnly, 'diagram-message': hasDiagram || hasPoster }]">
    <div v-if="message.role === 'assistant'" class="message-avatar"><Sparkles :size="18" /></div>
    <div v-else class="message-avatar user-message-avatar"><User :size="18" /></div>
    <div class="message-body">
      <div v-if="message.role === 'assistant'" class="message-role">
        <strong>MindPilot</strong>
      </div>

      <!-- 这条提问用的哪条能力、它的专用系统提示词已注入本次上下文 -->
      <div
        v-if="message.skill"
        class="message-skill-badge"
        :title="`本条提问套用了「${message.skill.label}」的专用系统提示词`"
      >
        <component :is="skillIcon" :size="13" />
        <span>{{ message.skill.label }}</span>
      </div>

      <div v-if="message.type === 'voice'" class="voice-message-block">
        <div class="voice-message-row">
          <span class="voice-transcribe-trigger" aria-hidden="true" />
          <button
            type="button"
            class="voice-transcribe-button"
            :class="{ active: transcriptVisible, loading: transcribing }"
            :title="transcriptVisible ? '收起识别文字' : '语音转文字'"
            :aria-label="transcriptVisible ? '收起识别文字' : '语音转文字'"
            @click="toggleTranscript"
          >
            <FileText :size="17" />
          </button>
          <button
            type="button"
            class="voice-message"
            :class="{ playing }"
            :style="{ width: voiceWidth }"
            :title="playing ? '暂停播放' : '播放语音'"
            @click="toggleVoicePlay"
          >
            <span class="voice-duration">{{ formatDuration(message.duration) }}</span>
            <span class="voice-play"><Pause v-if="playing" :size="15" /><Play v-else :size="15" /></span>
            <span class="voice-wave">
              <i
                v-for="(height, index) in voiceWave"
                :key="index"
                :style="{ height: `${height}%`, animationDelay: `${index * 45}ms` }"
              />
            </span>
          </button>
        </div>
        <Transition name="voice-transcript">
          <div v-if="transcribing || transcriptVisible" class="voice-message-text">
            <span v-if="transcribing" class="voice-transcribing"><i /><i /><i />正在识别语音</span>
            <p v-else>{{ message.transcript || message.content || '未识别到语音内容' }}</p>
          </div>
        </Transition>
      </div>
      <div v-else-if="hasDiagram" class="diagram-answer">
        <div class="diagram-answer-intro">{{ message.content }}</div>
        <div class="diagram-answer-card"><DiagramCard :message="message" embedded /></div>
      </div>
      <div v-else-if="hasPoster" class="diagram-answer poster-answer">
        <div class="diagram-answer-intro">{{ message.content }}</div>
        <div class="poster-answer-card"><PosterCard :message="message" /></div>
      </div>
      <div v-else-if="message.content || documentLegend.length" class="message-bubble">
        <div class="message-prose" @mouseover="showWebSource" @focusin="showWebSource"
          @mouseout="hideWebSource" @focusout="hideWebSource" @mouseleave="hoveredWebSource = null"
          @error.capture="fallbackWebIcon">
          <template v-for="(segment, index) in contentSegments" :key="index">
            <div v-if="segment.type === 'text'" class="message-prose-text" v-html="segment.html" />
            <CodeBlock v-else :code="segment.code" :language="segment.language" />
          </template>
        </div>
        <div v-if="documentLegend.length" class="message-reference-list">
          <strong>引用：</strong>
          <div class="message-reference-files">
            <span v-for="document in documentLegend" :key="document.documentId" class="message-reference-item">
              <FileText :size="16" aria-hidden="true" />
              <span>{{ document.filename }}</span>
              <small v-if="document.originLabel" class="message-retrieval-origin">{{ document.originLabel }}</small>
            </span>
          </div>
        </div>
      </div>

      <div v-if="message.attachments?.length" class="message-files" :class="{ 'standalone-attachments': attachmentOnly }">
        <button v-for="file in message.attachments" :key="file.name" type="button"
          :class="{ 'standalone-image': attachmentOnly && file.type === 'image', 'standalone-document': attachmentOnly && file.type !== 'image' }"
          :disabled="!file.content && !filePreviewUrl(file)" @click="openAttachment(file)">
          <template v-if="attachmentOnly && file.type === 'image'">
            <img v-if="filePreviewUrl(file)" :src="filePreviewUrl(file)" :alt="file.name" class="message-file-image" />
            <ImageIcon v-else :size="26" />
          </template>
          <template v-else-if="attachmentOnly">
            <span class="standalone-document-icon"><FileText :size="22" /></span>
            <span class="standalone-document-details"><strong>{{ file.name }}</strong><small>文档</small></span>
          </template>
          <template v-else>
            <img v-if="file.type === 'image' && filePreviewUrl(file)" :src="filePreviewUrl(file)" :alt="file.name" class="message-file-image" />
            <ImageIcon v-else-if="file.type === 'image'" :size="16" />
            <FileText v-else :size="15" />
            <span>{{ file.name }}</span>
          </template>
        </button>
      </div>
      <div v-if="message.sources?.length && !documentLegend.length" class="message-sources">
        <small>引用资料</small>
        <span v-for="source in message.sources" :key="source" class="message-source-action">
          <button :data-tooltip-suppressed="feedback.key === `source-${source}` ? 'true' : undefined"
            @click="showFeedback(`source-${source}`, `正在预览：${source}`)">
            <FileText :size="13" />{{ source }}
          </button>
          <span v-if="feedback.key === `source-${source}`" class="message-action-feedback" role="status">{{ feedback.text }}</span>
        </span>
      </div>

      <div v-if="message.outputPaused || message.outputStopped" class="message-output-paused" role="status">已暂停输出</div>

      <div v-if="!message.outputStopped && (message.role === 'assistant' || (message.type !== 'voice' && message.content))" class="message-actions">
        <span v-if="message.type !== 'voice' && message.content" class="message-action-item">
          <button :title="copied ? '已复制' : '复制'"
            :data-tooltip-suppressed="feedback.key === 'copy' ? 'true' : undefined" @click="copy">
            <component :is="copied ? Check : Copy" :size="15" />
          </button>
          <span v-if="feedback.key === 'copy'" class="message-action-feedback" role="status">{{ feedback.text }}</span>
        </span>
        <template v-if="message.role === 'assistant'">
          <button v-if="!message.diagram && !message.metadata?.diagram" type="button" aria-label="重新生成" @click="emit('resend')"><RotateCcw :size="15" /></button>
          <button type="button" :title="reading ? '暂停朗读' : readingPaused ? '继续朗读' : '朗读消息'"
            :aria-label="reading ? '暂停朗读' : readingPaused ? '继续朗读' : '朗读消息'"
            :aria-pressed="reading" :class="{ 'reading-active': reading }" @click="toggleReading">
            <Pause v-if="reading" :size="15" /><Volume2 v-else :size="15" />
          </button>
        </template>
        <template v-else>
        </template>
      </div>
    </div>
    <Teleport to="body">
      <div v-if="hoveredWebSource" class="web-source-tooltip"
        :style="{ left: `${webTooltipPosition.left}px`, top: `${webTooltipPosition.top}px`, width: `${webTooltipPosition.width}px` }"
        role="tooltip">
        <div class="web-source-tooltip-heading">
          <img v-if="hoveredWebSource.icon" :src="hoveredWebSource.icon" alt="" @error="hoveredWebSource.icon = ''" />
          <span v-else class="web-source-tooltip-fallback">↗</span>
          <strong>{{ hoveredWebSource.title }}</strong>
        </div>
        <div v-if="hoveredWebSource.date" class="web-source-tooltip-date">{{ formattedSourceDate(hoveredWebSource.date) }}</div>
        <div class="web-source-tooltip-url">{{ hoveredWebSource.url }}</div>
      </div>
    </Teleport>
  </article>
</template>

<style>
.message-retrieval-origin{flex:none;padding:2px 6px;border-radius:6px;background:#f7f2fc;color:#613792;font-size:11px;line-height:1.5;font-weight:600}
.message-output-paused{margin-top:12px;color:#9684a8;font-size:13px;line-height:1.7}
.review-assistant-page .chat-message.assistant.diagram-message{width:100%;max-width:100%}
.chat-message.diagram-message .message-body{flex:1;min-width:0}
.diagram-answer{box-sizing:border-box;width:100%;overflow:hidden;border:1px solid #c6ace6;border-radius:22px;background:#f0e8fa;box-shadow:0 12px 30px rgba(72,26,128,.08)}
.diagram-answer-intro{padding:28px 30px 18px;color:#432b61;font-size:17px;line-height:1.75;text-align:left}
.diagram-answer-card{padding:0 14px 16px}
.poster-answer-card{padding:0 20px 22px}.poster-answer-card :deep(.poster-card){margin:0 auto}
@media(max-width:650px){.diagram-answer-intro{padding:18px 18px 15px;font-size:15px}.diagram-answer-card{padding-right:8px;padding-left:8px;padding-bottom:8px}}
.chat-message .web-source-link{display:inline-flex;vertical-align:baseline;align-items:center;gap:5px;max-width:min(180px,45vw);margin:0 2px;padding:2px 7px;border:1px solid #c4ace2;border-radius:8px;background:#e5d8f4;color:#430a89;font-size:.73em;font-weight:650;line-height:1.5;text-decoration:none;white-space:nowrap;transition:background .16s,border-color .16s}
.chat-message .web-source-link:hover,.chat-message .web-source-link:focus-visible{background:#d9c5f1;border-color:#a379d7;color:#380774;outline:none}
.chat-message .web-source-icon{display:inline-grid;place-items:center;flex:none;width:15px;height:15px;font-size:13px;line-height:1}
.chat-message .web-source-icon img{display:block;width:15px;height:15px;border-radius:3px;object-fit:contain}
.chat-message .web-source-label{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis}
.web-source-tooltip{position:fixed;z-index:11000;box-sizing:border-box;max-height:min(230px,45vh);overflow:auto;pointer-events:none;padding:12px 14px;border:1px solid #ded6e8;border-radius:13px;background:#fff;color:#40295d;box-shadow:0 14px 38px rgba(49,22,81,.18);font-size:13px;line-height:1.5}
.web-source-tooltip-heading{display:grid;grid-template-columns:18px minmax(0,1fr);align-items:start;gap:7px;min-width:0}
.web-source-tooltip-heading img,.web-source-tooltip-fallback{display:grid;place-items:center;flex:none;width:18px;height:18px;border-radius:4px;object-fit:contain;color:#4b089d}
.web-source-tooltip-heading strong{min-width:0;overflow-wrap:anywhere;color:#3a2456;font-weight:700}
.web-source-tooltip-date{margin-top:6px;padding-left:25px;color:#817096;line-height:1.4}
.web-source-tooltip-url{margin-top:7px;padding-top:7px;border-top:1px solid #ede8f3;color:#6a5486;overflow-wrap:anywhere;word-break:break-word;white-space:normal}
</style>
