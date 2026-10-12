export function conversationQuestions(messages) {
  return messages.filter(message => message.role === 'user' && message.id != null).map(message => {
    const attachments = message.attachments || message.metadata?.attachments || []
    const content = message.content || message.transcript || message.voice?.transcript || ''
    const text = String(content).trim() || (attachments.length
      ? `附件提问：${attachments.map(item => item.name || '附件').join('、')}` : '语音提问')
    return { id: String(message.id), text, summary: text.replace(/\s+/g, ' ') }
  })
}

export function questionAtScrollPosition(positions, anchor) {
  let active = positions[0]?.id || null
  for (const position of positions) {
    if (position.top > anchor) break
    active = position.id
  }
  return active
}
