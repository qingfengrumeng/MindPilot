/** Preview contains masked saved credentials; only unsaved input may be revealed. */
export function modelConfigPreview(document, drafts, dirty, hideKeys = true) {
  const result = JSON.parse(JSON.stringify(document || { format_version: 1, model_routes: {}, providers: {}, integrations: {} }))
  for (const id of dirty) {
    const [providerId, category] = id.split(':')
    const draft = drafts[providerId], model = draft?.configs[category]
    if (!model) continue
    const provider = result.providers[providerId] ||= { display_name: providerId, api_family: providerId === 'custom' ? 'openai' : providerId, credentials: { api_key: '', speech_key: '' }, models: {} }
    const speech = providerId === 'volcengine' && ['asr', 'tts'].includes(category)
    const field = speech ? 'speechApiKey' : 'apiKey', clear = speech ? 'clearSpeechApiKey' : 'clearApiKey', name = speech ? 'speech_key' : 'api_key'
    if (draft[clear]) provider.credentials[name] = ''
    else if (draft[field]?.trim()) provider.credentials[name] = hideKeys ? '••••••••' : draft[field].trim()
    provider.models[category] = { endpoint: model.baseUrl, model_id: model.model, options: { dimensions: model.dimensions ?? null, voice: model.voice ?? null, instruction: model.instruction ?? null, embedding_protocol: model.embeddingProtocol || 'compatible', vision: !!model.vision } }
  }
  return result
}

/** Split JSON into plain text tokens; Vue escapes every token when rendering. */
export function jsonSyntaxTokens(line) {
  const tokens = [], pattern = /"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g
  let offset = 0
  for (const match of line.matchAll(pattern)) {
    if (match.index > offset) tokens.push({ text: line.slice(offset, match.index), kind: 'punctuation' })
    const text = match[0], end = match.index + text.length
    const kind = text.startsWith('"') ? (/^\s*:/.test(line.slice(end)) ? 'key' : 'string') : text === 'null' ? 'null' : ['true', 'false'].includes(text) ? 'boolean' : 'number'
    tokens.push({ text, kind }); offset = end
  }
  if (offset < line.length) tokens.push({ text: line.slice(offset), kind: 'punctuation' })
  return tokens
}
