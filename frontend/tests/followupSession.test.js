import test from 'node:test'
import assert from 'node:assert/strict'
import {createFollowupSession} from '../src/lib/followupSession.js'
const tick=()=>new Promise(resolve=>setTimeout(resolve,0))
const ITEMS=Array.from({length:3},(_,i)=>({title:'推荐'+i,question:'推荐问题'+i}))

test('recommendations start with the question, stay hidden until reply completes, and use instant fallback for slow requests',async()=>{
  let state,resolve
  const calls=[]
  const session=createFollowupSession({request:(id,question)=>{calls.push({id,question});return new Promise(done=>resolve=done)},onChange:value=>state=value})
  assert.equal(state,undefined)
  session.begin('chat','turn-1','什么是 RAG？')
  await tick()
  assert.deepEqual(calls,[{id:'chat',question:'什么是 RAG？'}])
  assert.equal(state.replyId,null)
  session.finish('chat','reply-1','什么是 RAG？')
  assert.equal(state.replyId,'reply-1')
  assert.equal(state.items.length,3)
  resolve({items:ITEMS});await tick()
  assert.deepEqual(state.items,ITEMS)
})
test('switching or closing clears cards and ignores late completion; reopening history does not start generation',async()=>{
  let state,resolve
  const calls=[]
  const session=createFollowupSession({request:()=>{calls.push(1);return new Promise(done=>resolve=done)},onChange:value=>state=value})
  session.begin('chat','turn-1','RAG？');await tick()
  session.clear()
  session.finish('chat','historical-reply','RAG？')
  resolve({items:ITEMS});await tick()
  assert.equal(state,null)
  assert.equal(calls.length,1)
})
test('an older recommendation cannot replace a newer turn, and failures do not block cards',async()=>{
  let state
  const resolvers=[]
  const session=createFollowupSession({request:()=>new Promise((resolve,reject)=>resolvers.push({resolve,reject})),onChange:value=>state=value})
  session.begin('chat','turn-1','第一个问题');await tick()
  session.begin('chat','turn-2','第二个问题');await tick()
  resolvers[0].resolve({items:ITEMS});await tick()
  assert.equal(state.turnId,'turn-2')
  assert.notDeepEqual(state.items,ITEMS)
  resolvers[1].reject(Error('unavailable'));await tick()
  session.finish('chat','reply-2','第二个问题')
  assert.equal(state.replyId,'reply-2')
  assert.equal(state.items.length,3)
})
