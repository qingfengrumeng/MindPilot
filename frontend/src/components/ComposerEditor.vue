<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({ modelValue: String, skill: Object, placeholder: String, label: String })
const emit = defineEmits(['update:modelValue', 'keydown', 'show-info', 'paste-files', 'paste-long-text'])
const element = ref()
const box = ref()
const empty = ref(true)
let composing = false

// Only this empty span is browser-editable. Vue owns the separate skill button.
function read() {
  const el = element.value
  const text = el?.innerText.replace(/\r\n/g, '\n') || ''
  return el?.lastChild?.matches?.('[data-composer-tail]') ? text.replace(/\n$/, '') : text
}
// A final text newline needs a browser caret line; exclude this BR from the model.
function ensureTail() {
  const el = element.value
  if (el?.textContent.endsWith('\n') && !el.lastChild?.matches?.('[data-composer-tail]')) {
    const tail = document.createElement('br')
    tail.dataset.composerTail = ''
    el.append(tail)
  }
}
function resizeEditor() {
  const el = box.value
  if (!el) return
  const style = getComputedStyle(el)
  const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.7
  const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom)
  const limit = lineHeight * 3 + padding
  el.style.minHeight = `${lineHeight + padding}px`
  el.style.maxHeight = `${limit}px`
  el.style.height = 'auto'
  const height = Math.max(lineHeight + padding, el.scrollHeight)
  el.style.height = `${Math.min(height, limit)}px`
  el.style.overflowY = height > limit + 1 ? 'auto' : 'hidden'
}
function updateEmpty() { empty.value = !read().trim(); nextTick(resizeEditor) }
function placeCaret(offset) {
  const el = element.value
  if (!el) return
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  let node
  let remaining = offset
  const range = document.createRange()
  if (offset === read().length && el.lastChild?.matches?.('[data-composer-tail]')) {
    range.setStartBefore(el.lastChild)
    range.collapse(true)
    const selection = window.getSelection()
    selection.removeAllRanges()
    selection.addRange(range)
    return
  }
  while ((node = walker.nextNode())) {
    if (remaining <= node.length) { range.setStart(node, remaining); break }
    remaining -= node.length
  }
  if (!node) { range.selectNodeContents(el); range.collapse(false) }
  else range.collapse(true)
  const selection = window.getSelection()
  selection.removeAllRanges()
  selection.addRange(range)
}
function caretOffset() {
  const selection = window.getSelection()
  if (!selection?.rangeCount || !element.value.contains(selection.anchorNode)) return read().length
  const range = selection.getRangeAt(0).cloneRange()
  range.selectNodeContents(element.value)
  range.setEnd(selection.getRangeAt(0).startContainer, selection.getRangeAt(0).startOffset)
  return range.toString().length
}
function sync() {
  if (!element.value || composing) return
  if (read() !== (props.modelValue || '')) {
    element.value.textContent = props.modelValue || ''
    ensureTail()
    if (document.activeElement === element.value) placeCaret(read().length)
  }
  updateEmpty()
}
function focus() { element.value?.focus(); placeCaret(read().length) }
function focusBackground() {
  const selection = window.getSelection()
  if (selection?.rangeCount && !selection.isCollapsed && selection.getRangeAt(0).intersectsNode(element.value)) return
  focus()
}

// A drag may start in the blank space after the last line. Start that selection
// inside the editable span, so crossing its boundary does not cancel the drag.
let dragAnchor = null
function pointCaret(x, y) {
  const el = element.value
  const hit = document.caretPositionFromPoint?.(x, y)
  const range = hit ? null : document.caretRangeFromPoint?.(x, y)
  const node = hit?.offsetNode || range?.startContainer
  const offset = hit?.offset ?? range?.startOffset
  if (node && el.contains(node)) return { node, offset }
  const bounds = el.getBoundingClientRect()
  return { node: el, offset: y < bounds.top || (y < bounds.top + 20 && x < bounds.left) ? 0 : el.childNodes.length }
}
function dragMove(event) {
  if (!dragAnchor) return
  const point = pointCaret(event.clientX, event.clientY)
  window.getSelection().setBaseAndExtent(dragAnchor.node, dragAnchor.offset, point.node, point.offset)
}
function endDrag() {
  dragAnchor = null
  window.removeEventListener('pointermove', dragMove)
  window.removeEventListener('pointerup', endDrag)
  window.removeEventListener('pointercancel', endDrag)
}
function startBackgroundSelection(event) {
  if (event.button !== 0 || event.pointerType === 'touch') return
  event.preventDefault()
  element.value.focus()
  dragAnchor = pointCaret(event.clientX, event.clientY)
  dragMove(event)
  window.addEventListener('pointermove', dragMove)
  window.addEventListener('pointerup', endDrag)
  window.addEventListener('pointercancel', endDrag)
}
function input(event) {
  updateEmpty()
  if (composing || event?.isComposing) return
  const value = read()
  if (!value.trim()) {
    element.value.replaceChildren()
    updateEmpty()
  }
  emit('update:modelValue', value.trim() ? value : '')
}
function insert(text) {
  const el = element.value
  const selection = window.getSelection()
  if (!selection?.rangeCount || !el.contains(selection.getRangeAt(0).commonAncestorContainer)) focus()
  const range = window.getSelection().getRangeAt(0)
  range.deleteContents()
  const node = document.createTextNode(text)
  range.insertNode(node)
  ensureTail()
  range.setStart(node, node.length)
  range.collapse(true)
  const remaining = range.cloneRange()
  remaining.setEnd(el, el.childNodes.length)
  if (!remaining.toString() && el.lastChild?.matches?.('[data-composer-tail]')) range.setStartBefore(el.lastChild)
  selection.removeAllRanges()
  selection.addRange(range)
  input()
}
function paste(event) {
  event.preventDefault()
  const clipboard = event.clipboardData
  const pastedFiles = Array.from(clipboard?.files || [])
  if (pastedFiles.length) {
    emit('paste-files', pastedFiles)
    return
  }
  const text = clipboard?.getData('text/plain') || ''
  if (text.length > 800) emit('paste-long-text', text)
  else insert(text)
}
function drop(event) {
  const droppedFiles = Array.from(event.dataTransfer?.files || [])
  if (droppedFiles.length) emit('paste-files', droppedFiles)
}
function compositionStart() { composing = true; empty.value = false }
function compositionEnd() { composing = false; input(); nextTick(sync) }
watch(() => props.modelValue, sync, { flush: 'post' })
watch(() => props.skill, () => nextTick(resizeEditor), { flush: 'post' })
let observer
onMounted(() => {
  sync()
  let width = 0
  observer = new ResizeObserver(entries => {
    const nextWidth = entries[0].contentRect.width
    if (nextWidth !== width) { width = nextWidth; resizeEditor() }
  })
  observer.observe(box.value)
  document.fonts?.ready.then(() => { if (box.value) resizeEditor() })
})
onBeforeUnmount(() => { endDrag(); observer?.disconnect() })
defineExpose({ read, focus, insert, caretOffset })
</script>

<template>
  <div ref="box" class="composer-editor" @pointerdown.self="startBackgroundSelection" @click.self="focusBackground">
    <button v-if="skill" type="button" class="composer-skill-chip" aria-haspopup="dialog" @click="emit('show-info')">
      <component :is="skill.icon" :size="20" /><b>{{ skill.label }}</b>
    </button><span
      ref="element"
      class="composer-text"
      :class="{ 'is-empty': empty && !modelValue }"
      contenteditable="true"
      role="textbox"
      aria-multiline="true"
      :aria-label="label"
      :data-placeholder="placeholder"
      @input="input"
      @compositionstart="compositionStart"
      @compositionend="compositionEnd"
      @keydown="emit('keydown', $event)"
      @paste="paste"
      @dragover.prevent
      @drop.prevent="drop"
    ></span>
  </div>
</template>

<style scoped>
.composer-editor{box-sizing:border-box;scrollbar-width:thin;scrollbar-color:#c9b4e7 transparent}
.composer-skill-chip{border:0;font-family:inherit;text-align:inherit}
.composer-text{outline:none;white-space:pre-wrap;overflow-wrap:anywhere}
.composer-text.is-empty{display:inline-block;min-width:1px}
.composer-text.is-empty:before{content:attr(data-placeholder);color:#929cac;pointer-events:none}
</style>
