/**
 * 数据适配层 —— 前端唯一的取数入口。
 *
 * 后端模式下账号、会话和文字回复使用 FastAPI；其他模块仍保留演示数据。
 *
 * 接入 FastAPI 时只需把下面每个方法的实现换成 request(...) 调用，
 * 返回结构保持不变，页面与 store 无需改动。
 */
import {
  demoState,
  demoSeed,
  delay,
  nextId,
  now,
  clock,
  persistDemoState
} from '@/mock/store'
import { apiJsonLines, apiRequest, apiStream, backendEnabled } from '@/api/http'
import { recordingToPcmBase64 } from '@/lib/speechPcm'
import { latestConversationMessageAt } from '@/lib/conversationTime'

export const knowledgeGraphApi = {
  async get() {
    if (!backendEnabled) return { wiki: { nodes: [], edges: [], issues: [] }, semantic: { nodes: [], edges: [], issues: [] }, communities: [], build: { status: 'empty' } }
    return apiRequest('get', '/knowledge-graph')
  },
  async build() {
    if (!backendEnabled) throw new Error('知识图谱构建需要连接后端与文本模型')
    return apiRequest('post', '/knowledge-graph/build')
  },
  async query(question) {
    if (!backendEnabled) throw new Error('图谱查询需要连接后端')
    return apiRequest('post', '/knowledge-graph/query', { question }, { timeout: 120000 })
  },
  async export() { return apiRequest('get', '/knowledge-graph/export') }
}

/* ------------------------------------------------------------------ *
 * 演示用的检索与应答
 * ------------------------------------------------------------------ */

const domainLabels = Object.fromEntries(demoSeed.domains.map(item => [item.id, item.label]))

/** 深拷贝一份演示数据，避免页面直接改动种子对象。 */
const clone = value => JSON.parse(JSON.stringify(value))

function withConversationActivity(item) {
  const messages = demoState.messages[item.id] || []
  return { ...item, createdAt: item.createdAt || messages[0]?.createdAt || item.updatedAt,
    lastMessageAt: latestConversationMessageAt(messages) }
}

/** 极简关键词召回，用来在演示中挑出与提问最相关的原文片段。 */
function recallChunks(query, limit = 3) {
  const text = String(query || '').toLowerCase()
  const tokens = text.split(/[\s，。、？；：""''（）()【】\[\],.!?/\\-]+/).filter(item => item.length >= 2)
  const scored = demoSeed.chunks.map(chunk => {
    const haystack = `${chunk.text} ${chunk.section} ${chunk.documentId}`.toLowerCase()
    const document = demoSeed.documents.find(item => item.id === chunk.documentId)
    const title = String(document?.title || '').toLowerCase()
    let score = 0
    for (const token of tokens) {
      if (haystack.includes(token)) score += 2
      if (title.includes(token)) score += 3
    }
    return { chunk, document, score }
  })
  const hits = scored.filter(item => item.score > 0).sort((a, b) => b.score - a.score)
  const picked = hits.length ? hits : scored.slice(0, limit)
  return picked.slice(0, limit).map(({ chunk, document }) => ({
    chunkId: chunk.id,
    documentId: chunk.documentId,
    title: document?.title || '本地资料',
    domain: chunk.domain,
    page: chunk.page,
    section: chunk.section,
    text: chunk.text
  }))
}

/** 演示用的回答模板。真实实现中这里由后端 LLM 生成。 */
function composeReply(question) {
  const sources = recallChunks(question, 3)
  const primary = sources[0]
  if (!primary) {
    return {
      content: '这个问题在当前的授权知识域内没有检索到直接证据。\n\n我没有为此编造引用。可以选择的下一步：\n\n1. 换一个更具体的问法，或指明希望检索的知识域；\n2. 在「知识资料」中导入相关材料后重新提问；\n3. 如果属于库外信息，我可以走 research 任务联网检索（会先检查外发授权与预算）。',
      citations: [],
      toolCalls: [
        { id: nextId('call'), tool: 'search_knowledge_base', params: `query=${JSON.stringify(question.slice(0, 40))} top_k=8`, status: 'empty', duration: '286 ms' }
      ],
      inference: '证据不足'
    }
  }

  const lines = [
    `根据检索到的 ${sources.length} 个片段，可以这样回答：`,
    '',
    `**原文事实**：${primary.text}`,
    ''
  ]
  if (sources.length > 1) {
    lines.push('**补充证据**：')
    sources.slice(1).forEach((source, index) => {
      lines.push(`${index + 1}. 《${source.title}》第 ${source.page} 页「${source.section}」：${source.text}`)
    })
    lines.push('')
  }
  lines.push(
    '**需要区分的地方**：以上是原文表述，未做外推。如果要把结论迁移到你的具体场景，还需要结合你手上的实验数据确认，这一步属于模型推断而不是原文事实。'
  )

  return {
    content: lines.join('\n'),
    citations: sources,
    toolCalls: [
      { id: nextId('call'), tool: 'search_knowledge_base', params: `query=${JSON.stringify(String(question).slice(0, 40))} top_k=8 domains=[${Object.keys(domainLabels).join(', ')}]`, status: 'ok', duration: `${280 + Math.floor(Math.random() * 180)} ms` },
      { id: nextId('call'), tool: 'read_source', params: `chunk-id=${primary.chunkId}`, status: 'ok', duration: `${60 + Math.floor(Math.random() * 60)} ms` }
    ],
    inference: '原文事实'
  }
}

/**
 * 挂上能力之后，输入框里的内容就是这次的提问本身——卡片铺进去的完整示例也一样，
 * 用户没改就照原样发。这里只做一次空白收尾，不再从正文里摘掉什么前缀。
 */
function focusText(content) {
  return String(content || '').trim()
}

/** 能力在消息与轨迹上留的最小信息：够展示标识、够说明用了哪段系统提示词，不含凭据。 */
function skillMeta(skill) {
  if (!skill?.id) return null
  return { id: skill.id, label: skill.label, systemPrompt: skill.systemPrompt }
}

function buildMessage(role, content, extra = {}) {
  return {
    id: nextId('msg'),
    role,
    content,
    citations: [],
    toolCalls: [],
    createdAt: new Date().toISOString(),
    ...extra
  }
}

/** 工具调用在监控链上的展示名。 */
const toolLabels = {
  search_knowledge_base: '知识库检索',
  read_source: '读取原文片段',
  web_search: '联网检索',
  push_feishu: '飞书推送'
}

/**
 * 组装一次对话的 Agent 全链路轨迹：主 Agent 路由 → RAG 检索 → 子 Agent 工具调用 → LLM 生成。
 * 真实实现中这些节点来自后端的 span，这里用本地演示数据还原同样的结构。
 */
function buildTrace(question, reply, tokens, skill = null) {
  const sources = reply.citations || []
  const hasSources = sources.length > 0
  const stages = [
    {
      id: nextId('stage'),
      kind: 'agent',
      agent: 'main',
      title: '主 Agent · 任务路由',
      status: 'ok',
      duration: '24 ms',
      summary: hasSources ? '识别为知识问答，分配 knowledge_qa 任务并规划检索流程' : '识别为知识问答，但未命中可检索证据',
      detail: {
        decision: 'knowledge_qa',
        confidence: hasSources ? 0.97 : 0.62,
        plan: hasSources
          ? ['1. 改写查询并拆分检索意图', '2. 并行召回向量 + 关键词候选', '3. RRF 融合后交给 Reranker 重排', '4. 依据片段生成带引用的回答']
          : ['1. 改写查询并拆分检索意图', '2. 在授权知识域内召回候选', '3. 未命中 → 如实说明证据不足，不编造引用']
      }
    },
    // 走了能力才有这一段：说明这一次回答套用了哪条能力的专用系统提示词。
    ...(skill
      ? [{
          id: nextId('stage'),
          kind: 'skill',
          agent: 'main',
          title: '主 Agent · 载入能力系统提示词',
          status: 'ok',
          duration: '11 ms',
          summary: `能力「${skill.label}」的专用系统提示词已注入本次上下文，回答按该能力的口径组织`,
          detail: {
            skill: skill.id,
            label: skill.label,
            systemPrompt: skill.systemPrompt
          }
        }]
      : []),
    {
      id: nextId('stage'),
      kind: 'retrieval',
      title: 'RAG 检索',
      status: hasSources ? 'ok' : 'empty',
      duration: `${280 + Math.floor(Math.random() * 220)} ms`,
      summary: hasSources ? `召回 ${sources.length} 个相关片段，经重排后进入生成上下文` : '授权知识域内未召回相关片段',
      detail: {
        query: String(question || '').slice(0, 60),
        strategy: 'vector + keyword → RRF 融合 → reranker 重排',
        results: sources.map(source => ({
          title: source.title,
          page: source.page,
          section: source.section,
          text: source.text
        }))
      }
    },
    ...(reply.toolCalls || []).map(call => ({
      id: call.id,
      kind: 'tool',
      agent: 'sub',
      title: `子 Agent · ${toolLabels[call.tool] || call.tool}`,
      status: call.status === 'ok' ? 'ok' : 'empty',
      duration: call.duration,
      summary: call.status === 'ok' ? `已完成 ${toolLabels[call.tool] || call.tool}` : '未命中结果，返回空集',
      detail: {
        tool: call.tool,
        params: call.params,
        result: call.status === 'ok' ? '命中并返回对应片段 / 原文' : 'empty'
      }
    })),
    {
      id: nextId('stage'),
      kind: 'model',
      title: 'LLM 生成',
      model: 'gpt-4o-mini',
      status: 'ok',
      duration: `${420 + Math.floor(Math.random() * 260)} ms`,
      summary: `输入 ${tokens.input} / 输出 ${tokens.output} tokens · ${tokens.cost}`,
      detail: {
        model: 'gpt-4o-mini',
        inputTokens: tokens.input,
        outputTokens: tokens.output,
        output: reply.content
      }
    }
  ]
  return {
    runId: nextId('run'),
    status: hasSources ? 'ok' : 'empty',
    startedAt: now(),
    finishedAt: now(),
    tokens,
    stages
  }
}

/* ------------------------------------------------------------------ *
 * 对话
 * ------------------------------------------------------------------ */

export const chatApi = {
  suggestions: (conversationId, question) => apiRequest('post', `/conversations/${encodeURIComponent(conversationId)}/suggestions`, {question}, {timeout:90000}),
  titleStatus(id) {
    if (!backendEnabled) return Promise.resolve({ status: 'idle' })
    return apiRequest('get', `/conversations/${encodeURIComponent(id)}/title-generation`)
  },
  generateDiagram(id, payload) {
    if (!backendEnabled) throw new Error('AI 绘图需要启动本地后端')
    return apiRequest('post', `/conversations/${id}/diagrams`, payload, { timeout: 120000 })
  },
  async streamDiagram(id, payload, onEvent, signal) {
    if (!backendEnabled) throw new Error('AI 绘图需要启动本地后端')
    let result = null
    await apiJsonLines(`/conversations/${id}/diagrams/stream`, payload, signal, event => {
      onEvent?.(event)
      if (event.type === 'done') result = event
    })
    return result
  },
  async streamPoster(id, payload, onEvent, signal) {
    if (!backendEnabled) throw new Error('海报设计需要启动本地后端')
    let result = null
    let failure = null
    await apiJsonLines(`/conversations/${id}/posters/stream`, payload, signal, event => {
      onEvent?.(event)
      if (event.type === 'done') result = event
      if (event.type === 'error') failure = event.message || '海报设计失败'
    })
    if (failure) throw new Error(failure)
    if (!result) throw new Error('海报任务未返回结果')
    return result
  },
  artifactBlob(artifactId) {
    if (!backendEnabled) throw new Error('下载海报需要启动本地后端')
    return apiRequest('get', `/agent-artifacts/${encodeURIComponent(artifactId)}`,
      undefined, { responseType: 'blob', timeout: 60000 })
  },
  saveDiagram(id, messageId, xml, baseVersion) {
    if (!backendEnabled) throw new Error('保存图表需要启动本地后端')
    return apiRequest('put', `/conversations/${id}/messages/${messageId}/diagram`,
      { xml, baseVersion }, { timeout: 30000 })
  },
  editDiagramTurn(id, messageId, content, xml, baseVersion) {
    if (!backendEnabled) throw new Error('AI 修改图表需要启动本地后端')
    return apiRequest('post', `/conversations/${id}/messages/${messageId}/diagram/turns`,
      { content, xml, baseVersion }, { timeout: 120000 })
  },
  async latestAgentRun(id) {
    if (backendEnabled) return apiRequest('get', `/conversations/${id}/agent-runs/latest`)
    const messages = demoState.messages[id] || []
    return { trace: [...messages].reverse().find(item => item.role === 'assistant' && item.trace)?.trace || null }
  },
  async agentRuns(id) {
    if (backendEnabled) return apiRequest('get', `/conversations/${id}/agent-runs`)
    return { items: (demoState.messages[id] || []).filter(item => item.trace).map(item => ({ id: item.trace.runId, trace: item.trace })) }
  },
  addMessage(id, payload) {
    if (!backendEnabled) throw new Error('实时通话记录需要启动本地后端')
    return apiRequest('post', `/conversations/${id}/messages`, payload)
  },
  streamReply(id, content, signal, onEvent, options = {}) {
    if (!backendEnabled) throw new Error('语音对话需要启动本地后端')
    return apiJsonLines(`/conversations/${id}/reply/stream`, { content, voiceMode: true, realtimeSessionId: options.realtimeSessionId }, signal, onEvent)
  },
  streamChatReply(id, payload, signal, onEvent) {
    if (!backendEnabled) throw new Error('文本对话需要启动本地后端')
    return apiJsonLines(`/conversations/${id}/reply/stream`, payload, signal, onEvent)
  },
  controlReply(id, streamId, action) {
    return apiRequest('post', `/conversations/${id}/reply/streams/${streamId}/${action}`)
  },
  async regenerate(id, assistantId, question, append = false) {
    if (backendEnabled) throw new Error('请使用流式回复接口重新生成')
    await delay(900)
    const target = (demoState.messages[id] || []).find(item => item.id === assistantId && item.role === 'assistant')
    if (!target) throw new Error('要重新生成的回复不存在')
    const reply = composeReply(focusText(question))
    if (append) {
      const repeatedQuestion = buildMessage('user', question)
      const assistantMessage = buildMessage('assistant', reply.content, {
        citations: reply.citations, toolCalls: reply.toolCalls, inference: reply.inference
      })
      demoState.messages[id].push(repeatedQuestion, assistantMessage)
      persistDemoState()
      return { ...assistantMessage, repeatedQuestion }
    }
    Object.assign(target, { content: reply.content, citations: reply.citations, toolCalls: reply.toolCalls, inference: reply.inference })
    persistDemoState()
    return target
  },
  async list() {
    if (backendEnabled) return apiRequest('get', '/conversations')
    await delay(180)
    const items = [...demoState.conversations].sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
      return String(b.updatedAt).localeCompare(String(a.updatedAt))
    })
    return { items: items.map(withConversationActivity) }
  },

  async messages(id) {
    if (backendEnabled) {
      const result = await apiRequest('get', `/conversations/${id}/messages`)
      return { items: result.items.map(item => ({ ...item, ...item.metadata })) }
    }
    await delay(160)
    return { items: demoState.messages[id] || [] }
  },

  async create(payload = {}) {
    if (backendEnabled) return apiRequest('post', '/conversations', payload)
    await delay(120)
    if ((!payload.title || payload.title === '新会话') && (!payload.taskId || payload.taskId === 'general')) {
      const blank = demoState.conversations.find(item => item.title === '新会话' &&
        (!item.taskId || item.taskId === 'general') && !(demoState.messages[item.id] || []).length)
      if (blank) return withConversationActivity(blank)
    }
    const conversation = {
      id: nextId('conv'),
      title: payload.title || '新会话',
      taskId: payload.taskId || 'general',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      pinned: false,
      messages: 0
    }
    demoState.conversations.unshift(conversation)
    demoState.messages[conversation.id] = []
    persistDemoState()
    return withConversationActivity(conversation)
  },

  async update(id, payload) {
    if (backendEnabled) return apiRequest('patch', `/conversations/${id}`, payload)
    await delay(100)
    const conversation = demoState.conversations.find(item => item.id === id)
    if (!conversation) return {}
    Object.assign(conversation, payload, { updatedAt: now() })
    persistDemoState()
    return withConversationActivity(conversation)
  },

  async remove(id) {
    if (backendEnabled) return apiRequest('delete', `/conversations/${id}`)
    await delay(140)
    demoState.conversations = demoState.conversations.filter(item => item.id !== id)
    delete demoState.messages[id]
    persistDemoState()
    return { ok: true }
  },

  async removeMessage(conversationId, messageId) {
    if (backendEnabled) return apiRequest('delete', `/conversations/${conversationId}/messages/${messageId}`)
    demoState.messages[conversationId] = (demoState.messages[conversationId] || []).filter(item => item.id !== messageId)
    const conversation = demoState.conversations.find(item => item.id === conversationId)
    if (conversation) conversation.messages = demoState.messages[conversationId].length
    persistDemoState()
    return { ok: true }
  },

  async send(id, payload) {
    if (backendEnabled) {
      const result = await apiRequest('post', `/conversations/${id}/reply`, payload, { timeout: 90000 })
      return {
        userMessage: { ...result.userMessage, ...result.userMessage.metadata },
        assistantMessage: { ...result.assistantMessage, ...result.assistantMessage.metadata }
      }
    }
    await delay(900)
    const list = demoState.messages[id] || (demoState.messages[id] = [])
    const skill = skillMeta(payload.skill)
    // 提问用输入框里的原文：卡片铺进来的完整示例也可以直接就是这次的问题。
    const focus = focusText(payload.content)
    const demoAttachments = (payload.textAttachments || []).map(file => ({ ...file, type: 'text' }))
    const userMessage = buildMessage('user', payload.content, {
      ...(skill ? { skill } : {}), ...(demoAttachments.length ? { attachments: demoAttachments } : {})
    })
    const reply = composeReply(focus)
    const tokens = {
      input: 1200 + reply.citations.length * 860,
      output: 240 + reply.content.length,
      cost: `¥${(0.08 + reply.citations.length * 0.05).toFixed(2)}`
    }
    const assistantMessage = buildMessage('assistant', reply.content, {
      citations: reply.citations,
      toolCalls: reply.toolCalls,
      inference: reply.inference,
      tokens,
      trace: buildTrace(focus, reply, tokens, skill)
    })
    list.push(userMessage, assistantMessage)
    const conversation = demoState.conversations.find(item => item.id === id)
    if (conversation) {
      if (conversation.title === '新会话' && payload.content?.trim()) conversation.title = payload.content.trim().slice(0, 160)
      conversation.updatedAt = now()
      conversation.messages = list.length
    }
    persistDemoState()
    return { userMessage, assistantMessage }
  },

  async sendVoice(id, form, duration) {
    if (backendEnabled) throw new Error('语音问答接口尚未接入后端')
    await delay(1100)
    const seconds = Number(duration) || 0
    const transcript = '这条语音已经转成文字，可以直接作为提问使用。'
    const list = demoState.messages[id] || (demoState.messages[id] = [])
    const userMessage = buildMessage('user', transcript, { voice: { duration: seconds } })
    const reply = composeReply(transcript)
    const tokens = {
      input: 1200 + reply.citations.length * 860,
      output: 240 + reply.content.length,
      cost: `¥${(0.08 + reply.citations.length * 0.05).toFixed(2)}`
    }
    const assistantMessage = buildMessage('assistant', reply.content, {
      citations: reply.citations,
      toolCalls: reply.toolCalls,
      inference: reply.inference,
      tokens,
      trace: buildTrace(transcript, reply, tokens)
    })
    list.push(userMessage, assistantMessage)
    persistDemoState()
    return { userMessage, assistantMessage }
  },

  async uploadFile(form) {
    if (backendEnabled) {
      return apiRequest('post', '/files', form, { timeout: 130000 })
    }
    await delay(420)
    const file = form.get?.('file')
    return {
      id: nextId('upload'),
      name: file?.name || 'attachment.pdf',
      size: file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : '0.1 MB'
    }
  },

  uploadPosterAsset(form) {
    if (!backendEnabled) return this.uploadFile(form)
    return apiRequest('post', '/files/poster-assets', form, { timeout: 130000 })
  },
  previewImage(previewId) {
    if (!backendEnabled) throw new Error('图片预览需要启动本地后端')
    return apiRequest('get', `/files/previews/${encodeURIComponent(previewId)}`, undefined, { responseType: 'blob' })
  },

  async suggestTask(content) {
    await delay(80)
    const text = String(content || '')
    if (/对比|比较|差异/.test(text)) return 'paper_compare'
    if (/追溯|演进|脉络/.test(text)) return 'concept_trace'
    if (/导图|流程|海报|可视化/.test(text)) return 'visualize'
    if (/调研|联网|最新/.test(text)) return 'research'
    if (/推送|周报|发送/.test(text)) return 'push_notification'
    if (/记忆|偏好/.test(text)) return 'memory_manage'
    if (/导入|整理|编译/.test(text)) return 'wiki_organize'
    return 'knowledge_qa'
  }
}

/* ------------------------------------------------------------------ *
 * 知识资料
 * ------------------------------------------------------------------ */

export const documentsApi = {
  async compileWiki(id){
    if(backendEnabled)return apiRequest('post',`/documents/${encodeURIComponent(id)}/wiki-compile`)
    throw new Error('Wiki编译需要连接后端与已配置的文本模型')
  },
  async list(params = {}) {
    if (backendEnabled) {
      const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''))
      return apiRequest('get', `/documents${query.toString() ? `?${query}` : ''}`)
    }
    await delay(200)
    let items = [...demoState.documents]
    if (params.domain && params.domain !== 'all') items = items.filter(item => item.domain === params.domain)
    if (params.type && params.type !== 'all') items = items.filter(item => item.type === params.type)
    if (params.keyword) {
      const keyword = String(params.keyword).toLowerCase()
      items = items.filter(item => `${item.title} ${item.tags?.join(' ')}`.toLowerCase().includes(keyword))
    }
    return { items, total: items.length }
  },

  async get(id) {
    if (backendEnabled) return apiRequest('get', `/documents/${id}`)
    await delay(140)
    const document = demoState.documents.find(item => item.id === id)
    if (!document) throw new Error('资料不存在')
    return {
      ...document,
      chunks: demoSeed.chunks.filter(item => item.documentId === id),
      relatedWiki: demoSeed.pageSources.filter(item => item.documentId === id).map(item => ({
        pageId: item.pageId,
        title: demoSeed.wikiPages.find(page => page.id === item.pageId)?.title || ''
      }))
    }
  },

  async search(query, topK = 5) {
    if (backendEnabled) return apiRequest('post', '/documents/search', { query, topK })
    await delay(120)
    return { items: recallChunks(query, topK) }
  },

  async importFile(form) {
    if (backendEnabled) return apiRequest('post', '/documents', form, { timeout: 120000 })
    await delay(240)
    const file = form.get?.('file')
    const name = file?.name || '新导入资料'
    const document = {
      id: nextId('doc'),
      title: name.replace(/\.[^.]+$/, ''),
      type: 'note',
      typeLabel: '笔记',
      domain: form.get?.('domain') || 'personal_learning',
      source: file ? `本地文件 · ${name}` : '本地文件',
      importedAt: now(),
      pages: 1,
      size: file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : '0.2 MB',
      chunks: 0,
      indexedChunks: 0,
      status: 'uploaded',
      contentHash: 'sha256:pending…',
      version: 'v1',
      author: '本人',
      year: new Date().getFullYear(),
      tags: ['待整理'],
      quality: 'ok',
      qualityLabel: '待解析',
      index: { vector: 'pending', keyword: 'pending', wiki: 'pending' },
      summary: '文件已保存。点击向量化按钮，开始解析与建立索引。'
    }
    demoState.documents.unshift(document)
    persistDemoState()
    return document
  },

  async vectorize(id) {
    if (backendEnabled) return apiRequest('post', `/documents/${id}/vectorize`)
    const document = demoState.documents.find(item => item.id === id)
    if (!document) throw new Error('资料不存在')
    if (document.status === 'ready') throw new Error('该资料已完成向量化')
    if (['queued', 'parsing', 'chunking', 'embedding'].includes(document.status)) throw new Error('该资料正在处理')
    document.status = 'queued'
    document.chunks = 0
    document.indexedChunks = 0
    document.readable = false
    document.errorMessage = ''
    persistDemoState()
    window.setTimeout(() => { document.status = 'parsing'; persistDemoState() }, 300)
    window.setTimeout(() => { document.status = 'chunking'; persistDemoState() }, 1100)
    window.setTimeout(() => { document.chunks = 24 + Math.floor(Math.random() * 80); document.status = 'embedding'; persistDemoState() }, 1900)
    window.setTimeout(() => { document.indexedChunks = Math.round(document.chunks * .5); persistDemoState() }, 2700)
    window.setTimeout(() => {
      document.indexedChunks = document.chunks
      document.status = 'ready'
      document.readable = true
      document.summary = `已生成 ${document.chunks} 个可引用知识分块。`
      persistDemoState()
    }, 3700)
    return document
  },

  async update(id, payload) {
    await delay(120)
    const document = demoState.documents.find(item => item.id === id)
    if (!document) return {}
    Object.assign(document, payload)
    persistDemoState()
    return document
  },

  async remove(id) {
    if (backendEnabled) return apiRequest('delete', `/documents/${id}`)
    await delay(180)
    demoState.documents = demoState.documents.filter(item => item.id !== id)
    persistDemoState()
    return { ok: true }
  }
}

/* ------------------------------------------------------------------ *
 * LLM Wiki
 * ------------------------------------------------------------------ */

export const wikiApi = {
  async list(params = {}) {
    await delay(200)
    let items = demoSeed.wikiPages
    if (params.domain && params.domain !== 'all') items = items.filter(item => item.domain === params.domain)
    if (params.type && params.type !== 'all') items = items.filter(item => item.type === params.type)
    return { items }
  },

  async get(id) {
    await delay(160)
    const page = demoSeed.wikiPages.find(item => item.id === id)
    if (!page) throw new Error('页面不存在')
    const sources = demoSeed.pageSources
      .filter(item => item.pageId === id)
      .map(item => {
        const chunk = demoSeed.chunks.find(entry => entry.id === item.chunkId)
        const document = demoSeed.documents.find(entry => entry.id === item.documentId)
        return {
          chunkId: item.chunkId,
          documentId: item.documentId,
          title: document?.title || '',
          page: item.page,
          section: chunk?.section || '',
          text: chunk?.text || ''
        }
      })
    const related = [...page.outgoing.map(link => ({ ...link, id: link.targetId })), ...page.backlinks.map(id2 => ({ id: id2, targetId: id2, relation: '反向链接', direction: 'in' }))]
      .map(link => ({
        ...link,
        title: demoSeed.wikiPages.find(entry => entry.id === link.id)?.title || link.id,
        typeLabel: demoSeed.wikiPages.find(entry => entry.id === link.id)?.typeLabel || ''
      }))
    return { ...page, sources, related }
  },

  /** 保存人工修改；人工编辑过的页面在自动编译时会被标记保护。 */
  async save(id, payload) {
    await delay(300)
    return { ...payload, id, version: payload.version, manuallyEdited: true }
  },

  /** 自动编译产生的更新建议，需要人工确认后才写入。 */
  async proposals() {
    await delay(240)
    return {
      items: [
        {
          id: 'proposal-1',
          pageId: 'wiki-long-context',
          title: '长上下文技术',
          kind: 'append',
          reason: '《Zotero 导出文献元数据》新增 3 条长上下文文献，其中 1 条包含可引用的对比结论',
          addedLines: 2,
          removedLines: 0,
          at: '2026-09-20 09:12',
          status: 'pending'
        },
        {
          id: 'proposal-2',
          pageId: 'wiki-domain-isolation',
          title: '知识域隔离',
          kind: 'conflict',
          reason: '来源《知识域隔离设计草稿》已更新至 v4，与当前页面在「缓存退化」结论上不一致',
          addedLines: 6,
          removedLines: 4,
          at: '2026-09-17 09:30',
          status: 'conflict'
        },
        {
          id: 'proposal-3',
          pageId: 'wiki-rrf',
          title: 'RRF 融合',
          kind: 'append',
          reason: '《Chroma 向量检索实践笔记》新增 metadata 过滤相关内容',
          addedLines: 3,
          removedLines: 0,
          at: '2026-09-15 19:44',
          status: 'pending'
        }
      ]
    }
  },

  async approve(proposalId) {
    await delay(420)
    return { id: proposalId, status: 'merged' }
  },

  async reject(proposalId) {
    await delay(260)
    return { id: proposalId, status: 'rejected' }
  }
}

/* ------------------------------------------------------------------ *
 * 知识可视化
 * ------------------------------------------------------------------ */

/** 产出类型的中文口径，覆盖首页功能与知识可视化里的全部产物类型。 */
const ARTIFACT_TYPE_LABELS = {
  mindmap: '思维导图',
  concept: '概念图谱',
  flowchart: '流程图',
  compare: '对比表',
  navigation: '知识导航',
  report: '调研报告',
  poster: '技术海报'
}

/** 只有结构化的图类产物才带节点与连线，并登记一份可打开的结构图。 */
const GRAPH_ARTIFACT_TYPES = new Set(['mindmap', 'concept', 'flowchart', 'compare', 'navigation'])

/** 图类产物各自取一份同类型的示例结构，保证打开后形态对得上。 */
const GRAPH_SOURCE_BY_TYPE = {
  flowchart: 'artifact-flowchart-rope',
  mindmap: 'artifact-mindmap-lc'
}

export const visualizationApi = {
  async artifacts() {
    await delay(200)
    return { items: demoState.artifacts }
  },

  async graph(id) {
    await delay(180)
    return demoSeed.mindmapGraph[id] || { root: null, nodes: [], edges: [] }
  },

  async generate(payload) {
    await delay(1500)
    const type = payload.type || 'mindmap'
    const isGraph = GRAPH_ARTIFACT_TYPES.has(type)
    const sourceGraph = demoSeed.mindmapGraph[GRAPH_SOURCE_BY_TYPE[type] || 'artifact-mindmap-lc']
    const artifact = {
      id: nextId('artifact'),
      type,
      typeLabel: ARTIFACT_TYPE_LABELS[type] || '结构化产物',
      title: payload.title || '新生成的产物',
      domain: payload.domain || 'personal_learning',
      createdAt: now(),
      version: 'v1',
      nodes: isGraph ? sourceGraph.nodes.length : 0,
      edges: isGraph ? sourceGraph.edges.length : 0,
      sources: 2,
      stale: false,
      updatedBy: '自动生成'
    }
    demoState.artifacts.unshift(artifact)
    if (isGraph) demoSeed.mindmapGraph[artifact.id] = clone(sourceGraph)
    persistDemoState()
    return artifact
  },

  async remove(id) {
    await delay(160)
    demoState.artifacts = demoState.artifacts.filter(item => item.id !== id)
    persistDemoState()
    return { ok: true }
  }
}

export const imageApi = {
  list() {
    if (!backendEnabled) return Promise.resolve({ items: [] })
    return apiRequest('get', '/images')
  },
  file(id) {
    return apiRequest('get', `/images/${id}/file`, undefined, { responseType: 'blob' })
  },
  remove(id) {
    return apiRequest('delete', `/images/${id}`)
  },
  async generate(payload) {
    if (!backendEnabled) throw new Error('AI 生图需要启动本地后端')
    return apiRequest('post', '/images/generate', payload, { timeout: 260000 })
  }
}

/* ------------------------------------------------------------------ *
 * 记忆管理
 * ------------------------------------------------------------------ */

export const memoryApi = {
  async list(params = {}) {
    await delay(200)
    let items = demoState.memoryItems
    if (params.tier && params.tier !== 'all') items = items.filter(item => item.tier === params.tier)
    if (params.domain && params.domain !== 'all') items = items.filter(item => item.domain === params.domain)
    return { items }
  },

  async create(payload) {
    await delay(280)
    const item = {
      id: nextId('mem'),
      tier: payload.tier || 'long_term',
      title: payload.title || '未命名记忆',
      content: payload.content || '',
      source: payload.source || '手动添加',
      updatedAt: now(),
      expiresAt: payload.tier === 'working' ? '任务结束后释放' : payload.tier === 'episodic' ? '30 天后' : '长期',
      domain: payload.domain || 'personal_learning',
      confirmed: true
    }
    demoState.memoryItems.unshift(item)
    persistDemoState()
    return item
  },

  async update(id, payload) {
    await delay(200)
    const item = demoState.memoryItems.find(entry => entry.id === id)
    if (!item) return {}
    Object.assign(item, payload, { updatedAt: now() })
    persistDemoState()
    return item
  },

  async remove(id) {
    await delay(180)
    demoState.memoryItems = demoState.memoryItems.filter(item => item.id !== id)
    persistDemoState()
    return { ok: true }
  }
}

/* ------------------------------------------------------------------ *
 * 授权中心
 * ------------------------------------------------------------------ */

export const grantsApi = {
  async list() {
    await delay(200)
    return { items: demoState.grants.filter(item => !item.hidden) }
  },

  async revoke(id) {
    await delay(360)
    const grant = demoState.grants.find(item => item.id === id)
    if (grant) {
      grant.status = 'revoked'
      grant.statusLabel = '已撤销'
      grant.expiresAt = '—'
      persistDemoState()
    }
    return grant || {}
  },

  async restore(id) {
    await delay(360)
    const grant = demoState.grants.find(item => item.id === id)
    if (grant) {
      grant.status = 'active'
      grant.statusLabel = '生效中'
      grant.expiresAt = '2026-12-31'
      persistDemoState()
    }
    return grant || {}
  },

  async create(payload) {
    await delay(600)
    const grant = {
      id: nextId('grant'),
      scope: payload.scope || 'tool',
      scopeLabel: payload.scope === 'directory' ? '授权目录' : payload.scope === 'sender' ? '推送目标' : '工具与供应商',
      title: payload.title || '新授权',
      detail: payload.detail || '由用户在授权中心手动添加',
      targets: payload.targets || [],
      targetLabel: (payload.targets || []).join('、') || '—',
      expiresAt: payload.expiresAt || '2026-12-31',
      status: 'active',
      statusLabel: '生效中',
      grantedAt: now(),
      lastUsedAt: '—'
    }
    demoState.grants.unshift(grant)
    persistDemoState()
    return grant
  },

  async egressCheck(domain) {
    await delay(260)
    const target = demoSeed.domains.find(item => item.id === domain)
    const blocked = target?.egress === 'local_only'
    return {
      allowed: !blocked,
      domain,
      rule: blocked ? 'domain.egress = local_only' : 'domain.egress = cloud_allowed',
      reason: blocked
        ? '该知识域标记为仅本地处理，检索片段不会进入云端 Embedding、重排与生成路径。'
        : '该知识域允许云端处理，外发前仍会按当前授权复核。'
    }
  }
}

/* ------------------------------------------------------------------ *
 * 运行面板
 * ------------------------------------------------------------------ */

export const tracesApi = {
  async tasks() {
    await delay(220)
    return { items: demoSeed.tasks }
  },

  async task(id) {
    await delay(180)
    const task = demoSeed.tasks.find(item => item.id === id)
    if (!task) throw new Error('任务不存在')
    return {
      ...task,
      spans: demoSeed.traces.filter(item => item.taskId === id),
      profile: demoSeed.taskProfiles.find(item => item.id === task.taskId)
    }
  },

  async traces() {
    await delay(200)
    return { items: demoSeed.traces }
  },

  async usage() {
    await delay(200)
    return demoSeed.usage
  }
}

/* ------------------------------------------------------------------ *
 * 模型与检索配置
 * ------------------------------------------------------------------ */

const configStorageKey = 'mindpilot-model-config'

function loadConfigOverride() {
  try {
    return JSON.parse(localStorage.getItem(configStorageKey) || 'null')
  } catch {
    return null
  }
}

export const configApi = {
  async get() {
    await delay(220)
    const override = loadConfigOverride()
    const services = demoSeed.modelServices.map(service => {
      const saved = override?.services?.[service.id]
      if (!saved) return clone(service)
      return {
        ...service,
        ...saved,
        fields: service.fields.map(field => (
          saved.fields?.[field.key] !== undefined ? { ...field, value: saved.fields[field.key] } : field
        ))
      }
    })
    return {
      services,
      settings: { ...demoSeed.defaultSettings, ...(override?.settings || {}) },
      strategies: demoSeed.retrievalStrategies,
      egressRules: [
        { id: 'local_only', label: 'local_only 域不进入云端路径', enabled: true, locked: true, note: '检索、重排、生成、摘要与缓存均不例外' },
        { id: 'strict_egress', label: '外发前按当前授权复核', enabled: true, locked: false, note: '授权撤销后旧结果不再返回' },
        { id: 'strip_credentials', label: '日志与轨迹中剥离凭证', enabled: true, locked: true, note: 'API Key 不进入日志、轨迹与模型上下文' },
        { id: 'cache_scope', label: '缓存键包含资料版本与权限范围', enabled: true, locked: false, note: '避免不同授权状态命中同一条缓存' }
      ]
    }
  },

  async save(payload) {
    await delay(340)
    try {
      localStorage.setItem(configStorageKey, JSON.stringify(payload))
    } catch {
      // 忽略存储失败，配置仅在本次会话生效。
    }
    return { ok: true }
  },

  /** 演示环境不发起真实探测，仅回显一条本地校验结果。 */
  async test(id) {
    await delay(880)
    return {
      id,
      health: 'ok',
      healthLabel: '配置格式校验通过',
      latency: `${80 + Math.floor(Math.random() * 300)} ms`,
      message: '演示环境未发起真实请求。接入后端后此处会探测连通性并返回真实延迟。'
    }
  },

  async reset() {
    await delay(200)
    localStorage.removeItem(configStorageKey)
    return { ok: true }
  }
}

/* ------------------------------------------------------------------ *
 * 知识域
 * ------------------------------------------------------------------ */

export const domainsApi = {
  async list() {
    await delay(140)
    return { items: demoSeed.domains }
  },
  async taskProfiles() {
    await delay(140)
    return { items: demoSeed.taskProfiles, pools: demoSeed.toolPools }
  },
  async quickActions() {
    await delay(120)
    return { items: demoSeed.quickActions }
  }
}

/* ------------------------------------------------------------------ *
 * 语音识别仅使用后端配置的 ASR 服务。
 * ------------------------------------------------------------------ */

export const speechApi = {
  greeting(signal) {
    return apiStream('/speech/greeting', {}, signal)
  },
  synthesize(text, signal) {
    return apiStream('/speech/synthesize', { text }, signal)
  },
  async transcribe(form) {
    if (backendEnabled) {
      const blob = form.get('file')
      if (!blob) throw new Error('请先录制语音')
      const audio = await recordingToPcmBase64(blob)
      return apiRequest('post', '/speech/transcribe', { audio }, { timeout: 100000 })
    }
    throw new Error('语音转文字需要连接后端 ASR 服务')
  }
}
