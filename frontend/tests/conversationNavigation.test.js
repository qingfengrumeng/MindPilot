import assert from 'node:assert/strict'
import test from 'node:test'
import { userMessageForSequence } from '../src/lib/conversationNavigation.js'

const messages = [
  { id: 'q1', role: 'user' }, { id: 'a1', role: 'assistant' },
  { id: 'q2', role: 'user' }, { id: 'a2', role: 'assistant' }, { id: 'a2-extra', role: 'assistant' },
]
const sequences = { q1: 1, a1: 2, q2: 3, a2: 4, 'a2-extra': 5 }

test('opening either the question or its reply targets the same user message', () => {
  assert.equal(userMessageForSequence(messages, sequences, 1), messages[0])
  assert.equal(userMessageForSequence(messages, sequences, 2), messages[0])
  assert.equal(userMessageForSequence(messages, sequences, 3), messages[2])
  assert.equal(userMessageForSequence(messages, sequences, 5), messages[2])
})

test('an unavailable sequence does not jump to an unrelated message', () => {
  assert.equal(userMessageForSequence(messages, sequences, 99), null)
  assert.equal(userMessageForSequence(messages, undefined, 1), null)
})

test('a live turn without a committed sequence opens its latest user question', () => {
  assert.equal(userMessageForSequence(messages, sequences, undefined), messages[2])
})
