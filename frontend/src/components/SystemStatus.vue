<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Activity, Database, FileText, LoaderCircle, RefreshCw, X } from 'lucide-vue-next'
import { workbenchApi } from '@/api/workbench'

const emit = defineEmits(['close'])
const status = ref(null)
const loading = ref(false)
const error = ref('')
let disposed = false
const labels = {
  uploaded: '已上传', processing: '处理中', vectorizing: '索引中', indexed: '已索引',
  ready: '已就绪', queued: '排队中', pending: '等待中', running: '运行中',
  completed: '已完成', succeeded: '已完成', failed: '失败', error: '异常',
  cancelled: '已取消', interrupted: '已中断'
}
const sections = computed(() => [
  { title: '资料索引', icon: FileText, unit: '份', counts: status.value?.documents || {} },
  { title: '运行任务', icon: Activity, unit: '个', counts: status.value?.tasks || {} }
])

async function refresh() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const result = await workbenchApi.system()
    if (!disposed) status.value = result
  } catch (cause) {
    if (!disposed) error.value = cause?.message || '系统状态加载失败，请重试'
  } finally {
    if (!disposed) loading.value = false
  }
}
function keydown(event) { if (event.key === 'Escape') emit('close') }
onMounted(() => { refresh(); window.addEventListener('keydown', keydown) })
onBeforeUnmount(() => { disposed = true; window.removeEventListener('keydown', keydown) })
</script>

<template>
  <div class="modal-mask system-status-mask" @click.self="emit('close')">
    <section class="system-status-dialog" role="dialog" aria-modal="true" aria-labelledby="system-status-title">
      <header>
        <div><span class="system-status-icon"><Database :size="21" /></span><h2 id="system-status-title">系统状态</h2></div>
        <button type="button" class="system-status-close" aria-label="关闭系统状态" @click="emit('close')"><X :size="20" /></button>
      </header>
      <div class="system-status-content" :aria-busy="loading">
        <p v-if="error" class="system-status-error" role="alert">{{ error }}</p>
        <p v-if="loading && !status" class="system-status-loading" role="status"><LoaderCircle :size="18" class="system-status-spin" />正在读取系统状态…</p>
        <template v-if="status">
          <article class="system-status-storage"><Database :size="19" /><div><h3>本地数据库</h3><p>知识条目 {{ Number(status.entries || 0).toLocaleString('zh-CN') }} 条</p><small>按当前账户隔离保存</small></div></article>
          <div class="system-status-sections">
            <article v-for="section in sections" :key="section.title">
              <h3><component :is="section.icon" :size="18" />{{ section.title }}</h3>
              <dl v-if="Object.keys(section.counts).length"><div v-for="(count, key) in section.counts" :key="key"><dt>{{ labels[key] || key }}</dt><dd>{{ Number(count).toLocaleString('zh-CN') }} {{ section.unit }}</dd></div></dl>
              <p v-else class="system-status-empty">{{ section.title === '资料索引' ? '尚无资料' : '尚无任务' }}</p>
            </article>
          </div>
        </template>
      </div>
      <footer><button type="button" :disabled="loading" @click="refresh"><RefreshCw :size="15" :class="{ 'system-status-spin': loading }" />{{ loading ? '刷新中…' : error ? '重新加载' : '刷新状态' }}</button></footer>
    </section>
  </div>
</template>

<style scoped>
.system-status-mask{padding:20px}
.system-status-dialog{display:flex;flex-direction:column;width:min(600px,100%);max-height:calc(100dvh - 40px);overflow:hidden;border:1px solid #e7def2;border-radius:24px;background:#fff;box-shadow:0 24px 90px #44236b30;color:#39284b}
header{display:flex;align-items:center;justify-content:space-between;padding:22px 24px;border-bottom:1px solid #eee7f5}header>div{display:flex;align-items:center;gap:12px}h2{margin:0;font-size:18px}.system-status-icon{display:grid;place-items:center;width:40px;height:40px;border-radius:12px;background:#f3edfd;color:#7c3aed}
button{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid #e7def2;border-radius:10px;padding:9px 12px;font:inherit;font-size:13px;background:#f8f5fc;color:#6d28d9;cursor:pointer}button:hover{background:#f0e8fc}button:focus-visible{outline:2px solid #a78bfa;outline-offset:3px}button:disabled{opacity:.6;cursor:default}.system-status-close{width:34px;height:34px;padding:0;border:0;color:#9585a5}
.system-status-content{min-height:0;overflow:auto;padding:24px}.system-status-storage{display:flex;gap:12px;align-items:flex-start;padding:18px;border:1px solid #e8e0f0;border-radius:16px;background:#fdfbff}.system-status-storage>svg{color:#7c3aed;margin-top:2px}h3{margin:0;font-size:14px}p{margin:10px 0;font-size:14px}small{color:#94849f;font-size:12px}
.system-status-sections{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.system-status-sections article{padding:18px;border:1px solid #eee7f5;border-radius:16px}.system-status-sections h3{display:flex;align-items:center;gap:8px}.system-status-sections h3 svg{color:#7c3aed}dl{margin:15px 0 0}dl>div{display:flex;justify-content:space-between;gap:12px;margin-top:10px;font-size:13px}dt{color:#8c7b9a}dd{margin:0;font-variant-numeric:tabular-nums}.system-status-empty{color:#94849f;font-size:13px}.system-status-loading{display:flex;align-items:center;justify-content:center;gap:8px;min-height:90px;color:#8c7b9a}.system-status-error{margin:0 0 14px;padding:12px;border-radius:10px;background:#fff3f5;color:#bc4770;line-height:1.6;overflow-wrap:anywhere}
footer{display:flex;justify-content:flex-end;padding:15px 24px;border-top:1px solid #eee7f5;background:#fdfbff}.system-status-spin{animation:system-status-spin 1s linear infinite}@keyframes system-status-spin{to{transform:rotate(360deg)}}
@media(max-width:480px){.system-status-mask{padding:10px}.system-status-dialog{max-height:calc(100dvh - 20px);border-radius:18px}header,.system-status-content{padding:18px}.system-status-sections{grid-template-columns:1fr}footer{padding:14px 18px}}
</style>
