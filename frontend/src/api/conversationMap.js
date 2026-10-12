import { apiRequest, backendEnabled } from '@/api/http'
import { demoState, persistDemoState } from '@/mock/store'
import { summaryText } from '@/lib/conversationSummary'

const storageKey = 'mindpilot-conversation-map-demo'
const empty = () => ({ nodes: {}, groups: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 }, synapse: {} })

export const conversationMapApi = {
  async load() {
    if (backendEnabled) return apiRequest('get', '/conversation-map')
    const previews = {}
    for (const item of demoState.conversations) {
      const rows = demoState.messages[item.id] || []
      const answer = [...rows].reverse().find(row => row.role === 'assistant')
      const user = [...rows].reverse().find(row => row.role === 'user')
      const hasFeatureDomain = Boolean((item.taskId && item.taskId !== 'general') || rows.some(row => {
        const skill = row.skill || row.metadata?.skill
        return row.role === 'user' && skill?.id && skill.id !== 'general'
      }))
      previews[item.id] = { summary: summaryText(answer?.content || user?.content || '新会话，尚无内容').slice(0, 200),
        nextStep: '', hasFeatureDomain, status: answer ? 'done' : user ? 'waiting' : 'idle' }
    }
    try { return { state: JSON.parse(localStorage.getItem(storageKey) || 'null') || empty(), previews } }
    catch { return { state: empty(), previews } }
  },
  async save(state) {
    if (backendEnabled) return apiRequest('put', '/conversation-map', state)
    localStorage.setItem(storageKey, JSON.stringify(state))
    return { ok: true }
  },
  async digest(id) {
    if (backendEnabled) return apiRequest('post', `/conversation-map/${id}/digest`, {}, { timeout: 90000 })
    const rows = demoState.messages[id] || []
    const answer = [...rows].reverse().find(row => row.role === 'assistant')
    const user = [...rows].reverse().find(row => row.role === 'user')
    return { summary: summaryText(answer?.content || user?.content || '').slice(0, 220), keyFindings: '', nextStep: '' }
  },
  async branch(payload) {
    if (backendEnabled) return apiRequest('post', '/conversation-map/branch', payload)
    return null
  },
  async branchPreview(sourceId, mode) {
    if (backendEnabled) return apiRequest('post', '/conversation-map/branch-preview', { sourceId, mode })
    return { context: '' }
  },
  async inject(payload) {
    if (backendEnabled) return apiRequest('post', '/conversation-map/inject', payload)
    const source = demoState.conversations.find(item => item.id === payload.sourceId)
    const target = demoState.conversations.find(item => item.id === payload.targetId)
    if (!source || !target) throw new Error('会话不存在')
    const rows = demoState.messages[source.id] || []
    const context = payload.mode === 'full'
      ? rows.map(row => `${row.role === 'user' ? '用户' : '助手'}：${row.content}`).join('\n')
      : summaryText([...rows].reverse().find(row => row.role === 'assistant')?.content || rows.at(-1)?.content || source.title)
    if (!context.trim()) throw new Error('来源会话没有可注入的内容')
    target.mapInjectedContext = [target.mapInjectedContext, `来源会话《${source.title}》${payload.mode === 'full' ? '完整对话' : '摘要'}：\n${context}`].filter(Boolean).join('\n\n')
    persistDemoState()
    return { ok: true, contextLength: target.mapInjectedContext.length }
  }
}
