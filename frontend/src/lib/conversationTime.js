const pad = value => String(value).padStart(2, '0')

/** Prefer the latest actual turn; renaming or pinning should not change its time. */
export function conversationActivityAt(item) {
  return item.lastMessageAt || (item.lastMessageAt === undefined ? item.updatedAt : null) || item.createdAt
}

export function latestConversationMessageAt(messages = []) {
  let latest = null
  let latestTime = -Infinity
  for (const message of messages) {
    if (message.failed || !['user', 'assistant'].includes(message.role)) continue
    const time = new Date(message.createdAt).getTime()
    if (time > latestTime) {
      latest = message.createdAt
      latestTime = time
    }
  }
  return latest
}

/** Shared time labels for the conversation list and map cards. */
export function formatConversationTime(value, now = new Date()) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const current = now instanceof Date ? now : new Date(now)
  const today = new Date(current.getFullYear(), current.getMonth(), current.getDate())
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const daysAgo = Math.round((today - day) / 86400000)
  if (daysAgo <= 0) return `${pad(date.getHours())}:${pad(date.getMinutes())}`
  if (daysAgo === 1) return '昨天'
  if (daysAgo < 7) return `${daysAgo}天前`
  const monthDay = `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  return date.getFullYear() === current.getFullYear() ? monthDay : `${date.getFullYear()}-${monthDay}`
}
