<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, LoaderCircle, Trash2, X } from 'lucide-vue-next'
defineProps({ items: Array, busy: Boolean, error: String })
const emit = defineEmits(['cancel','confirm']), dialog = ref(null), cancel = ref(null)
const previousFocus = document.activeElement, previousOverflow = document.body.style.overflow
onMounted(async()=>{document.body.style.overflow='hidden';await nextTick();cancel.value?.focus()})
onBeforeUnmount(()=>{document.body.style.overflow=previousOverflow;previousFocus?.focus?.()})
function keyboard(event) {
  if(event.key==='Escape'){event.stopPropagation();dialog.value?.querySelector('[data-cancel]')?.click()}
  if(event.key!=='Tab')return
  const controls=[...dialog.value.querySelectorAll('button:not(:disabled)')], first=controls[0],last=controls.at(-1)
  if(!controls.length){event.preventDefault();return}
  if(event.shiftKey&&[first,dialog.value].includes(document.activeElement)){event.preventDefault();last.focus()}
  else if(!event.shiftKey&&[last,dialog.value].includes(document.activeElement)){event.preventDefault();first.focus()}
}
</script>
<template>
  <Teleport to="body"><div class="delete-confirm-mask" @click.self="!busy&&emit('cancel')">
    <section ref="dialog" class="delete-confirm" role="alertdialog" aria-modal="true" aria-labelledby="delete-confirm-title" aria-describedby="delete-confirm-description" tabindex="-1" @keydown="keyboard">
      <button data-cancel class="delete-confirm-close" aria-label="关闭删除确认" :disabled="busy" @click="emit('cancel')"><X :size="20"/></button>
      <span class="delete-confirm-icon"><AlertTriangle :size="26"/></span>
      <h2 id="delete-confirm-title">{{items.length===1?'删除这条内容？':'删除选中的 '+items.length+' 条内容？'}}</h2>
      <p id="delete-confirm-description">删除后无法恢复，请确认所选内容。</p>
      <ul><li v-for="item in items.slice(0,4)" :key="item.id">{{item.title}}</li><li v-if="items.length>4" class="delete-confirm-more">另有 {{items.length-4}} 条内容</li></ul>
      <p v-if="error" class="delete-confirm-error" role="alert">{{error}}</p>
      <footer><button ref="cancel" data-cancel :disabled="busy" @click="emit('cancel')">取消</button><button class="delete-confirm-submit" :disabled="busy" @click="emit('confirm')"><LoaderCircle v-if="busy" :size="16" class="wb-spin"/><Trash2 v-else :size="16"/>{{busy?'删除中…':'确认删除'}}</button></footer>
    </section>
  </div></Teleport>
</template>
<style scoped>
.delete-confirm-mask{position:fixed;inset:0;z-index:220;display:grid;place-items:center;padding:20px;background:#27143166;backdrop-filter:blur(5px)}.delete-confirm{position:relative;box-sizing:border-box;width:min(460px,100%);max-height:85vh;overflow:auto;padding:30px;border:1px solid #ece2f4;border-radius:24px;background:white;box-shadow:0 24px 80px #27143133;color:#38244d;outline:none}.delete-confirm-icon{display:grid;place-items:center;width:54px;height:54px;border-radius:17px;background:#fff1f1;color:#dc5366}.delete-confirm h2{margin:20px 0 10px;font-size:21px;line-height:1.5}.delete-confirm p{margin:0;color:#a08dab;font-size:13px;line-height:1.8}.delete-confirm ul{margin:18px 0 24px;padding:12px 16px;list-style:none;border:1px solid #eee7f5;border-radius:12px;background:#fcfaff}.delete-confirm li{padding:6px 0;line-height:1.6;font-size:13px;overflow-wrap:anywhere}.delete-confirm-more{color:#a08dab}.delete-confirm button{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:11px 19px;border:1px solid #e4d8ef;border-radius:11px;background:white;color:#8b739d;font:inherit;font-size:13px;cursor:pointer}.delete-confirm button:disabled{opacity:.5;cursor:wait}.delete-confirm .delete-confirm-close{position:absolute;right:16px;top:16px;padding:7px;border:0;background:transparent}.delete-confirm footer{display:flex;justify-content:flex-end;gap:10px}.delete-confirm .delete-confirm-submit{background:#df5267;border-color:#df5267;color:white;box-shadow:0 6px 18px #df526720}.delete-confirm-submit:hover:not(:disabled){background:#cd4156}.delete-confirm :focus-visible{outline:2px solid #a78bfa;outline-offset:3px}.delete-confirm .delete-confirm-error{margin-bottom:16px;color:#ce4056}
</style>
