export function userMessageForSequence(messages, sequences, seq) {
  if (seq === undefined) return messages.findLast(message => message.role === 'user') ?? null
  const id = Object.entries(sequences || {}).find(([, value]) => value === seq)?.[0]
  let index = messages.findIndex(message => String(message.id) === id)
  while (index >= 0) {
    if (messages[index].role === 'user') return messages[index]
    index -= 1
  }
  return null
}
