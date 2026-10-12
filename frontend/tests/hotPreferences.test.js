import test from 'node:test'
import assert from 'node:assert/strict'
import { filterHotCandidates, defaultHotPreferences } from '../src/lib/hotPreferences.js'
import { createDailyHotLoader } from '../src/lib/ai-hot.mjs'
const now = Date.parse('2026-10-11T12:00:00Z')
const rows = [
  { id:'1',kind:'selected',title:'DeepSeek最新模型',publishedAt:'2026-10-11T01:00:00Z' },
  { id:'2',kind:'selected',title:'医疗研究论文',publishedAt:'2026-10-09T01:00:00Z' },
  { id:'3',kind:'selected',title:'医疗旧新闻',publishedAt:'2026-09-01T01:00:00Z' },
  { id:'4',kind:'hot-topic',title:'金融消息' }
]
test('topics, custom keywords, date windows and missing source dates use real candidate data', () => {
  const prefs = defaultHotPreferences()
  assert.deepEqual(filterHotCandidates(rows,prefs,now).map(row=>row.id),['1','2','4'])
  prefs.topics=['大模型与AI']; prefs.keywords='医疗'
  assert.deepEqual(filterHotCandidates(rows,prefs,now).map(row=>row.id),['1','2'])
  prefs.lookbackDays=1
  assert.deepEqual(filterHotCandidates(rows,prefs,now).map(row=>row.id),['1'])
  prefs.topics=[];prefs.keywords='金融'
  assert.deepEqual(filterHotCandidates(rows,prefs,now).map(row=>row.id),['4'])
  assert.equal(filterHotCandidates([rows[0],rows[0]],defaultHotPreferences(),now).length,1)
})
test('explicit synchronization can retrieve more than the former built-in tier limit', async () => {
  const fetchImpl = async url => ({ok:true,json:async()=> {
    if (url.includes('hot-topics')) return {items:[]}
    if (url.includes('dailies')) return {report:{sections:[]}}
    return {items:Array.from({length:20},(_,id)=>({id:String(id),title:`模型新闻${id}`,links:{original:`https://example.com/${id}`}}))}
  }})
  const loader = createDailyHotLoader({fetchImpl,now:()=>now})
  const response = await loader({force:true,strategy:{mustReadLimit:100,browseLimit:100,otherLimit:100}})
  assert.equal(response.status,'live')
  assert.equal(Object.values(response.tiers).flat().length,20)
})
