import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { chatApi, documentsApi, speechApi } from '@/api'
import { backendEnabled } from '@/api/http'
import { useUiStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { latestConversationMessageAt } from '@/lib/conversationTime'
import { createReplyControl } from '@/lib/replyControl'

function displayDate(value) {
  if (!value) return ''
  const date = new Date(value)
  const days = Math.floor((Date.now() - date.getTime()) / 86400000)
  if (days <= 0) return '刚刚'
  if (days === 1) return '昨天'
  return `${date.getMonth() + 1}月${String(date.getDate()).padStart(2, '0')}日`
}

function normalizeSources(citations) {
  return [...new Set((citations || [])
    .map(source => typeof source === 'string' ? source : source?.title)
    .map(title => String(title || '').trim())
    .filter(Boolean))]
}

async function fillCitationFilenames(items) {
  const missing = items.some(item => item.citations?.some(citation => citation?.documentId && !citation.filename))
  if (!missing) return
  try {
    const result = await documentsApi.list()
    const filenames = new Map((result.items || []).map(document => [document.id, document.filename]))
    items.forEach(item => {
      if (!item.citations?.length) return
      item.citations = item.citations.map(citation => citation?.documentId && !citation.filename && filenames.has(citation.documentId)
        ? { ...citation, filename: filenames.get(citation.documentId) }
        : citation)
    })
  } catch {
    // 引用元数据仍可显示；资料列表恢复后，下次打开会话会再次回填文件名。
  }
}

export const useChatStore = defineStore('chat', () => {
  const ui = useUiStore()
  const conversations = ref([])
  const activeId = ref(null)
  const messages = ref([])
  const generating = ref(false)
  const outputPaused = ref(false)
  let liveReply = null

  function startReply(conversationId, draftId, placeholderId = null) {
    const reply = { ...createReplyControl(), conversationId, draftId, placeholderId,
      streamId: crypto.randomUUID(), epoch: storeEpoch, stopped: false, serverControlled: false }
    liveReply = reply
    outputPaused.value = false
    return reply
  }

  async function requestReplyControl(reply, action) {
    if (!backendEnabled || !reply.serverControlled) return
    // Serialize rapid pause/continue clicks so server state follows UI order.
    const pending = (reply.controlRequest || Promise.resolve()).catch(() => {})
      .then(() => chatApi.controlReply(reply.conversationId, reply.streamId, action))
    reply.controlRequest = pending
    try { await pending }
    catch (error) { if (action !== 'cancel') throw error }
  }

  async function pauseOutput() {
    const reply = liveReply
    if (!reply || reply.stopped || outputPaused.value) return
    const draft = messages.value.find(item => item.id === reply.draftId)
    if (!draft?.content) {
      reply.stopped = true
      reply.cancel()
      void requestReplyControl(reply, 'cancel')
      outputPaused.value = false
      generating.value = false
      agentStatus.value = ''
      drawingProgress.value = []
      if (reply.placeholderId) messages.value = messages.value.filter(item => item.id !== reply.placeholderId)
      messages.value.push({ id: `local-stopped-${Date.now()}`, role: 'assistant', content: '',
        outputStopped: true, createdAt: new Date().toISOString() })
      return
    }
    reply.pause()
    outputPaused.value = true
    draft.outputPaused = true
    try { await requestReplyControl(reply, 'pause') }
    catch (error) {
      // The server may have completed already; the local gate still holds its tail.
      if (error.status !== 404) ui.toast(error.message, 'error')
    }
  }

  async function resumeOutput() {
    const reply = liveReply
    if (!reply || !outputPaused.value || reply.stopped) return
    try { await requestReplyControl(reply, 'resume') }
    catch (error) { if (error.status !== 404) { ui.toast(error.message, 'error'); return } }
    const draft = messages.value.find(item => item.id === reply.draftId)
    if (draft) delete draft.outputPaused
    outputPaused.value = false
    reply.resume()
  }

  function cancelLiveReply() {
    if (!liveReply) return
    const reply = liveReply
    reply.stopped = true
    reply.cancel()
    void requestReplyControl(reply, 'cancel')
    liveReply = null
    generating.value = false
    outputPaused.value = false
    agentStatus.value = ''
    drawingProgress.value = []
    regeneratingId.value = null
  }
  const agentStatus = ref('')
  const drawingProgress = ref([])
  const latestTrace = ref(null)
  const regeneratingId = ref(null)
  const loaded = ref(false)
  const pendingMapMessage = ref(null)
  let traceLoadVersion = 0
  let conversationLoadPromise = null
  let newChatPromise = null
  let storeEpoch = 0
  const activeConversation = computed(() => conversations.value.find(item => item.id === activeId.value))
  const titleObservers = new Map()
  const titleSettled = new Set()

  function activeConversationStorageKey() {
    const user = useAuthStore().user
    return `mindpilot:${user?.id || user?.username || 'anonymous'}:active-conversation`
  }

  function rememberedConversationId() {
    try { return sessionStorage.getItem(activeConversationStorageKey()) } catch { return null }
  }

  // Keep each browser tab and account on the conversation the user selected.
  // A store reset on logout must not erase the previous account's selection.
  watch(activeId, id => {
    if (!id) return
    try { sessionStorage.setItem(activeConversationStorageKey(), id) } catch { /* Storage can be unavailable. */ }
  }, { flush: 'sync' })

  // Read-only polling; creating a title task is exclusively a server-side first-turn hook.
  function observeTitle(id) {
    if (!backendEnabled || !id || typeof chatApi.titleStatus !== 'function' || titleObservers.has(id) || titleSettled.has(id)) return
    const epoch = storeEpoch
    titleObservers.set(id, null)
    const poll = async () => {
      try {
        const result = await chatApi.titleStatus(id)
        if (epoch !== storeEpoch) return
        const conversation = conversations.value.find(item => item.id === id)
        if (conversation && result.title) conversation.title = result.title
        if (conversation && ['queued', 'running'].includes(result.status)) {
          titleObservers.set(id, setTimeout(poll, 2000))
          return
        }
        // 'idle' may mean the first reply has not committed yet; allow observing on completion.
        if (result.status !== 'idle') titleSettled.add(id)
      } catch { /* 下次打开会话时再获取任务结果；不重新生成标题。 */ }
      titleObservers.delete(id)
    }
    void poll()
  }

  // Observe message timestamps rather than content, so streaming tokens do not reorder the list.
  watch(() => latestConversationMessageAt(messages.value), latest => {
    const conversation = activeConversation.value
    if (conversation) {
      conversation.lastMessageAt = latest
      conversation.messages = messages.value.filter(item => ['user', 'assistant'].includes(item.role) && !item.failed).length
      if (messages.value.length) delete conversation.emptyDraft
    }
  })

  function reset() {
    cancelLiveReply()
    for (const timer of titleObservers.values()) clearTimeout(timer)
    titleObservers.clear()
    titleSettled.clear()
    storeEpoch++
    conversationLoadPromise = null
    newChatPromise = null
    traceLoadVersion++
    conversations.value = []
    activeId.value = null
    messages.value = []
    generating.value = false
    agentStatus.value = ''
    drawingProgress.value = []
    latestTrace.value = null
    regeneratingId.value = null
    loaded.value = false
    pendingMapMessage.value = null
  }

  async function loadConversations() {
    if (conversationLoadPromise) return conversationLoadPromise
    const epoch = storeEpoch
    const rememberedId = rememberedConversationId()
    const promise = (async () => {
      const result = await chatApi.list()
      if (epoch !== storeEpoch) return
      const emptyDraftIds = new Set(conversations.value.filter(item => item.emptyDraft).map(item => item.id))
      conversations.value = (result.items || []).map(item => ({ ...item, emptyDraft: emptyDraftIds.has(item.id), date: displayDate(item.updatedAt || item.createdAt) }))
      if (!conversations.value.some(item => item.id === activeId.value)) {
        activeId.value = conversations.value.find(item => item.id === rememberedId)?.id
          || conversations.value.find(item => item.messages > 0)?.id
          || conversations.value[0]?.id || null
      }
      loaded.value = true
      for (const item of conversations.value) if (item.messages >= 2) observeTitle(item.id)
      if (activeId.value) await loadMessages(activeId.value)
      else { messages.value = []; latestTrace.value = null }
    })()
    conversationLoadPromise = promise
    try { await promise } finally { if (conversationLoadPromise === promise) conversationLoadPromise = null }
  }

  async function loadMessages(id) {
    if (liveReply && liveReply.conversationId !== id) cancelLiveReply()
    const version = ++traceLoadVersion
    const result = await chatApi.messages(id)
    if (version !== traceLoadVersion) return
    const items = (result.items || []).map(item => {
      const merged = { ...item, ...(item.metadata || {}) }
      return { ...merged, sources: normalizeSources(merged.citations) }
    })
    await fillCitationFilenames(items)
    if (version === traceLoadVersion) {
      activeId.value = id
      latestTrace.value = null
      messages.value = items
      if (items.some(item => item.role === 'assistant')) observeTitle(id)
      try {
        const run = await chatApi.latestAgentRun(id)
        if (activeId.value === id && version === traceLoadVersion) latestTrace.value = run.trace
      } catch { /* 历史消息仍应正常显示；新回复会通过流式事件提供轨迹。 */ }
    }
  }

  async function loadLatestTrace(id = activeId.value) {
    if (!id || generating.value) return
    const version = traceLoadVersion
    try {
      const run = await chatApi.latestAgentRun(id)
      if (activeId.value === id && version === traceLoadVersion) latestTrace.value = run.trace
    } catch { /* 不影响会话消息的展示。 */ }
  }

  async function newChat({ keepEmpty = false } = {}) {
    if (liveReply) cancelLiveReply()
    if (newChatPromise) return newChatPromise
    const epoch = storeEpoch
    const promise = (async () => {
      if (conversationLoadPromise) await conversationLoadPromise
      else if (!loaded.value) await loadConversations()
      if (epoch !== storeEpoch) return
      const blank = conversations.value.find(item => item.title === '新会话' && item.messages === 0 &&
        (!item.taskId || item.taskId === 'general') && !(item.id === activeId.value && messages.value.length))
      if (blank) {
        if (activeId.value !== blank.id) await loadMessages(blank.id)
        return
      }
      traceLoadVersion++
      const item = await chatApi.create({ title: '新会话' })
      if (epoch !== storeEpoch) return
      const index = conversations.value.findIndex(row => row.id === item.id)
      if (index >= 0) conversations.value[index] = { ...conversations.value[index], ...item }
      else conversations.value.unshift({ ...item, date: '刚刚', emptyDraft: !keepEmpty })
      activeId.value = item.id
      messages.value = []
      latestTrace.value = null
    })()
    newChatPromise = promise
    try { await promise } finally { if (newChatPromise === promise) newChatPromise = null }
  }

  function queueMapMessage(conversationId, content, skillId = '') {
    pendingMapMessage.value = { conversationId, content, skillId }
  }

  function takeMapMessage(conversationId) {
    if (pendingMapMessage.value?.conversationId !== conversationId) return null
    const pending = pendingMapMessage.value
    pendingMapMessage.value = null
    return pending
  }

  async function remove(id) {
    if (liveReply?.conversationId === id) cancelLiveReply()
    await chatApi.remove(id)
    conversations.value = conversations.value.filter(item => item.id !== id)
    if (activeId.value === id) {
      activeId.value = conversations.value[0]?.id || null
      messages.value = []
      latestTrace.value = null
      if (activeId.value) await loadMessages(activeId.value)
    }
  }

  async function removeMessage(messageId) {
    if (!activeId.value) return
    await chatApi.removeMessage(activeId.value, messageId)
    messages.value = messages.value.filter(item => item.id !== messageId)
  }

  async function removeMany(ids) {
    const idSet = new Set(ids)
    if (liveReply && idSet.has(liveReply.conversationId)) cancelLiveReply()
    for (const id of idSet) await chatApi.remove(id)
    conversations.value = conversations.value.filter(item => !idSet.has(item.id))
    if (idSet.has(activeId.value)) {
      activeId.value = conversations.value[0]?.id || null
      messages.value = []
      latestTrace.value = null
      if (activeId.value) await loadMessages(activeId.value)
    }
  }

  async function rename(id, title) {
    const updated = await chatApi.update(id, { title })
    const index = conversations.value.findIndex(item => item.id === id)
    if (index >= 0) conversations.value[index] = { ...conversations.value[index], ...updated }
    if (index >= 0) delete conversations.value[index].emptyDraft
  }

  async function togglePin(id) {
    const item = conversations.value.find(conversation => conversation.id === id)
    if (!item) return
    const updated = await chatApi.update(id, { pinned: !item.pinned })
    Object.assign(item, updated)
    delete item.emptyDraft
  }

  async function ensureConversation() {
    if (!loaded.value) await loadConversations()
    if (activeId.value && !conversations.value.some(item => item.id === activeId.value)) activeId.value = null
    if (!activeId.value) await newChat()
    return activeId.value
  }

  /**
   * 发一条消息。skill 是挂在输入框上的能力（可为空），
   * 它自带专用系统提示词，随之一起交给对话链路，标题也只取用户补充的那部分。
   */
  async function send(content, attachments = [], skill = null, display = null, options = {}) {
    if (generating.value) return false
    generating.value = true
    let id
    try { id = await ensureConversation() }
    catch (error) { generating.value = false; ui.toast(error.message, 'error'); return false }
    traceLoadVersion++
    latestTrace.value = null
    const temporaryId = `local-user-${Date.now()}`
    const optimisticMessage = {
      id: temporaryId,
      role: 'user',
      content,
      ...(display || {}),
      deepThinking: Boolean(options.deepThinking),
      skill: skill ? { id: skill.id, label: skill.label, systemPrompt: skill.systemPrompt } : undefined,
      createdAt: new Date().toISOString()
    }
    messages.value.push(optimisticMessage)
    generating.value = true
    drawingProgress.value = []
    agentStatus.value = options.deepThinking ? '知识生成中 · 第 1 轮' : ''
    const draftId = `local-assistant-${Date.now()}`
    const reply = startReply(id, draftId)
    let pendingCitations = []
    let pendingWebSources = []
    try {
      const payload = {
        streamId: reply.streamId,
        content,
        attachmentIds: attachments.filter(item => item.type === 'image').map(item => item.id).filter(Boolean),
        attachmentNames: attachments.filter(item => item.type === 'image').map(item => item.name),
        attachmentPreviewIds: attachments.filter(item => item.type === 'image').map(item => item.previewId || ''),
        textAttachments: attachments.filter(item => item.type === 'text').map(item => ({
          name: item.name, content: item.content, mimeType: item.mimeType || 'text/plain'
        })),
        deepThinking: Boolean(options.deepThinking),
        skill: skill ? { id: skill.id, label: skill.label, systemPrompt: skill.systemPrompt } : null
      }
      if (backendEnabled && ['flowchart', 'mindmap', 'poster'].includes(skill?.id)) {
        agentStatus.value = skill.id === 'poster' ? '正在设计海报' :
          skill.id === 'flowchart' ? '正在绘制流程图' : '正在绘制思维导图'
        const onDrawingEvent = event => {
          if (reply.stopped || reply.epoch !== storeEpoch) return
          if (event.type === 'trace' && event.trace && activeId.value === id) {
            latestTrace.value = event.trace
          }
          if (event.type === 'error' && event.trace && activeId.value === id) {
            latestTrace.value = event.trace
          }
          if (event.type !== 'progress' || !event.step) return
          const current = drawingProgress.value.findIndex(step => step.title === event.step.title)
          if (current >= 0) drawingProgress.value.splice(current, 1, event.step)
          else drawingProgress.value.push(event.step)
        }
        let result
        try {
          result = await (skill.id === 'poster' ? chatApi.streamPoster(id, payload, onDrawingEvent, reply.controller.signal)
            : chatApi.streamDiagram(id, payload, onDrawingEvent, reply.controller.signal))
        } catch (error) {
          if (reply.stopped) throw error
          if (error?.status !== 404 || error?.message !== '会话不存在') throw error
          liveReply = null
          await newChat()
          liveReply = reply
          id = activeId.value
          reply.conversationId = id
          messages.value.push(optimisticMessage)
          drawingProgress.value = []
          result = await (skill.id === 'poster' ? chatApi.streamPoster(id, payload, onDrawingEvent, reply.controller.signal)
            : chatApi.streamDiagram(id, payload, onDrawingEvent, reply.controller.signal))
        }
        const localIndex = messages.value.findIndex(item => item.id === temporaryId)
        if (localIndex >= 0) messages.value.splice(localIndex, 1,
          { ...result.userMessage, ...result.userMessage.metadata, ...(display || {}) })
        // The progress card belongs only to the active drawing request.
        // Remove it before the completed diagram enters the conversation.
        drawingProgress.value = []
        generating.value = false
        messages.value.push({ ...result.assistantMessage, ...result.assistantMessage.metadata })
        if (activeId.value === id) latestTrace.value = result.trace || null
      } else if (backendEnabled) {
        reply.serverControlled = true
        await chatApi.streamChatReply(id, payload, reply.controller.signal, async event => {
          await reply.wait()
          if (reply.epoch !== storeEpoch || activeId.value !== id) return
          if (event.type === 'trace' && activeId.value === id) latestTrace.value = event.trace
          if (event.type === 'agent_start') {
            agentStatus.value = `${event.agent === 'reflection' ? '反思评估中' : '知识生成中'} · 第 ${event.attempt} 轮`
          }
          if (event.type === 'agent_review' && !event.approved) {
            agentStatus.value = `评分 ${Number(event.score).toFixed(2)}，正在修订`
          }
          if (event.type === 'tool_end' && event.tool === 'search_knowledge_base' && event.citations?.length) {
            pendingCitations = event.citations
            const draft = messages.value.find(item => item.id === draftId)
            if (draft) draft.citations = pendingCitations
          }
          if (event.type === 'tool_end' && event.tool === 'web_search') {
            pendingWebSources = event.sources || []
            const draft = messages.value.find(item => item.id === draftId)
            if (draft) draft.webSources = pendingWebSources
          }
          if (event.type === 'delta') {
            if (!event.text) return
            const draft = messages.value.find(item => item.id === draftId)
            if (draft) draft.content += event.text
            else messages.value.push({ id: draftId, role: 'assistant', content: event.text,
              citations: pendingCitations, webSources: pendingWebSources, createdAt: new Date().toISOString() })
          }
          if (event.type === 'done') {
            if (event.trace && activeId.value === id) latestTrace.value = event.trace
            const userIndex = messages.value.findIndex(item => item.id === temporaryId)
            if (userIndex >= 0) messages.value.splice(userIndex, 1, { ...event.userMessage, ...event.userMessage.metadata, ...(display || {}) })
            const assistantMessage = { ...event.assistantMessage, ...event.assistantMessage.metadata }
            const draftIndex = messages.value.findIndex(item => item.id === draftId)
            if (draftIndex >= 0) messages.value.splice(draftIndex, 1, { ...assistantMessage, sources: normalizeSources(assistantMessage.citations) })
            else messages.value.push({ ...assistantMessage, sources: normalizeSources(assistantMessage.citations) })
          }
        })
        await fillCitationFilenames(messages.value)
        if (activeId.value === id) {
          try {
            latestTrace.value = (await chatApi.latestAgentRun(id)).trace || latestTrace.value
          } catch { /* 流式轨迹仍可显示；下次打开会话再尝试恢复。 */ }
        }
      } else {
        const result = await chatApi.send(id, payload)
        await reply.wait()
        latestTrace.value = (await chatApi.latestAgentRun(id)).trace
        const localIndex = messages.value.findIndex(item => item.id === temporaryId)
        if (localIndex >= 0) messages.value.splice(localIndex, 1, { ...result.userMessage, ...(display || {}) })
        messages.value.push({
          ...result.assistantMessage,
          sources: normalizeSources(result.assistantMessage.citations)
        })
      }
      const conversation = conversations.value.find(item => item.id === id)
      if (conversation?.title === '新会话') conversation.title = String(content || attachments[0]?.name || '新会话').trim().slice(0, 160)
      observeTitle(id)
      return true
    } catch (error) {
      if (reply.stopped || error?.name === 'AbortError' || reply.epoch !== storeEpoch) return false
      messages.value = messages.value.filter(item => item.id !== draftId)
      messages.value.push({
        id: `local-assistant-error-${Date.now()}`,
        role: 'assistant',
        content: error?.message || '回复生成失败，请稍后重试。',
        failed: true,
        createdAt: new Date().toISOString()
      })
      return false
    } finally {
      if (liveReply === reply) {
        liveReply = null
        outputPaused.value = false
        generating.value = false
        agentStatus.value = ''
        drawingProgress.value = []
      }
    }
  }

  async function saveDiagram(messageId, xml, baseVersion) {
    const id = activeId.value
    if (!id) throw new Error('会话不存在')
    const updated = await chatApi.saveDiagram(id, messageId, xml, baseVersion)
    if (activeId.value === id) {
      const index = messages.value.findIndex(item => item.id === messageId)
      if (index >= 0) messages.value.splice(index, 1, { ...updated, ...updated.metadata })
    }
    return updated
  }

  async function editDiagramTurn(messageId, content, xml, baseVersion) {
    const id = activeId.value
    if (!id) throw new Error('会话不存在')
    const result = await chatApi.editDiagramTurn(id, messageId, content, xml, baseVersion)
    if (activeId.value === id) {
      const index = messages.value.findIndex(item => item.id === messageId)
      if (index >= 0) messages.value.splice(index, 1, { ...result.message, ...result.message.metadata })
    }
    return result
  }

  async function regenerate(assistantId) {
    if (generating.value) return false
    const index = messages.value.findIndex(item => item.id === assistantId && item.role === 'assistant')
    if (index < 0) return false
    const original = messages.value[index]
    const question = messages.value.slice(0, index).reverse().find(item => item.role === 'user')
    const questionText = question?.content || question?.transcript || ''
    if (!questionText && !question?.attachments?.length) return false
    const conversationId = activeId.value
    traceLoadVersion++
    latestTrace.value = null
    const appendRegeneration = messages.value.slice(index + 1).some(item => item.role === 'user' || item.role === 'assistant')
    const placeholderId = `local-regenerating-${assistantId}`
    const repeatedQuestionId = `local-repeated-question-${assistantId}`
    const draftId = appendRegeneration ? `local-regenerated-${assistantId}` : assistantId
    const reply = startReply(conversationId, draftId, placeholderId)
    if (appendRegeneration) {
      messages.value.push({ ...question, id: repeatedQuestionId, content: questionText, createdAt: new Date().toISOString() })
      messages.value.push({ id: placeholderId, role: 'assistant', regenerating: true })
    } else {
      messages.value.splice(index, 1, { id: placeholderId, role: 'assistant', regenerating: true })
    }
    generating.value = true
    agentStatus.value = question.deepThinking ? '知识生成中 · 第 1 轮' : ''
    regeneratingId.value = assistantId
    let pendingCitations = []
    let pendingWebSources = []
    try {
      if (backendEnabled) {
        reply.serverControlled = true
        await chatApi.streamChatReply(conversationId, {
          streamId: reply.streamId,
          content: questionText,
          regenerateMessageId: assistantId,
          skill: question.skill || null,
          deepThinking: Boolean(question.deepThinking),
          voiceMode: Boolean(question.realtime),
          realtimeSessionId: question.realtimeSessionId || null
        }, reply.controller.signal, async event => {
          await reply.wait()
          if (reply.epoch !== storeEpoch || activeId.value !== conversationId) return
          if (event.type === 'trace' && activeId.value === conversationId) latestTrace.value = event.trace
          if (event.type === 'agent_start') {
            agentStatus.value = `${event.agent === 'reflection' ? '反思评估中' : '知识生成中'} · 第 ${event.attempt} 轮`
          }
          if (event.type === 'agent_review' && !event.approved) {
            agentStatus.value = `评分 ${Number(event.score).toFixed(2)}，正在修订`
          }
          if (event.type === 'tool_end' && event.tool === 'search_knowledge_base' && event.citations?.length) {
            pendingCitations = event.citations
          }
          if (event.type === 'tool_end' && event.tool === 'web_search') pendingWebSources = event.sources || []
          if (event.type === 'delta' && event.text) {
            const currentIndex = messages.value.findIndex(item => item.id === placeholderId)
            const draftIndex = messages.value.findIndex(item => item.id === draftId && item.regeneratedDraft)
            if (currentIndex >= 0) messages.value.splice(currentIndex, 1, {
              id: draftId, role: 'assistant', content: event.text, citations: pendingCitations,
              webSources: pendingWebSources,
              regeneratedDraft: true, createdAt: appendRegeneration ? new Date().toISOString() : original.createdAt
            })
            else if (draftIndex >= 0) messages.value[draftIndex].content += event.text
          }
          if (event.type === 'done') {
            if (event.trace && activeId.value === conversationId) latestTrace.value = event.trace
            const updated = { ...event.assistantMessage, ...event.assistantMessage.metadata }
            const currentIndex = messages.value.findIndex(item => item.id === placeholderId || (item.id === draftId && item.regeneratedDraft))
            if (currentIndex >= 0) messages.value.splice(currentIndex, 1, { ...updated, sources: normalizeSources(updated.citations) })
            if (appendRegeneration) {
              const questionIndex = messages.value.findIndex(item => item.id === repeatedQuestionId)
              if (questionIndex >= 0) messages.value.splice(questionIndex, 1, { ...event.userMessage, ...event.userMessage.metadata })
            }
          }
        })
        if (activeId.value === conversationId) {
          try {
            latestTrace.value = (await chatApi.latestAgentRun(conversationId)).trace || latestTrace.value
          } catch { /* 保留流式事件里的轨迹。 */ }
        }
      } else {
        const updated = await chatApi.regenerate(conversationId, assistantId, questionText, appendRegeneration)
        await reply.wait()
        latestTrace.value = (await chatApi.latestAgentRun(conversationId)).trace
        const currentIndex = messages.value.findIndex(item => item.id === placeholderId)
        if (currentIndex >= 0) messages.value.splice(currentIndex, 1, { ...updated, sources: normalizeSources(updated.citations) })
        if (appendRegeneration) {
          const questionIndex = messages.value.findIndex(item => item.id === repeatedQuestionId)
          if (questionIndex >= 0) messages.value.splice(questionIndex, 1, updated.repeatedQuestion)
        }
      }
      await fillCitationFilenames(messages.value)
      return true
    } catch (error) {
      if (reply.stopped || error?.name === 'AbortError' || reply.epoch !== storeEpoch) {
        if (!appendRegeneration && activeId.value === conversationId && !messages.value.some(item => item.id === assistantId)) {
          messages.value.splice(index, 0, original)
        }
        return false
      }
      const currentIndex = messages.value.findIndex(item => item.id === placeholderId || (item.id === draftId && item.regeneratedDraft))
      if (currentIndex >= 0) messages.value.splice(currentIndex, 1, ...(appendRegeneration ? [] : [original]))
      if (appendRegeneration) messages.value = messages.value.filter(item => item.id !== repeatedQuestionId)
      ui.toast(error?.message || '重新生成失败，请稍后重试', 'error')
      return false
    } finally {
      if (liveReply === reply) {
        liveReply = null
        outputPaused.value = false
        generating.value = false
        agentStatus.value = ''
        regeneratingId.value = null
      }
    }
  }

  async function sendVoice(blob, duration, knownTranscript = '') {
    const audioUrl = URL.createObjectURL(blob)
    const wave = Array.from({ length: 22 }, (_, index) => 26 + Math.round(Math.abs(Math.sin(index * 1.7)) * 68))
    const voiceDisplay = transcript => ({ type: 'voice', content: '', transcript, audioUrl,
      duration: Math.max(1, Math.round(duration || 1)), wave })
    if (backendEnabled) {
      generating.value = true
      try {
        const form = new FormData()
        form.append('file', blob, `voice-${Date.now()}.webm`)
        const result = knownTranscript ? { text: knownTranscript } : await speechApi.transcribe(form)
        generating.value = false
        const sent = await send(result.text, [], null, voiceDisplay(result.text))
        if (!sent) URL.revokeObjectURL(audioUrl)
        return sent
      } catch (error) {
        messages.value.push({
          id: `local-assistant-error-${Date.now()}`,
          role: 'assistant',
          content: error?.message || '语音识别失败，请检查 ASR 配置后重试。',
          failed: true,
          createdAt: new Date().toISOString()
        })
        return false
      } finally {
        generating.value = false
      }
    }
    const id = await ensureConversation()
    const form = new FormData()
    form.append('file', blob, `voice-${Date.now()}.webm`)
    generating.value = true
    try {
      const result = await chatApi.sendVoice(id, form, duration)
      messages.value.push(result.userMessage)
      messages.value.push({
        ...result.assistantMessage,
        sources: normalizeSources(result.assistantMessage.citations)
      })
      const transcript = result.userMessage?.content || ''
      const conversation = conversations.value.find(item => item.id === id)
      if (conversation?.title === '新会话' && transcript.trim()) conversation.title = transcript.trim().slice(0, 160)
      observeTitle(id)
      const index = messages.value.length - 2
      if (index >= 0 && messages.value[index]?.role === 'user') {
        messages.value.splice(index, 1, { ...messages.value[index], type: 'voice', content: '', transcript, audioUrl,
          duration: Math.max(1, Math.round(duration || 1)), wave })
      }
      return true
    } catch (error) {
      messages.value.push({
        id: `local-assistant-error-${Date.now()}`,
        role: 'assistant',
        content: error?.message || '语音消息处理失败，请检查 ASR 与 LLM 配置后重试。',
        failed: true,
        createdAt: new Date().toISOString()
      })
      return false
    } finally {
      generating.value = false
    }
  }

  return {
    conversations, activeId, activeConversation, messages, generating, outputPaused, pauseOutput, resumeOutput, agentStatus, latestTrace, regeneratingId,
    loaded, observeTitle, reset, loadConversations, loadMessages, loadLatestTrace, newChat, queueMapMessage, takeMapMessage, remove, removeMessage, removeMany, rename, togglePin, send, saveDiagram, editDiagramTurn, regenerate, sendVoice, drawingProgress
  }
})
