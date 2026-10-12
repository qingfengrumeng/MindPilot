/**
 * 演示数据仓库。
 *
 * 在数据种子（data.js）之上维护一份可变的运行时副本，并把用户在前端产生的改动
 * 持久化到 localStorage，这样"新增会话、导入资料、撤销授权"等操作在刷新后依然保留。
 * 后端接入后这一层整体由真实接口替代，页面代码不需要改动。
 */
import * as seed from './data'

const STORAGE_KEY = 'mindpilot-demo-state'
// 清空旧演示资料的一次性迁移标记。只处理 documents，不影响会话、授权等其他数据。
const DOCUMENTS_RESET_KEY = 'mindpilot-documents-reset-v1'
/** 数据结构变化时递增，旧数据直接丢弃，避免残留的旧字段影响页面。 */
const STATE_VERSION = 1

const persistKeys = ['conversations', 'messages', 'documents', 'memoryItems', 'grants', 'artifacts']
const demoEmbeddingModel = 'qwen3.7-text-embedding'

function normalizeDocuments(documents) {
  return documents.map(doc => {
    const readable = doc.readable === true || Number(doc.chunks) > 0
    return {
      ...doc,
      quality: readable ? 'ok' : doc.quality,
      qualityLabel: readable ? '解析正常' : doc.quality === 'error' ? '解析失败' : '待解析',
      index: {
        ...doc.index,
        ...(doc.index?.vector === 'done' ? { embeddingModel: doc.index.embeddingModel || demoEmbeddingModel } : {}),
        ...(doc.index?.keyword === 'done' ? { keywordModel: doc.index.keywordModel || 'BM25' } : {})
      }
    }
  })
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function createState() {
  const state = {}
  for (const key of persistKeys) state[key] = clone(seed[key])
  // 资料库从空库开始，用户上传的资料会写入运行时状态。
  state.documents = []
  return state
}

function restore() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed?.version !== STATE_VERSION) return null
    const state = createState()
    for (const key of persistKeys) {
      if (parsed.data?.[key]) state[key] = parsed.data[key]
    }
    state.documents = normalizeDocuments(state.documents)
    if (!localStorage.getItem(DOCUMENTS_RESET_KEY)) {
      state.documents = []
      localStorage.setItem(DOCUMENTS_RESET_KEY, '1')
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: STATE_VERSION, data: state }))
    }
    return state
  } catch {
    return null
  }
}

export const demoState = restore() || createState()
try {
  // 空库初始化也要记录迁移已完成，避免首次上传后下一次刷新又被清空。
  if (!localStorage.getItem(DOCUMENTS_RESET_KEY)) localStorage.setItem(DOCUMENTS_RESET_KEY, '1')
} catch {
  // 存储被禁用时使用内存状态。
}

export function persistDemoState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: STATE_VERSION, data: demoState }))
  } catch {
    // 存储被禁用时退化为纯内存演示，不影响使用。
  }
}

export function resetDemoState() {
  const fresh = createState()
  for (const key of persistKeys) demoState[key] = fresh[key]
  persistDemoState()
}

/** 只读数据直接来自种子，不参与持久化。 */
export const demoSeed = seed

/** 模拟网络往返，让加载态、骨架屏在演示中可见。 */
export function delay(ms = 220) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/** 生成演示用的自增 id。 */
let idCounter = 0
export function nextId(prefix) {
  idCounter += 1
  return `${prefix}-${Date.now().toString(36)}${idCounter}`
}

export function now() {
  const date = new Date()
  const pad = value => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function clock() {
  const date = new Date()
  const pad = value => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}
