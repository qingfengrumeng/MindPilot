<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, Image as ImageIcon } from 'lucide-vue-next'
import { chatApi } from '@/api'

const props = defineProps({ message: { type: Object, required: true } })
const poster = computed(() => props.message.poster || props.message.metadata?.poster || {})
const previewUrl = ref('')
const error = ref('')
const busy = ref(false)
let mounted = true

watch(() => poster.value.pngArtifactId, async id => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  error.value = ''
  if (!id) return
  try {
    const blob = await chatApi.artifactBlob(id)
    if (mounted && poster.value.pngArtifactId === id) previewUrl.value = URL.createObjectURL(blob)
  } catch (cause) { error.value = cause?.message || '预览加载失败' }
}, { immediate: true })

onBeforeUnmount(() => {
  mounted = false
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})

async function download(kind) {
  const ids = { html: poster.value.htmlArtifactId, png: poster.value.pngArtifactId,
    pdf: poster.value.pdfArtifactId }
  if (!ids[kind] || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const blob = await chatApi.artifactBlob(ids[kind])
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `海报.${kind}`
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  } catch (cause) { error.value = cause?.message || '下载失败' }
  finally { busy.value = false }
}
</script>

<template>
  <div class="poster-card">
    <div class="poster-card-head"><span><ImageIcon :size="18" /> 海报设计</span><small>HTML · PNG · PDF</small></div>
    <div class="poster-card-preview">
      <img v-if="previewUrl" :src="previewUrl" alt="生成的海报预览" />
      <span v-else>{{ error || '正在加载海报预览…' }}</span>
    </div>
    <div class="poster-card-actions">
      <button type="button" :disabled="busy" @click="download('html')"><Download :size="15" /> HTML源文件</button>
      <button type="button" :disabled="busy" @click="download('png')"><Download :size="15" /> PNG图片</button>
      <button type="button" :disabled="busy" @click="download('pdf')"><Download :size="15" /> PDF文件</button>
    </div>
    <p v-if="error && previewUrl" class="poster-card-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.poster-card{width:min(100%,620px);overflow:hidden;border:1px solid #ceb8ea;border-radius:22px;background:#faf7fe;box-shadow:0 16px 45px #380b7014}
.poster-card-head{padding:17px 20px;display:flex;justify-content:space-between;align-items:center;color:#35165b;border-bottom:1px solid #e5d9f4}
.poster-card-head span{display:flex;align-items:center;gap:9px;font-size:17px;font-weight:800}.poster-card-head small{color:#856aa6;font-size:12px}
.poster-card-preview{min-height:280px;max-height:600px;display:flex;justify-content:center;align-items:center;background:#f0e9f9;padding:16px;color:#7d61a0}
.poster-card-preview img{display:block;max-width:100%;max-height:565px;object-fit:contain;border-radius:4px;box-shadow:0 8px 25px #1e063c35}
.poster-card-actions{display:flex;flex-wrap:wrap;gap:9px;padding:15px 18px}.poster-card-actions button{display:inline-flex;align-items:center;gap:6px;border:1px solid #ceb7ea;border-radius:10px;background:white;color:#4b089c;padding:9px 12px;cursor:pointer;font-weight:700}.poster-card-actions button:hover{background:#f0e6fc}.poster-card-actions button:disabled{opacity:.5;cursor:default}.poster-card-error{padding:0 18px 12px;color:#b34444}
</style>
