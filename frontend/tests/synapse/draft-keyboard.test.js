import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import test from 'node:test'

async function keyboard() {
  const source = await readFile(new URL('../../public/synapse/app.js', import.meta.url), 'utf8')
  const code = source.slice(source.indexOf('const draftCompositions'), source.indexOf("app.addEventListener('beforeinput'"))
  const handlers = {}, state = { draft: { text: '', sending: false } }
  let sends = 0
  class Textarea {
    value = '新的追问'
    closest() { return {} }
  }
  const input = new Textarea()
  const context = vm.createContext({
    app: { addEventListener: (name, handler) => { handlers[name] = handler } },
    HTMLTextAreaElement: Textarea, state,
    updateDraftText: text => { state.draft.text = text },
    submitDraft: () => { sends += 1 },
  })
  vm.runInContext(code, context)
  const key = (options = {}) => {
    const event = { target: input, key: 'Enter', shiftKey: false, isComposing: false,
      prevented: false, preventDefault() { this.prevented = true }, ...options }
    handlers.keydown(event)
    return event
  }
  return { handlers, state, input, key, sends: () => sends }
}

test('Enter sends the latest input and Shift+Enter allows the native newline', async () => {
  const editor = await keyboard()
  assert.equal(editor.key({ shiftKey: true }).prevented, false)
  assert.equal(editor.sends(), 0)
  assert.equal(editor.key().prevented, true)
  assert.equal(editor.state.draft.text, editor.input.value)
  assert.equal(editor.sends(), 1)
})

test('IME confirmation does not send and a subsequent normal Enter does', async () => {
  const editor = await keyboard()
  editor.handlers.compositionstart({ target: editor.input })
  assert.equal(editor.key().prevented, false)
  editor.handlers.compositionend({ target: editor.input })
  assert.equal(editor.key({ isComposing: true }).prevented, false)
  assert.equal(editor.key({ keyCode: 229 }).prevented, false)
  assert.equal(editor.sends(), 0)
  editor.key()
  assert.equal(editor.sends(), 1)
})

test('Enter does not submit a draft already being sent or another input field', async () => {
  const editor = await keyboard()
  editor.state.draft.sending = true
  editor.key()
  assert.equal(editor.sends(), 0)
  assert.equal(editor.key({ target: {} }).prevented, false)
})
