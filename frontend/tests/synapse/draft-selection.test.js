import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import test from 'node:test'

async function rangesAfterEdit() {
  const source = await readFile(new URL('../../public/synapse/app.js', import.meta.url), 'utf8')
  const code = source.slice(source.indexOf('function draftRangesAfterEdit('), source.indexOf('function updateDraftText('))
  const context = vm.createContext({})
  vm.runInContext(`${code};globalThis.edit = draftRangesAfterEdit`, context)
  return (...args) => JSON.parse(JSON.stringify(context.edit(...args)))
}

test('appending a quick phrase or typed text does not extend the selected range', async () => {
  const edit = await rangesAfterEdit()
  assert.deepEqual(edit('印成 P', '印成 P 举例', [{ start: 0, end: 4 }]), [{ start: 0, end: 4 }])
  assert.deepEqual(edit('印成 P', '印成 P 自己输入', [{ start: 0, end: 4 }]), [{ start: 0, end: 4 }])
})

test('typing inside selected text splits the purple range around the new text', async () => {
  const edit = await rangesAfterEdit()
  assert.deepEqual(edit('ABCD', 'AB手动CD', [{ start: 0, end: 4 }]), [
    { start: 0, end: 2 }, { start: 4, end: 6 },
  ])
  assert.deepEqual(edit('ABCD', '', [{ start: 0, end: 4 }]), [])
})

test('replacing selected text with identical manual input removes its purple origin', async () => {
  const edit = await rangesAfterEdit()
  assert.deepEqual(edit('ABCD', 'ABCD', [{ start: 0, end: 4 }], { start: 0, end: 4 }), [])
  assert.deepEqual(edit('AAAA', 'AAAAA', [{ start: 0, end: 4 }], { start: 4, end: 4 }), [{ start: 0, end: 4 }])
})
