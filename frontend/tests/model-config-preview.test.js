import test from 'node:test'
import assert from 'node:assert/strict'
import { jsonSyntaxTokens, modelConfigPreview } from '../src/utils/modelConfigPreview.js'

test('preview keeps saved keys masked and shares unsaved keys within the correct service', () => {
  const saved = { format_version: 1, model_routes: { text: 'volcengine' }, providers: { volcengine: { display_name: '豆包', api_family: 'volcengine', credentials: { api_key: '••••••••', speech_key: '' }, models: {} } }, integrations: {} }
  const drafts = { volcengine: { apiKey: '', speechApiKey: 'new-speech-key', configs: { asr: { baseUrl: 'wss://speech.example/asr', model: 'resource' } } } }
  const dirty = new Set(['volcengine:asr'])
  const hidden = modelConfigPreview(saved, drafts, dirty)
  assert.equal(hidden.providers.volcengine.credentials.speech_key, '••••••••')
  const revealed = modelConfigPreview(saved, drafts, dirty, false)
  assert.equal(revealed.providers.volcengine.credentials.api_key, '••••••••')
  assert.equal(revealed.providers.volcengine.credentials.speech_key, 'new-speech-key')
  assert.equal(revealed.providers.volcengine.models.asr.endpoint, 'wss://speech.example/asr')
  assert.deepEqual(saved.providers.volcengine.models, {})
  drafts.volcengine.clearSpeechApiKey = true
  assert.equal(modelConfigPreview(saved, drafts, dirty).providers.volcengine.credentials.speech_key, '')
})

test('JSON syntax tokens preserve escaped strings and compact JSON exactly', () => {
  const text = JSON.stringify({ 'a"b': '<script>false</script>\\path', enabled: false, count: -1.25e30, missing: null })
  const tokens = jsonSyntaxTokens(text)
  assert.equal(tokens.map(t => t.text).join(''), text)
  assert.equal(tokens.find(t => t.text.includes('<script>')).kind, 'string')
  assert.equal(tokens.find(t => t.text === 'false').kind, 'boolean')
  assert.equal(tokens.find(t => t.text === 'null').kind, 'null')
  assert.equal(tokens.find(t => t.kind === 'number').text, '-1.25e+30')
  assert.equal(tokens.filter(t => t.kind === 'key').length, 4)
})
