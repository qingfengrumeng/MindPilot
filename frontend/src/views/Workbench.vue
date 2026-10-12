<script setup>
import AppSelect from '@/components/AppSelect.vue'
import DeleteConfirmation from '@/components/DeleteConfirmation.vue'
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  ArrowRight, Check, ExternalLink, ListChecks, FileUp,
  Flame, LoaderCircle, Pencil, Plus, Search, Trash2, X, ChevronLeft, ChevronRight, ChevronDown, RefreshCw
} from 'lucide-vue-next'
import PageShell from '@/components/PageShell.vue'
import HotSources from '@/components/HotSources.vue'
import { workbenchApi } from '@/api/workbench'
import { documentsApi } from '@/api'
import { hotMarkdownFile } from '@/lib/hotMarkdown'
import { defaultHotPreferences } from '@/lib/hotPreferences'
import { fitHotCardPreviews } from '@/lib/hotCardPreview'
import { sortHotByPublished } from '@/lib/hotChronology'
import { useUiStore } from '@/stores/ui'
import '@/styles/workbench.css'
import '@/styles/workbench-theme.css'

const route = useRoute()
const ui = useUiStore()
const sectionMap = {
  'daily-hot': { title: '每日热点', eyebrow: 'EXTERNAL SIGNALS', subtitle: '记录热点来源和判断，不用演示数据代替真实内容。', icon: Flame, kind: 'hot' },
}
const currentSection = computed(() => {
  const requested = String(route.params.section || 'daily-hot')
  return sectionMap[requested] ? requested : 'daily-hot'
})
const current = computed(() => sectionMap[currentSection.value] || sectionMap['daily-hot'])
const loading = ref(false)
const saving = ref(false)
const syncingHot = ref(false)
const hotSyncStage = ref(''), hotJob = ref(null)
let hotPollTimer = null, hotStatusChecking = false, componentActive = true
const notifiedHotJobs = new Set()
const error = ref('')
const items = ref([])
const batchMode = ref(false), checkedIds = ref([]), deleteTargets = ref(null), deleting = ref(false), deleteError = ref('')
function cancelBatch() { batchMode.value=false;checkedIds.value=[] }
watch(currentSection, () => {cancelBatch();deleteTargets.value=null})
const query = ref('')
const statusFilter = ref('all')
const selected = ref(null)
const importingHot = ref(null), importedHot = reactive({})
async function importHotDocument() {
  const item=selected.value
  if(!item || item.kind!=='hot' || importingHot.value || importedHot[item.id])return
  importingHot.value=item.id
  try {
    const form=new FormData()
    form.append('file',hotMarkdownFile(item,fullHotContent(item)))
    form.append('domain','personal_learning')
    const document=await documentsApi.importFile(form)
    importedHot[item.id]=document.id
    ui.toast('已保存 Markdown 到知识资料，可前往向量化')
  } catch(cause) {ui.toast(cause?.message || '导入知识资料失败，请重试','error')}
  finally {importingHot.value=null}
}
const detailDialog = ref(null)
function fullHotContent(item) {
  if (!item) return ''
  // Old imports stored an attention reason or a short event update as body.
  // Those fields are not article text and must not be presented as full content.
  if (item.kind === 'hot' && item.data?.source === 'AI HOT' &&
      !item.data?.hasFullContent && !item.data?.contentEdited &&
      /(?:^|\n)(?:已进入 AI HOT 精选，可按兴趣浏览，不占用今日必看名额。|\d+ 个独立信源正在跟进[^\n]*|与[^\n]+相关，值得快速了解事实与当前边界。)\s*$/.test(item.body || '')) return ''
  return item.body || ''
}
const selectedFullContent = computed(() => fullHotContent(selected.value))
let detailPreviousFocus, detailPreviousOverflow
const editorOpen = ref(false)
const editingId = ref(null)
let loadVersion = 0
const form = reactive({ title: '', summary: '', body: '', status: 'draft', tags: '', links: [],
  sourceUrl: '', priority: 'browse' })
const statusLabels = { draft: '草稿', active: '进行中', archived: '已归档' }
const statusOptions = ['draft', 'active', 'archived']
const hotPreferences = ref(defaultHotPreferences())
const page = ref(1), pageSize = ref(12)
const cardGrid = ref(null)
let stopPreviewLayout = null
onBeforeUnmount(() => stopPreviewLayout?.())
const pageSizes = [12, 24, 36, 48]
const pageSizeOpen = ref(false), pageSizePicker = ref(null)
function closePageSize(event) {
  if (!pageSizePicker.value?.contains(event.target)) pageSizeOpen.value = false
}
async function togglePageSize() {
  pageSizeOpen.value = !pageSizeOpen.value
  if (pageSizeOpen.value) {
    await nextTick()
    pageSizePicker.value?.querySelector('[aria-selected="true"]')?.focus()
  }
}
function choosePageSize(size) {
  pageSize.value = size
  pageSizeOpen.value = false
  pageSizePicker.value?.querySelector('.wb-page-size-trigger')?.focus()
}
function pageSizeKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); pageSizeOpen.value = false; pageSizePicker.value?.querySelector('.wb-page-size-trigger')?.focus() }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    if (!pageSizeOpen.value) { void togglePageSize(); return }
    const options = [...pageSizePicker.value.querySelectorAll('[role="option"]')]
    const index = options.indexOf(document.activeElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
    options[next]?.focus()
  }
}
window.addEventListener('pointerdown', closePageSize)
const currentStatusOptions = computed(() => currentSection.value === 'daily-hot' ? ['unread', 'read'] : statusOptions)
function itemStatus(item) { return item.kind === 'hot' ? (item.data?.viewedAt ? 'read' : 'unread') : item.status }
function statusLabel(item) { return item.kind === 'hot' ? (item.data?.viewedAt ? '已查看' : '未查看') : statusLabels[item.status] || item.status }
const filteredItems = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase('zh-CN')
  const rows = items.value.filter(item => (statusFilter.value === 'all' || itemStatus(item) === statusFilter.value)
    && (!needle || `${item.title} ${item.summary} ${item.body} ${(item.tags || []).join(' ')}`
      .toLocaleLowerCase('zh-CN').includes(needle)))
  return currentSection.value === 'daily-hot' ? sortHotByPublished(rows) : rows
})
const pageCount = computed(() => Math.max(1, Math.ceil(filteredItems.value.length / pageSize.value)))
const pagedItems = computed(() => currentSection.value === 'daily-hot' ? filteredItems.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value) : filteredItems.value)
const allPageChecked = computed(() => pagedItems.value.length > 0 && pagedItems.value.every(item => checkedIds.value.includes(item.id)))
const somePageChecked = computed(() => !allPageChecked.value && pagedItems.value.some(item => checkedIds.value.includes(item.id)))
function togglePageSelection() {
  const pageIds=new Set(pagedItems.value.map(item=>item.id))
  checkedIds.value=allPageChecked.value ? checkedIds.value.filter(id=>!pageIds.has(id)) : [...new Set([...checkedIds.value,...pageIds])]
}
function requestBatchDelete() { deleteTargets.value=items.value.filter(item=>checkedIds.value.includes(item.id));deleteError.value='' }
watch([pagedItems, loading], async () => {
  await nextTick()
  stopPreviewLayout?.()
  stopPreviewLayout = currentSection.value === 'daily-hot' && cardGrid.value ? fitHotCardPreviews(cardGrid.value) : null
}, { flush: 'post' })
const pageStart = computed(() => filteredItems.value.length ? (page.value - 1) * pageSize.value + 1 : 0)
const pageEnd = computed(() => Math.min(page.value * pageSize.value, filteredItems.value.length))
const pageNumbers = computed(() => {
  const numbers = [...new Set([1, pageCount.value, ...Array.from({length:5}, (_, index) => page.value + index - 2).filter(value => value >= 1 && value <= pageCount.value)])].sort((a,b) => a-b)
  return numbers.flatMap((value, index) => index && value - numbers[index - 1] > 1 ? ['gap-'+value,value] : [value])
})
watch([query, statusFilter, pageSize], () => { page.value = 1 })
watch(pageCount, value => { page.value = Math.min(page.value, value) })
function preferencesChanged(event) { hotPreferences.value = event.detail }
window.addEventListener('mindpilot:hot-preferences', preferencesChanged)
onBeforeUnmount(() => {
  componentActive=false; window.clearTimeout(hotPollTimer)
  window.removeEventListener('pointerdown', closePageSize)
  loadVersion++; window.removeEventListener('mindpilot:hot-preferences', preferencesChanged)
  if (detailPreviousOverflow !== undefined) document.body.style.overflow = detailPreviousOverflow
})
watch(() => selected.value?.kind === 'hot', async open => {
  if (open) {
    detailPreviousFocus = document.activeElement
    detailPreviousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await nextTick(); detailDialog.value?.focus()
  } else if (detailPreviousOverflow !== undefined) {
    document.body.style.overflow = detailPreviousOverflow; detailPreviousOverflow = undefined
    detailPreviousFocus?.focus?.()
  }
})
function detailKeydown(event) {
  if (event.key === 'Escape') selected.value = null
  if (event.key !== 'Tab' || selected.value?.kind !== 'hot') return
  const controls = [...detailDialog.value.querySelectorAll('button,a[href]')]
  if (event.shiftKey && [controls[0],detailDialog.value].includes(document.activeElement)) { event.preventDefault(); controls.at(-1)?.focus() }
  else if (!event.shiftKey && [controls.at(-1),detailDialog.value].includes(document.activeElement)) { event.preventDefault(); controls[0]?.focus() }
}

function dateLabel(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN')
}
async function load() {
  const section = currentSection.value
  const version = ++loadVersion
  error.value = ''
  selected.value = null
  query.value = ''
  statusFilter.value = 'all'
  loading.value = true
  try {
    if (current.value.kind) {
      const rows = []
      let result
      do {
        result = await workbenchApi.items({ kind: sectionMap[section].kind, limit: 500, offset: rows.length })
        if (version !== loadVersion) return
        rows.push(...(result.items || []))
      } while (rows.length < (result.total || 0) && result.items?.length)
      if (version !== loadVersion) return
      items.value = rows
      page.value = 1
      if (section === 'daily-hot') { hotPreferences.value = await workbenchApi.hotPreferences(); void refreshHotStatus() }
    }
  } catch (cause) { if (version === loadVersion) error.value = cause?.message || '工作台加载失败' }
  finally { if (version === loadVersion) loading.value = false }
}
watch(currentSection, load, { immediate: true })
watch(currentSection, () => { window.clearTimeout(hotPollTimer); if(currentSection.value === 'daily-hot') void refreshHotStatus() })

function applyHotJob(job) {
  hotJob.value=job
  syncingHot.value=['queued','running'].includes(job.status)
  hotSyncStage.value=job.detail || '正在获取热点新闻'
}
function scheduleHotStatus() {
  window.clearTimeout(hotPollTimer)
  if(componentActive && currentSection.value==='daily-hot' && syncingHot.value) hotPollTimer=window.setTimeout(refreshHotStatus,1500)
}
async function refreshHotStatus() {
  if(hotStatusChecking || !componentActive || currentSection.value!=='daily-hot')return
  hotStatusChecking=true
  try {
    const job=await workbenchApi.hotSyncStatus()
    if(!componentActive || currentSection.value!=='daily-hot')return
    applyHotJob(job)
    if(['completed','failed'].includes(job.status) && !notifiedHotJobs.has(job.id)) {
      notifiedHotJobs.add(job.id)
      if(job.status==='failed') ui.toast(job.detail || '热点获取失败','error')
      else {
        ui.toast(job.imported ? `已同步 ${job.imported} 条热点${job.requested != null && job.imported<job.requested?'（补搜后按实际数量保存）':''}` : '暂无新热点信息')
        await load()
      }
    }
  } catch(cause) {
    if(componentActive && currentSection.value==='daily-hot') hotSyncStage.value='暂时无法读取进度，后台任务仍在执行'
  } finally {hotStatusChecking=false;scheduleHotStatus()}
}
async function syncDailyHot() {
  if(syncingHot.value)return
  syncingHot.value=true;hotSyncStage.value='正在启动热点获取'
  try {
    const job=await workbenchApi.syncHot()
    if(!componentActive)return
    applyHotJob(job)
    void refreshHotStatus()
  } catch(cause) {
    if(!componentActive)return
    syncingHot.value=false
    ui.toast(cause?.message || '无法启动热点获取，请重试','error')
    void refreshHotStatus()
  } finally {scheduleHotStatus()}
}

function resetForm() {
  Object.assign(form, { title: '', summary: '', body: '', status: 'draft',
    tags: '', links: [], sourceUrl: '', priority: 'browse' })
}
function createEntry() {
  editingId.value = null
  resetForm()
  editorOpen.value = true
}
function editEntry(item) {
  editingId.value = item.id
  Object.assign(form, { title: item.title, summary: item.summary || '', body: fullHotContent(item),
    status: item.status, tags: (item.tags || []).join('，'), links: [...(item.links || [])],
    sourceUrl: item.data?.sourceUrl || '', priority: item.data?.priority || 'browse' })
  editorOpen.value = true
}
async function saveEntry() {
  if (!form.title.trim() || saving.value) return
  saving.value = true
  const previous = items.value.find(item => item.id === editingId.value)
  const data = { ...(previous?.data || {}), sourceUrl: form.sourceUrl.trim(),
    contentEdited: Boolean(form.body.trim()) }
  if (current.value.kind === 'hot' && data.sources?.length && data.sources[0].url !== data.sourceUrl) {
    data.sources = data.sourceUrl ? [{...data.sources[0],url:data.sourceUrl}, ...data.sources.slice(1)] : data.sources.slice(1)
  }
  const payload = { kind: current.value.kind, title: form.title.trim(), summary: form.summary.trim(),
    body: form.body,
    links: [], data }
  try {
    const result = editingId.value
      ? await workbenchApi.update(editingId.value, payload)
      : await workbenchApi.create(payload)
    items.value = [result, ...items.value.filter(item => item.id !== result.id)]
    selected.value = result
    editorOpen.value = false
    ui.toast(editingId.value ? '已保存修改' : '已保存到本地数据库')
  } catch (cause) { ui.toast(cause?.message || '保存失败', 'error') }
  finally { saving.value = false }
}
function deleteEntry(item) {deleteTargets.value=[item];deleteError.value=''}
async function confirmDelete() {
  if(deleting.value || !deleteTargets.value?.length)return
  const targets=[...deleteTargets.value], ids=targets.map(item=>item.id)
  deleting.value=true;deleteError.value=''
  try {
    if(ids.length===1) await workbenchApi.remove(ids[0])
    else await workbenchApi.removeMany(ids)
    items.value = items.value.filter(row => !ids.includes(row.id))
    checkedIds.value=checkedIds.value.filter(id=>!ids.includes(id))
    if (ids.includes(selected.value?.id)) selected.value = null
    deleteTargets.value=null
    ui.toast(`已删除 ${ids.length} 条内容`)
  } catch (cause) { deleteError.value=cause?.message || '删除失败，请重试' }
  finally {deleting.value=false}
}
function sourceHref(item) { return item.data?.sourceUrl || '' }
async function viewEntry(item) {
  selected.value = item
  if (item.kind !== 'hot' || item.data?.viewedAt) return
  try {
    const updated = await workbenchApi.markViewed(item.id)
    const index = items.value.findIndex(row => row.id === item.id)
    if (index >= 0) items.value.splice(index, 1, updated)
    if (selected.value?.id === item.id) selected.value = updated
  } catch (cause) { ui.toast(cause.message || '查看状态保存失败', 'error') }
}
</script>

<template>
  <PageShell :title="current.title" :subtitle="current.subtitle" immersive>
    <div class="wb-page">
      <header class="wb-hero">
        <div>
          <span class="wb-eyebrow">{{ current.eyebrow }}</span>
          <h1>{{ current.title }}</h1>
          <p>{{ current.subtitle }}</p>
        </div>
        <div class="wb-hero-icon"><component :is="current.icon" :size="27" /></div>
      </header>

      <div v-if="error" class="wb-error" role="alert">{{ error }} <button type="button" @click="load">重试</button></div>
      <div v-if="loading" class="wb-loading"><LoaderCircle :size="22" class="wb-spin" /> 正在读取本地数据库…</div>

      <template v-else>
        <div v-if="currentSection==='daily-hot' && syncingHot" class="wb-hot-progress" role="status" aria-live="polite"><span class="wb-hot-progress-icon"><RefreshCw :size="21" class="wb-sync-spin"/></span><div><strong>正在获取热点新闻</strong><p>{{hotSyncStage}}<span v-if="hotJob?.round"> · 第 {{hotJob.round}} 轮</span></p><small>获取与整理可能需要几分钟，切换页面后仍会在后台继续执行。</small></div><span class="wb-hot-progress-tag">后台运行中</span></div>
        <div class="wb-toolbar">
          <label class="wb-search"><Search :size="17" /><input v-model="query" placeholder="搜索标题、正文或标签" /></label>
          <AppSelect v-model="statusFilter" aria-label="筛选状态"><option value="all">全部状态</option><option v-for="status in currentStatusOptions" :key="status" :value="status">{{ status === 'unread' ? '未查看' : status === 'read' ? '已查看' : statusLabels[status] }}</option></AppSelect>
          <button v-if="currentSection === 'daily-hot'" type="button" class="wb-secondary" :class="{'wb-sync-active':syncingHot}" :disabled="syncingHot" :aria-busy="syncingHot" :title="syncingHot ? hotSyncStage : '根据热点配置联网搜索并整理'" @click="syncDailyHot"><RefreshCw v-if="syncingHot" :size="17" class="wb-sync-spin" /><Flame v-else :size="17" /> {{ syncingHot ? '正在同步' : '同步热点' }}</button>
          <button v-if="currentSection !== 'daily-hot'" type="button" class="wb-primary" @click="createEntry"><Plus :size="17" /> 新增条目</button>
          <button v-if="!batchMode" type="button" class="wb-secondary" :disabled="!items.length" @click="batchMode=true"><ListChecks :size="17"/>批量处理</button>
          <button v-else type="button" class="wb-secondary" :disabled="deleting" @click="cancelBatch"><X :size="16"/>取消</button>
        </div>
        <div v-if="batchMode" class="wb-batch-bar"><label><input type="checkbox" :checked="allPageChecked" :indeterminate="somePageChecked" :disabled="deleting" @change="togglePageSelection"/>全选本页</label><span>已选择 <strong>{{checkedIds.length}}</strong> 条<span class="wb-batch-note">可跨页选择</span></span><button type="button" :disabled="!checkedIds.length||deleting" @click="requestBatchDelete"><Trash2 :size="16"/>删除所选{{checkedIds.length?'（'+checkedIds.length+'）':''}}</button></div>

        <div v-if="!filteredItems.length" class="wb-empty wb-panel" :class="{'wb-hot-empty':currentSection === 'daily-hot'}"><component :is="current.icon" :size="31" /><strong>{{ query ? '没有匹配的结果' : '这里还没有内容' }}</strong><p>{{ currentSection === 'daily-hot' ? '在个人账户中配置热点方向，然后点击“同步热点”。' : '点击“新增”把第一条内容保存到本地数据库。' }}</p></div>
        <div v-else ref="cardGrid" class="wb-card-grid" :class="{ 'wb-hot-grid': currentSection === 'daily-hot' }">
          <article v-for="item in pagedItems" :key="item.id" class="wb-entry-card" :class="{ 'wb-entry-selected': selected?.id === item.id, 'wb-hot-card': item.kind === 'hot', 'wb-batch-selected':batchMode&&checkedIds.includes(item.id) }">
            <div class="wb-card-top"><div class="wb-card-heading"><label v-if="batchMode" class="wb-card-check"><input v-model="checkedIds" type="checkbox" :value="item.id" :disabled="deleting" :aria-label="'选择：'+item.title" @click.stop/></label><span class="wb-eyebrow">{{ item.kind.toUpperCase() }}</span></div><span class="wb-status" :class="{ 'wb-status-read': item.kind === 'hot' && item.data?.viewedAt, 'wb-status-unread': item.kind === 'hot' && !item.data?.viewedAt }">{{ statusLabel(item) }}</span></div>
            <h2><button v-if="item.kind === 'hot'" type="button" class="wb-hot-title" :aria-label="'查看：' + item.title" @click="viewEntry(item)">{{ item.title }}</button><template v-else>{{ item.title }}</template></h2><p>{{ item.summary || (item.body || '').slice(0, item.kind === 'hot' ? 500 : 130) || '尚无摘要' }}</p>
            <div v-if="item.kind !== 'hot' && item.tags?.length" class="wb-tags"><span v-for="tag in item.tags.slice(0, 4)" :key="tag">{{ tag }}</span></div>
            <footer><small>{{ dateLabel(item.data?.publishedAt || item.createdAt) }}</small><div>
              <HotSources v-if="item.kind === 'hot'" :item="item" />
              <button type="button" class="wb-view-button" :aria-label="'查看：'+item.title" @click.stop="viewEntry(item)"><span>查看</span><ArrowRight :size="15" /></button>
              <button v-if="item.kind !== 'hot'" type="button" aria-label="编辑" @click.stop="editEntry(item)"><Pencil :size="15" /></button>
              <button type="button" aria-label="删除" @click.stop="deleteEntry(item)"><Trash2 :size="15" /></button>
            </div></footer>
          </article>
        </div>

        <footer v-if="currentSection === 'daily-hot' && filteredItems.length" class="wb-pagination">
          <span>共 {{ filteredItems.length }} 条热点 · 显示 {{ pageStart }}–{{ pageEnd }} 条</span>
          <div><button type="button" :disabled="page === 1" @click="page--"><ChevronLeft :size="16" />上一页</button>
            <template v-for="number in pageNumbers" :key="number"><span v-if="typeof number === 'string'">…</span><button v-else type="button" :class="{active:page === number}" :aria-current="page === number ? 'page' : undefined" @click="page = number">{{ number }}</button></template>
            <button type="button" :disabled="page === pageCount" @click="page++">下一页<ChevronRight :size="16" /></button>
            <div ref="pageSizePicker" class="wb-page-size-picker" @keydown="pageSizeKeydown" @focusout="!$event.currentTarget.contains($event.relatedTarget) && (pageSizeOpen = false)">
              <span>每页</span>
              <button type="button" class="wb-page-size-trigger" aria-label="每页热点数量" aria-haspopup="listbox" :aria-expanded="pageSizeOpen" aria-controls="hot-page-size-options" @click="togglePageSize">{{ pageSize }} 条<ChevronDown :size="16" :class="{ 'is-open': pageSizeOpen }" /></button>
              <div v-if="pageSizeOpen" id="hot-page-size-options" class="wb-page-size-options" role="listbox" aria-label="每页热点数量">
                <button v-for="size in pageSizes" :key="size" type="button" role="option" :aria-selected="pageSize === size" :class="{selected:pageSize === size}" @click="choosePageSize(size)"><span>{{ size }} 条 / 页</span><Check v-if="pageSize === size" :size="16" /></button>
              </div>
            </div>
          </div>
        </footer>
        <div v-if="selected" :class="{ 'wb-hot-detail-mask': selected.kind === 'hot' }" @click.self="selected = null">
        <section ref="detailDialog" class="wb-detail wb-panel" tabindex="-1" @keydown="detailKeydown" :role="selected.kind === 'hot' ? 'dialog' : undefined" :aria-modal="selected.kind === 'hot' ? true : undefined" :aria-label="selected.title">
          <div class="wb-section-head"><div><span class="wb-eyebrow">DETAIL</span><h2>{{ selected.title }}</h2></div><button type="button" aria-label="关闭详情" @click="selected = null"><X :size="19" /></button></div>
          <template v-if="selected.kind === 'hot'">
            <section class="wb-hot-content-section" aria-label="摘要"><h3>摘要</h3><p class="wb-detail-summary">{{ selected.summary || '暂无摘要' }}</p></section>
            <section class="wb-hot-content-section" aria-label="完整内容"><h3>完整内容</h3><p v-if="selected.data?.source === 'hot-agent'" class="wb-content-provenance">基于联网搜索返回的来源内容整理，保留原始来源供核对。</p><div class="wb-detail-body" :class="{ 'wb-content-unavailable': !selectedFullContent }">{{ selectedFullContent || '来源暂未提供完整内容，可打开原始来源阅读全文，或通过编辑内容补充。' }}</div></section>
          </template>
          <template v-else><p v-if="selected.summary" class="wb-detail-summary">{{ selected.summary }}</p><div class="wb-detail-body">{{ selected.body || '暂无正文' }}</div></template>
          <div class="wb-detail-actions"><HotSources v-if="selected.kind === 'hot'" :item="selected" detail /><a v-else-if="sourceHref(selected)" :href="sourceHref(selected)" target="_blank" rel="noopener noreferrer">打开原始来源 <ExternalLink :size="14" /></a><button type="button" @click="editEntry(selected)"><Pencil :size="15" /> 编辑内容</button><button v-if="selected.kind==='hot'" type="button" class="wb-import-hot" :disabled="!!importingHot || !!importedHot[selected.id]" @click="importHotDocument"><LoaderCircle v-if="importingHot===selected.id" :size="15" class="wb-spin"/><Check v-else-if="importedHot[selected.id]" :size="15"/><FileUp v-else :size="15"/>{{importingHot===selected.id?'保存中…':importedHot[selected.id]?'已保存到知识资料':'保存到知识资料'}}</button><RouterLink v-if="selected.kind==='hot'&&importedHot[selected.id]" to="/documents">前往知识资料<ArrowRight :size="15"/></RouterLink></div>
        </section>
        </div>
      </template>
    </div>

    <div v-if="editorOpen" class="wb-modal-backdrop" @click.self="editorOpen = false">
      <form class="wb-editor" @submit.prevent="saveEntry">
        <header><div><span class="wb-eyebrow">DATABASE ENTRY</span><h2>{{ editingId ? '编辑' : '新增' }}{{ current.title }}</h2></div><button type="button" aria-label="关闭" @click="editorOpen = false"><X :size="20" /></button></header>
        <div class="wb-editor-fields">
          <label :class="{ 'wb-field-wide': currentSection === 'daily-hot' }">标题<input v-model="form.title" required maxlength="200" placeholder="输入清晰的标题" /></label>
          <label v-if="currentSection !== 'daily-hot'">状态<AppSelect v-model="form.status"><option v-for="status in statusOptions" :key="status" :value="status">{{ statusLabels[status] }}</option></AppSelect></label>
          <label class="wb-field-wide">摘要<textarea v-model="form.summary" maxlength="2000" :rows="currentSection === 'daily-hot' ? 5 : 2" :class="{'wb-hot-editor-text':currentSection === 'daily-hot'}" :placeholder="currentSection === 'daily-hot' ? '热点新闻的摘要' : '一句话说明核心内容或结论'" /></label>
          <label v-if="currentSection === 'daily-hot'" class="wb-field-wide">原始来源链接<input v-model="form.sourceUrl" type="url" placeholder="https://…" /></label>
          <label class="wb-field-wide">{{ currentSection === 'daily-hot' ? '完整内容' : '正文 / 研究记录' }}<textarea v-model="form.body" rows="10" maxlength="100000" :class="{'wb-hot-editor-text':currentSection === 'daily-hot'}" :placeholder="currentSection === 'daily-hot' ? '热点新闻的完整正文' : '记录内容、证据与下一步…'" /></label>
          <label v-if="currentSection !== 'daily-hot'" class="wb-field-wide">标签（用逗号分隔）<input v-model="form.tags" placeholder="研究, 产品, 待核对" /></label>
        </div>
        <footer><button type="button" class="wb-secondary" @click="editorOpen = false">取消</button><button class="wb-primary" type="submit" :disabled="saving"><LoaderCircle v-if="saving" :size="16" class="wb-spin" /><Check v-else :size="16" /> 保存到数据库</button></footer>
      </form>
    </div>
  </PageShell>
  <DeleteConfirmation v-if="deleteTargets" :items="deleteTargets" :busy="deleting" :error="deleteError" @cancel="!deleting&&(deleteTargets=null)" @confirm="confirmDelete"/>
</template>
