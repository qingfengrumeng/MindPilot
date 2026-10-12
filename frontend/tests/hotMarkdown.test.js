import test from 'node:test'
import assert from 'node:assert/strict'
import {hotMarkdownFile} from '../src/lib/hotMarkdown.js'

test('hotspot Markdown retains summary, body and multiple safe sources with a usable filename',async()=>{
  const file=hotMarkdownFile({title:'新闻：A/B *模型*',summary:'真实摘要',body:'第一段正文\n\n第二段正文',data:{source:'hot-agent',publishedAt:'2026-10-11',sources:[{title:'发布[说明]',url:'https://example.com/a'},{title:'报道',url:'https://example.org/b'},{title:'重复',url:'https://example.org/b'},{title:'恶意',url:'javascript:alert(1)'}]}})
  const text=await file.text()
  assert.equal(file.name,'新闻：A_B _模型_.md')
  assert.match(file.type,/text\/markdown/)
  assert.ok(text.includes('## 摘要\n\n真实摘要'))
  assert.ok(text.includes('## 完整内容\n\n第一段正文\n\n第二段正文'))
  assert.ok(text.includes('[发布\\[说明\\]](<https://example.com/a>)'))
  assert.equal((text.match(/https:\/\/example.org\/b/g)||[]).length,1)
  assert.ok(!text.includes('javascript:'))
  assert.ok(text.includes('发布时间：2026-10-11'))
})
test('missing full content uses the supplied empty body and legacy single source',async()=>{
  const file=hotMarkdownFile({title:'旧热点',summary:'摘要',body:'旧导入中的阅读建议',data:{sourceUrl:'https://example.com/news'}},'')
  const text=await file.text()
  assert.ok(text.includes('来源暂未提供完整内容。'))
  assert.ok(!text.includes('旧导入中的阅读建议'))
  assert.ok(text.includes('[原始来源](<https://example.com/news>)'))
})
