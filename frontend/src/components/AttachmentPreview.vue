<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { FileText, Image as ImageIcon, X, ZoomIn, ZoomOut } from 'lucide-vue-next'

const props = defineProps({ file: { type: Object, required: true } })
const emit = defineEmits(['close'])
const zoom = ref(1)
const naturalSize = ref({ width: 0, height: 0 })
const viewportSize = ref({ width: 0, height: 0 })
const viewport = ref(null)
let resizeObserver
let previousBodyOverflow = ''

const imageWidth = computed(() => {
  if (!naturalSize.value.width || !viewportSize.value.width) return undefined
  const fit = Math.min(1, viewportSize.value.width / naturalSize.value.width,
    viewportSize.value.height / naturalSize.value.height)
  return `${Math.round(naturalSize.value.width * fit * zoom.value)}px`
})

function measureViewport() {
  if (!viewport.value) return
  viewportSize.value = {
    width: Math.max(1, viewport.value.clientWidth - 40),
    height: Math.max(1, viewport.value.clientHeight - 40)
  }
}

function imageLoaded(event) {
  naturalSize.value = { width: event.target.naturalWidth, height: event.target.naturalHeight }
  measureViewport()
}

function changeZoom(step) {
  zoom.value = Math.max(0.5, Math.min(3, Math.round((zoom.value + step) * 100) / 100))
}

function onKeydown(event) { if (event.key === 'Escape') emit('close') }

watch(() => props.file.previewUrl, () => {
  zoom.value = 1
  naturalSize.value = { width: 0, height: 0 }
  nextTick(measureViewport)
})

onMounted(() => {
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', onKeydown)
  nextTick(() => {
    measureViewport()
    if (viewport.value && window.ResizeObserver) {
      resizeObserver = new ResizeObserver(measureViewport)
      resizeObserver.observe(viewport.value)
    }
  })
})

onBeforeUnmount(() => {
  document.body.style.overflow = previousBodyOverflow
  window.removeEventListener('keydown', onKeydown)
  resizeObserver?.disconnect()
})
</script>

<template>
  <Teleport to="body">
    <div class="attachment-preview-overlay" role="presentation" @click.self="emit('close')">
      <section class="attachment-preview-dialog" role="dialog" aria-modal="true" :aria-label="`预览 ${file.name}`">
        <header>
          <span class="attachment-preview-title"><ImageIcon v-if="file.type === 'image'" :size="18" /><FileText v-else :size="18" /><strong>{{ file.name }}</strong></span>
          <div class="attachment-preview-actions">
            <template v-if="file.type === 'image' && file.previewUrl">
              <button type="button" aria-label="缩小图片" title="缩小图片" :disabled="zoom <= 0.5" @click="changeZoom(-0.25)"><ZoomOut :size="18" /></button>
              <small>{{ Math.round(zoom * 100) }}%</small>
              <button type="button" aria-label="放大图片" title="放大图片" :disabled="zoom >= 3" @click="changeZoom(0.25)"><ZoomIn :size="18" /></button>
            </template>
            <button type="button" aria-label="关闭预览" title="关闭预览" @click="emit('close')"><X :size="19" /></button>
          </div>
        </header>
        <div ref="viewport" class="attachment-preview-body" :class="{ 'is-image': file.type === 'image' }">
          <div v-if="file.type === 'image' && file.previewUrl" class="attachment-preview-image-canvas">
            <img :src="file.previewUrl" :alt="file.name" :style="imageWidth ? { width: imageWidth } : {}" @load="imageLoaded" />
          </div>
          <p v-else-if="file.type === 'image'">图片预览暂不可用</p>
          <pre v-else>{{ file.content || (file.uploading ? '正在读取文件…' : '文件内容为空') }}</pre>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.attachment-preview-overlay{position:fixed;inset:0;z-index:10000;display:grid;place-items:center;padding:18px;background:rgba(33,16,54,.58);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.attachment-preview-dialog{display:flex;flex-direction:column;width:min(680px,100%);height:min(84vh,820px);min-width:0;overflow:hidden;border:1px solid #d7c9e9;border-radius:18px;background:#fff;box-shadow:0 28px 75px rgba(31,9,59,.25)}
.attachment-preview-dialog header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex:none;min-height:58px;padding:10px 16px;border-bottom:1px solid #e8e1f1}
.attachment-preview-title{display:flex;align-items:center;gap:9px;min-width:0;color:#432567}
.attachment-preview-title strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}
.attachment-preview-actions{display:flex;align-items:center;gap:3px;flex:none}
.attachment-preview-actions button{display:grid;place-items:center;width:32px;height:32px;border:0;border-radius:8px;background:transparent;color:#685283;cursor:pointer}
.attachment-preview-actions button:hover:not(:disabled){background:#efe8f7;color:#4d0a9e}
.attachment-preview-actions button:disabled{opacity:.4;cursor:default}
.attachment-preview-actions button:last-child{margin-left:7px}
.attachment-preview-actions small{min-width:39px;color:#7d6a95;font-size:11px;font-weight:700;text-align:center}
.attachment-preview-body{flex:1;min-height:0;overflow:auto;padding:20px;background:#fbf9fd}
.attachment-preview-body.is-image{background:#f2eef8}
.attachment-preview-image-canvas{display:flex;align-items:center;justify-content:center;width:max-content;min-width:100%;min-height:100%}
.attachment-preview-body img{display:block;max-width:none;height:auto;object-fit:contain}
.attachment-preview-body pre{margin:0;color:#3d2956;font:13px/1.7 "MindPilot Latin",Consolas,'Cascadia Code',monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.attachment-preview-body p{color:#75638b}
@media(max-width:600px){.attachment-preview-overlay{padding:10px}.attachment-preview-dialog{height:min(88vh,820px)}.attachment-preview-body{padding:14px}.attachment-preview-actions small{min-width:35px}}
</style>
