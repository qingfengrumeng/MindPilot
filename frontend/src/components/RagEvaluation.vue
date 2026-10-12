<script setup>
import AppSelect from '@/components/AppSelect.vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { BookOpen, Check, ChevronRight, Download, FileText, FlaskConical, LoaderCircle, Play, Plus, RefreshCw, Save, Square, Trash2, Upload, X } from 'lucide-vue-next'
import { evaluationsApi,evaluationReportsApi } from '@/api/evaluations'
import TestModelPicker from './TestModelPicker.vue'
import GoldenDatasetManager from './GoldenDatasetManager.vue'
import EvaluationReportHistory from './EvaluationReportHistory.vue'
import {metricBand} from '@/lib/ragBenchmarks'

const props = defineProps({ state: Object })
const emit = defineEmits(['busy'])
const workspace = ref(null), questions = ref([]), error = ref(''), loading = ref(true), busy = ref(false), running = ref(false)
const questionSearch=ref(''),questionPage=ref(1)
const filteredQuestions=computed(()=>questions.value.filter(q=>`${q.query} ${q.answer}`.toLowerCase().includes(questionSearch.value.toLowerCase())))
const questionPages=computed(()=>Math.max(1,Math.ceil(filteredQuestions.value.length/12)))
const visibleQuestions=computed(()=>filteredQuestions.value.slice((Math.min(questionPage.value,questionPages.value)-1)*12,Math.min(questionPage.value,questionPages.value)*12))
const section = ref('data'), selectedQuestion = ref(''), selectedDocument = ref(''), selectedPage = ref(1)
const uploadInput = ref(null), importInput = ref(null), dirty = ref(false), progress = ref(''), picker = ref(null)
const plans = ref([]), generator = ref(null), judge = ref(null), split = ref('dev'), maxTokens = ref(1024)
const semanticThreshold=ref(.65),lexicalThreshold=ref(.8)
const report = ref(null), partial = ref([])
const manager=ref(''),historyOpen=ref(false)
const archivedView=ref(false)
function openArchivedReport(value){report.value=value;archivedView.value=true;section.value='results'}
async function loadSamples(){
  if(busy.value||running.value)return
  if(documents.value.length||questions.value.length){error.value='当前空间已有资料，请先导出保留并清空，再加载配套样例。';return}
  busy.value=true;error.value=''
  try{const dataset=await evaluationsApi.sample();applyWorkspace(await evaluationsApi.import(workspace.value.id,workspace.value.revision,dataset));progress.value='已载入12份黄金文档、72页正文与144条完整标注问答（合成评测样例）。'}catch(e){error.value=e.message}finally{busy.value=false}
}
async function editDocument(value){
  if(dirty.value&&!await saveGold())return
  busy.value=true;error.value=''
  try{const {id,...body}=value;applyWorkspace(await evaluationsApi.editDocument(workspace.value.id,id,workspace.value.revision,body));progress.value='文档已保存，正文发生变化时请重新标注该文档的黄金证据。'}catch(e){error.value=e.message}finally{busy.value=false}
}
async function saveManagedQuestions(value){
  if(busy.value||running.value)return
  if(value.some(q=>!q.query.trim())){error.value='每条测试问题都需要填写问题';return}
  busy.value=true;error.value=''
  try{applyWorkspace(await evaluationsApi.gold(workspace.value.id,workspace.value.revision,clone(value)));progress.value='测试集已保存'}catch(e){error.value=e.message}finally{busy.value=false}
}
async function retainReport(){
  if(!report.value||busy.value||running.value)return
  busy.value=true;error.value=''
  try{await evaluationReportsApi.save({kind:'rag',title:`RAG评测 · ${report.value.plans.length}个方案`,result:clone(report.value)});progress.value='评测结果已永久保存，可通过已保存结果查看。'}catch(e){error.value=e.message}finally{busy.value=false}
}
const readOnly = computed(() => props.state?.editable === false)
const activeQuestion = computed(() => questions.value.find(q => q.id === selectedQuestion.value))
const documents = computed(() => workspace.value?.documents || [])
const doc = computed(() => documents.value.find(d => d.id === selectedDocument.value))
const page = computed(() => doc.value?.pages.find(p => p.page === Number(selectedPage.value)))
const reportPlans = computed(() => report.value?.plans || partial.value)
const stale = computed(() => report.value && (JSON.stringify(report.value.documentIds) !== JSON.stringify(documents.value.map(d => d.id)) || JSON.stringify(report.value.questions) !== JSON.stringify(questions.value.filter(q => report.value.settings.split === 'all' || q.split === report.value.settings.split))))
const metricLabels = [ ['chunkPrecision','片段Precision@k'], ['precision', '文档Precision@k'], ['recall', 'Recall@k'], ['mrr', 'MRR@k'], ['ndcg', 'nDCG@k'], ['hitRate','Hit Rate@k'], ['judgedCoverage', '标注覆盖'], ['evidenceCoverage', '证据覆盖'], ['faithfulness', 'Faithfulness · 事实支持'], ['semanticFaithfulness','语义忠实度 · 余弦'], ['groundedness','Groundedness · 双信号'], ['factualConsistency','Factual Consistency'], ['potentialHallucinationRate','潜在幻觉率'], ['answerConsistency', '参考一致性'], ['referenceRecall', '参考事实召回'] ]
let controller = null, disposed = false
const clone = value => JSON.parse(JSON.stringify(value))
const id = () => crypto.randomUUID()
function modelLabel(value) { return value?.model || '选择模型' }
function score(value) { return value == null ? '—' : `${(value * 100).toFixed(1)}%` }
function duration(value) { return value == null ? '—' : `${(value / 1000).toFixed(2)} s` }
function applyWorkspace(value, replaceQuestions = true) {
  workspace.value = value
  if (replaceQuestions) { questions.value = clone(value.questions || []); dirty.value = false }
  if (!questions.value.some(q => q.id === selectedQuestion.value)) selectedQuestion.value = questions.value[0]?.id || ''
  if (!documents.value.some(d => d.id === selectedDocument.value)) { selectedDocument.value = documents.value[0]?.id || ''; selectedPage.value = doc.value?.pages[0]?.page || 1 }
}
async function load() {
  loading.value = true; error.value = ''
  try {
    const value = await evaluationsApi.create()
    if (disposed) return
    applyWorkspace(value); report.value = value.reports?.at(-1) || null
    const ready = (props.state.providers || []).find(p => p.hasKey && p.configs?.embedding?.baseUrl)
    const embedding = ready ? { providerId: ready.id, model: ready.configs.embedding.model, dimensions: ready.configs.embedding.dimensions, embeddingProtocol: ready.configs.embedding.embeddingProtocol || 'compatible' } : null
    if (!plans.value.length) { plans.value = [newPlan(embedding)]; plans.value.push(newPlan(embedding, 1200)) }
  } catch (cause) { if (!disposed) error.value = cause.message }
  finally { if (!disposed) loading.value = false }
}
function newPlan(embedding = null, chunkSize = 800) {
  return { id: id(), name: `方案 ${plans.value.length + 1}`, embedding: embedding ? clone(embedding) : null,
    chunkSize, overlap: 120, topK: 5, candidateK: 20, reranker: null, useReranker: false }
}
function addPlan() { if (plans.value.length < 6) plans.value.push(newPlan(plans.value[0]?.embedding)) }
function choose(category, target, field) { picker.value = { category, target, field, value: target ? target[field] : field === 'generator' ? generator.value : judge.value } }
function chosen(value) {
  if (picker.value.target) picker.value.target[picker.value.field] = value
  else if (picker.value.field === 'generator') generator.value = value
  else judge.value = value
  picker.value = null
}
function addQuestion() {
  if (questions.value.length >= 200) return
  const question = { id: id(), query: '', answer: '', split: 'dev', complete: false, judgments: {}, evidence: [] }
  questions.value.push(question); selectedQuestion.value = question.id; dirty.value = true
  questionSearch.value='';questionPage.value=Math.ceil(questions.value.length/12)
}
function removeQuestion(question) {
  questions.value = questions.value.filter(q => q.id !== question.id); selectedQuestion.value = questions.value[0]?.id || ''; dirty.value = true
}
async function saveGold() {
  if (!workspace.value || busy.value) return false
  if (questions.value.some(q => !q.query.trim())) { error.value = '每条黄金问答都需要填写问题'; return false }
  busy.value = true; error.value = ''
  try {
    applyWorkspace(await evaluationsApi.gold(workspace.value.id, workspace.value.revision, clone(questions.value)))
    return true
  } catch (cause) { error.value = cause.message; return false }
  finally { busy.value = false }
}
async function uploadFiles(event) {
  const files = [...event.target.files]; event.target.value = ''
  if (!files.length || busy.value || running.value) return
  if (dirty.value && !await saveGold()) return
  busy.value = true; error.value = ''
  try {
    for (const file of files) {
      progress.value = `正在读取 ${file.name}`
      const value = await evaluationsApi.upload(workspace.value.id, file)
      if (disposed) return
      applyWorkspace(value)
    }
  } catch (cause) { if (!disposed) error.value = cause.message }
  finally { busy.value = false; progress.value = '' }
}
async function removeDoc(document) {
  if (dirty.value && !await saveGold()) return
  busy.value = true; error.value = ''
  try { applyWorkspace(await evaluationsApi.removeDocument(workspace.value.id, document.id)); report.value = null }
  catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
function grade(question, documentId, value) {
  if (value === '') delete question.judgments[documentId]
  else question.judgments[documentId] = Number(value)
  question.complete = false; dirty.value = true
}
function addEvidence(question, chunk) {
  if (!question || question.evidence.length >= 60) return
  const value = { documentId: chunk.documentId, page: chunk.page, start: chunk.start, end: chunk.end }
  if (!question.evidence.some(e => JSON.stringify(e) === JSON.stringify(value))) question.evidence.push(value)
  question.judgments[chunk.documentId] = Math.max(1, question.judgments[chunk.documentId] || 0)
  question.complete = false; dirty.value = true
}
function evidenceText(evidence) { return documents.value.find(d => d.id === evidence.documentId)?.pages.find(p => p.page === evidence.page)?.text.slice(evidence.start, evidence.end) || '' }
function documentName(value) { return documents.value.find(d => d.id === value)?.name || value }
function resultQuestion(result) { return questions.value.find(q => q.id === result.questionId) }
function markComplete(question) {
  if (question.complete && documents.value.some(d => !(d.id in question.judgments))) {
    question.complete = false; error.value = '请先给所有测试文档标注相关性，再声明标注完整'
  }
  dirty.value = true
}
async function start() {
  if (running.value || busy.value || readOnly.value) return
  error.value = ''
  if (!documents.value.length || !questions.value.length) { error.value = '先上传测试文档并添加黄金问答'; section.value = 'data'; return }
  if (plans.value.some(p => !p.embedding || (p.useReranker && !p.reranker))) { error.value = '请为每个方案选择 Embedding，以及启用的 Rerank 型号'; return }
  if (judge.value && !generator.value) { error.value = '回答质量评测需要选择回答模型'; return }
  if (dirty.value && !await saveGold()) return
  const snapshot = plans.value.map(p => ({ id: p.id, name: p.name, embedding: p.embedding, chunkSize: Number(p.chunkSize), overlap: Number(p.overlap), topK: Number(p.topK), candidateK: Number(p.candidateK), reranker: p.useReranker ? p.reranker : null }))
  if (snapshot.some(p => !p.name.trim() || !Number.isInteger(p.chunkSize) || p.chunkSize < 100 || p.chunkSize > 3000 || !Number.isInteger(p.overlap) || p.overlap < 0 || p.overlap > 1000 || p.overlap >= p.chunkSize || !Number.isInteger(p.topK) || p.topK < 1 || p.topK > 20 || !Number.isInteger(p.candidateK) || p.candidateK < 1 || p.candidateK > 100 || (p.reranker && p.candidateK < p.topK))) {
    error.value = '请检查方案：chunk_size 为 100—3000，重叠小于分块长度且不超过 1000，top-k 为 1—20，重排候选数为 1—100 且不少于 top-k'
    section.value = 'plans'; return
  }
  archivedView.value=false
  controller = new AbortController(); running.value = true; emit('busy', true); section.value = 'results'; report.value = null
  partial.value = snapshot.map(p => ({ ...p, settings: p, results: [], summary: {} }))
  try {
    await evaluationsApi.run(workspace.value.id, { revision: workspace.value.revision, plans: snapshot, generator: generator.value, judge: judge.value, split: split.value, maxTokens: Number(maxTokens.value),semanticThreshold:Number(semanticThreshold.value),lexicalThreshold:Number(lexicalThreshold.value) }, controller.signal, event => {
      if (disposed) return
      if (event.type === 'progress') progress.value = event.message
      if (event.type === 'result') partial.value.find(p => p.id === event.planId)?.results.push(event.result)
      if (event.type === 'plan') { const index = partial.value.findIndex(p => p.id === event.plan.id); if (index >= 0) partial.value[index] = event.plan }
      if (event.type === 'done') { report.value = event.report; progress.value = '评测完成' }
    })
    if (!disposed) applyWorkspace(await evaluationsApi.get(workspace.value.id), !dirty.value)
  } catch (cause) { if (!disposed) { error.value = controller.signal.aborted ? '测试已停止，已返回的结果保留在当前界面' : cause.message; progress.value = '' } }
  finally { running.value = false; emit('busy', false); controller = null }
}
function stop() { controller?.abort() }
async function rescore() {
  if (!report.value || busy.value || running.value) return
  if (dirty.value && !await saveGold()) return
  busy.value = true; error.value = ''
  try { report.value = await evaluationsApi.rescore(workspace.value.id, report.value.id); applyWorkspace(await evaluationsApi.get(workspace.value.id)); progress.value = '已根据最新标注重算检索指标，无需再次调用模型' }
  catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
function download(value, name) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function exportDataset() { download({ schemaVersion: 1, documents: clone(documents.value), questions: clone(questions.value) }, 'rag-golden-dataset.json') }
async function importDataset(event) {
  const file = event.target.files[0]; event.target.value = ''
  if (!file) return
  if (file.size > 4 * 1024 * 1024) { error.value = '测试集 JSON 请控制在 4 MB 以内'; return }
  busy.value = true; error.value = ''
  try {
    const value = JSON.parse(await file.text())
    applyWorkspace(await evaluationsApi.import(workspace.value.id, workspace.value.revision, value)); report.value = null
  } catch (cause) { error.value = cause.message || '测试集格式无效' }
  finally { busy.value = false }
}
async function clear() {
  if (running.value || busy.value) return
  busy.value = true; error.value = ''
  try { await evaluationsApi.clear(workspace.value.id); report.value = null; partial.value = []; plans.value = []; await load() }
  catch (cause) { error.value = cause.message }
  finally { busy.value = false }
}
onMounted(load)
onBeforeUnmount(() => { disposed = true; controller?.abort(); emit('busy', false) })
</script>

<template>
  <div class="rag-workspace"><GoldenDatasetManager v-if="manager" :mode="manager" :message="error" :documents="documents" :questions="questions" :busy="busy" @close="manager=''" @save-document="editDocument" @save-questions="saveManagedQuestions" @remove-document="removeDoc"/><EvaluationReportHistory v-if="historyOpen" kind="rag" @close="historyOpen=false" @open="openArchivedReport"/>
    <div v-if="loading" class="rag-loading"><LoaderCircle :size="24" class="spin" />加载临时测试空间…</div>
    <template v-else-if="workspace">
      <div class="rag-toolbar"><div><strong>RAG 评测实验室</strong><small>与正式资料库隔离 · 24 小时未活动后过期 · 版本 {{ workspace.revision }}</small></div><button :disabled="busy || running" @click="exportDataset"><Download :size="15" />导出测试集</button><button :disabled="busy || running" @click="importInput.click()"><Upload :size="15" />导入测试集</button><button :disabled="busy || running" class="rag-danger" @click="clear"><Trash2 :size="15" />清空</button><input ref="importInput" type="file" accept="application/json,.json" hidden @change="importDataset" /></div>
      <div class="rag-manager-actions"><button :disabled="busy||running" @click="manager='documents'"><BookOpen :size="17"/>黄金文档 · {{documents.length}}份</button><button :disabled="busy||running" @click="manager='questions'"><FileText :size="17"/>测试集 · {{questions.length}}题</button><button :disabled="busy||running||documents.length>0||questions.length>0" @click="loadSamples"><Plus :size="17"/>载入配套样例（144题）</button><button :disabled="busy||running||!report" @click="retainReport"><Save :size="17"/>保存评测结果</button><button :disabled="running" @click="historyOpen=true"><BookOpen :size="17"/>已保存结果</button></div><nav class="rag-sections" aria-label="RAG 评测步骤"><button v-for="(value, index) in [['data', '测试集与黄金标注'], ['plans', '对比方案'], ['results', '结果与相关性复核']]" :key="value[0]" :class="{ active: section === value[0] }" @click="section = value[0]"><span>{{ index + 1 }}</span>{{ value[1] }}</button></nav>
      <p v-if="error" class="rag-alert" role="alert">{{ error }}</p><p v-if="progress" class="rag-progress" role="status"><LoaderCircle v-if="running || busy" :size="14" class="spin" /><Check v-else :size="14" />{{ progress }}</p>
      <section v-show="section === 'data'" class="rag-data">
        <aside class="rag-panel rag-corpus"><header><div><h3>测试文档</h3><small>{{ documents.length }} / 12 份 · PDF / TXT / MD</small></div><button :disabled="busy || running" @click="uploadInput.click()"><Plus :size="16" />上传</button><input ref="uploadInput" type="file" accept=".pdf,.txt,.md" multiple hidden @change="uploadFiles" /></header>
          <p class="rag-note">这里上传的文件仅用于本测试空间，不进入知识资料、正式向量库或记忆。导出测试集可保留黄金标注。</p>
          <div v-if="!documents.length" class="rag-empty"><Upload :size="28" /><p>添加用于检索评测的文档</p><small>单份不超过 10 MB，总计不超过 15 万字符</small></div>
          <div v-for="document in documents" :key="document.id" class="rag-document" :class="{ selected: selectedDocument === document.id }"><button @click="selectedDocument = document.id; selectedPage = document.pages[0].page"><FileText :size="17" /><span>{{ document.name }}<small>{{ document.pages.length }} 页</small></span></button><button class="rag-icon" :disabled="busy || running" aria-label="移除测试文档" @click="removeDoc(document)"><X :size="15" /></button></div>
          <div v-if="doc" class="rag-preview"><header><strong>{{ doc.name }}</strong><AppSelect v-model="selectedPage" aria-label="文档页码"><option v-for="p in doc.pages" :key="p.page" :value="p.page">第 {{ p.page }} 页</option></AppSelect></header><pre>{{ page?.text }}</pre><button :disabled="!activeQuestion || busy || running || !page" @click="addEvidence(activeQuestion, { documentId: doc.id, page: page.page, start: 0, end: page.text.length })"><BookOpen :size="15" />当前页加入所选问题的黄金证据</button><small>也可在测试结果中添加更精确的命中片段。</small></div>
        </aside>
        <main class="rag-panel rag-gold"><header><div><h3>黄金问答与相关性</h3><small>黄金答案与证据可以持续补充</small></div><button :disabled="busy || running || questions.length >= 200" @click="addQuestion"><Plus :size="16" />添加问题</button></header>
          <div class="rag-question-pagination"><input v-model="questionSearch" placeholder="搜索测试问题或参考答案" aria-label="搜索测试问题" @input="questionPage=1"/><button :disabled="questionPage<=1" @click="questionPage--">上一页</button><small>{{Math.min(questionPage,questionPages)}} / {{questionPages}}</small><button :disabled="questionPage>=questionPages" @click="questionPage++">下一页</button></div><div class="rag-question-tabs"><button v-for="(q, index) in visibleQuestions" :key="q.id" :class="{ active: selectedQuestion === q.id }" @click="selectedQuestion = q.id">{{ index + 1 }}. {{ q.query || '待填写问题' }}</button></div>
          <div v-if="activeQuestion" class="rag-question-form"><div class="rag-row"><label>分组<AppSelect v-model="activeQuestion.split" :disabled="running" @change="dirty = true"><option value="dev">开发集 · 参数调优</option><option value="test">测试集 · 最终验证</option></AppSelect></label><button class="rag-danger" :disabled="running" @click="removeQuestion(activeQuestion)"><Trash2 :size="15" />删除问题</button></div>
            <label>测试问题<textarea v-model="activeQuestion.query" :disabled="running" maxlength="4000" placeholder="输入测试问题" @input="dirty = true" /></label><label>黄金参考答案<textarea v-model="activeQuestion.answer" :disabled="running" maxlength="8000" placeholder="填写可验证的正确答案；只测检索时可以留空" @input="dirty = true" /></label>
            <h4>文档相关性</h4><p class="rag-note">0 不相关，1 弱相关，2 相关，3 高度相关。未标注与不相关分别显示；新发现的相关资料可随时补充。</p>
            <div v-for="document in documents" :key="document.id" class="rag-grade"><span>{{ document.name }}</span><AppSelect :value="activeQuestion.judgments[document.id] ?? ''" :disabled="running" :aria-label="`${document.name} 相关性等级`" @change="grade(activeQuestion, document.id, $event.target.value)"><option value="">未标注</option><option v-for="(label, i) in ['0 · 不相关', '1 · 弱相关', '2 · 相关', '3 · 高度相关']" :key="i" :value="i">{{ label }}</option></AppSelect></div>
            <label class="rag-checkbox"><input v-model="activeQuestion.complete" type="checkbox" :disabled="running" @change="markComplete(activeQuestion)" />已复核整个测试语料，标注完整</label>
            <h4>黄金证据 · {{ activeQuestion.evidence.length }} 条</h4><div v-for="(evidence, index) in activeQuestion.evidence" :key="index" class="rag-evidence"><div><small>{{ documentName(evidence.documentId) }} · 第 {{ evidence.page }} 页 · {{ evidence.start }}—{{ evidence.end }}</small><button class="rag-icon" :disabled="running" aria-label="删除黄金证据" @click="activeQuestion.evidence.splice(index, 1); dirty = true"><X :size="14" /></button></div><p>{{ evidenceText(evidence) }}</p></div>
          </div><div v-else class="rag-empty"><BookOpen :size="28" /><p>添加真实问题和已确认的相关资料</p><small>无需一次标注完，测试后可以继续完善。</small></div>
          <footer><span>{{ dirty ? '有待保存的标注' : '黄金标注已同步' }}</span><button class="rag-primary" :disabled="busy || running || !dirty" @click="saveGold"><Save :size="16" />保存黄金标注</button><button @click="section = 'plans'">配置对比方案<ChevronRight :size="15" /></button></footer>
        </main>
      </section>
      <section v-show="section === 'plans'" class="rag-plans">
        <div class="rag-section-heading"><div><h3>检索方案对比</h3><p>每次固定同一测试集，比较 Embedding、分块、top-k 与 Rerank 的影响。</p></div><button :disabled="running || readOnly || plans.length >= 6" @click="addPlan"><Plus :size="16" />添加方案</button></div>
        <div class="rag-plan-grid"><article v-for="plan in plans" :key="plan.id" class="rag-panel rag-plan"><header><input v-model="plan.name" maxlength="80" :disabled="running" aria-label="方案名称" /><button class="rag-icon" :disabled="running || plans.length <= 1" aria-label="删除测试方案" @click="plans = plans.filter(p => p.id !== plan.id)"><Trash2 :size="16" /></button></header>
            <label>Embedding 型号<button class="rag-model" :disabled="running || readOnly" @click="choose('embedding', plan, 'embedding')"><span>{{ modelLabel(plan.embedding) }}<small v-if="plan.embedding">{{ plan.embedding.dimensions }} 维</small></span><ChevronRight :size="16" /></button></label>
            <div class="rag-parameters"><label>chunk_size<input v-model="plan.chunkSize" type="number" min="100" max="3000" :disabled="running" /></label><label>重叠字符<input v-model="plan.overlap" type="number" min="0" max="1000" :disabled="running" /></label><label>top-k<input v-model="plan.topK" type="number" min="1" max="20" :disabled="running" /></label><label>重排候选数<input v-model="plan.candidateK" type="number" min="1" max="100" :disabled="running || !plan.useReranker" /></label></div>
            <label class="rag-checkbox"><input v-model="plan.useReranker" type="checkbox" :disabled="running" />使用 Rerank 重排</label><button v-if="plan.useReranker" class="rag-model" :disabled="running || readOnly" @click="choose('reranker', plan, 'reranker')"><span>{{ modelLabel(plan.reranker) }}</span><ChevronRight :size="16" /></button>
          </article></div>
        <div class="rag-panel rag-generation"><header><div><h3>生成一致性评测 · 可选</h3><small>选择回答模型计算语义与双信号指标；选择独立评审模型核验事实。</small></div></header><div class="rag-generation-grid"><label>回答 LLM<button class="rag-model" :disabled="running || readOnly" @click="choose('text', null, 'generator')"><span>{{ modelLabel(generator) }}</span><ChevronRight :size="16" /></button><button v-if="generator" class="rag-text-button" :disabled="running" @click="generator = null; judge = null">仅测检索</button></label><label>事实核验 LLM<button class="rag-model" :disabled="running || readOnly || !generator" @click="choose('text', null, 'judge')"><span>{{ modelLabel(judge) }}</span><ChevronRight :size="16" /></button><button v-if="judge" class="rag-text-button" :disabled="running" @click="judge = null">取消评审</button></label><label>测试分组<AppSelect v-model="split" :disabled="running"><option value="dev">开发集</option><option value="test">测试集</option><option value="all">全部</option></AppSelect></label><label>回答最大 token<input v-model="maxTokens" type="number" min="64" max="4096" :disabled="running" /></label></div><div class="rag-signal-settings"><label>语义依据阈值<input v-model.number="semanticThreshold" type="number" min="0" max="1" step="0.05" :disabled="running"/></label><label>字面重合阈值<input v-model.number="lexicalThreshold" type="number" min="0" max="1" step="0.05" :disabled="running"/></label><p>一句话满足语义或字面信号任一项即有依据。两个信号均不足才标记潜在幻觉；这是启发式结果，不能替代事实核验。</p></div><p class="rag-note">分块按字符计数；向量检索为独立内存中的精确余弦检索。每个方案单独生成向量并测量耗时。评审结果是模型估计，可展开事实核验记录复核。</p></div>
        <div class="rag-run-bar"><p v-if="readOnly">共享密钥调用仅主账户可使用。</p><p v-else>{{ plans.length }} 个方案 · {{ questions.filter(q => split === 'all' || q.split === split).length }} 条问题 · 使用实际模型接口</p><button v-if="running" class="rag-primary" @click="stop"><Square :size="16" />停止测试</button><button v-else class="rag-primary" :disabled="busy || readOnly" @click="start"><Play :size="16" />开始评测</button></div>
      </section>
      <section v-show="section === 'results'" class="rag-results">
        <div class="rag-section-heading"><div><h3>评测结果</h3><p v-if="report">运行数据版本 {{ report.datasetRevision }} · 评分标注版本 {{ report.scoringRevision }}</p><p v-else>检索指标与回答质量分别计分</p></div><div class="rag-row"><button v-if="report" :disabled="busy || running" @click="download(report, 'rag-evaluation-report.json')"><Download :size="15" />导出结果</button><button :disabled="busy || running || !report || archivedView" @click="rescore"><RefreshCw :size="15" />按最新标注重算</button><button v-if="running" class="rag-primary" @click="stop"><Square :size="16" />停止</button><button v-else class="rag-primary" :disabled="busy || readOnly" @click="start"><Play :size="16" />重新评测</button></div></div>
        <p v-if="dirty || stale" class="rag-warning">标注或测试资料已变化；下表保留的是原版本分数，保存后可重算检索指标。</p>
        <div v-if="!reportPlans.length" class="rag-empty"><FlaskConical :size="34" /><p>配置方案并开始评测</p></div>
        <div v-else class="rag-score-table"><table><thead><tr><th>方案</th><th v-for="metric in metricLabels" :key="metric[0]">{{ metric[1] }}</th><th>向量耗时</th><th>成功 / 失败</th></tr></thead><tbody><tr v-for="plan in reportPlans" :key="plan.id"><th>{{ plan.name }}<small v-if="plan.summary?.provisional">暂定 · 标注待完善</small><small v-if="plan.error" class="rag-error">{{ plan.error }}</small></th><td v-for="metric in metricLabels" :key="metric[0]">{{ score(plan.summary?.[metric[0]]) }}<small v-if="metricBand(metric[0],plan.summary?.[metric[0]],plan.settings.topK)" class="rag-band" :class="{good:metricBand(metric[0],plan.summary?.[metric[0]],plan.settings.topK)==='优秀',bad:metricBand(metric[0],plan.summary?.[metric[0]],plan.settings.topK)==='需优化'}">{{metricBand(metric[0],plan.summary?.[metric[0]],plan.settings.topK)}}</small><small v-if="plan.summary?.metricCounts">{{plan.summary.metricCounts[metric[0]]||0}}题已计分</small></td><td>{{ duration(plan.indexingMs) }}</td><td>{{ plan.summary?.successful ?? 0 }} / {{ plan.summary?.failed ?? 0 }}</td></tr></tbody></table></div>
        <details class="rag-metric-guide"><summary>参考基准 · 可展开查看</summary><table class="rag-reference"><thead><tr><th>指标</th><th>优秀</th><th>良好</th><th>需优化</th></tr></thead><tbody><tr v-for="row in [['Recall@5','>85%','70%—85%','<70%'],['Precision@5','>60%','40%—60%','<40%'],['MRR','>80%','60%—80%','<60%'],['nDCG@5','>80%','65%—80%','<65%'],['Faithfulness','>80%','65%—80%','<65%'],['Groundedness','>80%','60%—80%','<60%'],['Factual Consistency','>85%','70%—85%','<70%'],['潜在幻觉率','<5%','5%—15%','>15%']]" :key="row[0]"><td v-for="cell in row" :key="cell">{{cell}}</td></tr></tbody></table><p>以上为当前项目参考阈值，需用业务标注校准，非通用行业标准。top-k不为5时不套用@5的等级；未计分显示“—”，不视为0分。</p></details><details class="rag-metric-guide"><summary>指标口径与评分限制</summary><p>Precision / Recall / MRR / nDCG：以文档为单位，同一文档的多个分块只计一次；按 top-k 截断，Precision 分母为 k。相关等级大于 0 算相关，nDCG 使用 2^等级−1。没有已知相关文档时不计分。</p><p>标注覆盖率：已判断相关或不相关的命中文档比例。未标注暂按 0 参与排序分数，结果标为暂定；Recall 只针对已知相关文档，不代表全语料的完整召回。</p><p>证据覆盖：检索片段与黄金证据字符范围的覆盖比例，帮助比较不同 chunk_size。Faithfulness：回答事实中得到检索证据支持的比例。参考一致性：回答事实中得到黄金答案支持的比例；参考事实召回：黄金事实被回答覆盖的比例。语义忠实度为逐句与检索片段最高余弦相似度的平均值；Groundedness为满足语义或字面阈值的句子比例，潜在幻觉率为两种信号都未命中的比例。Factual Consistency由独立LLM核验内部矛盾和来源冲突，不能以语义相似直接推断。均可查看逐条评审；无评审、无参考或评审失败显示“—”。</p></details>
        <article v-for="plan in reportPlans" :key="plan.id" class="rag-panel rag-plan-results"><header><div><h3>{{ plan.name }}</h3><small>{{ plan.settings.embedding.model }} · chunk_size {{ plan.settings.chunkSize }} · top-k {{ plan.settings.topK }}{{ plan.settings.reranker ? ` · Rerank ${plan.settings.reranker.model}` : ' · 无重排' }}</small></div><span>{{ plan.chunkCount ?? '—' }} 个分块</span></header>
          <details v-for="result in plan.results" :key="result.questionId" class="rag-query-result"><summary><span>{{ result.query }}</span><small>{{ duration(result.retrievalMs) }} 检索 · {{ duration(result.rerankMs) }} 重排</small></summary><p v-if="result.error" class="rag-alert">{{ result.error }}</p><div class="rag-result-metrics"><span v-for="metric in metricLabels" :key="metric[0]">{{ metric[1] }} <strong>{{ score(result.metrics?.[metric[0]]) }}</strong></span></div>
            <div v-for="(chunk, index) in result.chunks" :key="chunk.id" class="rag-hit"><header><strong>{{ index + 1 }} · {{ chunk.name }}</strong><small>第 {{ chunk.page }} 页 · {{ chunk.start }}—{{ chunk.end }} · {{ (chunk.rerankScore ?? chunk.score).toFixed(4) }}</small></header><pre>{{ chunk.text }}</pre><footer v-if="resultQuestion(result)&&!stale&&!archivedView"><label>相关性<AppSelect :value="resultQuestion(result).judgments[chunk.documentId] ?? ''" :disabled="running" @change="grade(resultQuestion(result), chunk.documentId, $event.target.value)"><option value="">未标注</option><option v-for="(label, i) in ['不相关', '弱相关', '相关', '高度相关']" :key="i" :value="i">{{ i }} · {{ label }}</option></AppSelect></label><button :disabled="running || dirty && !resultQuestion(result)" @click="addEvidence(resultQuestion(result), chunk)"><Plus :size="14" />加入黄金证据</button></footer></div>
            <details v-if="result.groundednessSignals" class="rag-judge"><summary>逐句双信号依据 · {{result.groundednessSignals.length}}句</summary><div v-for="(signal,index) in result.groundednessSignals" :key="index"><strong :class="{unsupported:!signal.supported}">{{signal.supported?'有依据':'潜在幻觉 · 待人工复核'}}</strong><p>{{signal.sentence}}</p><small>语义 {{score(signal.semanticSimilarity)}} · 字面 {{score(signal.lexicalOverlap)}} · 来源 {{signal.sources.map(i=>i+1).join(', ')||'—'}}</small></div></details><p v-if="result.signalError" class="rag-warning">{{result.signalError}}</p><div v-if="result.answer" class="rag-response"><h4>模型回答</h4><pre>{{ result.answer }}</pre></div><p v-if="result.qualityError" class="rag-warning">{{ result.qualityError }}</p><details v-if="result.judgment" class="rag-judge"><summary>逐条事实核验 · 可人工复核</summary><p v-if="result.judgment.consistencyVerdict">事实一致性：{{result.judgment.consistencyVerdict}} · {{score(result.judgment.factualConsistency)}}<br/>{{result.judgment.consistencyReason}}</p><div v-for="(claim, i) in result.judgment.claims" :key="i"><strong :class="{ unsupported: !claim.supported }">{{ claim.supported ? '有检索证据' : '缺乏检索证据' }}</strong><p>{{ claim.text }}</p><small>来源 {{ claim.sources.map(i => i + 1).join(', ') || '—' }} · {{ claim.referenceSupported ? '符合参考答案' : '参考答案未支持' }}</small></div><div v-for="(claim, i) in result.judgment.referenceClaims" :key="`reference-${i}`"><strong>{{ claim.covered ? '已覆盖参考事实' : '遗漏参考事实' }}</strong><p>{{ claim.text }}</p></div></details>
          </details>
        </article><footer v-if="dirty" class="rag-sticky-save"><span>新增黄金标注待保存</span><button :disabled="busy || running" class="rag-primary" @click="saveGold"><Save :size="16" />保存黄金标注</button></footer>
      </section>
    </template>
    <div v-else class="rag-loading"><p>{{ error }}</p><button @click="load">重新载入</button></div>
    <TestModelPicker v-if="picker" :state="state" :category="picker.category" :value="picker.value" @close="picker = null" @select="chosen" />
  </div>
</template>

<style scoped>
.rag-workspace{flex:1;min-height:0;overflow:auto;padding:0 26px 26px;color:#40344b;font-size:13px}.rag-workspace button{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:10px 13px;border:1px solid #e3dbea;border-radius:11px;color:#76608d;background:white;font:inherit;font-size:12px;cursor:pointer;transition:border-color .15s}.rag-workspace button:hover:not(:disabled){border-color:#a681e6;color:#7c3aed}.rag-workspace button:disabled{opacity:.45;cursor:not-allowed}.rag-workspace .rag-primary{background:#7c3aed;color:white;border-color:#7c3aed}.rag-workspace .rag-primary:hover:not(:disabled){color:white;background:#7130dd}.rag-workspace .rag-danger{color:#b56577}.rag-toolbar,.rag-section-heading,.rag-panel>header,.rag-panel>footer,.rag-hit>header,.rag-hit>footer,.rag-row,.rag-run-bar{display:flex;align-items:center;gap:12px}.rag-toolbar{flex-wrap:wrap;margin:0 0 16px}.rag-toolbar>div{margin-right:auto}.rag-toolbar strong{font-size:17px}.rag-toolbar small{display:block;margin-top:6px;color:#9e91aa;font-size:11px}.rag-sections{display:flex;gap:12px;border-bottom:1px solid #ece6f2;margin-bottom:20px;padding-bottom:14px;flex-wrap:wrap}.rag-sections button{border:0;color:#998aa5;justify-content:flex-start}.rag-sections button span{border-radius:7px;padding:2px 6px;background:#f1edf5}.rag-sections button.active{color:#7c3aed;background:#f3edfd}.rag-sections button.active span{background:#7c3aed;color:white}.rag-data{display:grid;grid-template-columns:minmax(270px,.8fr) minmax(400px,1.5fr);gap:20px;align-items:start}.rag-panel{border:1px solid #e6dfed;border-radius:18px;background:white;padding:20px;min-width:0}.rag-panel>header{justify-content:space-between;margin-bottom:14px}.rag-workspace h3{font-size:16px;margin:0 0 6px}.rag-workspace h4{font-size:13px;margin:22px 0 10px}.rag-panel small,.rag-note,.rag-section-heading p{color:#9c90a7;font-size:11px;line-height:1.8}.rag-note{line-height:1.9;margin:12px 0}.rag-workspace label{display:block;margin:12px 0;color:#7b6a8b;font-size:12px}.rag-workspace input:not([type=checkbox]),.rag-workspace textarea,.rag-workspace select{display:block;box-sizing:border-box;width:100%;margin:9px 0 0;border:1px solid #e2d9ed;border-radius:10px;background:white;color:#44384e;padding:11px;font:inherit;outline:none}.rag-workspace input:focus,.rag-workspace textarea:focus,.rag-workspace select:focus{border-color:#a278f3;box-shadow:0 0 0 2px #f3edfc}.rag-workspace textarea{min-height:100px;resize:vertical;line-height:1.8}.rag-workspace .rag-checkbox{display:flex;gap:8px;align-items:center;margin:18px 0}.rag-checkbox input{accent-color:#7c3aed;width:15px;height:15px;margin:0}.rag-document{display:flex;align-items:center;gap:6px;border-radius:11px;margin:8px 0;padding:4px}.rag-document.selected{background:#f4eefc}.rag-document>button:first-child{border:0;background:none;flex:1;min-width:0;justify-content:flex-start;text-align:left;padding:8px}.rag-document span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rag-document small{display:block}.rag-workspace .rag-icon{border:0;background:none;padding:6px;flex-shrink:0}.rag-preview{margin-top:20px;border-top:1px solid #eee8f4;padding-top:18px}.rag-preview header{display:flex;align-items:center;justify-content:space-between;gap:12px}.rag-preview strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.rag-preview select{width:auto;margin:0;flex-shrink:0;padding:7px}.rag-preview pre{max-height:320px;overflow:auto;background:#faf9fc;border-radius:12px;padding:14px;font:inherit;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere}.rag-preview>small{display:block;margin:10px 0}.rag-question-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.rag-question-tabs button{max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}.rag-question-tabs button.active{border-color:#bc9af4;background:#f5efff;color:#7c3aed}.rag-question-form>.rag-row{justify-content:space-between}.rag-row label{flex:1;max-width:300px;margin:0}.rag-grade{display:flex;gap:16px;align-items:center;margin:10px 0;padding:8px 12px;background:#faf9fc;border-radius:11px}.rag-grade>span{flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.rag-grade select{width:135px;margin:0;padding:8px;font-size:11px}.rag-evidence{background:#faf8fd;border:1px solid #eee5f8;border-radius:12px;margin:10px 0;padding:12px}.rag-evidence>div{display:flex;justify-content:space-between;align-items:center}.rag-evidence p{max-height:100px;overflow:auto;margin:6px 0 0;line-height:1.8;white-space:pre-wrap;font-size:12px}.rag-gold>footer{border-top:1px solid #eee7f6;margin-top:20px;padding-top:16px;flex-wrap:wrap;justify-content:flex-end}.rag-gold>footer>span{margin-right:auto;font-size:11px;color:#9b8aaa}.rag-empty{display:flex;flex-direction:column;align-items:center;text-align:center;padding:40px 16px;color:#ac98c2;gap:8px}.rag-empty p{color:#847090}.rag-empty small{line-height:1.8}.rag-alert,.rag-warning{padding:12px 15px;border-radius:11px;font-size:12px;line-height:1.8}.rag-alert{background:#fff2f5;color:#b54660}.rag-warning{background:#fff8ec;color:#a67b38}.rag-progress{display:flex;gap:8px;align-items:center;color:#8a62b7;font-size:12px;margin:12px 0}.rag-section-heading{justify-content:space-between;margin-bottom:20px;flex-wrap:wrap}.rag-section-heading p{margin:4px 0 0}.rag-plan-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.rag-plan header input{padding:0!important;border:0!important;font-weight:600!important;font-size:15px!important;margin:0!important}.rag-plan header button{flex-shrink:0}.rag-parameters{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.rag-workspace .rag-model{width:100%;justify-content:space-between;text-align:left;min-height:45px;margin-top:10px;padding:12px;font-size:12px;background:#fcfaff}.rag-model span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rag-model small{margin-left:7px;font-size:10px}.rag-generation{margin-top:20px}.rag-generation-grid{display:grid;grid-template-columns:1fr 1fr .7fr .7fr;gap:18px}.rag-workspace .rag-text-button{border:0;background:none;padding:8px 0;font-size:11px;color:#998aa7}.rag-run-bar{padding:18px 0;justify-content:space-between}.rag-run-bar p{color:#9889a4;font-size:12px}.rag-score-table{width:100%;overflow:auto;border:1px solid #e9e0f1;border-radius:14px;margin-bottom:18px}.rag-score-table table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:11px}.rag-score-table th,.rag-score-table td{padding:15px 13px;border-bottom:1px solid #eee8f5;text-align:left}.rag-score-table thead{background:#f6f1fd;color:#917aa8}.rag-score-table tbody th{font-size:12px;font-weight:500}.rag-score-table small{display:block;color:#b09364;font-size:10px;margin-top:5px;max-width:220px;white-space:normal}.rag-score-table .rag-error{color:#bb516b}.rag-metric-guide{border:1px solid #eee8f5;background:#faf8fd;border-radius:12px;padding:14px 18px;margin-bottom:20px;font-size:12px;color:#8f7f9e;line-height:1.9}.rag-metric-guide summary{cursor:pointer;color:#765491}.rag-plan-results{margin-top:18px}.rag-plan-results>header>span{color:#9b89ac;font-size:11px}.rag-query-result{border-top:1px solid #eee8f4;padding:15px 0}.rag-query-result>summary{display:flex;align-items:center;justify-content:space-between;gap:20px;cursor:pointer;font-size:13px;color:#6e5687;line-height:1.8}.rag-query-result>summary:before{content:'›';font-size:20px;color:#b59ecb}.rag-query-result[open]>summary:before{transform:rotate(90deg)}.rag-query-result>summary span{flex:1}.rag-query-result>summary small{color:#ad9abb;font-size:10px}.rag-result-metrics{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.rag-result-metrics>span{font-size:10px;color:#9a8aa8;background:#faf7fd;padding:7px 10px;border-radius:9px}.rag-result-metrics strong{margin-left:7px;color:#7c5c9e}.rag-hit{background:#faf9fc;border:1px solid #ece5f4;border-radius:12px;padding:14px;margin:12px 0}.rag-hit>header{justify-content:space-between;flex-wrap:wrap}.rag-hit>header strong{font-size:12px}.rag-hit>header small{color:#a58fae;font-size:10px}.rag-hit pre,.rag-response pre{font:inherit;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.9;max-height:340px;overflow:auto}.rag-hit>footer{justify-content:flex-end;flex-wrap:wrap}.rag-hit label{display:flex;align-items:center;gap:8px;margin:0;font-size:11px}.rag-hit select{width:130px;padding:7px;margin:0;font-size:11px}.rag-judge{background:#f9f7fc;padding:14px;border-radius:12px;color:#89739e;font-size:12px}.rag-judge summary{cursor:pointer}.rag-judge>div{padding:12px 0;border-top:1px solid #eee6f6;margin-top:10px}.rag-judge strong{font-size:11px;color:#609b82}.rag-judge strong.unsupported{color:#b26575}.rag-judge small{color:#a290b1}.rag-sticky-save{position:sticky;bottom:0;display:flex;align-items:center;justify-content:flex-end;gap:18px;background:#ffffffef;border:1px solid #e8def5;border-radius:14px;padding:14px;margin-top:15px;box-shadow:0 -3px 20px #4322580a;font-size:12px;color:#9d87ad}.rag-loading{display:flex;align-items:center;justify-content:center;gap:12px;padding:60px;color:#9c83b7}.spin{animation:rag-spin 1s linear infinite}@keyframes rag-spin{to{transform:rotate(360deg)}}@media(max-width:1100px){.rag-plan-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.rag-generation-grid{grid-template-columns:1fr 1fr}.rag-data{grid-template-columns: minmax(230px,.7fr) minmax(330px,1.1fr)}}@media(max-width:800px){.rag-workspace{padding:0 16px 20px}.rag-data{grid-template-columns:1fr}.rag-toolbar{gap:7px}.rag-toolbar>div{width:100%;margin-bottom:8px}.rag-sections{gap:2px}.rag-sections button{font-size:11px;padding:8px}.rag-panel{padding:16px}.rag-plan-grid{grid-template-columns:1fr}.rag-section-heading .rag-row{flex-wrap:wrap;gap:7px}.rag-query-result>summary{flex-wrap:wrap;gap:8px}.rag-query-result>summary small{width:100%;padding-left:20px}.rag-preview pre{max-height:200px}.rag-grade{padding:8px}.rag-generation-grid{gap:12px}.rag-run-bar{flex-wrap:wrap}}@media(prefers-reduced-motion:reduce){.spin{animation:none}}
.rag-workspace input[hidden]{display:none!important}
.rag-manager-actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}.rag-manager-actions button{background:#f6f0ff;color:#7344a5;border-color:#dac8ef;padding:12px 16px}.rag-manager-actions button:hover:not(:disabled){background:#eee2fc}.rag-signal-settings{display:flex;align-items:center;gap:18px;margin:15px 0;flex-wrap:wrap}.rag-signal-settings label{max-width:180px}.rag-signal-settings p{font-size:12px;color:#9a85ab;flex:1;line-height:1.8}.rag-reference{width:100%;border-collapse:collapse;margin-top:18px}.rag-reference td,.rag-reference th{padding:12px;border:1px solid #e9e0f2;text-align:left}.rag-band{display:inline-block!important;border-radius:7px;padding:3px 7px;color:#997932!important;background:#fff7e6}.rag-band.good{color:#24846b!important;background:#eaf8f2}.rag-band.bad{color:#b44861!important;background:#fff0f3}.rag-question-pagination{display:flex;align-items:center;gap:8px;margin-top:15px}.rag-question-pagination input{flex:1;margin:0;min-width:0;font-size:12px;padding:10px}.rag-question-pagination button{padding:8px;font-size:11px}.rag-question-pagination small{white-space:nowrap;color:#a087b1}</style>
