import test from 'node:test'
import assert from 'node:assert/strict'
import { createReplyControl } from '../src/lib/replyControl.js'

test('pause holds the existing reply and resume delivers its tail exactly once', async () => {
  const reply = createReplyControl()
  const text = ['before']
  reply.pause()
  const pending = reply.wait().then(() => text.push('after'))
  await new Promise(resolve => setTimeout(resolve, 20))
  assert.deepEqual(text, ['before'])
  reply.resume()
  await pending
  assert.deepEqual(text, ['before', 'after'])
  await reply.wait()
})

test('cancel wakes a paused reader and prevents future output', async () => {
  const reply = createReplyControl()
  reply.pause()
  const pending = reply.wait()
  reply.cancel()
  await assert.rejects(pending, { name: 'AbortError' })
  await assert.rejects(reply.wait(), { name: 'AbortError' })
  assert.equal(reply.controller.signal.aborted, true)
})
