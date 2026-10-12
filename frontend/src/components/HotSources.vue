<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { ExternalLink, ChevronDown } from 'lucide-vue-next'
const props = defineProps({ item: Object, detail: Boolean })
const open = ref(false), container = ref(null)
const menuOffset = ref(0)
const sources = computed(() => {
  const values = props.item?.data?.sources?.length ? props.item.data.sources : [{url:props.item?.data?.sourceUrl,title:'原始来源'}]
  const seen = new Set()
  return values.filter(source => {
    try { const url=new URL(source.url); if (!['http:','https:'].includes(url.protocol) || seen.has(url.href)) return false; seen.add(url.href); return true } catch {return false}
  })
})
function outside(event) { if (!container.value?.contains(event.target)) open.value = false }
function hostname(url) { try {return new URL(url).hostname} catch {return ''} }
window.addEventListener('pointerdown', outside)
function close() {open.value=false}
window.addEventListener('resize', close)
onBeforeUnmount(() => {window.removeEventListener('pointerdown', outside);window.removeEventListener('resize', close)})
async function toggle() {
  open.value=!open.value;menuOffset.value=0
  if(open.value){
    await nextTick()
    container.value?.querySelector('[role="menuitem"]')?.focus()
    const bounds=container.value?.querySelector('[role="menu"]')?.getBoundingClientRect()
    if(bounds) menuOffset.value=Math.max(8-bounds.left,0)-Math.max(bounds.right-window.innerWidth+8,0)
  }
}
function keydown(event) {
  if(event.key==='Escape'){event.stopPropagation();open.value=false;container.value?.querySelector('button')?.focus()}
  if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();const links=[...container.value.querySelectorAll('[role="menuitem"]')];const index=links.indexOf(document.activeElement);links[(index+(event.key==='ArrowDown'?1:-1)+links.length)%links.length]?.focus()}
}
</script>
<template>
  <div v-if="sources.length" ref="container" class="hot-source-picker" :class="{'is-detail':detail}" @click.stop @keydown="keydown" @focusout="!$event.currentTarget.contains($event.relatedTarget) && (open=false)">
    <a v-if="sources.length===1" :href="sources[0].url" target="_blank" rel="noopener noreferrer">{{detail?'打开原始来源':'原始来源'}}<ExternalLink :size="13"/></a>
    <button v-else type="button" aria-haspopup="menu" :aria-expanded="open" @click="toggle">{{detail?'原始来源':'原始来源'}}<small>{{sources.length}}</small><ChevronDown :size="14"/></button>
    <div v-if="open" class="hot-source-options" :style="{transform:'translateX('+menuOffset+'px)'}" role="menu" aria-label="选择原始来源"><a v-for="(source,index) in sources" :key="source.url" :href="source.url" target="_blank" rel="noopener noreferrer" role="menuitem" @click="open=false"><span><strong>{{source.title||'来源 '+(index+1)}}</strong><small>{{hostname(source.url)}}</small></span><ExternalLink :size="14"/></a></div>
  </div>
</template>
<style scoped>
.hot-source-picker{position:relative;display:inline-flex;font-size:11px}.hot-source-picker>a,.hot-source-picker>button{display:inline-flex;align-items:center;gap:5px;padding:5px;border:0;border-radius:7px;color:#7c3aed;background:transparent;font:inherit;text-decoration:none;cursor:pointer;white-space:nowrap}.hot-source-picker>button small{padding:1px 5px;border-radius:5px;background:#f1e9ff;font-size:10px}.hot-source-picker>a:hover,.hot-source-picker>button:hover{background:#f3effe}.hot-source-options{display:block;position:absolute;right:0;bottom:calc(100% + 9px);z-index:40;width:300px;max-width:75vw;max-height:280px;overflow:auto;padding:7px;border:1px solid #e5d8f4;border-radius:14px;background:white;box-shadow:0 14px 40px #40225325}.hot-source-options a{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:9px;color:#735185;text-decoration:none}.hot-source-options a:hover{background:#f5effd;color:#7c3aed}.hot-source-options span{flex:1;min-width:0}.hot-source-options strong{display:block;font-size:12px;line-height:1.6;font-weight:500;overflow-wrap:anywhere}.hot-source-options small{display:block;margin-top:4px;font-size:10px;color:#a894b5}.hot-source-options svg{flex-shrink:0}.hot-source-picker.is-detail{font-size:13px}.hot-source-picker.is-detail>a,.hot-source-picker.is-detail>button{padding:10px 13px;border:1px solid #e3d5f7;border-radius:10px}.hot-source-picker :focus-visible{outline:2px solid #a78bfa;outline-offset:2px}
</style>
