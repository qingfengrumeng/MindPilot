<script setup>
import AppSelect from '@/components/AppSelect.vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  AlertTriangle,
  BookOpenText,
  CheckCircle2,
  Clock3,
  FileText,
  GitBranch,
  History,
  Layers,
  Link2,
  LoaderCircle,
  Pencil,
  Quote,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  X,
  XCircle
} from 'lucide-vue-next'
import PageShell from '@/components/PageShell.vue'
import { wikiApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { useUiStore } from '@/stores/ui'

const app = useAppStore()
const ui = useUiStore()

const pages = ref([])
const proposals = ref([])
const detail = ref(null)
const activeId = ref('')
const loading = ref(false)
const detailLoading = ref(false)
const proposalsLoading = ref(false)
const busyProposal = ref('')
const showProposals = ref(true)

const domainFilter = ref('all')
const typeFilter = ref('all')
const keyword = ref('')
const staleOnly = ref(false)

const editOpen = ref(false)
const savingEdit = ref(false)
const editError = ref('')
const form = reactive({ summary: '', note: '' })

/** 页面类型口径与后端 wiki page type 保持一致。 */
const typeOptions = [
  { id: 'all', label: '全部类型' },
  { id: 'topic', label: '主题页' },
  { id: 'concept', label: '概念页' },
  { id: 'paper', label: '论文页' },
  { id: 'comparison', label: '对比页' }
]

/** 关系类型仅在讨论 / 使用 / 引用 / 比较 / 扩展之间取值，颜色只做区分不表意。 */
const relationTone = { 讨论: 'indigo', 使用: 'cyan', 引用: 'violet', 比较: 'amber', 扩展: 'green' }
let requestToken = 0

const filteredPages = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return pages.value.filter(page => {
    if (staleOnly.value && !page.stale) return false
    if (!text) return true
    return `${page.title || ''} ${page.summary || ''}`.toLowerCase().includes(text)
  })
})

const stats = computed(() => ({
  total: pages.value.length,
  stale: pages.value.filter(page => page.stale).length,
  protectedPages: pages.value.filter(page => page.manuallyEdited).length,
  proposals: proposals.value.length
}))

/** 关联页面可能同时以出链与反向链接出现，按页面 id 去重后再渲染。 */
const relatedPages = computed(() => {
  const seen = new Set()
  return (detail.value?.related || []).filter(link => {
    if (!link?.id || link.id === detail.value?.id || seen.has(link.id)) return false
    seen.add(link.id)
    return true
  })
})

const sources = computed(() => detail.value?.sources || [])
const bodySections = computed(() => detail.value?.body || [])
const changelog = computed(() => detail.value?.changelog || [])

function pad(value) {
  return String(value).padStart(2, '0')
}

function nowStamp() {
  const date = new Date()
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** 版本号按 vN 递增，缺省时从 v1 起算。 */
function bumpVersion(version) {
  const current = Number.parseInt(String(version || 'v1').replace(/\D/g, ''), 10)
  return `v${(Number.isNaN(current) ? 0 : current) + 1}`
}

/** 列表接口只接收 domain / type，关键词在本地过滤，避免每次输入都打到编译层。 */
async function loadPages() {
  loading.value = true
  try {
    const result = await wikiApi.list({ domain: domainFilter.value, type: typeFilter.value })
    pages.value = result?.items || []
    // 当前选中页可能被筛选条件排除，此时自动落到第一个可见页面。
    if (!pages.value.some(page => page.id === activeId.value)) {
      await selectPage(pages.value[0]?.id || '')
    }
  } catch (error) {
    pages.value = []
    ui.toast(error?.message || 'Wiki页面加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function loadProposals() {
  proposalsLoading.value = true
  try {
    const result = await wikiApi.proposals()
    proposals.value = (result?.items || []).filter(item => item?.status !== 'merged' && item?.status !== 'rejected')
  } catch (error) {
    proposals.value = []
    ui.toast(error?.message || '编译建议加载失败', 'error')
  } finally {
    proposalsLoading.value = false
  }
}

async function selectPage(id) {
  if (!id) {
    activeId.value = ''
    detail.value = null
    return
  }
  activeId.value = id
  const token = ++requestToken
  detailLoading.value = true
  try {
    const result = await wikiApi.get(id)
    // 快速切换页面时丢弃过期响应，避免详情串页。
    if (token !== requestToken) return
    detail.value = {
      ...result,
      body: result?.body || [],
      sources: result?.sources || [],
      related: result?.related || [],
      changelog: result?.changelog || []
    }
  } catch (error) {
    if (token !== requestToken) return
    detail.value = null
    ui.toast(error?.message || '页面详情加载失败', 'error')
  } finally {
    if (token === requestToken) detailLoading.value = false
  }
}

function refresh() {
  loadPages()
  loadProposals()
}

function toggleProposals() {
  showProposals.value = !showProposals.value
}

/** 来源片段可直接预览：页面上的每条结论都应能回到原文。 */
function previewSource(source) {
  const text = source?.text || ''
  const snippet = text.length > 46 ? `${text.slice(0, 46)}…` : text
  ui.toast(`${source?.title || '来源资料'} · 第 ${source?.page ?? '—'} 页 · ${source?.section || '未标注章节'}｜${snippet}`, 'info')
}

function relationClass(relation) {
  return relationTone[relation] || 'gray'
}

function sourceName(reason) {
  return (String(reason || '').match(/《([^》]+)》/) || [])[1] || '未标注来源资料'
}

/** 建议卡片用极简 diff 呈现：只在有把握的字段上说明新增 / 替换的行数。 */
function diffRows(item) {
  const rows = []
  if (item?.removedLines) {
    rows.push({ sign: '−', tone: 'del', text: `原有 ${item.removedLines} 行结论与来源不一致，将被替换` })
  }
  if (item?.addedLines) {
    rows.push({ sign: '+', tone: 'add', text: `新增 ${item.addedLines} 行来自来源资料的表述` })
  }
  if (!rows.length) {
    rows.push({ sign: '+', tone: 'add', text: '新增与来源一致的表述' })
  }
  return rows
}

async function approveProposal(item) {
  if (busyProposal.value) return
  busyProposal.value = item.id
  try {
    await wikiApi.approve(item.id)
    proposals.value = proposals.value.filter(row => row.id !== item.id)
    // 建议合并后页面进入新版本，待更新标记随之解除。
    const index = pages.value.findIndex(page => page.id === item.pageId)
    if (index >= 0) {
      const version = bumpVersion(pages.value[index].version)
      pages.value[index] = { ...pages.value[index], version, stale: false, staleReason: '', updatedAt: nowStamp() }
      if (detail.value?.id === item.pageId) {
        detail.value = { ...detail.value, version, stale: false, staleReason: '' }
      }
    }
    ui.toast(`已通过《${item.title}》的编译建议，页面已合并更新`)
  } catch (error) {
    ui.toast(error?.message || '通过建议失败，请重试', 'error')
  } finally {
    busyProposal.value = ''
  }
}

async function rejectProposal(item) {
  if (busyProposal.value) return
  busyProposal.value = item.id
  try {
    await wikiApi.reject(item.id)
    proposals.value = proposals.value.filter(row => row.id !== item.id)
    ui.toast(`已拒绝《${item.title}》的编译建议，页面内容保持不变`, 'info')
  } catch (error) {
    ui.toast(error?.message || '拒绝建议失败，请重试', 'error')
  } finally {
    busyProposal.value = ''
  }
}

function openEdit() {
  if (!detail.value) return
  form.summary = detail.value.summary || ''
  form.note = ''
  editError.value = ''
  editOpen.value = true
}

/** 保存后同时更新列表与详情，并追加一条人工变更记录。 */
function applyManualEdit(updated, version, note) {
  const entry = { version, at: nowStamp(), note: note || '人工修订页面摘要', by: '本人', manual: true }
  if (detail.value?.id === updated.id) {
    detail.value = {
      ...detail.value,
      summary: updated.summary,
      version,
      manuallyEdited: true,
      updatedAt: entry.at,
      changelog: [entry, ...changelog.value]
    }
  }
  const index = pages.value.findIndex(page => page.id === updated.id)
  if (index >= 0) {
    pages.value[index] = {
      ...pages.value[index],
      summary: updated.summary,
      version,
      manuallyEdited: true,
      updatedAt: entry.at
    }
  }
}

async function submitEdit() {
  const summary = form.summary.trim()
  if (!summary) {
    editError.value = '摘要不能为空'
    return
  }
  editError.value = ''
  savingEdit.value = true
  try {
    const version = bumpVersion(detail.value?.version)
    const result = await wikiApi.save(activeId.value, { summary, version, note: form.note.trim() })
    applyManualEdit({ ...result, summary }, version, form.note.trim())
    editOpen.value = false
    ui.toast(`已保存人工修改，${version} 起该页面受保护，自动编译不会再直接覆盖`)
  } catch (error) {
    ui.toast(error?.message || '保存失败，请重试', 'error')
  } finally {
    savingEdit.value = false
  }
}

watch([domainFilter, typeFilter], loadPages)

onMounted(() => {
  app.load()
  loadPages()
  loadProposals()
})
</script>

<template>
  <PageShell
    title="LLM Wiki"
    subtitle="由自动编译持续维护的知识页面，每条结论都能回溯到原文；人工修改过的内容在下次编译时会被保护。"
  >
    <template #actions>
      <button class="btn secondary" :disabled="loading || proposalsLoading" @click="refresh">
        <RefreshCw :size="16" :class="{ spin: loading || proposalsLoading }" />刷新
      </button>
      <button class="btn" @click="toggleProposals">
        <Sparkles :size="16" />编译建议
        <em v-if="stats.proposals" class="wiki-action-count">{{ stats.proposals }}</em>
      </button>
    </template>

    <div class="wiki-shell">
      <section class="wiki-stats">
        <article>
          <span class="wiki-stat-icon brand"><BookOpenText :size="20" /></span>
          <p><small>当前筛选 · Wiki页面</small><strong>{{ stats.total }}</strong></p>
        </article>
        <article>
          <span class="wiki-stat-icon warn"><AlertTriangle :size="20" /></span>
          <p><small>待更新页面</small><strong>{{ stats.stale }}</strong></p>
        </article>
        <article>
          <span class="wiki-stat-icon green"><ShieldCheck :size="20" /></span>
          <p><small>人工保护页面</small><strong>{{ stats.protectedPages }}</strong></p>
        </article>
        <article>
          <span class="wiki-stat-icon violet"><Sparkles :size="20" /></span>
          <p><small>待确认编译建议</small><strong>{{ stats.proposals }}</strong></p>
        </article>
      </section>

      <section v-if="showProposals" class="wiki-panel wiki-proposal-panel">
        <header class="wiki-panel-head">
          <div>
            <span class="wiki-kicker">PENDING COMPILE PROPOSALS</span>
            <h2>待确认的编译建议</h2>
            <p>自动编译只生成建议，通过后才会写入页面；存在冲突的建议需要你判断哪一版结论成立。</p>
          </div>
          <button class="btn ghost" @click="toggleProposals">收起</button>
        </header>

        <div v-if="proposalsLoading" class="wiki-loading">
          <LoaderCircle class="spin" :size="18" />正在读取编译建议
        </div>
        <div v-else-if="!proposals.length" class="empty-state wiki-empty">
          <CheckCircle2 :size="34" />
          <h3>没有待确认的编译建议</h3>
          <p>当前所有页面都与来源资料保持一致。</p>
        </div>
        <div v-else class="wiki-proposal-grid">
          <article v-for="item in proposals" :key="item.id" class="wiki-proposal">
            <header>
              <div class="wiki-proposal-title">
                <span class="wiki-proposal-kind" :class="item.kind || 'append'">
                  {{ item.kind === 'conflict' ? '冲突待裁决' : '追加更新' }}
                </span>
                <strong>{{ item.title || '未命名页面' }}</strong>
                <small>{{ item.at || '—' }}</small>
              </div>
              <span class="wiki-chip" :class="item.status === 'conflict' ? 'stale' : 'pending'">
                <AlertTriangle v-if="item.status === 'conflict'" :size="12" />
                <Clock3 v-else :size="12" />
                {{ item.status === 'conflict' ? '存在冲突' : '待确认' }}
              </span>
            </header>
            <p class="wiki-proposal-reason">{{ item.reason || '来源资料发生变化，建议同步更新本页。' }}</p>
            <div class="wiki-diff">
              <div v-for="(row, index) in diffRows(item)" :key="index" :class="row.tone">
                <i>{{ row.sign }}</i><span>{{ row.text }}</span>
              </div>
            </div>
            <footer>
              <span class="wiki-source-doc"><FileText :size="14" />{{ sourceName(item.reason) }}</span>
              <div>
                <button class="btn ghost" :disabled="busyProposal === item.id" @click="rejectProposal(item)">
                  <XCircle :size="15" />拒绝
                </button>
                <button class="btn" :disabled="busyProposal === item.id" @click="approveProposal(item)">
                  <CheckCircle2 :size="15" />{{ busyProposal === item.id ? '处理中' : '通过' }}
                </button>
              </div>
            </footer>
          </article>
        </div>
      </section>

      <section v-else class="wiki-panel wiki-proposal-collapsed">
        <Sparkles :size="17" />
        <span>编译建议面板已收起，<button class="text-btn" @click="toggleProposals">重新展开</button></span>
        <em v-if="stats.proposals">{{ stats.proposals }} 条待确认</em>
      </section>

      <div class="wiki-workspace">
        <aside class="wiki-panel wiki-list-panel">
          <header class="wiki-list-toolbar">
            <label class="wiki-search">
              <Search :size="17" />
              <input v-model="keyword" placeholder="搜索页面标题或摘要" />
              <button v-if="keyword" type="button" aria-label="清空搜索" @click="keyword = ''"><X :size="15" /></button>
            </label>
            <div class="wiki-filter-row">
              <label class="wiki-select">
                <span>知识域</span>
                <AppSelect v-model="domainFilter">
                  <option value="all">全部知识域</option>
                  <option v-for="domain in app.domains" :key="domain.id" :value="domain.id">{{ domain.label }}</option>
                </AppSelect>
              </label>
              <label class="wiki-select">
                <span>页面类型</span>
                <AppSelect v-model="typeFilter">
                  <option v-for="option in typeOptions" :key="option.id" :value="option.id">{{ option.label }}</option>
                </AppSelect>
              </label>
              <button class="wiki-stale-toggle" :class="{ active: staleOnly }" type="button" @click="staleOnly = !staleOnly">
                <AlertTriangle :size="14" />仅看待更新
              </button>
            </div>
            <p class="wiki-list-count">共 {{ filteredPages.length }} 个页面 · 按是否待更新与类型筛选</p>
          </header>

          <div class="wiki-list-scroll">
            <div v-if="loading" class="wiki-loading">
              <LoaderCircle class="spin" :size="18" />正在加载Wiki页面
            </div>
            <div v-else-if="!filteredPages.length" class="empty-state wiki-empty">
              <BookOpenText :size="34" />
              <h3>没有符合条件的Wiki页面</h3>
              <p>调整知识域、页面类型或关键词后重试。</p>
            </div>
            <template v-else>
              <button
                v-for="page in filteredPages"
                :key="page.id"
                type="button"
                class="wiki-page-card"
                :class="{ active: page.id === activeId }"
                @click="selectPage(page.id)"
              >
                <div class="wiki-page-card-top">
                  <span class="wiki-type-badge" :class="page.type || 'concept'">{{ page.typeLabel || '知识页' }}</span>
                  <em class="wiki-page-version"><GitBranch :size="12" />{{ page.version || 'v1' }}</em>
                </div>
                <strong>{{ page.title || '未命名页面' }}</strong>
                <p>{{ page.summary || '暂无摘要' }}</p>
                <div class="wiki-page-card-meta">
                  <span><Layers :size="12" />{{ app.domainLabel(page.domain) }}</span>
                  <span><Clock3 :size="12" />{{ page.updatedAt || '—' }}</span>
                </div>
                <div v-if="page.stale || page.manuallyEdited" class="wiki-page-card-flags">
                  <span v-if="page.stale" class="wiki-chip stale"><AlertTriangle :size="12" />待更新</span>
                  <span v-if="page.manuallyEdited" class="wiki-chip protected"><ShieldCheck :size="12" />人工保护</span>
                </div>
              </button>
            </template>
          </div>
        </aside>

        <section class="wiki-panel wiki-detail">
          <div v-if="detailLoading" class="wiki-loading">
            <LoaderCircle class="spin" :size="18" />正在加载页面详情
          </div>
          <div v-else-if="!detail" class="empty-state wiki-empty wiki-detail-empty">
            <BookOpenText :size="38" />
            <h3>请选择一个Wiki页面</h3>
            <p>从左侧列表中选择页面，即可查看正文、引用来源与关联页面。</p>
          </div>
          <article v-else class="wiki-detail-body">
            <header class="wiki-detail-head">
              <div>
                <span class="wiki-type-badge" :class="detail.type || 'concept'">{{ detail.typeLabel || '知识页' }}</span>
                <h2>{{ detail.title }}</h2>
                <p>{{ detail.summary || '暂无摘要' }}</p>
              </div>
              <button class="btn secondary" @click="openEdit"><Pencil :size="15" />编辑</button>
            </header>

            <div class="wiki-meta-row">
              <span><Layers :size="13" />{{ app.domainLabel(detail.domain) }}</span>
              <span><GitBranch :size="13" />{{ detail.version || 'v1' }}</span>
              <span><Clock3 :size="13" />{{ detail.updatedAt || '—' }}</span>
              <span v-if="detail.manuallyEdited" class="wiki-chip protected"><ShieldCheck :size="12" />人工保护</span>
              <span v-if="detail.stale" class="wiki-chip stale"><AlertTriangle :size="12" />待更新</span>
            </div>
            <p v-if="detail.stale" class="wiki-stale-note">
              <AlertTriangle :size="14" />待更新原因：{{ detail.staleReason || '来源资料已更新，等待重新编译。' }}
            </p>

            <section class="wiki-section">
              <h3 class="wiki-kicker">正文 · {{ bodySections.length }} 个段落</h3>
              <div v-if="bodySections.length" class="wiki-body-grid">
                <article v-for="(section, index) in bodySections" :key="index">
                  <h4>{{ section?.heading || '未命名段落' }}</h4>
                  <p>{{ section?.text || '' }}</p>
                </article>
              </div>
              <p v-else class="wiki-inline-empty">该页面尚未编译出正文段落。</p>
            </section>

            <section class="wiki-section">
              <h3 class="wiki-kicker">引用来源 · {{ sources.length }} 个片段<Quote :size="13" /></h3>
              <div v-if="sources.length" class="wiki-source-list">
                <button v-for="source in sources" :key="source.chunkId" type="button" class="wiki-source" @click="previewSource(source)">
                  <span class="wiki-source-icon"><FileText :size="16" /></span>
                  <div>
                    <strong>{{ source?.title || '未命名资料' }}</strong>
                    <small>第 {{ source?.page ?? '—' }} 页 · {{ source?.section || '未标注章节' }}</small>
                    <p>{{ source?.text || '该片段暂无文本。' }}</p>
                  </div>
                </button>
              </div>
              <p v-else class="wiki-inline-empty">该页面暂未关联来源片段。</p>
            </section>

            <section class="wiki-section">
              <h3 class="wiki-kicker">关联页面 · {{ relatedPages.length }} 条关系<Link2 :size="13" /></h3>
              <div v-if="relatedPages.length" class="wiki-related-grid">
                <button v-for="link in relatedPages" :key="link.id" type="button" class="wiki-related" @click="selectPage(link.id)">
                  <span class="wiki-relation" :class="relationClass(link.relation)">{{ link.relation || '关联' }}</span>
                  <strong>{{ link.title || link.id }}</strong>
                  <small>{{ link.typeLabel || '知识页' }} · {{ link.direction === 'in' ? '被本页引用' : '本页引用它' }}</small>
                </button>
              </div>
              <p v-else class="wiki-inline-empty">该页面暂无关联页面。</p>
            </section>

            <section class="wiki-section">
              <h3 class="wiki-kicker">变更记录 · {{ changelog.length }} 次<History :size="13" /></h3>
              <ol v-if="changelog.length" class="wiki-timeline">
                <li v-for="(entry, index) in changelog" :key="index" :class="{ manual: entry?.manual }">
                  <span class="wiki-timeline-dot" />
                  <div>
                    <p class="wiki-timeline-head">
                      <strong>{{ entry?.version || 'v1' }}</strong>
                      <time>{{ entry?.at || '—' }}</time>
                      <em>{{ entry?.by || '自动编译' }}</em>
                    </p>
                    <p class="wiki-timeline-note">{{ entry?.note || '—' }}</p>
                  </div>
                </li>
              </ol>
              <p v-else class="wiki-inline-empty">该页面暂无变更记录。</p>
            </section>
          </article>
        </section>
      </div>

      <Transition name="modal">
        <div v-if="editOpen" class="modal-mask" @click.self="editOpen = false">
          <section class="modal-card wiki-edit-modal">
            <button class="icon-btn modal-close" aria-label="关闭" @click="editOpen = false"><X :size="19" /></button>
            <span class="eyebrow">MANUAL EDIT</span>
            <h3>人工编辑 · {{ detail?.title || '' }}</h3>
            <p>人工编辑过的页面在自动编译时会被保护，自动建议只能提示、不能直接覆盖。</p>

            <label class="wiki-field">
              <span>页面摘要</span>
              <textarea v-model="form.summary" rows="5" maxlength="240" placeholder="用一段话说明该页面现在要维护的核心结论"></textarea>
              <small>{{ form.summary.length }} / 240</small>
              <em class="field-error">{{ editError }}</em>
            </label>

            <label class="wiki-field">
              <span>变更说明（可选）</span>
              <input v-model="form.note" maxlength="60" placeholder="例如：补充128K以上的长程检索结论" />
            </label>

            <div class="wiki-protect-note">
              <ShieldCheck :size="16" />
              <span>保存后会记为 {{ bumpVersion(detail?.version) }}，并写入一条“本人”的变更记录。</span>
            </div>

            <div class="modal-actions">
              <button class="btn secondary" @click="editOpen = false">取消</button>
              <button class="btn" :disabled="savingEdit" @click="submitEdit">
                <Pencil :size="16" />{{ savingEdit ? '保存中' : '保存修改' }}
              </button>
            </div>
          </section>
        </div>
      </Transition>
    </div>
  </PageShell>
</template>

<style scoped>
.wiki-shell{display:grid;gap:20px}
.wiki-panel{background:#fff;border:1px solid var(--workspace-card-line);border-radius:22px;box-shadow:var(--workspace-card-shadow)}
.wiki-kicker{display:inline-block;font-size:11px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:var(--brand)}

/* 顶部统计 */
.wiki-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.wiki-stats article{display:flex;align-items:center;gap:14px;min-height:91px;padding:18px 19px;background:#fff;border:1px solid var(--workspace-card-line);border-radius:18px;box-shadow:0 8px 25px rgba(59,12,117,.05)}
.wiki-stat-icon{width:48px;height:48px;flex:0 0 48px;border-radius:15px;display:grid;place-items:center}
.wiki-stat-icon svg{width:23px;height:23px}
.wiki-stat-icon.brand{background:var(--brand-soft);color:var(--brand)}
.wiki-stat-icon.warn{background:#fff7e8;color:#d98500}
.wiki-stat-icon.green{background:#ecfdf5;color:#059669}
.wiki-stat-icon.violet{background:#f6f2fc;color:#4c0b9b}
.wiki-stats p{margin:0;display:grid;gap:3px;min-width:0}
.wiki-stats small{font-size:14px;color:#8c75a8;letter-spacing:0}
.wiki-stats strong{font-size:30px;line-height:1;color:#25133b;letter-spacing:-.4px}
.wiki-action-count{font-style:normal;display:inline-grid;place-items:center;min-width:20px;height:20px;padding:0 6px;border-radius:7px;background:rgba(255,255,255,.24);font-size:12px;font-weight:700}

/* 编译建议 */
.wiki-proposal-panel{padding:20px 22px 22px}
.wiki-panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:16px}
.wiki-panel-head>.btn{flex:0 0 auto;white-space:nowrap}
.wiki-panel-head h2{margin:6px 0 4px;font-size:21px;color:#34224b;letter-spacing:-.4px}
.wiki-panel-head p{font-size:14px;line-height:1.65;color:var(--muted);margin:0;max-width:720px}
.wiki-proposal-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.wiki-proposal{display:grid;gap:12px;padding:16px;border:1px solid var(--line);border-radius:14px;background:#fff;transition:.18s}
.wiki-proposal:hover{border-color:#e8dcf7;box-shadow:var(--shadow-sm)}
.wiki-proposal>header{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.wiki-proposal-title{display:grid;gap:5px;min-width:0}
.wiki-proposal-title strong{font-size:14px;color:var(--ink)}
.wiki-proposal-title small{font-size:12px;color:var(--muted)}
.wiki-proposal-kind{align-self:start;padding:3px 8px;border-radius:7px;font-size:11px;font-weight:700;letter-spacing:.6px;background:var(--soft);color:var(--muted)}
.wiki-proposal-kind.append{background:var(--brand-soft);color:var(--brand)}
.wiki-proposal-kind.conflict{background:#fff7e8;color:#b5730a}
.wiki-proposal-reason{margin:0;font-size:13.5px;line-height:1.7;color:var(--text)}
.wiki-diff{display:grid;gap:6px;padding:10px;border-radius:12px;background:var(--soft);font-family:"MindPilot Latin",ui-monospace,SFMono-Regular,Menlo,monospace}
.wiki-diff>div{display:flex;gap:9px;padding:7px 9px;border-radius:8px;font-size:13px;line-height:1.6}
.wiki-diff>div.add{background:#ecfdf5;color:#047857}
.wiki-diff>div.del{background:#fff1f2;color:#b42318}
.wiki-diff i{font-style:normal;font-weight:800}
.wiki-proposal>footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:12px;border-top:1px solid var(--line)}
.wiki-proposal>footer>div{display:flex;gap:8px}
.wiki-source-doc{display:inline-flex;align-items:center;gap:6px;min-width:0;font-size:12.5px;color:var(--muted)}
.wiki-source-doc svg{flex:0 0 auto}
.wiki-proposal-collapsed{display:flex;align-items:center;gap:10px;padding:14px 20px;font-size:14px;color:var(--muted)}
.wiki-proposal-collapsed em{margin-left:auto;font-style:normal;font-size:13px;color:var(--brand)}

/* 列表 + 详情 */
.wiki-workspace{display:grid;grid-template-columns:378px minmax(0,1fr);gap:18px;align-items:start}
.wiki-list-panel{display:flex;flex-direction:column;overflow:hidden;position:sticky;top:18px;max-height:calc(100vh - 205px)}
.wiki-list-toolbar{display:grid;gap:11px;padding:16px;border-bottom:1px solid var(--line)}
.wiki-search{display:flex;align-items:center;gap:8px;height:50px;padding:0 14px;border:1px solid #e3dcec;border-radius:14px;color:var(--muted);transition:.18s}
.wiki-search:focus-within{border-color:#dbc8f3;box-shadow:0 0 0 3px var(--brand-soft)}
.wiki-search input{flex:1;min-width:0;border:0;outline:0;background:none;font-size:14px;color:var(--text);font-family:inherit}
.wiki-search button{border:0;background:none;color:var(--muted);display:grid;place-items:center;padding:2px}
.wiki-search button:hover{color:var(--brand)}
.wiki-filter-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.wiki-select{display:grid;gap:4px;min-width:0}
.wiki-select span{font-size:11px;font-weight:700;letter-spacing:.8px;color:var(--muted)}
.wiki-select select{width:100%;height:36px;padding:0 8px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--text);font-size:13.5px;font-family:inherit}
.wiki-select select:focus{outline:0;border-color:#dbc8f3}
.wiki-stale-toggle{grid-column:span 2;display:inline-flex;align-items:center;justify-content:center;gap:7px;height:36px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--muted);font-size:13px;font-weight:600;transition:.18s}
.wiki-stale-toggle:hover{color:#b5730a;border-color:#f2d9a8}
.wiki-stale-toggle.active{background:#fff7e8;border-color:#f2d9a8;color:#b5730a}
.wiki-list-count{margin:0;font-size:12.5px;color:var(--muted)}
.wiki-list-scroll{display:grid;gap:9px;padding:11px;overflow-y:auto}
.wiki-page-card{display:grid;gap:8px;text-align:left;padding:13px;border:1px solid transparent;border-radius:13px;background:#fff;transition:.18s;font-family:inherit}
.wiki-page-card:hover{background:var(--soft)}
.wiki-page-card.active{background:var(--brand-soft);border-color:#e4d5f6}
.wiki-page-card-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.wiki-page-card>strong{font-size:14.5px;color:var(--ink);line-height:1.45}
.wiki-page-card>p{margin:0;font-size:13px;line-height:1.65;color:var(--muted);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.wiki-page-card-meta{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted)}
.wiki-page-card-meta span{display:inline-flex;align-items:center;gap:5px;min-width:0}
.wiki-page-card-flags{display:flex;flex-wrap:wrap;gap:6px}
.wiki-page-version{display:inline-flex;align-items:center;gap:4px;font-style:normal;font-size:12px;color:var(--muted)}
.wiki-type-badge{padding:3px 9px;border-radius:8px;font-size:11.5px;font-weight:700;letter-spacing:.4px}
.wiki-type-badge.topic{background:var(--brand-soft);color:var(--brand)}
.wiki-type-badge.concept{background:#f5edff;color:#631db8}
.wiki-type-badge.paper{background:#f6f2fc;color:#4c0b9b}
.wiki-type-badge.comparison{background:#fff7e8;color:#b5730a}
.wiki-chip{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:8px;font-size:12px;font-weight:650;background:var(--soft);color:var(--muted)}
.wiki-chip.stale{background:#fff7e8;color:#b5730a}
.wiki-chip.protected{background:#ecfdf5;color:#047857}
.wiki-chip.pending{background:var(--brand-soft);color:var(--brand)}

.wiki-detail{min-height:460px;padding:22px 24px 26px}
.wiki-detail-body{display:grid;gap:22px}
.wiki-detail-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px}
.wiki-detail-head h2{margin:10px 0 8px;font-size:21px;line-height:1.35;color:var(--ink);letter-spacing:-.5px}
.wiki-detail-head p{margin:0;font-size:14.5px;line-height:1.75;color:var(--text);max-width:760px}
.wiki-meta-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;padding:12px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-size:13px;color:var(--muted)}
.wiki-meta-row>span{display:inline-flex;align-items:center;gap:6px}
.wiki-stale-note{display:flex;align-items:flex-start;gap:8px;margin:0;padding:11px 13px;border-radius:12px;background:#fff7e8;color:#a8660a;font-size:13.5px;line-height:1.6}
.wiki-section{display:grid;gap:12px}
.wiki-section .wiki-kicker{display:flex;align-items:center;gap:6px;color:var(--muted)}
.wiki-body-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.wiki-body-grid article{padding:14px 15px;border:1px solid var(--line);border-radius:13px;background:#fff}
.wiki-body-grid h4{margin:0 0 7px;font-size:14px;color:var(--brand)}
.wiki-body-grid p{margin:0;font-size:14px;line-height:1.8;color:var(--text)}
.wiki-inline-empty{margin:0;padding:14px;border:1px dashed var(--line);border-radius:12px;font-size:13.5px;color:var(--muted)}

.wiki-source-list{display:grid;gap:10px}
.wiki-source{display:flex;gap:11px;text-align:left;padding:13px 14px;border:1px solid var(--line);border-radius:13px;background:#fff;transition:.18s;font-family:inherit}
.wiki-source:hover{border-color:#e4d5f6;background:#fdfcfe}
.wiki-source-icon{width:34px;height:34px;flex:0 0 auto;border-radius:10px;display:grid;place-items:center;background:var(--brand-soft);color:var(--brand)}
.wiki-source>div{display:grid;gap:4px;min-width:0}
.wiki-source strong{font-size:13.5px;color:var(--ink)}
.wiki-source small{font-size:12px;color:var(--muted)}
.wiki-source p{margin:0;font-size:13.5px;line-height:1.75;color:var(--text);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}

.wiki-related-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.wiki-related{display:grid;gap:6px;text-align:left;padding:13px 14px;border:1px solid var(--line);border-radius:13px;background:#fff;transition:.18s;font-family:inherit}
.wiki-related:hover{border-color:#e4d5f6;box-shadow:var(--shadow-sm)}
.wiki-related strong{font-size:14px;color:var(--ink);line-height:1.5}
.wiki-related small{font-size:12px;color:var(--muted)}
.wiki-relation{align-self:start;padding:3px 9px;border-radius:8px;font-size:11.5px;font-weight:700}
.wiki-relation.indigo{background:var(--brand-soft);color:var(--brand)}
.wiki-relation.cyan{background:#f5edff;color:#631db8}
.wiki-relation.violet{background:#f6f2fc;color:#4c0b9b}
.wiki-relation.amber{background:#fff7e8;color:#b5730a}
.wiki-relation.green{background:#ecfdf5;color:#047857}
.wiki-relation.gray{background:var(--soft);color:var(--muted)}

.wiki-timeline{display:grid;gap:0;margin:0;padding:0 0 0 6px;list-style:none}
.wiki-timeline li{position:relative;display:grid;grid-template-columns:auto minmax(0,1fr);gap:13px;padding:0 0 16px}
.wiki-timeline li:last-child{padding-bottom:0}
.wiki-timeline li:not(:last-child):before{content:"";position:absolute;left:5px;top:14px;bottom:0;width:1px;background:var(--line)}
.wiki-timeline-dot{width:11px;height:11px;margin-top:4px;border-radius:50%;background:#fff;border:2px solid #d9c4f3}
.wiki-timeline li.manual .wiki-timeline-dot{border-color:#10b981}
.wiki-timeline-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:0}
.wiki-timeline-head strong{font-size:13.5px;color:var(--ink)}
.wiki-timeline-head time{font-size:12.5px;color:var(--muted)}
.wiki-timeline-head em{font-style:normal;padding:2px 8px;border-radius:7px;background:var(--soft);font-size:11.5px;color:var(--muted)}
.wiki-timeline li.manual .wiki-timeline-head em{background:#ecfdf5;color:#047857}
.wiki-timeline-note{margin:5px 0 0;font-size:13.5px;line-height:1.7;color:var(--text)}

.wiki-loading{display:flex;align-items:center;justify-content:center;gap:9px;padding:44px 16px;font-size:13.5px;color:var(--muted)}
.wiki-empty{padding:52px 20px}
.wiki-empty svg{color:#cfc3dd;margin-bottom:10px}
.wiki-detail-empty{align-content:center;display:grid;place-items:center;text-align:center}

/* 人工编辑弹窗 */
.wiki-edit-modal{max-width:560px}
.wiki-edit-modal h3{margin-top:9px}
.wiki-edit-modal>p{margin:7px 0 0}
.wiki-field{display:grid;gap:7px;margin-top:18px}
.wiki-field>span{font-size:13.5px;font-weight:650;color:var(--ink)}
.wiki-field>small{font-size:12px;color:var(--muted);text-align:right}
.wiki-field textarea,.wiki-field input{width:100%;border:1px solid var(--line);border-radius:12px;padding:11px 12px;background:#fff;color:var(--text);font-size:14px;font-family:inherit;line-height:1.75}
.wiki-field textarea{resize:vertical;min-height:120px}
.wiki-field textarea:focus,.wiki-field input:focus{outline:0;border-color:#dbc8f3;box-shadow:0 0 0 3px var(--brand-soft)}
.wiki-field .field-error{font-style:normal;display:block;color:var(--danger)}
.wiki-protect-note{display:flex;align-items:center;gap:8px;margin-top:14px;padding:11px 13px;border-radius:12px;background:#ecfdf5;color:#047857;font-size:13.5px;line-height:1.6}

@media(max-width:1180px){
  .wiki-workspace{grid-template-columns:1fr}
  .wiki-list-panel{position:static;max-height:none}
  .wiki-proposal-grid{grid-template-columns:1fr}
}
@media(max-width:760px){
  .wiki-stats{grid-template-columns:repeat(2,minmax(0,1fr))}
  .wiki-body-grid{grid-template-columns:1fr}
  .wiki-related-grid{grid-template-columns:1fr}
  .wiki-detail-head{flex-direction:column}
}
</style>
