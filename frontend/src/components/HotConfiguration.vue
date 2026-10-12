<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Flame, Save, X } from 'lucide-vue-next'
import { workbenchApi } from '@/api/workbench'
import { defaultHotPreferences } from '@/lib/hotPreferences'
const emit = defineEmits(['close', 'saved'])
const form = reactive(defaultHotPreferences()), loading = ref(true), saving = ref(false), error = ref(''), dialog = ref(null)
const previousFocus = document.activeElement
const previousOverflow = document.body.style.overflow
onMounted(async () => {
  document.body.style.overflow = 'hidden'
  try { Object.assign(form, await workbenchApi.hotPreferences()) } catch (cause) { error.value = cause.message }
  finally { loading.value = false; await nextTick(); dialog.value?.focus() }
})
onBeforeUnmount(() => { document.body.style.overflow = previousOverflow; previousFocus?.focus?.() })
async function save() {
  saving.value = true; error.value = ''
  try { const result = await workbenchApi.saveHotPreferences({ direction: form.direction.trim(), maxItems: form.maxItems === '' || form.maxItems == null ? null : Number(form.maxItems) }); window.dispatchEvent(new CustomEvent('mindpilot:hot-preferences', { detail: result })); emit('saved'); emit('close') }
  catch (cause) { error.value = cause.message }
  finally { saving.value = false }
}
function keydown(event) {
  if (event.key === 'Escape' && !saving.value) emit('close')
  if (event.key !== 'Tab') return
  const elements = [...dialog.value.querySelectorAll('button:not(:disabled),input,textarea')]
  const first = elements[0], last = elements.at(-1)
  if (event.shiftKey && [first, dialog.value].includes(document.activeElement)) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && [last, dialog.value].includes(document.activeElement)) { event.preventDefault(); first?.focus() }
}
</script>
<template>
  <Teleport to="body"><div class="hot-config-mask" @click.self="!saving && emit('close')">
    <form ref="dialog" class="hot-config" role="dialog" aria-modal="true" aria-labelledby="hot-config-title" tabindex="-1" @submit.prevent="save" @keydown="keydown">
      <header><span><Flame :size="23" /></span><div><h2 id="hot-config-title">热点配置</h2><p>告诉 Agent 你想关注什么</p></div><button type="button" aria-label="关闭热点配置" :disabled="saving" @click="emit('close')"><X :size="22" /></button></header>
      <div v-if="loading" class="hot-config-body">正在读取配置…</div>
      <div v-else class="hot-config-body">
        <label for="hot-direction">热点方向</label><textarea id="hot-direction" v-model="form.direction" maxlength="1000" rows="4" :disabled="saving" placeholder="例如：最近一周 DeepSeek、RAG 和医疗 AI 的新进展，关注产品发布与研究成果" />
        <label for="hot-count">每次获取条数<span class="hot-optional">可留空</span></label><input id="hot-count" v-model="form.maxItems" type="number" min="1" max="100" step="1" :disabled="saving" placeholder="不限制" />
        <small class="hot-count-hint">留空时只搜索一次，保存 Agent 整理并校验通过的全部热点；填写条数后，数量不足会补搜。</small>
        <p v-if="error" class="hot-config-error" role="alert">{{ error }}</p>
      </div>
      <footer><span>配置仅对当前账户生效，下次同步时应用</span><button type="submit" :disabled="loading || saving"><Save :size="17" />{{ saving ? '保存中…' : '保存配置' }}</button></footer>
    </form>
  </div></Teleport>
</template>
<style scoped>
.hot-config-mask{position:fixed;inset:0;z-index:150;display:grid;place-items:center;padding:24px;background:#24133566;backdrop-filter:blur(5px)}.hot-config{width:min(850px,100%);max-height:90vh;overflow:auto;border:1px solid #ece3f5;border-radius:24px;background:white;box-shadow:0 30px 100px #26104230;color:#342044;outline:none}.hot-config header{display:flex;align-items:center;gap:16px;padding:26px 30px;border-bottom:1px solid #eee7f5}.hot-config header>span{display:grid;place-items:center;width:48px;height:48px;background:#f4edff;color:#7c3aed;border-radius:15px}.hot-config h2{margin:0;font-size:22px}.hot-config header p{margin:7px 0 0;color:#a092ae;font-size:13px}.hot-config header button{margin-left:auto;border:0;background:none;color:#a392b3;cursor:pointer}.hot-config-body{padding:28px 30px}.hot-config label{display:block;color:#715b85;font-size:14px;margin:0 0 12px}.hot-config small{display:block;color:#a296ad;font-size:12px;line-height:1.8;margin-bottom:24px}.hot-config textarea,.hot-config input{box-sizing:border-box;width:100%;padding:13px 15px;border:1px solid #e3d9ef;border-radius:12px;color:#44304f;background:#fdfbff;font:inherit;outline:none}.hot-config textarea{resize:vertical;margin-bottom:24px}.hot-config input{display:block;margin-top:12px}.hot-config footer{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:20px 30px;border-top:1px solid #eee7f5}.hot-config footer span{color:#ad9cba;font-size:12px}.hot-config footer button{display:flex;align-items:center;gap:8px;padding:12px 20px;border:0;border-radius:12px;background:#7c3aed;color:white;cursor:pointer;white-space:nowrap}.hot-config button:disabled{opacity:.5;cursor:default}.hot-config :focus-visible{outline:2px solid #a78bfa;outline-offset:3px}.hot-config-error{color:#bd4660;font-size:13px}@media(max-width:600px){.hot-config-mask{padding:12px}.hot-config header,.hot-config-body,.hot-config footer{padding:20px}.hot-config footer{align-items:flex-end}.hot-config footer span{max-width:50%}}

.hot-config{width:min(680px,100%)}.hot-config textarea{min-height:120px;line-height:1.8;margin-bottom:24px}.hot-config input{margin-top:0}.hot-optional{margin-left:10px;font-size:11px;color:#ac9db9;font-weight:400}.hot-config .hot-count-hint{margin:12px 0 0}.hot-config textarea:focus,.hot-config input:focus{border-color:#a78bfa;box-shadow:0 0 0 3px #a78bfa18}.hot-config-body{padding:26px 30px 30px}
</style>
