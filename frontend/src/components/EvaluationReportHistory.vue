<script setup>
import {onMounted,ref} from 'vue'
import {Download,FileText,Trash2,X} from 'lucide-vue-next'
import {evaluationReportsApi} from '@/api/evaluations'
const emit=defineEmits(['close','open'])
const props=defineProps({kind:String})
const items=ref([]),error=ref(''),busy=ref(false)
async function load(){try{items.value=(await evaluationReportsApi.list()).items.filter(item=>!props.kind||item.kind===props.kind)}catch(e){error.value=e.message}}
async function open(item){try{emit('open',(await evaluationReportsApi.get(item.id)).result);emit('close')}catch(e){error.value=e.message}}
async function download(item){try{const report=await evaluationReportsApi.get(item.id);const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`${item.kind}-${item.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){error.value=e.message}}
async function remove(item){busy.value=true;try{await evaluationReportsApi.remove(item.id);await load()}catch(e){error.value=e.message}finally{busy.value=false}}
onMounted(load)
</script>
<template><Teleport to="body"><div class="report-history-mask"><section class="report-history" role="dialog" aria-modal="true" aria-label="已保存测试结果"><header><h2>已保存测试结果</h2><button @click="emit('close')" aria-label="关闭"><X :size="22"/></button></header><p class="report-note">永久保存在业务数据目录，独立于24小时临时测试空间。</p><p v-if="error" role="alert">{{error}}</p><p v-if="!items.length" class="report-note">暂无已保存的结果</p><article v-for="item in items" :key="item.id"><FileText :size="24"/><div><strong>{{item.title}}</strong><small>{{new Date(item.createdAt).toLocaleString()}} · {{item.kind.toUpperCase()}}</small></div><button @click="open(item)">查看</button><button @click="download(item)" aria-label="下载报告"><Download :size="17"/></button><button :disabled="busy" @click="remove(item)" aria-label="删除报告"><Trash2 :size="17"/></button></article></section></div></Teleport></template>
<style scoped>
.report-history-mask{position:fixed;inset:0;z-index:3300;background:#25163866;display:grid;place-items:center;padding:20px;backdrop-filter:blur(5px)}.report-history{width:min(850px,100%);max-height:85vh;overflow:auto;background:#fff;border-radius:24px;padding:25px;color:#63467d}.report-history header{display:flex;justify-content:space-between;align-items:center}.report-history h2{font-size:22px}.report-history button{display:inline-flex;align-items:center;justify-content:center;border:1px solid #dfd2ef;background:#faf7ff;color:#8057a5;padding:9px 12px;border-radius:10px;cursor:pointer}.report-history article{display:flex;align-items:center;gap:12px;padding:18px 0;border-top:1px solid #eee6f5}.report-history article>div{flex:1;min-width:0}.report-history small{display:block;color:#a58db5;margin-top:8px;font-size:12px}.report-note{color:#a58db5;font-size:13px;line-height:1.8}
</style>
