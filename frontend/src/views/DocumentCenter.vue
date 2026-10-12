<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  BookOpenText,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  CloudUpload,
  Database,
  Eye,
  FileText,
  Layers,
  LoaderCircle,
  MessagesSquare,
  Network,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X
} from 'lucide-vue-next'
import PageShell from '@/components/PageShell.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { documentsApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const app = useAppStore()
const router = useRouter()
const search = ref('')
const domainFilter = ref('all')
const sortField = ref('导入时间')
const sortDirection = ref('降序')
const openSelect = ref(null)
const batchMode = ref(false)
const batchDeleteOpen = ref(false)
const deletingBatch = ref(false)
const page = ref(1)
const pageSize = ref(10)
const pageSizes = [5, 10, 20, 50]
const uploadOpen = ref(false)
const uploadDomain = ref('personal_learning')
const preview = ref(null)
const previewTab = ref('summary')
const deleteTarget = ref(null)
const uploading = ref(false)
const progress = ref(0)
const selected = ref([])
const selectedFiles = ref([])
const loading = ref(false)
const docs = ref([])
const activeDocumentStatuses = ['queued', 'parsing', 'chunking', 'embedding']
const activeWikiStatuses=['queued','compiling']
const wikiSupplementActive = doc => ['queued','running'].includes(doc.wikiSupplementStatus)
const vectorSteps = ['文本解析', 'Chunk切分', '文本向量化', '向量化完成']
let progressTimer = null
let refreshingProgress = false
let lastProgressRefresh = 0

const sortOptions = ['导入时间', '资料名称', '知识分块数量']
const directionOptions = ['升序', '降序']
const selectedDomainLabel = computed(() => domainFilter.value === 'all' ? '全部知识域' : app.domainLabel(domainFilter.value))

function vectorStatusLabel(doc) {
  return doc.status==='ready'||(!doc.status&&Number(doc.chunks||0)>0)?'向量化完成':'未向量化'
}
async function compileWiki(doc){
  try{const updated=await documentsApi.compileWiki(doc.id);docs.value=docs.value.map(item=>item.id===doc.id?{...item,...updated}:item);ui.toast('已开始Wiki编译，进度会在列表中更新')}
  catch(error){ui.toast(error?.message||'无法启动Wiki编译','error')}
}
function wikiActionLabel(doc){return doc.sourceAvailable===false?'原始文件缺失，请重新上传':wikiSupplementActive(doc)?'正在基于原文补充Wiki':doc.wikiStatus==='done'?'Wiki编译完成':activeWikiStatuses.includes(doc.wikiStatus)?'Wiki编译中':doc.wikiStatus==='failed'?'重试Wiki编译':'开始Wiki编译'}

function vectorStep(doc) {
  return { parsing: 0, chunking: 1, embedding: 2, ready: 4 }[doc.status] ?? (doc.status ? -1 : Number(doc.chunks || 0) > 0 ? 4 : -1)
}

function importedDate(value) {
  if (!value) return null
  const date = new Date(value.includes('T') ? value : value.replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? null : date
}

function formatImportedAt(value) {
  const date = importedDate(value)
  if (!date) return value || '—'
  const pad = number => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function vectorize(doc) {
  try {
    const updated = await documentsApi.vectorize(doc.id)
    docs.value = docs.value.map(item => item.id === doc.id ? { ...item, ...updated } : item)
    ui.toast('已开始向量化，进度会在列表中更新')
  } catch (error) {
    ui.toast(error?.message || '无法启动向量化', 'error')
  }
}

async function refreshDocumentProgress() {
  if (refreshingProgress) return
  const active = docs.value.some(doc => activeDocumentStatuses.includes(doc.status)||activeWikiStatuses.includes(doc.wikiStatus)||wikiSupplementActive(doc))
  if (!active && Date.now() - lastProgressRefresh < 5000) return
  lastProgressRefresh = Date.now()
  refreshingProgress = true
  try {
    const result = await documentsApi.list()
    docs.value = result.items || []
  } catch {
    // 短暂网络波动时保留最后一次进度，下次轮询继续更新。
  } finally {
    refreshingProgress = false
  }
}

function toggleSelect(name) {
  openSelect.value = openSelect.value === name ? null : name
}

function chooseDomain(value) {
  domainFilter.value = value
  openSelect.value = null
}

function chooseSortField(value) {
  sortField.value = value
  openSelect.value = 'sort-direction'
}

function chooseSortDirection(value) {
  sortDirection.value = value
  openSelect.value = null
}

function closeSelectOnOutside(event) {
  if (!event.target.closest('[data-document-select]')) openSelect.value = null
}

function closeSelectOnEscape(event) {
  if (event.key === 'Escape') openSelect.value = null
}

const filtered = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  const rows = (docs.value || []).filter(doc => {
    const matchesSearch = !keyword || `${doc.title} ${app.domainLabel(doc.domain)} ${(doc.tags || []).join(' ')}`.toLowerCase().includes(keyword)
    const matchesDomain = domainFilter.value === 'all' || doc.domain === domainFilter.value
    return matchesSearch && matchesDomain
  })
  return [...rows].sort((a, b) => {
    let difference = 0
    if (sortField.value === '资料名称') difference = a.title.localeCompare(b.title, 'zh-CN')
    else if (sortField.value === '知识分块数量') difference = Number(a.chunks || 0) - Number(b.chunks || 0)
    else difference = (importedDate(a.importedAt)?.getTime() || 0) - (importedDate(b.importedAt)?.getTime() || 0)
    return sortDirection.value === '升序' ? difference : -difference
  })
})

const stats = computed(() => {
  const list = docs.value || []
  return {
    all: list.length,
    domains: new Set(list.map(doc => doc.domain)).size,
    chunks: list.reduce((sum, doc) => sum + Number(doc.chunks || 0), 0)
  }
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const pageItems = computed(() => {
  const total = pageCount.value
  const visible = new Set([1, total])
  if (total <= 7) {
    for (let number = 1; number <= total; number += 1) visible.add(number)
  } else if (page.value <= 4) {
    for (let number = 2; number <= 5; number += 1) visible.add(number)
  } else if (page.value >= total - 3) {
    for (let number = total - 4; number < total; number += 1) visible.add(number)
  } else {
    for (let number = page.value - 1; number <= page.value + 1; number += 1) visible.add(number)
  }
  const numbers = [...visible].sort((a, b) => a - b)
  const items = []
  numbers.forEach((number, index) => {
    if (index && number - numbers[index - 1] === 2) items.push({ type: 'page', number: number - 1 })
    else if (index && number - numbers[index - 1] > 2) items.push({ type: 'ellipsis', key: `gap-${index}` })
    items.push({ type: 'page', number })
  })
  return items
})
const pageStart = computed(() => filtered.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const pageEnd = computed(() => Math.min(page.value * pageSize.value, filtered.value.length))

function choosePageSize(size) {
  pageSize.value = size
  openSelect.value = null
}
const allPageSelected = computed(() => paged.value.length > 0 && paged.value.every(doc => selected.value.includes(doc.id)))
const somePageSelected = computed(() => paged.value.some(doc => selected.value.includes(doc.id)) && !allPageSelected.value)

async function loadDocuments() {
  loading.value = true
  try {
    const result = await documentsApi.list()
    docs.value = result.items || []
  } catch (error) {
    ui.toast(error?.message || '资料加载失败', 'error')
    docs.value = []
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  document.addEventListener('pointerdown', closeSelectOnOutside)
  document.addEventListener('keydown', closeSelectOnEscape)
  app.load()
  await loadDocuments()
  progressTimer = window.setInterval(refreshDocumentProgress, 500)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', closeSelectOnOutside)
  document.removeEventListener('keydown', closeSelectOnEscape)
  if (progressTimer) window.clearInterval(progressTimer)
})

watch([search, domainFilter, sortField, sortDirection, pageSize], () => { page.value = 1 })
watch(pageCount, count => { page.value = Math.min(page.value, count) })

async function upload() {
  if (!selectedFiles.value.length) return ui.toast('请先选择需要导入的资料', 'info')
  uploading.value = true
  progress.value = 0
  try {
    const files = [...selectedFiles.value]
    const failed = []
    let next = 0
    let completed = 0
    const worker = async () => {
      while (next < files.length) {
        const file = files[next++]
        try {
          const form = new FormData()
          form.append('file', file)
          form.append('domain', uploadDomain.value)
          const imported = await documentsApi.importFile(form)
          docs.value.unshift(imported)
        } catch (error) {
          failed.push(file)
        } finally {
          completed += 1
          progress.value = Math.round((completed / files.length) * 100)
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(3, files.length) }, worker))
    selectedFiles.value = failed
    uploadOpen.value = failed.length > 0
    ui.toast(failed.length ? `${files.length - failed.length} 份已保存，${failed.length} 份上传失败，可重试` : '文件已保存，可在列表中点击向量化', failed.length ? 'error' : 'success')
  } finally {
    uploading.value = false
  }
}

function selectUploadFiles(event) {
  selectedFiles.value = [...event.target.files]
}

async function openPreview(doc) {
  try {
    preview.value = { ...doc, chunks: [], relatedWiki: [] }
    previewTab.value = 'summary'
    const detail = await documentsApi.get(doc.id)
    preview.value = { ...detail, chunkCount: doc.chunks }
  } catch (error) {
    ui.toast(error?.message || '资料详情加载失败', 'error')
    preview.value = null
  }
}

function askAboutDocument() {
  router.push({ path: '/', query: { context: 'document', id: preview.value.id } })
}

async function remove() {
  const target = deleteTarget.value
  try {
    await documentsApi.remove(target.id)
    docs.value = (docs.value || []).filter(doc => doc.id !== target.id)
    selected.value = selected.value.filter(item => item !== target.id)
    ui.toast('资料已删除')
  } catch (error) {
    ui.toast(error?.message || '删除失败', 'error')
  } finally {
    deleteTarget.value = null
  }
}

function toggleAll(event) {
  const pageIds = new Set(paged.value.map(doc => doc.id))
  selected.value = event.target.checked
    ? [...new Set([...selected.value, ...pageIds])]
    : selected.value.filter(id => !pageIds.has(id))
}

function toggleBatchMode() {
  batchMode.value = !batchMode.value
  selected.value = []
}

async function removeSelected() {
  if (!selected.value.length || deletingBatch.value) return
  deletingBatch.value = true
  let removed = 0
  try {
    for (const id of [...selected.value]) {
      await documentsApi.remove(id)
      docs.value = docs.value.filter(doc => doc.id !== id)
      selected.value = selected.value.filter(item => item !== id)
      removed += 1
    }
    batchMode.value = false
    ui.toast(`已删除 ${removed} 份资料`)
  } catch (error) {
    ui.toast(error?.message || '批量删除未完成，请重试', 'error')
  } finally {
    batchDeleteOpen.value = false
    deletingBatch.value = false
  }
}
</script>

<template>
  <PageShell immersive>
    <div class="doc-knowledge-shell">
      <header class="doc-inline-header">
        <div>
          <span><i />MINDPILOT WORKSPACE</span>
          <h1>知识资料</h1>
          <p>导入本地文档并按知识域整理，成为 智能知识管家检索与引用的原文来源。</p>
        </div>
        <button class="btn doc-upload-button" @click="uploadOpen = true"><Upload :size="18" />导入资料</button>
      </header>

      <main class="doc-knowledge-content">
        <section class="knowledge-mode-panel">
          <div class="knowledge-mode-copy">
            <span><Sparkles :size="20" /></span>
            <div>
              <small>个人知识库</small>
              <h2>按知识域整理资料</h2>
              <p>以个人学习、阅读笔记、工作资料等知识域归类资料，保留可引用的原文分块。</p>
            </div>
          </div>
          <div class="knowledge-mode-selector fixed">
            <div class="knowledge-current-mode wiki">
              <span><Database :size="21" /></span>
              <div>
                <small>当前索引后端</small>
                <strong>ChromaDB + SQLite</strong>
                <p>向量库与元数据均保存在本地</p>
              </div>
              <em><CheckCircle2 :size="15" />服务可用</em>
            </div>
          </div>
        </section>

        <section class="doc-stats knowledge-stats">
          <div><span class="stat-icon blue"><FileText :size="22" /></span><p><small>资料总数</small><strong>{{ stats.all }}</strong></p></div>
          <div><span class="stat-icon green"><Layers :size="22" /></span><p><small>知识域</small><strong>{{ stats.domains }}</strong></p></div>
          <div><span class="stat-icon orange"><Clock3 :size="22" /></span><p><small>知识分块</small><strong>{{ stats.chunks }}</strong></p></div>
        </section>

        <section class="document-library-panel">
          <header>
            <div>
              <h2>本地资料库</h2>
              <p>每份资料保留原文与分块，回答时按引用回到原文；受限知识域的资料不会进入云端索引</p>
            </div>
            <button class="knowledge-batch-toggle" :class="{ active: batchMode }" @click="toggleBatchMode">
              <CheckCircle2 :size="17" />{{ batchMode ? '完成批量处理' : '批量处理' }}
            </button>
          </header>

          <div class="knowledge-doc-toolbar">
            <label class="doc-search-field"><span>搜索资料</span><span class="doc-search-input"><Search :size="18" /><input v-model="search" placeholder="名称、标签或关键词" /></span></label>
            <div class="doc-select-field" data-document-select>
              <span class="doc-select-label">知识域</span>
              <button type="button" class="doc-select-trigger" :class="{ active: openSelect === 'domain' }" :aria-expanded="openSelect === 'domain'" aria-controls="document-domain-options" @click="toggleSelect('domain')">
                <span>{{ selectedDomainLabel }}</span><ChevronDown :size="17" />
              </button>
              <div v-if="openSelect === 'domain'" id="document-domain-options" class="doc-select-menu" role="group" aria-label="知识域选项">
                <button type="button" :class="{ selected: domainFilter === 'all' }" @click="chooseDomain('all')"><span>全部知识域</span><CheckCircle2 v-if="domainFilter === 'all'" :size="16" /></button>
                <button v-for="item in app.domains" :key="item.id" type="button" :class="{ selected: domainFilter === item.id }" @click="chooseDomain(item.id)"><span>{{ item.label }}</span><CheckCircle2 v-if="domainFilter === item.id" :size="16" /></button>
              </div>
            </div>
            <div class="doc-select-field" data-document-select>
              <span class="doc-select-label">排序</span>
              <button type="button" class="doc-select-trigger" :class="{ active: openSelect?.startsWith('sort-') }" :aria-expanded="openSelect?.startsWith('sort-')" aria-controls="document-sort-options" @click="toggleSelect('sort-field')">
                <span>{{ sortField }} · {{ sortDirection }}</span><ChevronDown :size="17" />
              </button>
              <div v-if="openSelect === 'sort-field'" id="document-sort-options" class="doc-select-menu" role="group" aria-label="排序字段">
                <p class="doc-select-menu-title">选择排序字段</p>
                <button v-for="option in sortOptions" :key="option" type="button" :class="{ selected: sortField === option }" @click="chooseSortField(option)"><span>{{ option }}</span><CheckCircle2 v-if="sortField === option" :size="16" /></button>
              </div>
              <div v-else-if="openSelect === 'sort-direction'" id="document-sort-options" class="doc-select-menu" role="group" aria-label="排序方向">
                <button type="button" class="doc-select-back" @click="openSelect = 'sort-field'">‹ 返回排序字段</button>
                <p class="doc-select-menu-title">{{ sortField }}的排序方向</p>
                <button v-for="option in directionOptions" :key="option" type="button" :class="{ selected: sortDirection === option }" @click="chooseSortDirection(option)"><span>{{ option }}</span><CheckCircle2 v-if="sortDirection === option" :size="16" /></button>
              </div>
            </div>
          </div>

          <div v-if="batchMode" class="knowledge-batch-bar">
            <span>{{ selected.length ? `已选择 ${selected.length} 份资料` : '勾选资料后可批量删除' }}</span>
            <button type="button" class="batch-cancel" @click="toggleBatchMode"><X :size="14" />取消</button>
            <button class="danger" :disabled="!selected.length" @click="batchDeleteOpen = true"><Trash2 :size="14" />删除所选</button>
          </div>

          <div v-if="loading" class="doc-loading"><LoaderCircle class="spin" :size="26" /><span>正在读取本地资料库</span></div>

          <div v-else-if="filtered.length" class="knowledge-table-section">
            <div class="knowledge-table-scroll">
            <table class="knowledge-doc-table">
              <thead>
                <tr>
                  <th v-if="batchMode" class="doc-check-cell"><label class="doc-select-all"><input type="checkbox" aria-label="全选当前页" :checked="allPageSelected" :indeterminate="somePageSelected" @change="toggleAll" /><span>全选</span></label></th>
                  <th>资料名称</th>
                  <th>知识域</th>
                  <th>知识分块</th>
                  <th>向量化状态</th>
                  <th>Wiki状态</th>
                  <th>导入时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="doc in paged" :key="doc.id">
                  <td v-if="batchMode" class="doc-check-cell"><input v-model="selected" type="checkbox" :value="doc.id" :aria-label="`选择《${doc.title}》`" /></td>
                  <td>
                    <div class="knowledge-file-name">
                      <span :class="doc.type"><FileText :size="20" /></span>
                      <p>
                        <strong>{{ doc.title }}</strong>
                        <small>{{ doc.size }} · {{ doc.version }}</small>
                      </p>
                    </div>
                  </td>
                  <td><span class="doc-domain-chip" :class="app.domain(doc.domain)?.color">{{ app.domainLabel(doc.domain) }}</span></td>
                  <td><span class="doc-chunk-count"><strong>{{ Number(doc.chunks || 0) > 0 ? Number(doc.chunks) : '—' }}</strong></span></td>
                  <td>
                    <div class="doc-vector-status" :class="doc.status">
                      <div class="doc-vector-status-label">
                        <LoaderCircle v-if="activeDocumentStatuses.includes(doc.status)" class="spin" :size="14" />
                        <CheckCircle2 v-else-if="doc.status === 'ready'" :size="14" />
                        <span v-else class="doc-vector-dot" />
                        <strong>{{ vectorStatusLabel(doc) }}</strong>
                      </div>
                      <div class="doc-vector-steps" :aria-label="vectorStatusLabel(doc)">
                        <span v-for="(step, index) in vectorSteps" :key="step" :class="{ done: vectorStep(doc) > index, current: vectorStep(doc) === index }" :title="step" />
                      </div>
                      <small v-if="doc.status === 'embedding'">{{ doc.indexedChunks || 0 }} / {{ doc.chunks }}</small>
                      <small v-else-if="doc.status === 'failed'" :title="doc.errorMessage">{{ doc.errorMessage || '请重试' }}</small>
                    </div>
                  </td>
                  <td><div class="doc-vector-status doc-wiki-status" :class="{ready:doc.wikiStatus==='done',failed:doc.wikiStatus==='failed'}"><div class="doc-vector-status-label"><LoaderCircle v-if="activeWikiStatuses.includes(doc.wikiStatus)" :size="14" class="spin"/><CheckCircle2 v-else-if="doc.wikiStatus==='done'" :size="14"/><span v-else class="doc-vector-dot"/><strong>{{doc.wikiStatus==='done'?'编译完成':'未编译'}}</strong></div><div class="doc-vector-steps"><span :class="{done:doc.wikiStatus==='done',current:activeWikiStatuses.includes(doc.wikiStatus)}"/></div><small v-if="activeWikiStatuses.includes(doc.wikiStatus)">{{doc.wikiCompletedBatches||0}} / {{doc.wikiTotalBatches||'—'}}</small><small v-else-if="doc.sourceAvailable===false" :title="doc.wikiErrorMessage||'原始文件缺失，请重新上传'">原始文件缺失，请重新上传</small><small v-else-if="wikiSupplementActive(doc)">后台补充知识中</small><small v-else-if="doc.wikiSupplementStatus==='failed'" :title="doc.wikiSupplementError">补充未完成</small><small v-else-if="doc.wikiSupplementCount">已补充 {{doc.wikiSupplementCount}} 次</small><small v-else-if="doc.wikiStatus==='failed'" :title="doc.wikiErrorMessage">{{doc.wikiErrorMessage||'请重试'}}</small></div></td>
                  <td>{{ formatImportedAt(doc.importedAt) }}</td>
                  <td>
                    <div class="knowledge-row-actions">
                      <button data-tooltip="查看详情" @click="openPreview(doc)"><Eye :size="17" /></button>
                      <button data-tooltip="向 智能知识管家提问" @click="router.push({ path: '/', query: { context: 'document', id: doc.id } })"><MessagesSquare :size="17" /></button>
                      <span class="vectorize-action-wrap" :data-tooltip="wikiActionLabel(doc)"><button class="wiki-compile-action" :disabled="doc.sourceAvailable===false||wikiSupplementActive(doc)||doc.wikiStatus==='done'||activeWikiStatuses.includes(doc.wikiStatus)" :aria-label="`${doc.title}：${wikiActionLabel(doc)}`" @click="compileWiki(doc)"><LoaderCircle v-if="activeWikiStatuses.includes(doc.wikiStatus)||wikiSupplementActive(doc)" class="spin" :size="17"/><CheckCircle2 v-else-if="doc.wikiStatus==='done'" :size="17"/><BookOpenText v-else :size="17"/></button></span>
                      <span class="vectorize-action-wrap" :data-tooltip="doc.status === 'ready' ? '已向量化完成' : doc.status === 'failed' ? '重试向量化' : '开始向量化'">
                        <button class="vectorize-action" :disabled="doc.status === 'ready' || activeDocumentStatuses.includes(doc.status)" :aria-label="`${doc.title}：${doc.status === 'ready' ? '已向量化完成' : doc.status === 'failed' ? '重试向量化' : '开始向量化'}`" @click="vectorize(doc)"><LoaderCircle v-if="activeDocumentStatuses.includes(doc.status)" class="spin" :size="17" /><CheckCircle2 v-else-if="doc.status === 'ready'" :size="17" /><Layers v-else :size="17" /></button>
                      </span>
                      <button class="danger" data-tooltip="删除资料" @click="deleteTarget = doc"><Trash2 :size="17" /></button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
            </div>
            <footer class="doc-pagination">
              <span class="doc-pagination-summary">共 {{ filtered.length }} 份资料 <i /> 显示 {{ pageStart }}–{{ pageEnd }} 份</span>
              <div class="doc-pagination-controls">
                <button type="button" class="doc-page-step" :disabled="page === 1" @click="page -= 1"><ChevronLeft :size="15" />上一页</button>
                <div class="doc-page-numbers" aria-label="资料页码">
                  <template v-for="item in pageItems" :key="item.type === 'page' ? `page-${item.number}` : item.key">
                    <button v-if="item.type === 'page'" type="button" class="doc-page-number" :class="{ active: page === item.number }" :aria-label="`第 ${item.number} 页`" :aria-current="page === item.number ? 'page' : undefined" @click="page = item.number">{{ item.number }}</button>
                    <span v-else class="doc-page-ellipsis" aria-hidden="true">…</span>
                  </template>
                </div>
                <button type="button" class="doc-page-step" :disabled="page === pageCount" @click="page += 1">下一页<ChevronRight :size="15" /></button>
                <div class="doc-page-size" data-document-select>
                  <span>每页</span>
                  <button type="button" class="doc-page-size-trigger" :class="{ active: openSelect === 'page-size' }" :aria-expanded="openSelect === 'page-size'" aria-controls="document-page-size-options" @click="toggleSelect('page-size')">{{ pageSize }} 条<ChevronDown :size="15" /></button>
                  <div v-if="openSelect === 'page-size'" id="document-page-size-options" class="doc-select-menu doc-page-size-menu" role="group" aria-label="每页资料数量">
                    <button v-for="size in pageSizes" :key="size" type="button" :class="{ selected: pageSize === size }" @click="choosePageSize(size)"><span>{{ size }} 条 / 页</span><CheckCircle2 v-if="pageSize === size" :size="15" /></button>
                  </div>
                </div>
              </div>
            </footer>
          </div>
          <div v-else class="empty-state">
            <BookOpenText :size="40" />
            <h3>没有找到匹配的资料</h3>
            <p>调整搜索或筛选条件，也可以导入一份新资料。</p>
            <button class="btn" @click="uploadOpen = true">导入资料</button>
          </div>
        </section>
      </main>

      <Transition name="modal">
        <div v-if="uploadOpen" class="modal-mask" @click.self="uploadOpen = false">
          <section class="modal-card upload-modal knowledge-upload-modal">
            <button class="icon-btn modal-close" @click="uploadOpen = false"><X :size="18" /></button>
            <span class="eyebrow">LOCAL DOCUMENT</span>
            <h3>导入本地资料</h3>
            <p>支持PDF、TXT和Markdown。请选择资料所属的知识域。</p>
            <label class="drop-zone">
              <input hidden type="file" multiple accept=".pdf,.txt,.md,.markdown" @change="selectUploadFiles" />
              <span><CloudUpload :size="27" /></span>
              <strong>{{ selectedFiles.length ? `已选择 ${selectedFiles.length} 份资料` : '点击或拖拽文件到这里' }}</strong>
              <small>{{ selectedFiles.length ? selectedFiles.map(file => file.name).join('、') : '单个文件最大50 MB' }}</small>
            </label>
            <div class="upload-domain-field">
              <span>知识域</span>
              <div class="upload-domain-options" role="radiogroup" aria-label="选择知识域">
                <button v-for="item in app.domains" :key="item.id" type="button" class="upload-domain-option" :class="[{ selected: uploadDomain === item.id }, item.color]" role="radio" :aria-checked="uploadDomain === item.id" @click="uploadDomain = item.id">
                  <span class="upload-domain-option-icon"><Layers :size="15" /></span>
                  <span><strong>{{ item.label }}</strong><small>{{ item.description }}</small></span>
                  <CheckCircle2 v-if="uploadDomain === item.id" class="upload-domain-option-check" :size="17" />
                </button>
              </div>
            </div>
            <div v-if="uploading" class="upload-progress">
              <div><span :style="{ width: progress + '%' }" /></div>
              <small>{{ progress }}% · 正在保存原始文档</small>
            </div>
            <div class="upload-pending-note">
              <Clock3 :size="16" />
              <span>上传只保存文件；请在资料列表点击“向量化”，再进行解析、切分和索引。</span>
            </div>
            <div class="modal-actions">
              <button class="btn secondary" @click="uploadOpen = false">取消</button>
              <button class="btn" :disabled="uploading || !selectedFiles.length" @click="upload"><Upload :size="16" />{{ uploading ? '导入中' : '导入资料' }}</button>
            </div>
          </section>
        </div>
      </Transition>

      <Transition name="modal">
        <div v-if="preview" class="modal-mask" @click.self="preview = null">
          <section class="modal-card doc-preview knowledge-preview">
            <button class="icon-btn modal-close" @click="preview = null"><X :size="18" /></button>
            <div class="preview-title">
              <span><FileText :size="23" /></span>
              <div>
                <h3>{{ preview.title }}</h3>
                <p>{{ app.domainLabel(preview.domain) }} · {{ preview.size }} · {{ preview.pages }} 页 · {{ formatImportedAt(preview.importedAt) }}</p>
              </div>
            </div>
            <div class="preview-tabs">
              <button :class="{ active: previewTab === 'summary' }" @click="previewTab = 'summary'">摘要</button>
              <button :class="{ active: previewTab === 'chunks' }" @click="previewTab = 'chunks'">原文分块</button>
              <button :class="{ active: previewTab === 'wiki' }" @click="previewTab = 'wiki'">关联Wiki</button>
            </div>
            <div v-if="previewTab === 'summary'" class="preview-content">
              <h4>资料摘要</h4>
              <p>{{ preview.summary }}</p>
              <h4>元信息</h4>
              <p>{{ preview.author }} · {{ preview.year }} · {{ preview.source }}</p>
              <p v-if="preview.tags?.length">标签：{{ preview.tags.join(' / ') }}</p>
              <p class="preview-hash">内容指纹 {{ preview.contentHash }} · {{ preview.version }}</p>
              <p>知识分块：{{ Number(preview.chunkCount || 0) }} 个</p>
            </div>
            <div v-else-if="previewTab === 'chunks'" class="preview-content">
              <div v-if="preview.chunks?.length" class="preview-chunk-list">
                <article v-for="chunk in preview.chunks" :key="chunk.id">
                  <small>第 {{ chunk.page }} 页 · {{ chunk.section }}</small>
                  <p>{{ chunk.text }}</p>
                </article>
              </div>
              <p v-else>该资料暂无可展示的原文分块。</p>
            </div>
            <div v-else class="preview-content">
              <pre v-if="preview.wikiMarkdown" class="doc-wiki-markdown">{{preview.wikiMarkdown}}</pre>
              <div v-if="preview.relatedWiki?.length" class="preview-chunk-list">
                <article v-for="page in preview.relatedWiki" :key="page.pageId">
                  <small><Network :size="13" />Wiki页面</small>
                  <p>{{ page.title || page.pageId }}</p>
                </article>
              </div>
              <p v-else>这份资料还没有编译进任何Wiki页面。</p>
            </div>
            <div class="modal-actions">
              <button class="btn secondary" @click="preview = null">关闭</button>
              <button class="btn" @click="askAboutDocument"><MessagesSquare :size="16" />向它提问</button>
            </div>
          </section>
        </div>
      </Transition>

      <ConfirmModal
        :open="!!deleteTarget"
        title="删除该资料？"
        :message="`将同时删除《${deleteTarget?.title || ''}》的原文分块、向量索引与Wiki编译初稿。`"
        confirm-text="确认删除"
        danger
        @cancel="deleteTarget = null"
        @confirm="remove"
      />
      <ConfirmModal
        :open="batchDeleteOpen"
        title="批量删除资料？"
        :message="`将删除选中的 ${selected.length} 份资料及其本地记录。`"
        confirm-text="确认删除"
        danger
        @cancel="batchDeleteOpen = false"
        @confirm="removeSelected"
      />
    </div>
  </PageShell>
</template>

<style scoped>
.knowledge-stats{grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.knowledge-stats>div{min-height:112px;border-color:#e5dcf0;background:linear-gradient(145deg,#fff,#faf8fd);box-shadow:0 10px 30px rgba(51,18,92,.055)}
.knowledge-stats .stat-icon{width:50px;height:50px;flex:0 0 50px;border-radius:16px}
.knowledge-stats p{gap:7px}.knowledge-stats small{font-size:13px;color:#827197}.knowledge-stats strong{font-size:32px;color:#2c1745;font-variant-numeric:tabular-nums}

.knowledge-doc-toolbar{display:grid;grid-template-columns:minmax(230px,1fr) minmax(170px,220px) minmax(170px,220px);align-items:end;gap:12px;padding:17px 20px 20px;min-height:0}
.knowledge-doc-toolbar>.doc-search-field,.knowledge-doc-toolbar>.doc-filter-field{width:auto;height:auto;max-width:none;min-width:0;display:grid;gap:7px;padding:0;border:0;border-radius:0;background:transparent;box-shadow:none;color:#7c6b91}
.doc-search-field>span:first-child,.doc-filter-field>span:first-child{font-size:12px;font-weight:700;color:#74628a}
.doc-search-input{height:44px;display:flex;align-items:center;gap:9px;padding:0 13px;border:1px solid #e2d9ee;border-radius:11px;background:#fff;color:#8b6fad;transition:border-color .18s,box-shadow .18s}
.doc-search-input:focus-within{border-color:#a375dc;box-shadow:0 0 0 3px rgba(89,17,177,.1)}
.knowledge-doc-toolbar .doc-search-input input{min-width:0;width:100%;font-size:13px}
.doc-filter-field select{width:100%;height:44px;padding:0 11px;border:1px solid #e2d9ee;border-radius:11px;outline:0;background:#fff;color:#493166;font-size:13px;font-weight:600;cursor:pointer}
.doc-filter-field select:focus-visible{border-color:#a375dc;box-shadow:0 0 0 3px rgba(89,17,177,.1)}
.doc-select-field{position:relative;min-width:0;display:grid;gap:7px}
.doc-select-label{font-size:12px;font-weight:700;color:#74628a}
.doc-select-trigger{width:100%;height:44px;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 13px;border:1px solid #e2d9ee;border-radius:11px;background:#fff;color:#493166;font-size:13px;font-weight:700;text-align:left;cursor:pointer;transition:border-color .18s,box-shadow .18s,background .18s}
.doc-select-trigger:hover,.doc-select-trigger.active{border-color:#a172da;background:#fdfbff;box-shadow:0 0 0 3px rgba(89,17,177,.08)}
.doc-select-trigger:focus-visible,.doc-select-menu button:focus-visible{outline:2px solid #8e56d2;outline-offset:2px}
.doc-select-trigger>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.doc-select-trigger svg{flex:none;transition:transform .18s}.doc-select-trigger.active svg{transform:rotate(180deg)}
.doc-select-menu{position:absolute;top:calc(100% + 8px);left:0;right:0;z-index:90;min-width:200px;max-height:290px;overflow-y:auto;padding:7px;border:1px solid #e5dcf0;border-radius:13px;background:#fff;box-shadow:0 16px 34px rgba(52,23,88,.17)}
.doc-select-menu-title{margin:3px 8px 7px;color:#91a3ad;font-size:11px;font-weight:700}
.doc-select-menu button{width:100%;min-height:37px;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border:1px solid transparent;border-radius:8px;background:transparent;color:#553f70;font-size:12px;font-weight:600;text-align:left;cursor:pointer;transition:background .15s,border-color .15s,color .15s}
.doc-select-menu button:hover:not(.selected){background:#f4f2f6;color:#493166}
.doc-select-menu button.selected,.doc-select-menu button.selected:hover{border-color:#b48fe2;background:#ebdff9;box-shadow:inset 3px 0 0 #5108aa;color:#410689;font-weight:750}
.doc-select-menu button svg{flex:none;color:#530aad}
.doc-select-menu .doc-select-back{justify-content:flex-start;margin-bottom:4px;color:#8e7ea2;font-size:11px}
.knowledge-batch-toggle{margin-left:auto}.knowledge-batch-bar{margin:12px 20px;padding:11px 14px;border:1px solid #e2d4f4;border-radius:11px;background:#f6f2fc}
.knowledge-batch-bar .danger{color:#b63a4b;border:1px solid #f5d6dc;background:#fff5f6;font-weight:700}
.knowledge-batch-bar .batch-cancel{border:1px solid #e2d9ee;color:#66527f;background:#fff;font-weight:700;cursor:pointer}.knowledge-batch-bar .batch-cancel:hover{border-color:#b08bdd;background:#faf8fd}
.knowledge-table-section{min-width:0}.knowledge-table-scroll{overflow-x:auto;border-radius:0}
.knowledge-doc-table{min-width:1280px;table-layout:fixed}.knowledge-doc-table th,.knowledge-doc-table td{vertical-align:middle}
.knowledge-doc-table th:nth-last-child(7),.knowledge-doc-table td:nth-last-child(7){width:27%}
.knowledge-doc-table th:nth-last-child(6),.knowledge-doc-table td:nth-last-child(6){width:10%;text-align:center}
.knowledge-doc-table th:nth-last-child(5),.knowledge-doc-table td:nth-last-child(5){width:8%}
.knowledge-doc-table th:nth-last-child(4),.knowledge-doc-table td:nth-last-child(4){width:15%}
.knowledge-doc-table th:nth-last-child(3),.knowledge-doc-table td:nth-last-child(3){width:13%}
.knowledge-doc-table th:nth-last-child(2),.knowledge-doc-table td:nth-last-child(2){width:14%;white-space:nowrap}
.knowledge-doc-table th:last-child,.knowledge-doc-table td:last-child{width:13%;text-align:center}
.knowledge-doc-table th:nth-last-child(5),.knowledge-doc-table td:nth-last-child(5),
.knowledge-doc-table th:nth-last-child(4),.knowledge-doc-table td:nth-last-child(4),
.knowledge-doc-table th:nth-last-child(3),.knowledge-doc-table td:nth-last-child(3),
.knowledge-doc-table th:nth-last-child(2),.knowledge-doc-table td:nth-last-child(2){text-align:center}
.knowledge-doc-table th.doc-check-cell,.knowledge-doc-table td.doc-check-cell{width:72px;padding-left:16px;padding-right:0}
.doc-select-all{display:flex;align-items:center;gap:5px;white-space:nowrap;cursor:pointer}
.knowledge-doc-table td{height:108px;padding-top:16px;padding-bottom:16px}
.knowledge-file-name{min-width:0}.knowledge-file-name p{min-width:0}.knowledge-file-name strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}
.doc-chunk-count{display:inline-flex;align-items:baseline;color:#533b70;white-space:nowrap}.doc-chunk-count strong{font-size:17px;font-variant-numeric:tabular-nums}
.doc-vector-status{display:grid;gap:7px;min-width:0}.doc-vector-status-label{display:flex;align-items:center;gap:6px;color:#837199;font-size:12px}.doc-vector-status-label strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:700}.doc-vector-status .spin{animation:doc-spin .9s linear infinite}.doc-vector-dot{width:8px;height:8px;border-radius:50%;background:#ac9ebe}.doc-vector-steps{display:flex;gap:4px;max-width:155px}.doc-vector-steps span{height:4px;flex:1;border-radius:10px;background:#e9e3f0}.doc-vector-steps span.done{background:#5f21aa}.doc-vector-steps span.current{background:#4d09a1;box-shadow:0 0 0 2px #e6d8f7}.doc-vector-status small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#816f98;font-size:11px}.doc-vector-status.ready .doc-vector-status-label{color:#4b168b}.doc-vector-status.failed .doc-vector-status-label,.doc-vector-status.failed small{color:#b74d57}.doc-vector-status.parsing .doc-vector-status-label,.doc-vector-status.chunking .doc-vector-status-label,.doc-vector-status.embedding .doc-vector-status-label{color:#4a089b}
.doc-vector-status{justify-items:center}.doc-vector-status-label{justify-content:center;max-width:100%}.doc-vector-steps{width:min(100%,155px)}.doc-vector-status small{max-width:100%}
.knowledge-row-actions{display:flex;align-items:center;justify-content:center;gap:3px;white-space:nowrap}.knowledge-row-actions button{width:32px;height:32px;display:inline-flex;align-items:center;justify-content:center;flex:none;color:#816f98}.knowledge-row-actions button:hover{background:#f1eaf9}.vectorize-action-wrap{display:inline-flex;align-items:center;justify-content:center;flex:none}.knowledge-row-actions .vectorize-action{color:#4a089b}.knowledge-row-actions .vectorize-action:disabled{opacity:.58;cursor:default;background:transparent}
.doc-pagination{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:17px 20px;border-top:1px solid #ebe6f2;color:#88789c;background:#fcfbfe;border-radius:0 0 22px 22px;font-size:12px}
.doc-pagination-summary{display:flex;align-items:center;gap:9px;white-space:nowrap}.doc-pagination-summary i{width:3px;height:3px;border-radius:50%;background:#b2a5c3}
.doc-pagination-controls,.doc-page-numbers{display:flex;align-items:center;gap:6px}.doc-pagination-controls{flex-wrap:wrap;justify-content:flex-end;margin-left:auto}
.doc-pagination .doc-page-step,.doc-pagination .doc-page-number,.doc-pagination .doc-page-size-trigger{height:36px;display:inline-flex;align-items:center;justify-content:center;gap:4px;border:1px solid #e5dcf0;border-radius:9px;background:#fff;color:#55416e;font-size:12px;font-weight:650;cursor:pointer;transition:border-color .15s,background .15s,color .15s,box-shadow .15s}
.doc-pagination .doc-page-step{padding:0 11px}.doc-pagination .doc-page-number{min-width:36px;padding:0 7px;font-variant-numeric:tabular-nums}
.doc-pagination .doc-page-step:hover:not(:disabled),.doc-pagination .doc-page-number:hover:not(.active),.doc-pagination .doc-page-size-trigger:hover{border-color:#bb9be2;background:#f7f3fc;color:#490898}
.doc-pagination .doc-page-number.active{border-color:#490898;background:#490898;color:#fff;box-shadow:0 5px 12px rgba(73,8,152,.18)}
.doc-pagination .doc-page-step:disabled{opacity:.42;cursor:default}.doc-pagination button:focus-visible{outline:2px solid #8e56d2;outline-offset:2px}
.doc-page-ellipsis{min-width:23px;text-align:center;color:#a696b9;font-size:16px;line-height:1}
.doc-page-size{position:relative;display:flex;align-items:center;gap:8px;margin-left:9px;white-space:nowrap;color:#7b6991;font-weight:650}
.doc-pagination .doc-page-size-trigger{min-width:91px;justify-content:space-between;padding:0 9px 0 12px;color:#493166}.doc-pagination .doc-page-size-trigger.active{border-color:#a172da;box-shadow:0 0 0 3px rgba(89,17,177,.08)}.doc-page-size-trigger svg{transition:transform .18s}.doc-page-size-trigger.active svg{transform:rotate(180deg)}
.doc-page-size-menu{top:auto;bottom:calc(100% + 9px);left:auto;right:0;min-width:154px;max-height:none}.doc-pagination .doc-page-size-menu button{height:37px;min-width:0;width:100%;justify-content:space-between;padding:8px 10px;border:1px solid transparent;border-radius:8px;background:transparent;color:#553f70;text-align:left;font-size:12px;font-weight:600}.doc-pagination .doc-page-size-menu button:hover:not(.selected){background:#f4f2f6;color:#493166}.doc-pagination .doc-page-size-menu button.selected,.doc-pagination .doc-page-size-menu button.selected:hover{border-color:#b48fe2;background:#ebdff9;box-shadow:inset 3px 0 0 #5108aa;color:#410689;font-weight:750}
@media(max-width:900px){.knowledge-doc-toolbar{grid-template-columns:repeat(2,minmax(0,1fr))}.knowledge-doc-toolbar>.doc-search-field{grid-column:1/-1}}
@media(max-width:700px){.knowledge-stats{grid-template-columns:1fr 1fr}.knowledge-stats>div:last-child{grid-column:1/-1}.doc-pagination{align-items:flex-start;flex-direction:column}.doc-pagination-controls{justify-content:flex-start;margin-left:0}}
@media(max-width:480px){.knowledge-doc-toolbar{grid-template-columns:1fr}}
.doc-loading{display:flex;align-items:center;justify-content:center;gap:11px;padding:56px 0;color:var(--muted);font-size:14px}
.doc-loading .spin{animation:doc-spin .9s linear infinite;color:var(--brand)}
@keyframes doc-spin{to{transform:rotate(360deg)}}

.doc-domain-chip{display:inline-flex;align-items:center;padding:4px 10px;border-radius:8px;font-size:12px;font-weight:650;background:var(--brand-soft);color:var(--brand-strong);white-space:nowrap}
.doc-domain-chip.cyan{background:#f1e8fb;color:#561d9c}
.doc-domain-chip.violet{background:#f4eefb;color:#4b0f94}
.doc-domain-chip.amber{background:#fdf3e3;color:#9a6a16}
.upload-domain-field{display:grid;gap:8px;margin:0 0 14px;color:#74628a;font-size:12px;font-weight:700}.upload-domain-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.upload-domain-option{position:relative;min-width:0;display:flex;align-items:center;gap:9px;padding:10px 11px;border:1px solid #e2d9ee;border-radius:12px;background:#fff;color:#493166;text-align:left;cursor:pointer;transition:border-color .18s,background .18s,box-shadow .18s,transform .18s}.upload-domain-option:hover{border-color:#ac83df;background:#faf7fd;transform:translateY(-1px)}.upload-domain-option.selected{border-color:#560ead;background:linear-gradient(135deg,#f6f0fd,#fff);box-shadow:0 4px 12px rgba(89,17,177,.12)}.upload-domain-option-icon{width:29px;height:29px;display:grid;place-items:center;flex:0 0 29px;border-radius:9px;background:#f3edfa;color:#53179c}.upload-domain-option.violet .upload-domain-option-icon{background:#f1f1fb;color:#6d73b6}.upload-domain-option.amber .upload-domain-option-icon{background:#fff5e5;color:#b17b1b}.upload-domain-option span:nth-child(2){min-width:0;display:grid;gap:3px}.upload-domain-option strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.upload-domain-option small{overflow:hidden;color:#998baa;font-size:10px;font-weight:500;text-overflow:ellipsis;white-space:nowrap}.upload-domain-option-check{margin-left:auto;flex:0 0 auto;color:#530baa}.upload-domain-option.selected .upload-domain-option-icon{background:#eadff8;color:#4c07a0}@media(max-width:480px){.upload-domain-options{grid-template-columns:1fr}}

.preview-hash{margin-top:8px;color:var(--muted);font-size:12px;font-family:"MindPilot Latin",ui-monospace,SFMono-Regular,Menlo,monospace}
.doc-wiki-markdown{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto;padding:20px;border:1px solid var(--line);border-radius:14px;background:var(--soft);font:inherit;line-height:1.9;color:var(--ink)}
.knowledge-row-actions .wiki-compile-action{color:#4a089b}.knowledge-row-actions .wiki-compile-action:disabled{opacity:.58;cursor:default;background:transparent}.knowledge-row-actions .spin{animation:doc-spin .9s linear infinite}
.preview-chunk-list{display:grid;gap:11px;max-height:340px;overflow-y:auto;padding-right:4px}
.preview-chunk-list article{padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--soft)}
.preview-chunk-list small{display:flex;align-items:center;gap:5px;color:var(--brand);font-size:11px;font-weight:700}
.preview-chunk-list p{margin:7px 0 0;font-size:14px;line-height:1.8;color:var(--ink)}
</style>
