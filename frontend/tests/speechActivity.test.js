import test from 'node:test'
import assert from 'node:assert/strict'
import { createSpeechActivityDetector } from '../src/lib/speechActivity.js'

test('silence and brief noise do not count as speech', () => {
  const detector = createSpeechActivityDetector()
  for (let i = 0; i < 20; i++) assert.equal(detector.observe(0.003, 128), false)
  assert.equal(detector.observe(0.04, 128), false)
  assert.equal(detector.observe(0.003, 128), false)
  assert.equal(detector.detected, false)
})

test('sustained speech enables transcription', () => {
  const detector = createSpeechActivityDetector()
  assert.equal(detector.observe(0.026, 128), false)
  assert.equal(detector.observe(0.031, 128), true)
  assert.equal(detector.detected, true)
  assert.equal(detector.observe(0.002, 128), true)
})
