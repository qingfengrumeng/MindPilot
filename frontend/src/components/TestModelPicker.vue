<script setup>
import AppSelect from '@/components/AppSelect.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, Globe, RefreshCw, X } from 'lucide-vue-next'
import { modelsApi } from '@/api/models'
import ModelNameSelect from './ModelNameSelect.vue'
import deepseek from '@/assets/providers/deepseek.svg'
import kimi from '@/assets/providers/kimi.svg'
import qwen from '@/assets/providers/qwen.svg'
import doubao from '@/assets/providers/doubao-color.svg'
import glm from '@/assets/providers/zhipu-color.svg'

const props = defineProps({ state: Object, category: { type: String, default: 'text' }, value: Object })
const emit = defineEmits(['close', 'select'])
const icons = { deepseek, kimi, qwen, doubao, glm }
const root = ref(null), providerId = ref(props.value?.providerId || ''), model = ref(props.value?.model || '')
const dimensions = ref(props.value?.dimensions || ''), options = ref([]), fetching = ref(false), error = ref('')
const embeddingProtocol = ref(props.value?.embeddingProtocol || props.state?.providers?.find(p => p.id === props.value?.providerId)?.configs?.embedding?.embeddingProtocol || 'compatible')
const providers = computed(() => (props.state?.providers || []).filter(p => p.hasKey && p.configs?.[props.category]?.baseUrl))
const provider = computed(() => providers.value.find(p => p.id === providerId.value))
const title = computed(() => ({ text: 'LLM', embedding: 'Embedding', reranker: 'Rerank' }[props.category] || props.category))
let disposed = false, version = 0
const modelLists=new Map()
function listKey(){return `${providerId.value}:${props.category}`}
const previousFocus = document.activeElement
function change() {
  version++; options.value = modelLists.get(listKey())||[]; fetching.value = false; error.value = ''
  model.value = provider.value?.configs?.[props.category]?.model || ''
  dimensions.value = provider.value?.configs?.[props.category]?.dimensions || ''
  embeddingProtocol.value = provider.value?.configs?.[props.category]?.embeddingProtocol || 'compatible'
}
async function fetchModels() {
  if (!provider.value || fetching.value) return
  if(modelLists.has(listKey())){options.value=modelLists.get(listKey());return}
  const cacheKey=listKey()
  const current = ++version
  fetching.value = true; options.value = []; error.value = ''
  try {
    const response = await modelsApi.discover(providerId.value, props.category, { baseUrl: provider.value.configs[props.category].baseUrl })
    if (!disposed && current === version) {
      options.value = [...new Set(response.models || [])].sort((a, b) => a.localeCompare(b))
      modelLists.set(cacheKey,options.value)
      if (!options.value.length) error.value = '接口未返回模型，可手动输入。'
    }
  } catch (cause) { if (!disposed && current === version) error.value = cause.message }
  finally { if (!disposed && current === version) fetching.value = false }
}
function select() {
  if (!provider.value || !model.value.trim()) { error.value = '请选择厂商并填写模型名称'; return }
  const selection = { providerId: providerId.value, model: model.value.trim() }
  if (props.category === 'embedding') {
    const count = Number(dimensions.value)
    if (!Number.isInteger(count) || count < 1 || count > 65536) { error.value = '请填写有效的向量维度'; return }
    selection.dimensions = count
    selection.embeddingProtocol = embeddingProtocol.value
  }
  emit('select', selection)
}
function keys(event) {
  if (event.key === 'Escape' && !event.defaultPrevented) { event.stopPropagation(); emit('close') }
  if (event.key === 'Tab') {
    const items = [...root.value.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')].filter(el => el.getClientRects().length)
    if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); event.stopPropagation(); items.at(-1)?.focus() }
    if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); event.stopPropagation(); items[0]?.focus() }
  }
}
onMounted(async () => {
  if (!providerId.value && providers.value.length) { providerId.value = providers.value[0].id; change() }
  await nextTick(); root.value?.querySelector('select')?.focus()
})
onBeforeUnmount(() => { disposed = true; version++; if (previousFocus?.isConnected) previousFocus.focus() })
</script>

<template>
  <div class="trial-picker-mask" @click.self="emit('close')" @keydown="keys">
    <section ref="root" class="trial-picker" role="dialog" aria-modal="true" aria-labelledby="trial-picker-title">
      <header><div><small>测试模型</small><h3 id="trial-picker-title">选择 {{ title }} 型号</h3></div><button type="button" aria-label="关闭模型选择" @click="emit('close')"><X :size="21" /></button></header>
      <p class="trial-note">仅显示已保存密钥和对应接口的厂商。测试选择不会修改或启用模型配置。</p>
      <label>模型厂商<AppSelect v-model="providerId" @change="change"><option value="">选择厂商</option><option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option></AppSelect></label>
      <div v-if="provider" class="trial-provider"><span :class="{ kimi: provider.icon === 'kimi' }"><img v-if="icons[provider.icon]" :src="icons[provider.icon]" alt="" /><Globe v-else :size="23" /></span><div><strong>{{ provider.name }}</strong><small>共用已保存的 API Key</small></div></div>
      <div class="trial-model-label"><label for="trial-model-name">模型名称</label><button type="button" class="trial-fetch" :disabled="!provider || fetching" @click="fetchModels"><RefreshCw :size="16" :class="{spin:fetching}"/>获取模型列表</button></div>
      <ModelNameSelect id="trial-model-name" v-model="model" :options="options" :disabled="!provider" />
      <small class="trial-note">{{ options.length ? `本次获取 ${options.length} 个模型，关闭后列表清空。` : '可直接输入型号；只有点击获取后才请求厂商模型列表。' }}</small>
      <label v-if="category === 'embedding'">向量维度<input v-model="dimensions" type="number" min="1" max="65536" placeholder="与所选模型一致的维度" /></label>
      <label v-if="category === 'embedding'">向量接口协议<AppSelect v-model="embeddingProtocol"><option value="compatible">OpenAI 兼容 · 文本向量</option><option v-if="provider?.id === 'volcengine' || provider?.icon === 'doubao'" value="multimodal">方舟多模态向量</option></AppSelect></label>
      <p v-if="!providers.length" class="trial-error">该类别还没有可测试的厂商，请先在模型配置中保存接口地址和密钥。</p><p v-if="error" class="trial-error" role="alert">{{ error }}</p>
      <footer><button type="button" @click="emit('close')">取消</button><button class="trial-confirm" type="button" :disabled="!provider" @click="select"><Check :size="17" />使用此模型</button></footer>
    </section>
  </div>
</template>

<style scoped>
.trial-picker-mask{position:absolute;inset:0;background:#24133942;z-index:30;display:flex;align-items:center;justify-content:center;padding:24px;border-radius:inherit}.trial-picker{width:640px;max-width:100%;max-height:90%;overflow:auto;border:1px solid #e8e1f2;border-radius:24px;background:white;padding:28px;box-shadow:0 24px 90px #2d154a33;color:#3b3049}.trial-picker header,.trial-picker footer,.trial-model-label{display:flex;align-items:center;justify-content:space-between;gap:12px}.trial-picker h3{font-size:23px;margin:6px 0 0}.trial-picker header small{color:#8b6aaf}.trial-picker button{display:inline-flex;align-items:center;gap:7px;border:1px solid #e6deef;border-radius:12px;background:white;color:#705389;padding:10px 14px;cursor:pointer}.trial-picker button:disabled{opacity:.45;cursor:not-allowed}.trial-picker header button{border:0;padding:8px}.trial-picker label{display:block;font-size:14px;margin:20px 0 10px}.trial-picker select,.trial-picker input{display:block;width:100%;padding:14px;margin-top:10px;border:1px solid #ded3eb;border-radius:12px;background:white;color:inherit;font:inherit;box-sizing:border-box}.trial-note{display:block;color:#90869f;font-size:12px;line-height:1.8;margin:12px 0}.trial-provider{display:flex;align-items:center;gap:12px;padding:16px;margin-top:12px;background:#faf8fd;border-radius:14px}.trial-provider span{display:grid;place-items:center;width:42px;height:42px;background:#f0e9fa;border-radius:12px}.trial-provider span.kimi{background:#050505}.trial-provider img{width:30px;height:30px;object-fit:contain}.trial-provider small{display:block;color:#94899f;font-size:12px;margin-top:4px}.trial-model-label label{margin:18px 0}.trial-error{color:#b4445d;font-size:13px;line-height:1.7}.trial-picker footer{justify-content:flex-end;margin-top:26px}.trial-picker .trial-confirm{background:#7c3aed;color:white;border-color:#7c3aed}@media(max-width:600px){.trial-picker-mask{padding:12px}.trial-picker{padding:20px}.trial-model-label{flex-wrap:wrap}}
.trial-picker .trial-fetch{background:#7c3aed;color:#fff;border-color:#7c3aed;box-shadow:0 4px 12px #7c3aed20}.trial-picker .trial-fetch:hover:not(:disabled){background:#6d28d9}
</style>
