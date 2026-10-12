import { chatApi } from '@/api'
import { conversationMapApi } from '@/api/conversationMap'
import { backendEnabled } from '@/api/http'
import { demoState, persistDemoState } from '@/mock/store'

const stringify = value => typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2)

/** Native conversations remain the source of truth; Synapse only owns organization. */
export function createSynapseBridge({ chat, conversationBoard, publish, notify }) {
  const board = conversationBoard.board
  const cache = new Map(), running = new Map()
  let timer, disposed = false
  function scheduleSave() {
    clearTimeout(timer)
    timer = setTimeout(() => { if (!disposed) conversationBoard.save().catch(error => notify(error.message)) }, 300)
  }
  function owned(id) {
    const conversation = chat.conversations.find(item => item.id === id)
    if (!conversation) throw new Error('会话不存在或不属于当前账号')
    return conversation
  }
  function node(id) { owned(id); return conversationBoard.ensureNode(id) }
  function mapRoot(id) {
    const ownedIds = new Set(chat.conversations.map(item => item.id)), visited = new Set()
    let cursor = id
    while (!visited.has(cursor)) {
      visited.add(cursor)
      const item = board.nodes[cursor]
      const parent = item?.synapseMapId || item?.synapseParentId
      if (!ownedIds.has(parent)) return cursor
      cursor = parent
    }
    // Invalid legacy cycles must still resolve consistently for every member.
    const chain = [...visited]
    return chain.slice(chain.indexOf(cursor)).sort()[0]
  }
  function workspaces() {
    const maps = new Map()
    for (const conversation of chat.conversations) {
      const root = mapRoot(conversation.id)
      if (!maps.has(root)) maps.set(root, { id: `conversation-map:${root}`, title: owned(root).title,
        path: null, rootSessionId: root, groupId: board.nodes[root]?.groupId || null, sessionIds: [] })
      maps.get(root).sessionIds.push(conversation.id)
    }
    return [...maps.values()]
  }
  function migrateRegionScopes() {
    const key = 'dsh-synapse:canvas-actions:v1', saved = board.synapse?.[key]
    if (!saved) return
    let actions
    try { actions = JSON.parse(saved) } catch { return }
    if (!Array.isArray(actions?.regions)) return
    const ids = new Set(chat.conversations.map(item => item.id))
    let changed = false
    actions.regions = actions.regions.flatMap(region => {
      if (!region || typeof region.workspaceId !== 'string' || region.workspaceId.startsWith('dsh:conversation-map:')) return [region]
      const roots = Array.isArray(region.roots) ? region.roots : []
      const sessions = Array.isArray(region.sessions) ? region.sessions : []
      const sessionOf = card => typeof card === 'string' ? card.split(':turn:')[0] : null
      const members = [...roots.map(sessionOf), ...sessions].filter(id => ids.has(id))
      const maps = [...new Set(members.map(mapRoot))]
      if (!maps.length) return [region]
      changed = true
      return maps.map((root, index) => ({ ...region, id: index ? `${region.id}:map:${root}` : region.id,
        workspaceId: `dsh:conversation-map:${root}`,
        roots: roots.filter(card => ids.has(sessionOf(card)) && mapRoot(sessionOf(card)) === root),
        sessions: sessions.filter(id => ids.has(id) && mapRoot(id) === root) }))
    })
    if (changed) { board.synapse[key] = JSON.stringify(actions); scheduleSave() }
  }
  function sync() {
    if (disposed) return
    migrateRegionScopes()
    publish('synapse:workspaces', { workspaces: workspaces() })
    const item = chat.activeConversation
    publish('synapse:current-session', { session: item ? { id: item.id, title: item.title, cwd: null } : null })
  }
  async function records(id, force = false) {
    const conversation = owned(id)
    const active = id === chat.activeId
    const stamp = `${conversation.updatedAt}:${conversation.lastMessageAt}:${conversation.messages}`
    if (running.has(id)) return running.get(id).messages
    if (!force && cache.get(id)?.stamp === null) return cache.get(id).messages
    if (active && chat.messages.length) return chat.messages.filter(item => !item.contextSource)
    if (!force && cache.get(id)?.stamp === stamp) return cache.get(id).messages
    const result = await chatApi.messages(id)
    cache.set(id, { stamp, messages: result.items || [] })
    return result.items || []
  }
  function sequences(id, rows) {
    const item = node(id)
    item.synapseSequences ||= {}
    let next = Math.max(item.synapseSeedLength || 1, ...Object.values(item.synapseSequences).map(value => value + 1))
    let changed = false
    for (const row of rows) {
      if (!['user', 'assistant'].includes(row.role) || row.contextSource) continue
      if (!Number.isSafeInteger(item.synapseSequences[row.id])) {
        item.synapseSequences[row.id] = next++
        changed = true
      }
    }
    if (changed) scheduleSave()
    return item.synapseSequences
  }
  function processOf(message, trace) {
    const calls = message.toolCalls || []
    if (calls.length) return calls.map(call => ({ callId: call.callId || call.id, name: call.tool || call.name || '工具调用',
      arguments: stringify(call.params || call.arguments), result: call.result ? stringify(call.result) : (call.status || ''), error: call.error || null }))
    return (trace?.stages || []).filter(stage => ['tool', 'retrieval'].includes(stage.kind)).map(stage => ({
      callId: stage.id, name: stage.title || stage.detail?.tool || '工具调用',
      arguments: stringify(stage.detail?.query || stage.detail?.arguments || {}),
      result: stringify(stage.detail?.result || stage.detail?.results || stage.summary),
      error: stage.status === 'error' ? stage.summary : null,
    }))
  }
  async function thread(id) {
    const conversation = owned(id), item = node(id)
    const rows = await records(id)
    // Call markers and the assistant's greeting do not start a user turn.
    if (!rows.some(row => row.role === 'user' && !row.contextSource
      && String(row.content || row.transcript || '').trim())) return null
    const seq = sequences(id, rows)
    const stored = cache.get(id) || { messages: rows }
    cache.set(id, stored)
    if (!stored.runsLoaded && !running.has(id)) {
      stored.runsLoaded = true
      try { stored.runs = (await chatApi.agentRuns(id)).items } catch { stored.runs = [] }
    }
    let latestTrace = id === chat.activeId ? chat.latestTrace : null
    if (!latestTrace && backendEnabled && !running.has(id)) {
      const stored = cache.get(id)
      if (stored && !stored.traceLoaded) {
        stored.traceLoaded = true
        try { stored.trace = (await chatApi.latestAgentRun(id)).trace } catch { /* Text cards still work. */ }
      }
      latestTrace = stored?.trace
    }
    const latestAssistant = [...rows].reverse().find(row => row.role === 'assistant')
    const messages = rows.filter(row => ['user', 'assistant'].includes(row.role) && !row.contextSource).map(row => {
      const meta = { ...row, ...row.metadata }
      const run = (stored.runs || []).find(run => run.id === meta.agentRunId || run.trace?.stages?.some(stage => ['output', 'result'].includes(stage.kind) && stage.detail?.answer === row.content))
      return { id: row.id, kind: row.failed || meta.failed ? 'error' : row.role, text: row.content || row.transcript || '',
        at: row.createdAt, sourceSeq: seq[row.id], process: row.role === 'assistant' ? processOf(meta, meta.trace || run?.trace || (row === latestAssistant ? latestTrace : null)) : [],
        ...(String(row.id).startsWith('local-assistant-') && !row.failed ? { pending: true } : {}) }
    })
    return { id, title: conversation.title, dshSessionId: id, dshSessionTitle: conversation.title,
      parentId: item.synapseParentId || null, sourceParentSessionId: item.synapseParentId || null, cardColors: item.synapseCardColors || {},
      sourceSeedLength: item.synapseSeedLength || null, color: item.color || '#8b5cf6',
      position: item.synapsePosition || { x: 86, y: 82 }, createdAt: conversation.createdAt,
      updatedAt: conversation.lastMessageAt || conversation.updatedAt, messages }
  }
  async function projection(id) {
    const workspace = workspaces().find(item => item.id === id)
    if (!workspace) throw new Error('工作区不存在')
    const projected = await Promise.all(workspace.sessionIds.map(thread))
    return { ...workspace, cwd: null, threads: projected.filter(Boolean) }
  }
  async function api(path, method = 'GET', body = {}) {
    if (path === '/synapse/api/workspaces' && method === 'GET') return { workspaces: workspaces().map(item => ({
      ...item, updatedAt: item.sessionIds.map(id => { const c = owned(id); return `${c.updatedAt}:${c.lastMessageAt}:${c.messages}:` }).join('|') })) }
    let match = path.match(/^\/synapse\/api\/workspaces\/([^/]+)$/)
    if (match && method === 'GET') return { workspace: await projection(match[1]) }
    match = path.match(/^\/synapse\/api\/threads\/([^/]+)\/branch$/)
    if (match && method === 'POST') {
      const parent = node(match[1]), child = node(body.dshSessionId)
      child.synapseParentId = match[1]
      child.groupId = parent.groupId || null
      if (body.position && Number.isFinite(body.position.x) && Number.isFinite(body.position.y)) child.synapsePosition = body.position
      if (body.title) await chat.rename(body.dshSessionId, String(body.title).slice(0, 160))
      await conversationBoard.save()
      // The committed question arrives just after the branch is allocated.
      return { thread: (await thread(body.dshSessionId)) || { id: body.dshSessionId, title: owned(body.dshSessionId).title,
        dshSessionId: body.dshSessionId, parentId: match[1], sourceSeedLength: child.synapseSeedLength, messages: [], position: child.synapsePosition } }
    }
    match = path.match(/^\/synapse\/api\/threads\/([^/]+)$/)
    if (match && method === 'PATCH') {
      const item = node(match[1])
      if (body.title) await chat.rename(match[1], String(body.title).slice(0, 160))
      if (body.color && /^#[0-9a-f]{6}$/i.test(body.color)) {
        if (body.cardId) {
          if (typeof body.cardId !== 'string' || !body.cardId.startsWith(`${match[1]}:turn:`) || body.cardId.length > 160) throw new Error('卡片不属于此会话')
          item.synapseCardColors ||= {}
          item.synapseCardColors[body.cardId] = body.color
        } else item.color = body.color
      }
      if (body.position && Number.isFinite(body.position.x) && Number.isFinite(body.position.y)) item.synapsePosition = body.position
      await conversationBoard.save(); return { thread: await thread(match[1]) }
    }
    if (path === '/synapse/api/sessions/sync' && method === 'POST') { sync(); return { workspaces: workspaces() } }
    if (path === '/synapse/api/reset' && method === 'POST') {
      for (const item of Object.values(board.nodes)) { delete item.synapseArchived; delete item.synapsePosition }
      board.synapse = {}; await conversationBoard.save(); return { workspaces: workspaces() }
    }
    throw new Error('不支持的地图操作')
  }
  async function fork(id, atSeq) {
    if (running.has(id)) throw new Error('请等待来源会话完成当前回复后再创建分支')
    const parent = owned(id), rows = await records(id, true), seq = sequences(id, rows)
    const source = Number.isInteger(atSeq) ? rows.find(row => seq[row.id] === atSeq && row.role === 'assistant') : [...rows].reverse().find(row => row.role === 'assistant')
    if (!source) throw new Error('请从已完成的回答创建分支')
    const title = `${parent.title.slice(0, 26)} · 分支`
    const result = await conversationMapApi.branch({ sourceId: id, mode: 'full', sourceMessageId: source.id, title })
    let childId
    if (result) {
      childId = result.id
      chat.conversations.unshift({ ...result, emptyDraft: false })
    } else {
      const created = await chatApi.create({ title })
      childId = created.id
      const end = rows.indexOf(source)
      const original = demoState.conversations.find(item => item.id === id)
      const child = demoState.conversations.find(item => item.id === childId)
      child.mapInjectedContext = [original?.mapInjectedContext, rows.slice(0, end + 1).map(row => `${row.role === 'user' ? '用户' : '助手'}：${row.content}`).join('\n')].filter(Boolean).join('\n\n')
      persistDemoState()
      chat.conversations.unshift({ ...created, emptyDraft: false })
    }
    const item = node(childId), parentNode = node(id)
    Object.assign(item, { synapseParentId: id, synapseSeedLength: seq[source.id] + 1, groupId: parentNode.groupId || null,
      x: parentNode.x + 310, y: parentNode.y + 210 })
    await conversationBoard.save()
    await chat.loadMessages(childId)
    sync()
    return { id: childId, title, cwd: null }
  }
  async function createSession(workspace) {
    const map = workspace ? workspaces().find(item => item.id === workspace) : workspaces().find(item => item.sessionIds.includes(chat.activeId))
    if (workspace && !map) throw new Error('会话地图不存在')
    const groupId = map?.groupId || null
    const id = await conversationBoard.createWorkspaceConversation(groupId, { reuseBlank: true })
    if (map && id !== map.rootSessionId) node(id).synapseMapId = map.rootSessionId
    await conversationBoard.save()
    sync()
    return { id, title: owned(id).title, cwd: null }
  }
  async function send(id, text, options = {}) {
    if (running.has(id) || (chat.generating && chat.activeId === id)) throw new Error('该会话正在回复，请稍后再发送')
    if (!String(text).trim()) throw new Error('消息不能为空')
    const base = [...await records(id)]
    const temporary = { id: `synapse-user-${crypto.randomUUID()}`, role: 'user', content: text, createdAt: new Date().toISOString() }
    const assistant = { id: `local-assistant-${Date.now()}`, role: 'assistant', content: '', createdAt: new Date().toISOString() }
    const task = { messages: [...base, temporary], text: '' }
    running.set(id, task)
    if (chat.activeId === id) chat.generating = true
    const registry = sequences(id, task.messages)
    const questionSeq = registry[temporary.id]
    if (owned(id).title === '新会话') owned(id).title = text.trim().slice(0, 160)
    owned(id).lastMessageAt = temporary.createdAt
    if (chat.activeId === id) chat.messages = task.messages
    publish('synapse:live-reply', { sessionId: id, running: true, text: '' })
    let accept, reject, accepted = false, completed = false
    const acknowledgment = new Promise((resolve, fail) => { accept = resolve; reject = fail })
    const onEvent = event => {
      if (!accepted) { accepted = true; accept({ sessionId: id }) }
      if (event.type === 'trace' && chat.activeId === id) chat.latestTrace = event.trace
      if (event.type === 'delta') {
        task.text += event.text
        assistant.content = task.text
        if (!task.messages.includes(assistant)) task.messages.push(assistant)
        if (chat.activeId === id) chat.messages = [...task.messages]
        publish('synapse:live-reply', { sessionId: id, running: true, text: task.text })
      }
      if (event.type === 'done') {
        completed = true
        registry[event.userMessage.id] = questionSeq
        delete registry[temporary.id]
        task.messages = [...base, event.userMessage, event.assistantMessage]
        if (chat.activeId === id) chat.messages = task.messages.map(row => ({ ...row, ...row.metadata }))
        cache.delete(id)
      }
    }
    ;(async () => {
      try {
        const payload = { content: text, deepThinking: Boolean(options.deepThinking) }
        if (backendEnabled) await chatApi.streamChatReply(id, payload, undefined, onEvent)
        else {
          accepted = true; accept({ sessionId: id })
          const result = await chatApi.send(id, payload)
          onEvent({ type: 'done', ...result })
        }
        if (!completed) throw new Error('回复未完成，请重试')
        const conversation = owned(id)
        conversation.messages = task.messages.length
        conversation.updatedAt = task.messages.at(-1)?.createdAt || new Date().toISOString()
        conversation.lastMessageAt = conversation.updatedAt
        delete conversation.emptyDraft
        chat.observeTitle?.(id)
      } catch (error) {
        if (!accepted) reject(error)
        const failed = { ...assistant, id: `${assistant.id}-error`, content: error.message || '回复失败，请重试', failed: true }
        task.messages = [...base, temporary, failed]
        cache.set(id, { stamp: null, messages: task.messages })
        if (chat.activeId === id) chat.messages = task.messages
        publish('synapse:bridge-error', { message: failed.content })
      } finally {
        running.delete(id)
        if (chat.activeId === id) chat.generating = false
        if (cache.get(id)?.stamp !== null) cache.delete(id)
        publish('synapse:live-reply', { sessionId: id, running: false, text: task.text })
        const conversation = chat.conversations.find(item => item.id === id)
        if (conversation) {
          conversation.messages = task.messages.length
          if (disposed) conversationBoard.save().catch(error => notify(error.message))
        }
        sync()
        scheduleSave()
      }
    })()
    return acknowledgment
  }
  function persist(key, value) {
    if (!/^dsh-synapse:(card-positions(?::v\d+)?|collapsed-cards:v1|quick-phrases:v1|branch-anchors|canvas-actions:v1)$/.test(key)) return
    if (value !== null && (typeof value !== 'string' || value.length > 500_000)) throw new Error('地图布局数据过大')
    board.synapse ||= {}
    if (value === null) delete board.synapse[key]
    else board.synapse[key] = value
    scheduleSave()
  }
  async function dispose() { disposed = true; clearTimeout(timer); if (conversationBoard.loaded) await conversationBoard.save() }
  return { api, fork, createSession, send, sync, persist, dispose, workspaces, running }
}
