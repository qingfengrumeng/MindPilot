import test from 'node:test'
import assert from 'node:assert/strict'
import {sortHotByPublished} from '../src/lib/hotChronology.js'
test('hot articles sort by actual publication rather than insertion, with safe legacy fallback',()=>{
  const rows=[{id:'yesterday',data:{publishedAt:'2026-10-10T12:00:00+08:00'},createdAt:'2026-10-12'},
    {id:'today',data:{publishedAt:'2026-10-11T15:00:00+08:00'}},
    {id:'legacy',data:{publishedAt:'invalid'},createdAt:'2026-10-11T01:00:00Z'},
    {id:'older',data:{publishedAt:'2026-10-04'}},{id:'missing',data:{}}]
  assert.deepEqual(sortHotByPublished(rows).map(row=>row.id),['today','legacy','yesterday','older','missing'])
  assert.equal(rows[0].id,'yesterday')
})
