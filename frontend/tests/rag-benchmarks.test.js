import test from 'node:test'
import assert from 'node:assert/strict'
import {metricBand} from '../src/lib/ragBenchmarks.js'
test('reference bands respect boundaries, missing values, low-is-good and k',()=>{
 assert.equal(metricBand('recall',.85),'良好')
 assert.equal(metricBand('recall',.86),'优秀')
 assert.equal(metricBand('recall',.69),'需优化')
 assert.equal(metricBand('recall',.95,3),null)
 assert.equal(metricBand('groundedness',null),null)
 assert.equal(metricBand('potentialHallucinationRate',.04),'优秀')
 assert.equal(metricBand('potentialHallucinationRate',.05),'良好')
 assert.equal(metricBand('potentialHallucinationRate',.16),'需优化')
})
