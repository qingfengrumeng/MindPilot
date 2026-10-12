export function fallbackFollowups(question) {
  const topic=String(question||'').replace(/\s+/g,' ').slice(0,60)
  if(!topic || /^\d+$/.test(topic))return [{title:'了解可用功能',question:'你能帮助我完成哪些任务？请给我三个具体示例。'},{title:'整理我的需求',question:'请引导我明确想解决的问题，并帮我整理成一个清晰的提问。'},{title:'开始一个实际任务',question:'我想用你处理一个实际任务，请告诉我需要提供哪些信息。'}]
  return [{title:'深入理解',question:`关于“${topic}”，请解释关键概念和容易误解的地方。`},{title:'看一个实际例子',question:`针对“${topic}”，请给我一个具体应用示例，并说明怎么操作。`},{title:'整理下一步',question:`围绕“${topic}”，请整理可执行的步骤，并说明需要补充什么信息。`}]
}

/** One fresh turn, in memory only. Never recover suggestions from chat history. */
export function createFollowupSession({request,onChange}) {
  let current=null, version=0
  function clear() {version++;current=null;onChange(null)}
  function begin(conversationId,turnId,question) {
    const epoch=++version
    current={conversationId,turnId,question,replyId:null,items:fallbackFollowups(question)}
    onChange({...current})
    // Do not await this task: the ordinary reply starts concurrently.
    Promise.resolve().then(()=>epoch===version ? request(conversationId,question) : null).then(result=>{
      if(epoch!==version || !current)return
      if(!Array.isArray(result?.items)||result.items.length!==3)return
      current.items=result.items;onChange({...current})
    }).catch(()=>{/* Keep instant, question-based fallback cards. */})
  }
  function finish(conversationId,replyId,question) {
    if(!current || current.conversationId!==conversationId || current.question!==question)return
    current.replyId=replyId;onChange({...current})
  }
  return {begin,finish,clear}
}
