<script setup>
import AppSelect from '@/components/AppSelect.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { BrainCircuit, Braces, ChevronDown, Copy, ExternalLink, Eye, EyeOff, Globe, KeyRound, LoaderCircle, Minimize2, Plus, RefreshCw, Save, Settings2, Trash2, X, Zap } from 'lucide-vue-next'
import { jsonSyntaxTokens, modelConfigPreview } from '@/utils/modelConfigPreview'
import ModelNameSelect from './ModelNameSelect.vue'
import VoiceNameSelect from './VoiceNameSelect.vue'
import { modelsApi } from '@/api/models'
import deepseekIcon from '@/assets/providers/deepseek.svg'
import kimiIcon from '@/assets/providers/kimi.svg'
import qwenIcon from '@/assets/providers/qwen.svg'
import doubaoIcon from '@/assets/providers/doubao-color.svg'
import glmIcon from '@/assets/providers/zhipu-color.svg'

const emit = defineEmits(['close'])
const icons = { deepseek: deepseekIcon, kimi: kimiIcon, qwen: qwenIcon, doubao: doubaoIcon, glm: glmIcon }
const data = ref(null), category = ref('text'), expanded = ref(''), loading = ref(true)
const error = ref(''), notice = ref(''), busy = ref(''), dialog = ref(null), adding = ref(false), customName = ref('')
const drafts = reactive({}), modelLists = reactive({}), diagnostics = reactive({}), testing = ref(''), clearingKey = ref('')
const voiceLists=reactive({}), fetchingVoices=ref(''), fetchingModels=ref('')
let voiceVersion=0
function clearVoiceLists(){voiceVersion++;for(const id of Object.keys(voiceLists))delete voiceLists[id]}
const hiddenKeys = ref(true), compactJson = ref(false), dirty = reactive(new Set()), timers = new Map()
const jsonDocument = computed(() => modelConfigPreview(data.value?.document, drafts, dirty, hiddenKeys.value))
const jsonText = computed(() => JSON.stringify(jsonDocument.value, null, compactJson.value ? 0 : 2))
const jsonLines = computed(() => jsonText.value.split('\n').map(jsonSyntaxTokens))
const readOnly = computed(() => data.value?.editable === false)
const previousFocus = document.activeElement
let disposed = false
let listVersion = 0
function clearModelLists() {
  clearVoiceLists()
  listVersion++
  for (const id of Object.keys(modelLists)) delete modelLists[id]
}
const categories = computed(() => data.value?.categories || [])
const providers = computed(() => (data.value?.providers || []).filter(p => p.defaults[category.value] || p.configs[category.value] || (p.custom && ['text', 'embedding'].includes(category.value))))
const activeProvider = computed(() => data.value?.providers.find(p => p.id === data.value.active[category.value]))
const activeModel = computed(() => activeProvider.value?.configs[category.value]?.model)
function setupDrafts() {
  for (const p of data.value.providers) {
    if (drafts[p.id]) continue
    const configs = {}
    for (const c of categories.value) configs[c.id] = { baseUrl: '', model: '', ...p.defaults[c.id], ...p.configs[c.id] }
    drafts[p.id] = { apiKey: '', speechApiKey: '', clearApiKey: false, clearSpeechApiKey: false, reveal: false, configs }
  }
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const result = await modelsApi.list()
    if (disposed) return
    data.value = result; setupDrafts()
    expanded.value = result.active[category.value] || providers.value[0]?.id || ''
  } catch (e) { if (!disposed) error.value = e.message }
  finally { loading.value = false }
}
function switchCategory(value) {
  category.value = value; error.value = ''; notice.value = ''
  expanded.value = data.value.active[value] || providers.value[0]?.id || ''
}
function options(p) {
  return [...new Set((modelLists[`${p.id}:${category.value}`] || []).filter(Boolean))].sort((a, b) => a.localeCompare(b))
}
function speechKey(p, c = category.value) { return p.separateSpeechKey && ['asr', 'tts'].includes(c) }
function keyField(p, c = category.value) { return speechKey(p, c) ? 'speechApiKey' : 'apiKey' }
function clearKeyField(p, c = category.value) { return speechKey(p, c) ? 'clearSpeechApiKey' : 'clearApiKey' }
function hasKey(p, c = category.value) { return speechKey(p, c) ? p.hasSpeechKey : p.hasKey }
function keyLabel(p) { return p.separateSpeechKey ? (speechKey(p) ? '豆包语音API Key' : '火山方舟API Key') : 'API Key' }
function modelChanged(p) {
  const config = drafts[p.id].configs[category.value]
  if (p.id !== 'volcengine' || category.value !== 'embedding') return
  if (config.model.startsWith('doubao-embedding-vision')) config.embeddingProtocol = 'multimodal'
  else if (config.model.startsWith('doubao-embedding-text')) config.embeddingProtocol = 'compatible'
  if (config.model === 'doubao-embedding-vision-250615') config.instruction = ''
}
function payload(p, selectedCategory) {
  const draft = drafts[p.id], config = { ...draft.configs[selectedCategory] }
  const key = keyField(p, selectedCategory), clear = clearKeyField(p, selectedCategory)
  if (!config.baseUrl.trim() || !config.model.trim()) throw new Error('请填写接口地址和模型名称')
  if (!hasKey(p, selectedCategory) && !draft[key].trim() && !draft[clear]) throw new Error('请填写对应的厂商API Key')
  if (draft[clear] && draft[key].trim()) throw new Error('清除密钥时请先清空新填写的API Key')
  if (config.dimensions === '') config.dimensions = null
  return { name: p.name, [key]: draft[key].trim() || null, [clear]: draft[clear], configs: { [selectedCategory]: config } }
}
async function persist(p, selectedCategory) {
  clearTimeout(timers.get(`${p.id}:${selectedCategory}`)); timers.delete(`${p.id}:${selectedCategory}`)
  const result = await modelsApi.save(p.id, payload(p, selectedCategory))
  if (!disposed) {
    data.value = result; drafts[p.id][keyField(p, selectedCategory)] = ''; drafts[p.id][clearKeyField(p, selectedCategory)] = false
    drafts[p.id].configs[selectedCategory] = { ...result.providers.find(item => item.id === p.id).configs[selectedCategory] }
    dirty.delete(`${p.id}:${selectedCategory}`)
  }
}
function queueAutosave(p, c = category.value) {
  if (readOnly.value) return
  const id = `${p.id}:${c}`
  delete diagnostics[id]
  dirty.add(id); clearTimeout(timers.get(id))
  timers.set(id, setTimeout(async () => {
    timers.delete(id)
    if (disposed) return
    if (busy.value) { queueAutosave(p, c); return }
    try { payload(p, c) } catch { return }
    await run(p.id, async () => { await persist(p, c) })
  }, 700))
}
async function copyJson() {
  try { await navigator.clipboard.writeText(jsonText.value); notice.value = '已复制当前JSON预览。' }
  catch { error.value = '复制失败，请手动选择JSON内容复制。' }
}
async function run(id, task) {
  if (busy.value || readOnly.value) return
  busy.value = id; error.value = ''; notice.value = ''
  try { await task() } catch (e) { if (!disposed) error.value = e.message }
  finally { busy.value = '' }
}
function save(p) {
  const c = category.value
  return run(p.id, async () => { await persist(p, c); notice.value = '已保存，同一凭证组的模型共用此API Key。' })
}
function clearSavedKey(p) {
  const c = category.value, key = keyField(p, c), clear = clearKeyField(p, c)
  return run(p.id, async () => {
    clearingKey.value = p.id
    try {
      const result = await modelsApi.save(p.id, { name: p.name, [clear]: true, configs: {} })
      if (disposed) return
      data.value = result
      drafts[p.id][key] = ''; drafts[p.id][clear] = false
      for (const item of categories.value) {
        if (keyField(p, item.id) !== key) continue
        const id = `${p.id}:${item.id}`
        clearTimeout(timers.get(id)); timers.delete(id)
        delete diagnostics[id]
      }
      clearModelLists()
      notice.value = '已清除当前凭证组的API Key，相关模型已停用。'
    } finally { clearingKey.value = '' }
  })
}
function toggle(p) {
  const c = category.value, isActive = data.value.active[c] === p.id
  return run(p.id, async () => {
    if (!isActive) await persist(p, c)
    const result = await modelsApi.activate(c, isActive ? null : p.id)
    if (!disposed) { data.value = result; notice.value = isActive ? '已停用此类别的模型。' : '已启用，新请求将使用此模型。' }
  })
}
function fetchModels(p) {
  const c = category.value
  if(Object.hasOwn(modelLists,`${p.id}:${c}`))return
  return run(p.id, async () => {
    const draft = drafts[p.id]
    const version = listVersion, key = keyField(p, c)
    if (draft[clearKeyField(p, c)]) throw new Error('请先取消清除API Key，或保存清除后填写新密钥')
    if (!draft.configs[c].baseUrl.trim() || (!draft[key].trim() && !hasKey(p, c))) throw new Error('请填写接口地址与API Key')
    fetchingModels.value=p.id
    let result
    try { result = await modelsApi.discover(p.id, c, { baseUrl: draft.configs[c].baseUrl, apiKey: draft[key].trim() || null }) }
    finally { fetchingModels.value='' }
    if (!disposed && version === listVersion) {
      modelLists[`${p.id}:${c}`] = result.models
      notice.value = result.models.length ? `已从厂商接口获取 ${result.models.length} 个模型，可搜索选择；本次列表不保存。` : '厂商未返回模型列表，可手动填写。'
    }
  })
}
function fetchVoices(p){
  const selectedModel=drafts[p.id].configs.tts.model.trim()
  const cacheId=`${p.id}:${selectedModel}`
  if(Object.hasOwn(voiceLists,cacheId))return
  return run(p.id,async()=>{
    const model=drafts[p.id].configs.tts.model.trim()
    if(!model)throw new Error('请先选择 TTS 模型')
    const version=voiceVersion
    fetchingVoices.value=p.id
    try{
      const result=await modelsApi.voices(p.id,model)
      if(!disposed && version===voiceVersion){
        voiceLists[`${p.id}:${model}`]=result.voices
        notice.value=`已获取 ${result.voices.length} 个官方系统音色，可按名称或 ID 搜索选择。`
      }
    }finally{fetchingVoices.value=''}
  })
}
function voicesFor(p){return voiceLists[`${p.id}:${drafts[p.id].configs.tts.model.trim()}`]||[]}
async function previewVoice(p,voice,signal){
  const draft=drafts[p.id]
  if(draft.clearApiKey)throw new Error('请先取消清除 API Key 或填写新密钥')
  return modelsApi.previewVoice(p.id,{baseUrl:draft.configs.tts.baseUrl,model:draft.configs.tts.model,voice:voice.id,apiKey:draft.apiKey.trim()||null},signal)
}
function testConnection(p) {
  const c = category.value, id = `${p.id}:${c}`
  return run(p.id, async () => {
    testing.value = id; delete diagnostics[id]
    try {
      const result = await modelsApi.test(p.id, c, payload(p, c))
      if (!disposed) diagnostics[id] = result
    } catch (e) {
      if (!disposed) diagnostics[id] = { ok: false, message: e.message }
    } finally { testing.value = '' }
  })
}
function addProvider() {
  return run('add', async () => {
    if (!customName.value.trim()) throw new Error('请填写厂商名称')
    const result = await modelsApi.add({ name: customName.value.trim(), configs: {} })
    if (!disposed) {
      data.value = result; setupDrafts(); category.value = 'text'
      expanded.value = result.providers.at(-1).id; adding.value = false; customName.value = ''
      notice.value = '已添加兼容接口，请填写接口地址、API Key和模型名称。'
    }
  })
}
async function close() {
  if (busy.value) return
  for (const id of [...dirty]) {
    clearTimeout(timers.get(id)); timers.delete(id)
    const [providerId, c] = id.split(':')
    const p = data.value.providers.find(p => p.id === providerId)
    try { payload(p, c) } catch { continue }
    await run(p.id, () => persist(p, c))
    if (error.value) return
  }
  emit('close')
}
function keydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (event.key !== 'Tab') return
  const items = [...dialog.value.querySelectorAll('button:not(:disabled),input:not(:disabled),a[href],select:not(:disabled),textarea:not(:disabled)')].filter(el => el.getClientRects().length)
  const first = items[0], last = items.at(-1)
  if (!items.includes(document.activeElement)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus() }
  else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(async () => { document.addEventListener('keydown', keydown); await nextTick(); dialog.value?.focus(); load() })
onBeforeUnmount(() => {
  disposed = true; document.removeEventListener('keydown', keydown)
  for (const timer of timers.values()) clearTimeout(timer)
  for (const draft of Object.values(drafts)) { draft.apiKey = ''; draft.speechApiKey = '' }
  previousFocus?.isConnected && previousFocus.focus()
})
</script>

<template>
  <Teleport to="body">
    <div class="model-config-mask" @click.self="close">
      <section ref="dialog" class="model-config-dialog" role="dialog" aria-modal="true" aria-labelledby="model-config-title" tabindex="-1">
        <header class="model-config-header">
          <span class="model-config-heading-icon"><Settings2 :size="24" /></span>
          <div><h2 id="model-config-title">模型配置</h2><p>按用途选择模型，统一管理厂商密钥与接口</p></div>
          <button class="model-icon-button" :disabled="!!busy" aria-label="关闭模型配置" @click="close"><X :size="22" /></button>
        </header>
        <div v-if="loading" class="model-config-loading"><LoaderCircle :size="22" class="spin" />正在读取模型配置…</div>
        <template v-else>
          <nav v-if="data" class="model-category-tabs" aria-label="模型类别">
            <button v-for="item in categories" :key="item.id" :class="{ selected: category === item.id }" :aria-pressed="category === item.id" :disabled="!!busy" @click="switchCategory(item.id)">
              <strong>{{ item.label }}</strong><small>{{ item.description }}</small>
            </button>
          </nav>
          <div class="model-config-scroll">
            <div v-if="error" class="model-feedback error" role="alert">{{ error }}<button v-if="!data" @click="load"><RefreshCw :size="15" />重试</button></div>
            <p v-if="notice" class="model-feedback success" role="status">{{ notice }}</p>
            <template v-if="data">
              <p v-if="readOnly" class="model-embedding-note">本机共享模型配置仅主账户可修改。当前账户可以查看配置。</p>
              <div class="model-section-heading"><div><h3>模型与接口</h3><p>独立保存各厂商配置，每个类别同时启用一个模型。</p></div><button class="model-secondary" :disabled="!!busy || readOnly" @click="adding = !adding"><Plus :size="16" />添加配置</button></div>
              <form v-if="adding" class="model-add-provider" @submit.prevent="addProvider"><label for="custom-provider-name">自定义兼容接口</label><input id="custom-provider-name" v-model="customName" placeholder="厂商名称，如本地模型服务" maxlength="80" /><button class="model-primary" :disabled="!!busy || readOnly">添加</button><button type="button" class="model-secondary" @click="adding = false">取消</button></form>
              <div class="model-active-banner"><span class="model-status-dot" :class="{ enabled: activeProvider }" /><span>{{ activeProvider ? `当前启用：${activeProvider.name} · ${activeModel}` : '当前未启用此类别的远程模型' }}</span><small>保存不等于启用</small></div>
              <p v-if="category === 'embedding'" class="model-embedding-note">切换向量模型或维度后，请重新向量化已有资料，以保持检索一致。</p>
              <article v-for="p in providers" :key="p.id" class="model-provider-card" :class="{ expanded: expanded === p.id }">
                <div class="model-provider-header">
                  <button class="model-provider-expand" :aria-expanded="expanded === p.id" :aria-controls="`provider-fields-${p.id}`" @click="expanded = expanded === p.id ? '' : p.id">
                    <span class="model-provider-icon" :class="{ kimi: p.icon === 'kimi' }"><img v-if="icons[p.icon]" :src="icons[p.icon]" :alt="`${p.name} 图标`" /><component v-else :is="p.icon === 'custom' ? Globe : BrainCircuit" :size="28" /></span>
                    <span class="model-provider-title"><strong>{{ p.name }}</strong><small>{{ p.configs[category]?.model || '点击展开配置' }}</small></span>
                  </button>
                  <span v-if="hasKey(p)" class="model-saved-badge">密钥已保存</span>
                  <button class="model-icon-button model-chevron" :aria-label="expanded === p.id ? `收起 ${p.name}` : `展开 ${p.name}`" @click="expanded = expanded === p.id ? '' : p.id"><ChevronDown :size="19" :class="{ rotated: expanded === p.id }" /></button>
                  <button class="model-enable" role="switch" :aria-checked="data.active[category] === p.id" :aria-label="`启用 ${p.name} ${category} 模型`" :disabled="!!busy || readOnly" @click="toggle(p)"><span>{{ data.active[category] === p.id ? '已启用' : '启用' }}</span><i :class="{ on: data.active[category] === p.id }" /></button>
                </div>
                <form v-if="expanded === p.id" :id="`provider-fields-${p.id}`" class="model-provider-fields" @input="queueAutosave(p)" @change="queueAutosave(p)" @submit.prevent="save(p)">
                  <p v-if="p.separateSpeechKey" class="model-provider-note">火山方舟与豆包语音的API Key分开管理，在各自服务内共用，无需按模型重复填写。</p>
                  <label :for="`model-url-${p.id}`">接口地址</label><input :id="`model-url-${p.id}`" v-model="drafts[p.id].configs[category].baseUrl" :placeholder="category === 'asr' || (category === 'tts' && p.id !== 'volcengine') ? 'wss://你的工作空间域名/api-ws/v1/…' : 'https://厂商接口地址/v1'" autocomplete="off" :disabled="!!busy || readOnly" />
                  <label :for="`model-key-${p.id}`">{{ keyLabel(p) }} <small>{{ hasKey(p) ? '留空保留现有密钥' : (p.separateSpeechKey ? '同一凭证组的模型共用' : '此厂商所有模型共用') }}</small></label>
                  <div class="model-key-input"><input :id="`model-key-${p.id}`" v-model="drafts[p.id][keyField(p)]" :type="drafts[p.id].reveal ? 'text' : 'password'" :placeholder="hasKey(p) ? '••••••••••' : '填写厂商API Key'" autocomplete="new-password" :disabled="!!busy || readOnly" /><button type="button" class="model-icon-button" :aria-label="drafts[p.id].reveal ? '隐藏API Key' : '显示API Key'" @click="drafts[p.id].reveal = !drafts[p.id].reveal"><EyeOff v-if="drafts[p.id].reveal" :size="18" /><Eye v-else :size="18" /></button></div>
                  <div class="model-key-tools"><a v-if="speechKey(p) ? p.speechKeyUrl : p.keyUrl" :href="speechKey(p) ? p.speechKeyUrl : p.keyUrl" target="_blank" rel="noopener noreferrer"><KeyRound :size="14" />获取API Key<ExternalLink :size="13" /></a><button v-if="hasKey(p)" type="button" class="model-clear-key" :disabled="!!busy || readOnly" @click="clearSavedKey(p)"><LoaderCircle v-if="clearingKey === p.id" :size="14" class="spin" /><Trash2 v-else :size="14" />{{ clearingKey === p.id ? '清除中…' : '清除API Key' }}</button></div>
                  <div class="model-name-heading"><label :for="`model-name-${p.id}`">{{ p.id === 'volcengine' && ['asr', 'tts'].includes(category) ? '语音模型资源ID' : '模型名称' }}</label><button type="button" class="model-primary model-fetch-button" :disabled="!!busy || readOnly" @click="fetchModels(p)"><RefreshCw :size="16" :class="{spin:fetchingModels===p.id}"/>获取模型列表</button></div>
                  <ModelNameSelect :id="`model-name-${p.id}`" v-model="drafts[p.id].configs[category].model" :options="options(p)" :disabled="!!busy || readOnly" @update:model-value="modelChanged(p); queueAutosave(p)" />
                  <template v-if="category === 'embedding' && p.id === 'volcengine'"><label :for="`model-protocol-${p.id}`">向量接口协议</label><AppSelect :id="`model-protocol-${p.id}`" v-model="drafts[p.id].configs[category].embeddingProtocol" :disabled="!!busy || readOnly"><option value="multimodal">多模态向量 · /embeddings/multimodal</option><option value="compatible">文本向量 · /embeddings</option></AppSelect><label v-if="drafts[p.id].configs[category].embeddingProtocol === 'multimodal'" :for="`model-instruction-${p.id}`">检索指令</label><textarea v-if="drafts[p.id].configs[category].embeddingProtocol === 'multimodal'" :id="`model-instruction-${p.id}`" v-model="drafts[p.id].configs[category].instruction" rows="3" :disabled="!!busy || readOnly" placeholder="251215及后续模型可填写检索指令" /></template>
                  <template v-if="category === 'embedding'"><label :for="`model-dimensions-${p.id}`">向量维度</label><input :id="`model-dimensions-${p.id}`" v-model.number="drafts[p.id].configs[category].dimensions" type="number" min="1" :disabled="!!busy || readOnly" /></template>
                  <template v-if="category === 'tts'"><div class="model-name-heading"><label :for="`model-voice-${p.id}`">音色<small v-if="p.id === 'volcengine'">须与语音资源ID的版本匹配</small></label><button v-if="p.id === 'dashscope'" type="button" class="model-primary voice-fetch-button" :disabled="!!busy || readOnly || !drafts[p.id].configs.tts.model.trim()" @click="fetchVoices(p)"><RefreshCw :size="16" :class="{spin:fetchingVoices===p.id}"/>获取音色列表</button></div><VoiceNameSelect :id="`model-voice-${p.id}`" v-model="drafts[p.id].configs[category].voice" :voices="voicesFor(p)" :preview-request="p.id==='dashscope' ? (voice,signal)=>previewVoice(p,voice,signal) : undefined" :model="drafts[p.id].configs.tts.model" :placeholder="p.id === 'volcengine' ? 'zh_female_vv_uranus_bigtts' : '音色名称或 ID'" :disabled="!!busy || readOnly" @update:model-value="queueAutosave(p)" /></template>
                  <p v-if="diagnostics[`${p.id}:${category}`]" class="model-test-result" :class="{ failed: !diagnostics[`${p.id}:${category}`].ok }" role="status">{{ diagnostics[`${p.id}:${category}`].ok ? `连接成功 · ${diagnostics[`${p.id}:${category}`].latencyMs}ms · ${diagnostics[`${p.id}:${category}`].checked}` : diagnostics[`${p.id}:${category}`].message }}</p>
                  <div class="model-provider-footer"><p>{{ p.separateSpeechKey ? '方舟密钥供LLM / Embedding共用；语音密钥供ASR / TTS共用。' : 'API Key在所有类别下共享；接口地址和模型按类别保存。' }}</p><div class="model-provider-actions"><button type="button" class="model-secondary" :disabled="!!busy || readOnly" @click="testConnection(p)"><LoaderCircle v-if="testing === `${p.id}:${category}`" :size="16" class="spin" /><Zap v-else :size="18" :stroke-width="1.8" aria-hidden="true" />{{ testing === `${p.id}:${category}` ? '测速中…' : '测速' }}</button><button class="model-primary" :disabled="!!busy || readOnly"><Save :size="16" />保存配置</button></div></div>
                  <p class="model-test-note">测速显示接口响应耗时，不代表模型生成速度；测试不会自动启用。</p>
                </form>
              </article>
              <p v-if="!providers.length" class="model-empty">此类别暂无可用厂商配置。</p>
              <section class="model-json-panel" aria-label="配置JSON预览">
                <header><span><Braces :size="20" />配置JSON</span><small :class="{ pending: dirty.size || busy }">{{ error ? '同步失败' : busy ? '正在同步…' : dirty.size ? '待保存 · 请补全配置' : '已同步' }}</small></header>
                <div class="model-json-toolbar"><label class="model-checkbox"><input v-model="hiddenKeys" type="checkbox" />隐藏API Key</label><span>表单修改实时预览，完整配置自动写入文件</span><button type="button" :aria-pressed="compactJson" @click="compactJson = !compactJson"><Minimize2 :size="15" />{{ compactJson ? '格式化' : '紧凑' }}</button><button type="button" @click="copyJson"><Copy :size="15" />复制</button></div>
                <div class="model-json-code" tabindex="0"><div v-for="(line, index) in jsonLines" :key="index" class="model-json-line"><span aria-hidden="true">{{ index + 1 }}</span><code><span v-for="(token, tokenIndex) in line" :key="tokenIndex" :class="`json-token-${token.kind}`">{{ token.text }}</span></code></div></div>
                <p>.mindpoilt/models.json · 已保存的密钥始终脱敏；取消隐藏仅显示本次填写的密钥。</p>
              </section>
            </template>
          </div>
        </template>
        <footer class="model-config-footer"><span>配置统一保存至.mindpoilt/models.json，保存后无需重启。密钥不保存在浏览器中。</span><button class="model-secondary" :disabled="!!busy" @click="close">完成</button></footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.model-provider-icon.kimi{background:#080808;border-color:#252525;box-shadow:inset 0 0 0 1px #ffffff0a}
.model-clear-key{display:inline-flex;align-items:center;gap:6px;padding:7px 10px;border:1px solid #ecdde6;border-radius:7px;background:#fff;color:#a66b83;font:inherit;font-size:11px}.model-clear-key:hover:not(:disabled){border-color:#e6b9c7;background:#fff4f6;color:#c14e72}
.model-provider-actions{display:flex;gap:9px;flex-shrink:0}.model-test-result{margin:8px 0 0;padding:10px 13px;border-radius:9px;background:#f1faf4;color:#42845b;font-size:12px;line-height:1.6;overflow-wrap:anywhere}.model-test-result.failed{background:#fff2f4;color:#b44465}.model-test-note{margin:0;color:#a198ab;font-size:11px;line-height:1.6}
@media(max-width:700px){.model-provider-footer{flex-wrap:wrap}.model-provider-actions{margin-left:auto}}
.model-config-dialog{--font-body:"MindPilot Latin",'JetBrains Mono',Consolas,'Noto Sans SC','Microsoft YaHei UI',monospace;font-family:var(--font-body);font-variant-numeric:tabular-nums;font-variant-ligatures:none}
.model-json-line code{font-family:inherit;font-weight:400}.json-token-key{color:#111827}.json-token-string{color:#ed3658}.json-token-boolean,.json-token-null{color:#9436ff}.json-token-number{color:#7c3aed}.json-token-punctuation{color:#4b5563}
.model-json-panel{margin-top:26px;border:1px solid #e0dbe6;border-radius:16px;overflow:hidden}.model-json-panel header{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border-bottom:1px solid #eee8f4}.model-json-panel header>span{display:flex;align-items:center;gap:10px;font-weight:600;font-size:14px}.model-json-panel header small{color:#20a45a;font-size:12px}.model-json-panel header small.pending{color:#a68140}.model-json-toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:12px;padding:14px 20px;font-size:11px;color:#a198ab;border-bottom:1px solid #eee8f4}.model-json-toolbar>span{flex:1;min-width:120px}.model-json-toolbar button{display:flex;align-items:center;gap:5px;padding:4px;border:0;background:none;color:#857b90;font-size:12px}.model-json-code{max-height:360px;overflow:auto;background:#fafafa;padding:15px 0;font:14px/1.9 "MindPilot Latin",'JetBrains Mono',Consolas,monospace;tab-size:2;outline:none}.model-json-line{display:flex;min-width:max-content}.model-json-line>span{position:sticky;left:0;width:50px;flex:0 0 50px;text-align:right;padding-right:14px;background:#fafafa;color:#9ca3af;border-right:1px solid #eee8f4;user-select:none}.model-json-line code{white-space:pre;padding:0 16px;color:#1f2937}.model-json-panel>p{margin:0;padding:12px 20px;border-top:1px solid #eee8f4;font-size:11px;line-height:1.7;color:#a198ab;overflow-wrap:anywhere}
.model-config-mask{position:fixed;inset:0;z-index:3000;display:grid;place-items:center;padding:28px;background:#20132c66;backdrop-filter:blur(5px)}
.model-config-dialog{width:min(1120px,100%);height:min(900px,calc(100dvh - 56px));display:flex;flex-direction:column;min-height:0;overflow:hidden;background:#fff;border:1px solid #ede5f4;border-radius:24px;box-shadow:0 24px 90px #21102e38;color:#3f3549;outline:none}
.model-config-header{display:flex;align-items:center;gap:14px;padding:24px 30px 22px;border-bottom:1px solid #eee8f4}.model-config-heading-icon{width:48px;height:48px;display:grid;place-items:center;border-radius:15px;color:#7c3aed;background:#f4efff}.model-config-header h2{margin:0;font-size:21px;font-weight:650}.model-config-header p{margin:6px 0 0;color:#9c91a5;font-size:13px}.model-config-header>.model-icon-button{margin-left:auto}
.model-category-tabs{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;flex-shrink:0;margin:22px 30px 16px;padding:6px;border:1px solid #eee8f5;border-radius:16px;background:#f5f0fe}.model-category-tabs button{min-width:0;display:flex;flex-direction:column;gap:5px;padding:13px 10px;border:1px solid transparent;border-radius:12px;text-align:left;background:transparent;color:#a198ab;font:inherit}.model-category-tabs strong{font-family:var(--font-body);font-size:15px;font-weight:500;letter-spacing:0}.model-category-tabs small{font-size:11px;line-height:1.4}.model-category-tabs .selected{border-color:#b69bff;background:#fff;color:#7c3aed;box-shadow:0 2px 7px #7c3aed08}
.model-config-scroll{flex:1;min-height:0;overflow-y:auto;padding:26px 30px 30px;scrollbar-width:thin;scrollbar-color:#d8cee6 transparent}.model-section-heading{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:20px}.model-section-heading h3{margin:0;font-size:17px;color:#25212b}.model-section-heading p{margin:8px 0 0;font-size:12px;color:#9c94a4}
.model-embedding-note{margin:0 0 18px;color:#9b8baa;font-size:12px;line-height:1.6}
.model-active-banner{display:flex;align-items:center;gap:9px;padding:15px 17px;margin-bottom:18px;border:1px solid #e7e2ec;border-radius:12px;background:#faf9fc;font-size:13px;overflow-wrap:anywhere}.model-active-banner>span:nth-child(2){min-width:0}.model-active-banner small{margin-left:auto;white-space:nowrap;color:#a198ab;font-size:11px}.model-status-dot{width:7px;height:7px;border-radius:50%;background:#b4aaba;flex-shrink:0}.model-status-dot.enabled{background:#20a45a}
.model-provider-card{margin-bottom:14px;border:1px solid #e0dbe6;border-radius:18px;overflow:hidden}.model-provider-card.expanded{border-color:#bca5fb}.model-provider-header{display:flex;align-items:center;gap:14px;padding:19px 20px}.model-provider-expand{display:flex;align-items:center;gap:14px;flex:1;min-width:0;text-align:left;border:0;background:transparent;padding:0;color:inherit}.model-provider-icon{width:45px;height:45px;flex:0 0 45px;display:grid;place-items:center;background:#f6f4ff;border:1px solid #ebe7f2;border-radius:13px;color:#7c3aed}.model-provider-icon img{width:32px;height:32px;object-fit:contain}.model-provider-title{display:flex;flex-direction:column;gap:6px;min-width:0}.model-provider-title strong{font-size:16px;font-weight:550}.model-provider-title small{font-size:12px;color:#a198ab;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.model-saved-badge{padding:3px 7px;border:1px solid #eee9f4;border-radius:5px;color:#a198ab;font-size:10px;white-space:nowrap}.model-enable{display:flex;align-items:center;gap:9px;border:0;background:none;padding:0;color:#a198ab;font-size:12px;white-space:nowrap}.model-enable i{position:relative;width:40px;height:23px;border-radius:14px;background:#eae9ed;transition:background .2s}.model-enable i:before{position:absolute;left:3px;top:3px;width:17px;height:17px;border-radius:50%;background:#fff;box-shadow:0 1px 3px #21102e18;content:'';transition:transform .2s}.model-enable i.on{background:#7c3aed}.model-enable i.on:before{transform:translateX(17px)}.model-chevron svg{transition:transform .2s}.model-chevron svg.rotated{transform:rotate(180deg)}
.model-provider-fields{display:flex;flex-direction:column;gap:11px;padding:23px 24px;background:#fcfbfd;border-top:1px solid #eee8f3}.model-provider-fields>label,.model-name-heading label{font-size:13px;color:#685e73}.model-provider-fields>label:not(:first-child){margin-top:8px}.model-provider-fields label small{margin-left:5px;color:#aaa0b1;font-size:11px}select,textarea,input:not([type=checkbox]){min-width:0;width:100%;height:43px;padding:10px 13px;border:1px solid #ddd6e5;border-radius:10px;background:#fff;color:#302738;font:inherit;font-size:13px;outline:none}input:focus,select:focus,textarea:focus{border-color:#a78bfa;box-shadow:0 0 0 2px #7c3aed0b}.model-provider-note{margin:0 0 6px;color:#9b8baa;font-size:12px;line-height:1.6}textarea{height:auto;min-height:80px;resize:vertical}input::placeholder{color:#b1a6ba}.model-key-input{position:relative}.model-key-input input{padding-right:45px}.model-key-input button{position:absolute;right:5px;top:4px}.model-key-tools{display:flex;align-items:center;flex-wrap:wrap;gap:15px;margin:0 0 10px}.model-key-tools a{display:flex;align-items:center;gap:5px;padding:7px 9px;color:#8b5cf6;background:#f3effb;border:1px solid #eee7f8;border-radius:7px;text-decoration:none;font-size:11px}.model-checkbox{display:flex;align-items:center;gap:6px;font-size:11px;color:#a096a8}.model-checkbox input{accent-color:#7c3aed}.model-name-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.model-provider-footer{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-top:8px}.model-provider-footer p{margin:0;font-size:11px;line-height:1.5;color:#a096a8}.model-primary,.model-secondary{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:9px 13px;min-height:35px;border-radius:9px;white-space:nowrap;font:inherit;font-size:12px}.model-primary{border:1px solid #7c3aed;background:#7c3aed;color:#fff}.model-secondary{border:1px solid #e1dbe8;background:#fff;color:#857b90}.model-icon-button{display:grid;place-items:center;flex-shrink:0;width:34px;height:34px;padding:0;border:0;border-radius:9px;background:none;color:#a198ab}.model-icon-button:hover{background:#f4effc;color:#7c3aed}button{cursor:pointer}button:disabled{opacity:.55;cursor:default}button:focus-visible,a:focus-visible{outline:2px solid #a78bfa;outline-offset:3px}.model-primary:hover:not(:disabled){background:#6d28d9}.model-secondary:hover:not(:disabled){border-color:#cdbdf1;color:#7c3aed}
.model-feedback{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 15px;border-radius:10px;margin:0 0 18px;font-size:12px;line-height:1.6}.model-feedback.error{background:#fff2f4;color:#b44465}.model-feedback.success{background:#f1faf4;color:#42845b}.model-feedback button{display:flex;align-items:center;gap:5px;background:none;border:0;color:inherit}.model-add-provider{display:flex;align-items:center;gap:10px;padding:14px;margin-bottom:18px;border:1px solid #e5dcf3;border-radius:12px;background:#faf7ff}.model-add-provider label{white-space:nowrap;font-size:12px;color:#847390}.model-add-provider input{flex:1}.model-empty{padding:40px;text-align:center;color:#a198ab}.model-config-loading{flex:1;display:flex;align-items:center;justify-content:center;gap:10px;color:#a198ab;font-size:13px}.model-config-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:15px 30px;border-top:1px solid #eee8f4;background:#fdfbff}.model-config-footer>span{font-size:11px;line-height:1.6;color:#a095ad}.spin{animation:model-spin 1s linear infinite}@keyframes model-spin{to{transform:rotate(360deg)}}
@media(max-width:700px){.model-config-mask{padding:12px}.model-config-dialog{height:calc(100dvh - 24px);border-radius:18px}.model-config-header{padding:18px;gap:10px}.model-config-header h2{font-size:18px}.model-config-header p{font-size:11px}.model-category-tabs{grid-template-columns:repeat(3,minmax(0,1fr));margin:16px 16px 12px}.model-category-tabs button{padding:10px}.model-config-scroll{padding:18px 16px}.model-config-footer{padding:12px 16px}.model-section-heading p{font-size:11px}.model-provider-header{padding:16px 12px;gap:6px}.model-provider-expand{gap:10px}.model-provider-icon{width:36px;height:36px;flex-basis:36px}.model-provider-icon img{width:26px;height:26px}.model-provider-title strong{font-size:14px}.model-provider-title small{font-size:11px}.model-saved-badge{display:none}.model-enable span{display:none}.model-active-banner{font-size:12px}.model-active-banner small{display:none}.model-provider-fields{padding:18px 14px}.model-provider-footer{align-items:flex-end}.model-add-provider{flex-wrap:wrap}.model-add-provider label{width:100%}.model-add-provider input{flex-basis:100%}}
.model-primary.voice-fetch-button{background:#eee5fc;border-color:#d9c5f5;color:#6d28b5;box-shadow:0 3px 10px #7c3aed0b;transition:background .18s,border-color .18s}.model-primary.voice-fetch-button:hover:not(:disabled){background:#e2d3f7;border-color:#c3a1e9;color:#5b21a0}
</style>
