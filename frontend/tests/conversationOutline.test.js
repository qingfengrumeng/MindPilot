import assert from 'node:assert/strict'
import test from 'node:test'
import { conversationQuestions, questionAtScrollPosition } from '../src/lib/conversationOutline.js'

test('the outline lists each user question in order and excludes replies and call markers', () => {
  const questions = conversationQuestions([
    { id: 'marker', role: 'system', content: '实时通话' },
    { id: 'greeting', role: 'assistant', content: '智能知识管家的介绍' },
    { id: 'q1', role: 'user', content: ' 什么是 RAG？\n请举例。 ' },
    { id: 'a1', role: 'assistant', content: '答案' },
    { id: 'q2', role: 'user', content: '如何引用本地文档？' }
  ])
  assert.deepEqual(questions.map(question => question.id), ['q1', 'q2'])
  assert.equal(questions[0].text, '什么是 RAG？\n请举例。')
  assert.equal(questions[0].summary, '什么是 RAG？ 请举例。')
})

test('voice transcripts and attachment-only questions have readable navigation labels', () => {
  const questions = conversationQuestions([
    { id: 'voice', role: 'user', transcript: '语音问题' },
    { id: 'file', role: 'user', content: '', metadata: { attachments: [{ name: '课程笔记.pdf' }] } }
  ])
  assert.deepEqual(questions.map(question => question.text), ['语音问题', '附件提问：课程笔记.pdf'])
})

test('scrolling within a long answer retains its question, then switches at the next question', () => {
  const positions = [{ id: 'first', top: -500 }, { id: 'second', top: 200 }, { id: 'third', top: 800 }]
  assert.equal(questionAtScrollPosition(positions, 24), 'first')
  assert.equal(questionAtScrollPosition(positions, 224), 'second')
  assert.equal(questionAtScrollPosition(positions, 824), 'third')
  assert.equal(questionAtScrollPosition([{ id: 'first', top: 50 }], 24), 'first')
  assert.equal(questionAtScrollPosition([], 24), null)
})
