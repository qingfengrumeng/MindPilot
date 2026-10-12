<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, Copy, FlaskConical, Globe, LoaderCircle, Play, Plus, RefreshCw, Save, Square, Trash2, X } from 'lucide-vue-next'
import { modelsApi } from '@/api/models'
import TestModelPicker from './TestModelPicker.vue'
import RagEvaluation from './RagEvaluation.vue'
import EvaluationReportHistory from './EvaluationReportHistory.vue'
import {evaluationReportsApi} from '@/api/evaluations'
import deepseekIcon from '@/assets/providers/deepseek.svg'
import kimiIcon from '@/assets/providers/kimi.svg'
import qwenIcon from '@/assets/providers/qwen.svg'
import doubaoIcon from '@/assets/providers/doubao-color.svg'
import glmIcon from '@/assets/providers/zhipu-color.svg'

const emit = defineEmits(['close', 'configure'])
const icons = { deepseek: deepseekIcon, kimi: kimiIcon, qwen: qwenIcon, doubao: doubaoIcon, glm: glmIcon }
const dialog = ref(null), state = ref(null), loading = ref(true), error = ref('')
const prompt = ref(''), systemPrompt = ref(''), maxTokens = ref(2048), temperature = ref('')
const cards = ref([]), copiedId = ref('')
const savingReport=ref(false),historyOpen=ref(false),savedNotice=ref('')
async function saveResults(){
  if(running.value||staleResults.value||savingReport.value)return
  savingReport.value=true;error.value=''
  try{await evaluationReportsApi.save({kind:'llm',title:`LLM对比 · ${cards.value.length}个型号`,result:{prompt:prompt.value,systemPrompt:systemPrompt.value,maxTokens:maxTokens.value,temperature:temperature.value,cards:JSON.parse(JSON.stringify(cards.value))}});savedNotice.value='测试结果已永久保存'}catch(e){error.value=e.message}finally{savingReport.value=false}
}
function restoreResults(value){prompt.value=value.prompt;systemPrompt.value=value.systemPrompt;maxTokens.value=value.maxTokens;temperature.value=value.temperature;cards.value=value.cards.map(card=>({...card,id:`comparison-${++nextId}`,inputSignature:inputSignature()}));tab.value='llm'}
const tab = ref('llm'), picker = ref(null), activeCard = ref(''), concurrency = ref(3), batchRunning = ref(false), ragRunning = ref(false)
const controllers = new Map()
const previousFocus = document.activeElement
const previousOverflow = document.body.style.overflow
const timers = new Set()
let disposed = false, nextId = 0, batchVersion = 0
const providers = computed(() => (state.value?.providers || []).filter(p => p.defaults?.text || p.configs?.text || p.custom))
const readyProviders = computed(() => providers.value.filter(ready))
const readOnly = computed(() => state.value?.editable === false)
const running = computed(() => batchRunning.value || cards.value.some(card => card.status === 'running'))
const finishedCount = computed(() => cards.value.filter(card => ['done', 'error', 'cancelled'].includes(card.status)).length)
const staleResults = computed(() => cards.value.some(card => card.inputSignature && card.inputSignature !== inputSignature()))
const labels = { idle: '待测试', running: '生成中', done: '已完成', error: '测试失败', cancelled: '已停止' }

function ready(p) { return !!(p.hasKey && p.configs?.text?.baseUrl) }
function provider(card) { return providers.value.find(p => p.id === card.providerId) }
function inputSignature() { return JSON.stringify([prompt.value.trim(), systemPrompt.value.trim(), Number(maxTokens.value), temperature.value === '' ? null : Number(temperature.value)]) }
function newCard(providerId = '') {
  const p = providers.value.find(p => p.id === providerId)
  return { id: `comparison-${++nextId}`, providerId, model: p?.configs?.text?.model || '', status: 'idle', answer: '', reasoning: '',
    failure: '', metrics: null, inputSignature: '', resultModel: '', resultProvider: '' }
}
function clearResult(card) {
  card.status = 'idle'; card.answer = ''; card.reasoning = ''; card.failure = ''; card.metrics = null
  card.inputSignature = ''; card.resultModel = ''; card.resultProvider = ''
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const result = await modelsApi.list()
    if (disposed) return
    state.value = result
    const readyIds = readyProviders.value.map(p => p.id)
    const active = readyIds.includes(result.active?.text) ? result.active.text : readyIds[0]
    cards.value = [newCard(active), newCard(readyIds.find(id => id !== active))]
  } catch (cause) { if (!disposed) error.value = cause.message || '模型配置加载失败' }
  finally { if (!disposed) loading.value = false }
}
function addCard() { if (!running.value && cards.value.length < 12) picker.value = { category: 'text', card: null } }
function selectModel(selection) {
  const card = picker.value?.card || newCard()
  Object.assign(card, selection); clearResult(card)
  if (!picker.value?.card) cards.value.push(card)
  picker.value = null; activeCard.value = card.id
}
function setCount(event) {
  if (running.value) return
  const count = Math.max(1, Math.min(12, Math.floor(Number(event.target.value) || 1)))
  while (cards.value.length < count) cards.value.push(newCard())
  cards.value = cards.value.slice(0, count)
  event.target.value = count
}
function focusCard(card) {
  activeCard.value = card.id
  document.getElementById(card.id)?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
}
function removeCard(card) {
  if (running.value || cards.value.length <= 1) return
  cards.value = cards.value.filter(item => item.id !== card.id)
}
function payload(card) {
  const p = provider(card)
  if (!p || !ready(p)) throw new Error('请为每个测试位选择已配置的厂商')
  if (!card.model.trim()) throw new Error('请填写模型名称，或获取模型列表后选择')
  if (!prompt.value.trim()) throw new Error('请输入用于对比的同一个问题')
  if (prompt.value.length > 32000 || systemPrompt.value.length > 8000) throw new Error('测试输入过长，请精简后重试')
  const limit = Number(maxTokens.value), temp = temperature.value === '' ? null : Number(temperature.value)
  if (!Number.isInteger(limit) || limit < 16 || limit > 16384) throw new Error('最大输出 token 应为 16—16384 的整数')
  if (temp !== null && (!Number.isFinite(temp) || temp < 0 || temp > 2)) throw new Error('温度应在 0—2 之间，留空使用厂商默认值')
  return { providerId: p.id, model: card.model.trim(), prompt: prompt.value.trim(),
    systemPrompt: systemPrompt.value.trim(), maxTokens: limit, temperature: temp }
}
async function runCard(card, request) {
  const controller = new AbortController()
  controllers.set(card.id, controller)
  clearResult(card); card.status = 'running'; card.inputSignature = inputSignature()
  card.resultModel = request.model; card.resultProvider = provider(card)?.name || request.providerId
  try {
    await modelsApi.compare(request, controller.signal, event => {
      if (disposed || controller.signal.aborted || controllers.get(card.id) !== controller) return
      if (event.type === 'delta') card.answer += event.text
      else if (event.type === 'reasoning') card.reasoning += event.text
      else if (event.type === 'done') { card.metrics = event; card.status = 'done' }
      else if (event.type === 'error') { card.failure = event.message; card.status = 'error' }
    })
  } catch (cause) {
    if (disposed || controllers.get(card.id) !== controller) return
    if (controller.signal.aborted) card.status = 'cancelled'
    else { card.status = 'error'; card.failure = cause.message || '模型测试失败，请重试' }
  } finally {
    if (controllers.get(card.id) === controller) controllers.delete(card.id)
  }
}
async function startComparison() {
  if (running.value || readOnly.value) return
  const version = ++batchVersion
  error.value = ''
  try {
    const requests = cards.value.map(payload)
    if (new Set(requests.map(item => `${item.providerId}:${item.model}`)).size !== requests.length) throw new Error('请选择不同的模型；同一厂商可以填写不同模型名称')
    batchRunning.value = true
    let cursor = 0
    const slots = [...cards.value]
    await Promise.allSettled(Array.from({ length: Math.min(Math.max(1, Number(concurrency.value) || 1), 6, slots.length) }, async () => {
      while (!disposed && batchRunning.value && version === batchVersion && cursor < slots.length) {
        const index = cursor++
        await runCard(slots[index], requests[index])
      }
    }))
  } catch (cause) { error.value = cause.message }
  finally { if (version === batchVersion) batchRunning.value = false }
}
function retryCard(card) {
  if (running.value || readOnly.value) return
  error.value = ''
  try { return runCard(card, payload(card)) } catch (cause) { error.value = cause.message }
}
function stop(card) {
  if (card.status !== 'running') return
  controllers.get(card.id)?.abort()
  card.status = 'cancelled'
}
function stopAll() { batchVersion++; batchRunning.value = false; for (const card of cards.value) stop(card) }
function close() { stopAll(); emit('close') }
async function copy(card) {
  try {
    await navigator.clipboard.writeText(card.answer)
    if (disposed) return
    copiedId.value = card.id
    const timer = setTimeout(() => { timers.delete(timer); copiedId.value = '' }, 1800)
    timers.add(timer)
  } catch { error.value = '复制失败，请手动选择回答内容复制' }
}
function duration(ms) {
  if (ms === null || ms === undefined) return '—'
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`
}
function number(value) { return value === null || value === undefined ? '—' : value.toLocaleString('zh-CN') }
function keydown(event) {
  if (event.defaultPrevented) return
  if (event.key === 'Escape') { event.preventDefault(); if (picker.value) picker.value = null; else close(); return }
  if (event.target?.closest('.model-options-panel')) return
  if (event.key !== 'Tab') return
  const items = [...(dialog.value?.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary') || [])].filter(el => el.getClientRects().length)
  const first = items[0], last = items.at(-1)
  if (!items.includes(document.activeElement)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus() }
  else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onMounted(async () => {
  document.body.style.overflow = 'hidden'
  document.addEventListener('keydown', keydown)
  await nextTick(); dialog.value?.focus(); load()
})
onBeforeUnmount(() => {
  disposed = true
  batchVersion++; batchRunning.value = false
  for (const controller of controllers.values()) controller.abort()
  for (const timer of timers) clearTimeout(timer)
  document.removeEventListener('keydown', keydown)
  document.body.style.overflow = previousOverflow
  if (previousFocus?.isConnected) previousFocus.focus()
})
</script>

<template><EvaluationReportHistory v-if="historyOpen" kind="llm" @close="historyOpen=false" @open="restoreResults"/>
  <Teleport to="body">
    <div class="comparison-mask" @click.self="close">
      <section ref="dialog" class="comparison-dialog" role="dialog" aria-modal="true" aria-labelledby="comparison-title" tabindex="-1">
        <header class="comparison-header">
          <span class="comparison-emblem"><FlaskConical :size="24" /></span>
          <div><h2 id="comparison-title">模型对比测试</h2><p>对比模型表现，持续优化检索与回答质量</p></div>
          <span class="comparison-type">{{ tab === 'llm' ? 'LLM · 性能对比' : 'RAG · 检索与回答' }}</span>
          <button class="comparison-icon" type="button" aria-label="关闭模型对比测试" @click="close"><X :size="22" /></button>
        </header>
        <nav class="evaluation-tabs" aria-label="测试类型"><button type="button" :class="{ active: tab === 'llm' }" :disabled="running || ragRunning" @click="tab = 'llm'">LLM 性能对比</button><button type="button" :class="{ active: tab === 'rag' }" :disabled="running || ragRunning" @click="tab = 'rag'">RAG 评测</button></nav>
        <div v-if="loading" class="comparison-loading" role="status"><LoaderCircle :size="22" class="spin" />正在读取已配置模型…</div>
        <div v-else-if="!state" class="comparison-loading"><p role="alert">{{ error }}</p><button class="comparison-secondary" type="button" @click="load">重新加载</button></div>
        <RagEvaluation v-else-if="tab === 'rag'" :state="state" @busy="ragRunning = $event" />
        <div v-else class="comparison-workspace">
          <aside class="comparison-controls">
            <div class="comparison-control-scroll">
              <div class="comparison-step"><span>01</span><h3>统一测试输入</h3></div>
              <div class="comparison-parameters"><label class="comparison-field">测试模型数<input :value="cards.length" type="number" min="1" max="12" :disabled="running || readOnly" @change="setCount" /></label><label class="comparison-field">同时请求数<input v-model="concurrency" type="number" min="1" max="6" :disabled="running || readOnly" /></label></div>
              <label class="comparison-field" for="comparison-prompt">测试问题<textarea id="comparison-prompt" v-model="prompt" :disabled="running || readOnly" maxlength="32000" placeholder="输入一个问题，所有模型将使用相同的输入…" /></label>
              <details class="comparison-settings">
                <summary>请求参数<span>可选</span></summary>
                <label class="comparison-field" for="comparison-system">系统提示词<textarea id="comparison-system" v-model="systemPrompt" :disabled="running || readOnly" maxlength="8000" placeholder="留空时不添加系统提示词" /></label>
                <div class="comparison-parameters">
                  <label class="comparison-field" for="comparison-max-tokens">最大输出 token<input id="comparison-max-tokens" v-model="maxTokens" type="number" min="16" max="16384" step="1" :disabled="running || readOnly" /></label>
                  <label class="comparison-field" for="comparison-temperature">温度<input id="comparison-temperature" v-model="temperature" type="number" min="0" max="2" step="0.1" placeholder="厂商默认" :disabled="running || readOnly" /></label>
                </div>
                <p>不同模型对参数的支持可能不同，温度留空时使用厂商默认值。</p>
              </details>
              <div class="comparison-tip"><FlaskConical :size="17" /><p>支持同一厂商的不同模型，也支持跨厂商对比。使用已保存的密钥，测试不会切换正在使用的模型。</p></div>
              <p v-if="readOnly" class="comparison-error" role="status">共享模型测试仅主账户可使用，请切换到首次注册的账户。</p>
              <div v-else-if="!readyProviders.length" class="comparison-empty-config"><p>还没有可测试的文本模型，请先配置接口地址和 API Key。</p><button class="comparison-secondary" type="button" @click="emit('configure')">去配置模型</button></div>
              <button v-else type="button" class="comparison-config-link" :disabled="running" @click="emit('configure')">管理模型配置</button>
              <p v-if="error" class="comparison-error" role="alert">{{ error }}</p>
            </div>
            <div class="comparison-start">
              <button v-if="running" type="button" class="comparison-primary stopping" @click="stopAll"><Square :size="17" />停止测试</button>
              <button v-else type="button" class="comparison-primary" :disabled="readOnly || !readyProviders.length" @click="startComparison"><Play :size="17" />{{ finishedCount ? '重新对比' : '开始对比' }}</button>
              <div class="comparison-result-actions"><button class="comparison-secondary" :disabled="running||savingReport||!finishedCount||staleResults" @click="saveResults"><Save :size="16"/>保存测试结果</button><button class="comparison-secondary" :disabled="running" @click="historyOpen=true">已保存结果</button></div>
              <span v-if="savedNotice" class="comparison-saved-notice" role="status">{{savedNotice}}</span>
              <small>测试会实际调用所选模型，费用按厂商规则计费。</small>
            </div>
          </aside>
          <main class="comparison-board">
            <div class="comparison-board-heading"><div><div class="comparison-step"><span>02</span><h3>选择模型并对比</h3></div><p>按具体型号对比，同一厂商可添加多个模型</p></div><button class="comparison-secondary" type="button" :disabled="running || cards.length >= 12 || readOnly" @click="addCard"><Plus :size="16" />添加测试模型</button></div>
            <nav class="comparison-model-tabs" aria-label="测试模型型号"><button v-for="(card, index) in cards" :key="card.id" type="button" :class="{ active: activeCard === card.id }" @click="focusCard(card)">{{ card.model || `待选模型 ${index + 1}` }}</button></nav>
            <p v-if="staleResults" class="comparison-stale" role="status">输入已修改，下方保留的是上次测试结果；重新运行后更新。</p>
            <div class="comparison-grid">
              <article v-for="(card, index) in cards" :id="card.id" :key="card.id" class="comparison-card" :class="{ 'is-running': card.status === 'running', 'is-selected': activeCard === card.id }">
                <div class="comparison-card-top"><strong>{{ card.model || `模型 ${String(index + 1).padStart(2, '0')}` }}</strong><span class="comparison-status" :class="card.status" role="status"><LoaderCircle v-if="card.status === 'running'" :size="12" class="spin" />{{ labels[card.status] }}</span><button class="comparison-icon" type="button" :disabled="running || cards.length <= 1" aria-label="移除该模型" @click="removeCard(card)"><Trash2 :size="15" /></button></div>
                <div class="comparison-card-selection">
                  <div class="comparison-provider"><span :class="{ kimi: provider(card)?.icon === 'kimi' }"><img v-if="icons[provider(card)?.icon]" :src="icons[provider(card).icon]" alt="" /><Globe v-else :size="21" /></span><strong>{{ provider(card)?.name || '尚未选择厂商' }}</strong><button class="comparison-secondary" type="button" :disabled="running || readOnly" @click="picker = { category: 'text', card }">{{ card.providerId ? '更换型号' : '选择模型' }}</button></div>
                  <small class="comparison-list-note">{{ card.model || '点击选择模型，支持手动填写或实时获取型号。' }}</small>
                </div>
                <dl class="comparison-metrics"><div><dt>首字耗时</dt><dd>{{ duration(card.metrics?.firstTokenMs) }}</dd></div><div><dt>总耗时</dt><dd>{{ duration(card.metrics?.latencyMs) }}</dd></div><div><dt>输出 token</dt><dd>{{ number(card.metrics?.tokens?.output) }}</dd></div><div><dt>输出速率</dt><dd>{{ card.metrics?.tokensPerSecond == null ? '—' : `${card.metrics.tokensPerSecond} t/s` }}</dd></div></dl>
                <div class="comparison-answer">
                  <details v-if="card.reasoning" class="comparison-reasoning"><summary>思考过程</summary><pre>{{ card.reasoning }}</pre></details>
                  <pre v-if="card.answer" class="comparison-answer-text">{{ card.answer }}</pre>
                  <p v-if="card.failure" class="comparison-error" role="alert">{{ card.failure }}</p>
                  <p v-if="card.metrics?.finishReason === 'length'" class="comparison-discovery-error">已达到最大输出 token，可提高上限后重试。</p>
                  <div v-if="!card.answer && !card.reasoning && !card.failure" class="comparison-answer-empty"><LoaderCircle v-if="card.status === 'running'" :size="24" class="spin" /><FlaskConical v-else :size="28" /><p>{{ card.status === 'running' ? '等待模型回答…' : card.status === 'cancelled' ? '测试已停止' : '回答将在这里显示' }}</p><small v-if="card.status === 'idle'">选择模型后开始测试</small></div>
                </div>
                <footer class="comparison-card-footer"><span :title="card.resultModel">{{ card.resultModel || '尚未测试' }}<small v-if="card.metrics">输入 {{ number(card.metrics.tokens?.input) }} token</small></span><button v-if="card.status === 'running'" class="comparison-secondary" type="button" @click="stop(card)"><Square :size="13" />停止</button><button v-else class="comparison-secondary" type="button" :disabled="running || readOnly || !card.providerId" @click="retryCard(card)"><RefreshCw :size="13" />{{ card.status === 'idle' ? '单独测试' : '重试' }}</button><button class="comparison-icon" type="button" :disabled="!card.answer" aria-label="复制模型回答" @click="copy(card)"><Check v-if="copiedId === card.id" :size="16" /><Copy v-else :size="16" /></button></footer>
              </article>
            </div>
            <p class="comparison-metric-note">耗时由服务端观测；首字指回答首个文本片段。速率按厂商返回的输出 token ÷ 总耗时计算。未返回用量时显示“—”。</p>
          </main>
        </div>
        <TestModelPicker v-if="picker" :state="state" :category="picker.category" :value="picker.card" @close="picker = null" @select="selectModel" />
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.comparison-mask{position:fixed;inset:0;z-index:3000;display:grid;place-items:center;padding:24px;background:#21102e55;backdrop-filter:blur(5px)}
.comparison-dialog{display:flex;flex-direction:column;width:min(1480px,100%);height:min(980px,calc(100dvh - 48px));min-height:0;overflow:hidden;border:1px solid #ece5f5;border-radius:24px;background:#fff;box-shadow:0 24px 90px #21102e38;color:#3f3549;font-family:var(--font-body);font-variant-numeric:tabular-nums;outline:none}
.comparison-header{display:flex;align-items:center;gap:14px;flex-shrink:0;padding:23px 28px;border-bottom:1px solid #eee8f5}.comparison-emblem{display:grid;place-items:center;flex-shrink:0;width:48px;height:48px;border-radius:15px;background:#f3edff;color:#7c3aed}.comparison-header h2{margin:0;font-size:21px;color:#322442}.comparison-header p{margin:6px 0 0;font-size:12px;color:#9a8aa9}.comparison-type{margin-left:auto;padding:7px 12px;border:1px solid #e6dcf7;border-radius:20px;background:#faf7ff;color:#8b6baa;font-size:11px;white-space:nowrap}
button,input,textarea,select{font:inherit}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}button:focus-visible,summary:focus-visible{outline:2px solid #a78bfa;outline-offset:3px}.comparison-icon{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;padding:0;border:0;border-radius:9px;background:transparent;color:#9b8aaa;flex-shrink:0}.comparison-icon:hover:not(:disabled){background:#f3edff;color:#7c3aed}.comparison-primary,.comparison-secondary{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid #e1d6ee;border-radius:11px;font-size:12px}.comparison-secondary{padding:9px 12px;background:#fff;color:#7a658e}.comparison-secondary:hover:not(:disabled){border-color:#c7b2eb;background:#faf7ff;color:#7c3aed}.comparison-primary{width:100%;padding:13px;background:#7c3aed;border-color:#7c3aed;color:#fff;font-size:14px;font-weight:600}.comparison-primary:hover:not(:disabled){background:#6d28d9}.comparison-primary.stopping{background:#f5efff;color:#7c3aed;border-color:#d9c7f3}
.comparison-loading{display:flex;flex:1;flex-direction:column;align-items:center;justify-content:center;gap:15px;color:#9a8aa9;font-size:14px}.comparison-workspace{display:grid;grid-template-columns:300px minmax(0,1fr);flex:1;min-height:0}.comparison-controls{display:flex;flex-direction:column;min-height:0;border-right:1px solid #eee8f5;background:#fdfbff}.comparison-control-scroll{flex:1;min-height:0;overflow:auto;padding:25px 22px}.comparison-step{display:flex;align-items:center;gap:9px}.comparison-step>span{display:grid;place-items:center;width:26px;height:26px;border:1px solid #e8dcf8;border-radius:8px;background:#f4edff;color:#9466cc;font-size:11px}.comparison-step h3{margin:0;color:#5b4372;font-size:14px;font-weight:600}.comparison-field{display:flex;flex-direction:column;gap:9px;margin-top:23px;color:#7b6a8d;font-size:12px}.comparison-field textarea,.comparison-field input{width:100%;padding:12px;border:1px solid #e3d9ef;border-radius:11px;background:#fff;color:#41324f;outline:none;font-size:13px;line-height:1.8}.comparison-field textarea{min-height:190px;resize:vertical}.comparison-field textarea::placeholder,.comparison-field input::placeholder{color:#b1a4bd}.comparison-field textarea:focus,.comparison-field input:focus{border-color:#b599ed;box-shadow:0 0 0 3px #7c3aed08}.comparison-field :disabled{opacity:.65}.comparison-settings{margin-top:22px;padding:15px 0;border-top:1px solid #ece4f5;border-bottom:1px solid #ece4f5}.comparison-settings summary{color:#7b648f;font-size:12px;cursor:pointer}.comparison-settings summary span{float:right;color:#b1a4bd;font-size:11px}.comparison-settings textarea{min-height:98px}.comparison-settings .comparison-field{margin-top:15px}.comparison-settings p{margin:11px 0 0;color:#a191ae;font-size:10px;line-height:1.8}.comparison-parameters{display:grid;grid-template-columns:1fr 1fr;gap:10px}.comparison-parameters input{padding:8px 10px}.comparison-tip{display:flex;align-items:flex-start;gap:9px;margin-top:23px;color:#a189b6}.comparison-tip svg{flex-shrink:0;margin-top:3px}.comparison-tip p{margin:0;font-size:11px;line-height:1.9}.comparison-config-link{margin-top:14px;padding:0;border:0;background:transparent;color:#8c5dce;font-size:12px}.comparison-start{flex-shrink:0;padding:18px 22px;border-top:1px solid #eee8f5}.comparison-start>small{display:block;margin-top:10px;color:#ab9ab8;font-size:10px;line-height:1.7;text-align:center}.comparison-empty-config{margin-top:17px;padding:12px;border:1px solid #e7def1;border-radius:10px;background:#fff}.comparison-empty-config p{margin:0 0 12px;font-size:12px;line-height:1.8;color:#9685a5}
.comparison-board{min-width:0;overflow:auto;padding:25px;background:#faf9fc}.comparison-board-heading{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:21px}.comparison-board-heading p{margin:7px 0 0 35px;color:#a294ac;font-size:11px}.comparison-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.comparison-card{display:flex;flex-direction:column;min-width:0;overflow:hidden;border:1px solid #e6dff0;border-radius:18px;background:#fff;box-shadow:0 3px 12px #42216404}.comparison-card.is-running{border-color:#c8b0f2}.comparison-card-top{display:flex;align-items:center;gap:9px;padding:13px 17px;border-bottom:1px solid #f2edf7}.comparison-card-top>strong{font-size:12px;color:#76618b;font-weight:500}.comparison-status{display:flex;align-items:center;gap:5px;margin-left:auto;color:#ac9fb7;font-size:10px}.comparison-status.running{color:#8b5bd1}.comparison-status.done{color:#31916d}.comparison-status.error{color:#c35b75}.comparison-status.cancelled{color:#b0895e}.comparison-card-top .comparison-icon{width:24px;height:24px}.comparison-card-selection{padding:16px 17px}.comparison-provider{display:flex;align-items:center;gap:10px;min-width:0}.comparison-provider>span{display:grid;place-items:center;width:35px;height:35px;flex-shrink:0;border:1px solid #ece4f7;border-radius:10px;background:#faf7ff;color:#a48fb9}.comparison-provider img{width:26px;height:26px;object-fit:contain}.comparison-provider select{width:100%;min-width:0;padding:8px 10px;border:1px solid #e7def1;border-radius:9px;background:#fff;color:#604975;outline:none;font-size:12px}.comparison-provider select:focus{border-color:#b599ed}.comparison-model-label{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:17px 0 9px;color:#9884a6;font-size:11px}.comparison-model-label button{display:flex;align-items:center;gap:5px;padding:0;border:0;background:transparent;color:#8b5bd1;font-size:10px;white-space:nowrap}.comparison-list-note{display:block;margin-top:8px;color:#b0a1bb;font-size:10px;line-height:1.5}.comparison-discovery-error{margin:8px 0 0;color:#b57953;font-size:11px;line-height:1.7}
.comparison-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:0;padding:13px 17px;background:#faf7fe;border-top:1px solid #f0e9f8;border-bottom:1px solid #f0e9f8}.comparison-metrics dt{color:#ad9dbb;font-size:10px}.comparison-metrics dd{margin:6px 0 0;color:#674980;font-size:12px;overflow-wrap:anywhere;line-height:1.5}.comparison-answer{height:clamp(250px,38vh,470px);padding:20px;overflow:auto;font-size:13px;line-height:1.9;color:#44364f}.comparison-answer-text{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}.comparison-answer-empty{display:flex;align-items:center;justify-content:center;flex-direction:column;height:100%;min-height:150px;color:#cebde0}.comparison-answer-empty p{margin:15px 0 5px;color:#b6a5c3;font-size:12px}.comparison-answer-empty small{font-size:10px;color:#c6b8d0}.comparison-reasoning{margin-bottom:16px;padding:12px;border:1px solid #ece4f6;border-radius:10px;color:#a393b1;background:#fcfaff;font-size:11px}.comparison-reasoning summary{cursor:pointer}.comparison-reasoning pre{margin:12px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}.comparison-error{margin:14px 0 0;padding:11px 12px;border:1px solid #f4d9e1;border-radius:10px;background:#fff5f7;color:#ba5674;font-size:12px;line-height:1.8;overflow-wrap:anywhere}.comparison-card-footer{display:flex;align-items:center;gap:8px;margin-top:auto;padding:12px 16px;border-top:1px solid #f0eaf6;background:#fefcff}.comparison-card-footer>span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px;color:#a18bad}.comparison-card-footer>span small{display:block;margin-top:3px;color:#b5a6c1;font-size:9px}.comparison-card-footer .comparison-secondary{padding:7px 9px;font-size:10px}.comparison-metric-note{margin:20px 2px 0;color:#b4a5bf;font-size:10px;line-height:1.9}.comparison-stale{margin:0 0 15px;padding:10px 13px;border:1px solid #eee1ce;border-radius:10px;background:#fffaf3;color:#ae8e60;font-size:11px}.spin{animation:comparison-spin 1s linear infinite}@keyframes comparison-spin{to{transform:rotate(360deg)}}
.comparison-provider>span.kimi{background:#080808;border-color:#252525;box-shadow:inset 0 0 0 1px #ffffff0a}
@media(min-width:1650px){.comparison-workspace{grid-template-columns:330px minmax(0,1fr)}}
@media(max-width:1050px){.comparison-mask{padding:14px}.comparison-dialog{height:calc(100dvh - 28px)}.comparison-workspace{grid-template-columns:250px minmax(0,1fr)}.comparison-control-scroll{padding:20px 16px}.comparison-start{padding:16px}.comparison-board{padding:20px 16px}.comparison-grid{gap:12px}.comparison-card-selection{padding:13px}.comparison-metrics{padding:12px;gap:5px}.comparison-metrics dd{font-size:10px}}
@media(max-width:800px){.comparison-dialog{border-radius:18px}.comparison-header{padding:16px 18px;gap:10px}.comparison-header h2{font-size:17px}.comparison-header p{font-size:10px}.comparison-type{display:none}.comparison-header>.comparison-icon{margin-left:auto}.comparison-workspace{display:flex;flex-direction:column;overflow:auto}.comparison-controls{flex-shrink:0;border-right:0;border-bottom:1px solid #eee8f5}.comparison-control-scroll{overflow:visible;padding:18px}.comparison-field{margin-top:14px}.comparison-field textarea{min-height:100px}.comparison-settings{margin-top:15px}.comparison-tip{margin-top:15px}.comparison-start{padding:14px 18px}.comparison-board{overflow:visible;padding:18px}.comparison-card-selection{padding:14px}.comparison-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.comparison-answer{height:330px}.comparison-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.comparison-metrics dd{font-size:11px}}
@media(max-width:540px){.comparison-grid{grid-template-columns:minmax(0,1fr)}.comparison-board-heading{align-items:flex-start}.comparison-board-heading .comparison-secondary{padding:8px 10px;font-size:10px}.comparison-mask{padding:8px}.comparison-dialog{height:calc(100dvh - 16px)}.comparison-emblem{width:38px;height:38px;border-radius:12px}.comparison-metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.comparison-answer{height:300px}}
@media(prefers-reduced-motion:reduce){.spin{animation:none}}
.evaluation-tabs{display:flex;gap:8px;margin:0 24px 18px;padding:6px;border:1px solid #e2dbe9;border-radius:16px;flex-shrink:0}.evaluation-tabs button{flex:1;padding:14px;border:0;border-radius:11px;background:white;color:#988b9f;font:inherit;font-weight:600;cursor:pointer}.evaluation-tabs button.active{background:#7c3aed;color:white;box-shadow:0 3px 10px #7c3aed22}.comparison-model-tabs{display:flex;gap:8px;overflow:auto;margin:0 0 20px;padding-bottom:5px}.comparison-model-tabs button{white-space:nowrap;border:1px solid #e9e1f2;border-radius:10px;padding:8px 12px;background:white;color:#918399;font:inherit;font-size:12px;cursor:pointer}.comparison-model-tabs button.active{background:#f1e9fe;color:#7c3aed;border-color:#bd9af6}.comparison-card.is-selected{border-color:#b489f3}.comparison-card-top strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.comparison-provider strong{flex:1;min-width:0;font-size:13px}.comparison-dialog{position:relative}.comparison-card-selection{min-height:100px}@media(max-width:600px){.evaluation-tabs{margin:0 14px 12px}.evaluation-tabs button{font-size:12px;padding:11px 6px}.comparison-provider{flex-wrap:wrap}}
.comparison-result-actions{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:10px;margin-top:12px}.comparison-result-actions .comparison-secondary{width:100%;min-width:0;min-height:40px;padding:10px 8px;white-space:nowrap;font-size:12px}.comparison-saved-notice{display:block;margin-top:10px;text-align:center;color:#629982;font-size:11px}
</style>
