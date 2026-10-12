/** Persist a call only after its first recognized user utterance. */
export function createRealtimeTranscript({ api, chat, sessionId, conversationId = null, greeting }) {
  let currentId = conversationId
  let started = null
  let writes = Promise.resolve()
  let finished = null
  const metadata = { realtime: true, realtimeSessionId: sessionId }

  function start(text) {
    if (!text?.trim()) return Promise.resolve()
    if (!started) {
      started = (async () => {
        if (!currentId) currentId = (await api.create({ title: '新会话' })).id
        await api.addMessage(currentId, {
          role: 'system', content: '实时通话',
          metadata: { type: 'realtime_marker', realtimeSessionId: sessionId }
        })
        const introduction = greeting?.()
        if (introduction) await api.addMessage(currentId, {
          role: 'assistant', content: introduction, metadata
        })
      })()
    }
    return started
  }

  function append(role, content) {
    if (!content?.trim()) return writes
    if (role === 'user') start(content)
    if (!started) return writes
    writes = writes.catch(() => {}).then(async () => {
      await started
      return api.addMessage(currentId, { role, content, metadata })
    })
    return writes
  }

  function finish() {
    if (!finished) finished = (async () => {
      if (!started) return
      await started
      await writes
      await api.addMessage(currentId, {
        role: 'system', content: '实时通话结束',
        metadata: { type: 'realtime_marker', realtimeSessionId: sessionId }
      })
      await chat.loadConversations()
      await chat.loadMessages(currentId)
    })()
    return finished
  }

  return { start, append, finish, flush: () => writes, get conversationId() { return currentId } }
}
