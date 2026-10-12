import test from 'node:test'
import assert from 'node:assert/strict'
import { highlightCode } from '../src/lib/codeHighlight.js'

test('code highlighting keeps markup inert while styling Python tokens', () => {
  const result = highlightCode('from PIL import Image\nprint("<script>alert(1)</script>")', 'python')
  assert.match(result, /code-token-keyword/)
  assert.match(result, /code-token-string/)
  assert.match(result, /&lt;script&gt;/)
  assert.doesNotMatch(result, /<script>/)
})

test('plain code is escaped without changing its contents', () => {
  assert.equal(highlightCode('a < b && c > d', 'text'), 'a &lt; b &amp;&amp; c &gt; d')
})
