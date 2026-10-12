import { apiRequest, backendEnabled } from './http'
import { demoState } from '@/mock/store'

const count = value => Math.max(0, Math.floor(Number(value) || 0))
const dayOf = value => {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return null
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

export async function loadProfileStatistics() {
  if (backendEnabled) return apiRequest('get', '/auth/me/statistics')
  const stats = { totalTokens: 0, inputTokens: 0, outputTokens: 0, peakTokens: 0, conversationCount: demoState.conversations.length,
    messageCount: 0, longestTaskMs: 0, longestStreak: 0, currentStreak: 0, activeDays: 0,
    toolCallCount: 0, featureCallCount: 0, missingUsageCount: 0, features: [] }
  const days = new Set()
  const features = new Map()
  for (const conversation of demoState.conversations) {
    for (const record of demoState.messages[conversation.id] || []) {
      const message = { ...record, ...record.metadata }
      if (message.role === 'user') {
        stats.messageCount++
        const day = dayOf(message.createdAt)
        if (day) days.add(day)
        if (message.skill?.id) {
          const feature = features.get(message.skill.id) || { id: message.skill.id, label: message.skill.label || message.skill.id, count: 0 }
          feature.count++
          features.set(feature.id, feature)
        }
      } else if (message.role === 'assistant') {
        const tokens = message.tokens || message.trace?.tokens || {}
        const input = count(tokens.input), output = count(tokens.output)
        stats.inputTokens += input
        stats.outputTokens += output
        stats.peakTokens = Math.max(stats.peakTokens, input + output)
        stats.longestTaskMs = Math.max(stats.longestTaskMs, count(message.latencyMs))
        if (!input && !output) stats.missingUsageCount++
        stats.toolCallCount += Array.isArray(message.toolCalls) ? message.toolCalls.length : 0
      }
    }
  }
  const ordinals = [...days].map(day => Date.parse(`${day}T00:00:00Z`) / 86400000).sort((a, b) => a - b)
  let streak = 0, previous = null
  for (const day of ordinals) {
    streak = previous !== null && day === previous + 1 ? streak + 1 : 1
    stats.longestStreak = Math.max(stats.longestStreak, streak)
    previous = day
  }
  const today = Date.parse(`${dayOf(new Date())}T00:00:00Z`) / 86400000
  const active = new Set(ordinals)
  let cursor = active.has(today) ? today : today - 1
  while (active.has(cursor--)) stats.currentStreak++
  stats.totalTokens = stats.inputTokens + stats.outputTokens
  stats.activeDays = days.size
  stats.features = [...features.values()].sort((a, b) => b.count - a.count)
  stats.featureCallCount = stats.features.reduce((total, item) => total + item.count, 0)
  return stats
}
