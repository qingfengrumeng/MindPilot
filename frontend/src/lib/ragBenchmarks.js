// User-provided reference bands, not universal industry acceptance criteria.
export const ragBenchmarks={
 recall:[.85,.7],precision:[.6,.4],mrr:[.8,.6],ndcg:[.8,.65],
 faithfulness:[.8,.65],semanticFaithfulness:[.8,.65],groundedness:[.8,.6],factualConsistency:[.85,.7],potentialHallucinationRate:[.05,.15]
}
export function metricBand(key,value,k=5){
 if(value==null||!ragBenchmarks[key])return null
 if(['recall','precision','ndcg'].includes(key)&&k!==5)return null
 const [excellent,good]=ragBenchmarks[key]
 if(key==='potentialHallucinationRate')return value<excellent?'优秀':value<=good?'良好':'需优化'
 return value>excellent?'优秀':value>=good?'良好':'需优化'
}
