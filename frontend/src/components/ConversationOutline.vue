<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { MessageSquareText } from 'lucide-vue-next'
import { conversationQuestions, questionAtScrollPosition } from '@/lib/conversationOutline'

const props = defineProps({ messages: { type: Array, default: () => [] }, container: { default: null } })
const emit = defineEmits(['navigate'])
const questions = computed(() => conversationQuestions(props.messages))
const activeId = ref(null)
const expanded = ref(false)
const preview = ref(null)
const previewElement = ref(null)
const position = ref({ left: '0px', top: '0px', '--preview-arrow-top': '24px' })
const previewReady = ref(false)
const previewPlacement = ref('left')
const list = ref(null)
const outline = ref(null)
let container = null
let observer = null
let frame = null
let hideTimer = null
let collapseTimer = null
let previewTarget = null
let disposed = false

function update() {
  frame = null
  if (!container || disposed) return
  const positions = questions.value.map(question => {
    const element = document.getElementById(`chat-message-${question.id}`)
    return element ? { id: question.id, top: element.getBoundingClientRect().top } : null
  }).filter(Boolean)
  activeId.value = questionAtScrollPosition(positions, container.getBoundingClientRect().top + 24)
}
function scheduleUpdate() {
  if (frame === null) frame = requestAnimationFrame(update)
}
function closePreview() {
  clearTimeout(hideTimer)
  preview.value = null
  previewTarget = null
  previewReady.value = false
}
function scheduleHide() { clearTimeout(hideTimer); hideTimer = setTimeout(closePreview, 140) }
function expand() { clearTimeout(collapseTimer); expanded.value = true }
function collapse() { expanded.value = false; closePreview() }
function scheduleCollapse() { clearTimeout(collapseTimer); collapseTimer = setTimeout(collapse, 160) }
function keepPreview() { clearTimeout(hideTimer); clearTimeout(collapseTimer) }
function leaveFocus(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) scheduleCollapse()
}
async function showPreview(question, index, target) {
  if (question.id === activeId.value) { closePreview(); return }
  clearTimeout(hideTimer)
  previewTarget = target
  preview.value = { ...question, index }
  previewReady.value = false
  await nextTick()
  positionPreview(target)
}
function positionPreview(target) {
  if (disposed || previewTarget !== target || !previewElement.value) return
  const bubble = previewElement.value.getBoundingClientRect()
  const bounds = target.getBoundingClientRect()
  const fitsLeft = bounds.left - bubble.width - 14 >= 12
  previewPlacement.value = fitsLeft ? 'left' : bounds.top - bubble.height - 12 >= 12 ? 'top' : 'bottom'
  const preferredLeft = fitsLeft ? bounds.left - bubble.width - 14 : bounds.left + bounds.width / 2 - bubble.width / 2
  const left = Math.max(12, Math.min(preferredLeft, window.innerWidth - bubble.width - 12))
  const preferredTop = fitsLeft ? bounds.top + bounds.height / 2 - bubble.height / 2
    : previewPlacement.value === 'top' ? bounds.top - bubble.height - 12 : bounds.bottom + 12
  const top = Math.max(12, Math.min(preferredTop, window.innerHeight - bubble.height - 12))
  const arrowTop = Math.max(18, Math.min(bounds.top + bounds.height / 2 - top, bubble.height - 18))
  const arrowLeft = Math.max(18, Math.min(bounds.left + bounds.width / 2 - left, bubble.width - 18))
  position.value = { left: `${left}px`, top: `${top}px`, '--preview-arrow-top': `${arrowTop}px`, '--preview-arrow-left': `${arrowLeft}px` }
  previewReady.value = true
}
function navigate(question) { activeId.value = question.id; closePreview(); emit('navigate', question.id) }
function detach() {
  container?.removeEventListener('scroll', onScroll)
  observer?.disconnect()
  observer = null
}
function onScroll() { closePreview(); scheduleUpdate() }
function onResize() {
  scheduleUpdate()
  if (preview.value && previewTarget) nextTick(() => { if (previewTarget) positionPreview(previewTarget) })
}
watch(() => props.container, value => {
  detach()
  container = value
  if (!container) return
  container.addEventListener('scroll', onScroll, { passive: true })
  observer = new ResizeObserver(onResize)
  observer.observe(container)
  if (outline.value) observer.observe(outline.value)
  if (container.parentElement) observer.observe(container.parentElement)
  const content = container.querySelector('.assistant-messages')
  if (content) observer.observe(content)
  scheduleUpdate()
}, { immediate: true, flush: 'post' })
watch(questions, async () => { closePreview(); await nextTick(); scheduleUpdate() }, { flush: 'post' })
watch(activeId, async id => {
  if (preview.value?.id === id) closePreview()
  await nextTick()
  const button = list.value?.querySelector('[aria-current="location"]')
  if (!id || !button || !list.value) return
  const bounds = list.value.getBoundingClientRect()
  const item = button.getBoundingClientRect()
  if (item.top < bounds.top) list.value.scrollTop += item.top - bounds.top
  else if (item.bottom > bounds.bottom) list.value.scrollTop += item.bottom - bounds.bottom
})
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => {
  disposed = true
  detach()
  clearTimeout(hideTimer)
  clearTimeout(collapseTimer)
  if (frame !== null) cancelAnimationFrame(frame)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <nav v-if="questions.length" ref="outline" class="conversation-outline" :class="{ expanded }" :style="{ '--outline-natural-height': `${questions.length * 36 + 18}px` }" aria-label="对话目录"
    @mouseenter="expand" @mouseleave="scheduleCollapse" @focusin="expand" @focusout="leaveFocus" @keydown.esc="collapse">
    <div ref="list" class="outline-questions">
      <div v-for="(question, index) in questions" :key="question.id" class="outline-question-row">
      <button type="button"
        :class="{ active: activeId === question.id }" :aria-current="activeId === question.id ? 'location' : undefined"
        :aria-label="`第 ${index + 1} 次提问：${question.summary}`" :aria-describedby="preview?.id === question.id ? 'outline-question-preview' : undefined"
        @mouseenter="showPreview(question, index, $event.currentTarget)" @mouseleave="scheduleHide"
        @focus="showPreview(question, index, $event.currentTarget)" @blur="scheduleHide" @click="navigate(question)">
        <span class="outline-question-text">{{ question.summary }}</span><i aria-hidden="true" />
      </button>
      </div>
    </div>
    <Teleport to="body">
      <div v-if="preview" id="outline-question-preview" ref="previewElement" class="outline-question-preview"
        :class="[previewPlacement, { ready: previewReady }]" :style="position" role="tooltip" @mouseenter="keepPreview" @mouseleave="scheduleHide(); scheduleCollapse()">
        <header><MessageSquareText :size="15" /><span>第 {{ preview.index + 1 }} 次提问</span></header>
        <p>{{ preview.text }}</p>
      </div>
    </Teleport>
  </nav>
</template>

<style scoped>
/* Fit the question count, cap at one third of the page, and stay centered. */
.conversation-outline{position:absolute;right:10px;top:50%;transform:translateY(-50%);z-index:18;box-sizing:border-box;width:28px;height:min(var(--outline-natural-height),33.333333%);padding:8px 0;border:1px solid transparent;border-radius:18px;background:transparent;transition:width .16s ease,background .16s ease,border-color .16s ease,box-shadow .16s ease}
.conversation-outline.expanded{width:min(240px,calc(100% - 24px));padding-right:8px;padding-left:8px;border-color:#ece5f3;background:rgba(255,255,255,.97);box-shadow:0 10px 32px #4d287c12;backdrop-filter:blur(12px)}
.outline-questions{display:flex;flex-direction:column;height:100%;min-height:0;overflow-y:auto;overflow-x:hidden;scrollbar-width:none;overscroll-behavior:contain}.expanded .outline-questions{scrollbar-width:thin;scrollbar-color:#e2d5f1 transparent}
.outline-question-row{display:flex;align-items:center;flex:1 0 32px;min-height:32px}
.outline-questions button{display:flex;align-items:center;justify-content:center;gap:12px;width:100%;height:30px;min-height:30px;padding:0 4px;border:0;border-radius:9px;background:transparent;color:#9a91a4;font:inherit;font-size:12px;line-height:1.5;text-align:left;cursor:pointer}.expanded .outline-questions button{justify-content:flex-start;padding:0 10px}
.outline-question-text{display:none;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.expanded .outline-question-text{display:block}
.outline-questions i{width:8px;height:3px;flex:0 0 8px;border-radius:999px;background:#d9d0e1;transition:width .15s,background .15s}.outline-questions button:not(.active):hover{color:#49305d;background:#f8f4ff}.outline-questions button.active{color:#7c3aed}.outline-questions button.active i{width:14px;flex-basis:14px;background:#8b5cf6}.outline-questions button:focus-visible{outline:2px solid #b69ae8;outline-offset:-2px}
.outline-question-preview{position:fixed;z-index:3100;box-sizing:border-box;width:min(330px,calc(100vw - 24px));padding:14px 16px;border:1px solid #dfcff4;border-radius:15px;background:#fff;color:#49305d;box-shadow:0 14px 42px #4c277c22;opacity:0;transition:opacity .12s}.outline-question-preview.ready{opacity:1}.outline-question-preview::after{content:"";position:absolute;right:-5px;top:var(--preview-arrow-top);width:8px;height:8px;border-right:1px solid #dfcff4;border-top:1px solid #dfcff4;background:#fff;transform:translateY(-50%) rotate(45deg)}.outline-question-preview header{display:flex;align-items:center;gap:7px;color:#956dbb;font-size:11px;font-weight:600}.outline-question-preview p{max-height:min(240px,45vh);overflow:auto;margin:9px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.75;scrollbar-width:thin;scrollbar-color:#dfcff4 transparent}
.outline-question-preview.top::after{right:auto;left:var(--preview-arrow-left);top:auto;bottom:-5px;border-top:0;border-bottom:1px solid #dfcff4;transform:translateX(-50%) rotate(45deg)}.outline-question-preview.bottom::after{right:auto;left:var(--preview-arrow-left);top:-5px;border-right:0;border-left:1px solid #dfcff4;transform:translateX(-50%) rotate(45deg)}
@media(prefers-reduced-motion:reduce){.conversation-outline,.outline-question-preview,.outline-questions i{transition:none}}
</style>
