<script setup>
import { computed, ref, useId } from 'vue'
import { ZoomIn, ZoomOut, RotateCcw } from 'lucide-vue-next'
const props = defineProps({ nodes: { type: Array, default: () => [] }, edges: { type: Array, default: () => [] }, selectedId: String })
const emit = defineEmits(['select'])
const zoom = ref(1), pan = ref({ x: 0, y: 0 })
let drag = null
const markerId = useId()
const palette = { Wiki页面: '#6d38ba', 未解析页面: '#aaa0b7', 概念: '#7850d0', 产品: '#299790', 组织: '#c08a3a', 人物: '#cd6688', 事件: '#567fc3', 地点: '#739753' }
const points = computed(() => {
  const nodes = props.nodes.slice(0, 150)
  if (nodes.length === 1) return [{ ...nodes[0], x: 450, y: 240, color: palette[nodes[0].type] || '#7953b9' }]
  return nodes.map((node, index) => {
    const ring = nodes.length > 20 ? index % 3 : index % 2
    const angle = index * 2.399963229728653
    const radius = nodes.length < 4 ? 130 : 85 + ring * 65 + Math.sqrt(index / nodes.length) * 75
    return { ...node, x: 450 + Math.cos(angle) * radius * 1.35, y: 240 + Math.sin(angle) * radius * .75, color: palette[node.type] || '#7953b9' }
  })
})
const lookup = computed(() => Object.fromEntries(points.value.map(node => [node.id, node])))
const lines = computed(() => props.edges.filter(edge => lookup.value[edge.source] && lookup.value[edge.target]).slice(0, 300))
const related = computed(() => new Set(props.edges.filter(edge => edge.source === props.selectedId || edge.target === props.selectedId).flatMap(edge => [edge.source, edge.target])))
function reset() { zoom.value = 1; pan.value = { x: 0, y: 0 } }
function dragMove(event) { if(!drag)return; const rect=event.currentTarget.getBoundingClientRect();pan.value={x:drag.originX+(event.clientX-drag.startX)*900/rect.width,y:drag.originY+(event.clientY-drag.startY)*480/rect.height} }
function dragStart(event) { if(event.target.closest('[data-graph-item]'))return;drag={startX:event.clientX,startY:event.clientY,originX:pan.value.x,originY:pan.value.y};event.currentTarget.setPointerCapture(event.pointerId) }
</script>

<template>
  <div class="kg-canvas" :class="{dense:points.length>35}">
    <div class="kg-canvas-tools"><button aria-label="放大图谱" @click="zoom=Math.min(2.5,zoom+.2)"><ZoomIn :size="16"/></button><button aria-label="缩小图谱" @click="zoom=Math.max(.4,zoom-.2)"><ZoomOut :size="16"/></button><button aria-label="重置视图" @click="reset"><RotateCcw :size="16"/></button></div>
    <svg v-if="points.length" viewBox="0 0 900 480" role="group" aria-label="可点击节点与关系的知识图谱" @pointerdown="dragStart" @pointermove="dragMove" @pointerup="drag=null" @pointercancel="drag=null" @wheel.prevent="zoom=Math.max(.4,Math.min(2.5,zoom+($event.deltaY<0?.1:-.1)))">
      <defs><marker :id="markerId" viewBox="0 0 10 10" refX="42" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#b3a0ca"/></marker></defs>
      <g :transform="`translate(${450+pan.x} ${240+pan.y}) scale(${zoom}) translate(-450 -240)`">
        <g v-for="edge in lines" :key="edge.id" data-graph-item class="kg-edge" :class="{selected:edge.id===selectedId}" role="button" tabindex="0" :aria-label="edge.predicate||edge.label" @click="emit('select',{kind:'edge',item:edge})" @keydown.enter="emit('select',{kind:'edge',item:edge})">
          <line class="kg-edge-hit" :x1="lookup[edge.source].x" :y1="lookup[edge.source].y" :x2="lookup[edge.target].x" :y2="lookup[edge.target].y"/>
          <line :x1="lookup[edge.source].x" :y1="lookup[edge.source].y" :x2="lookup[edge.target].x" :y2="lookup[edge.target].y" :stroke-dasharray="edge.resolved===false?'5 5':undefined" :marker-end="`url(#${markerId})`"/>
          <text v-if="points.length<35" :x="(lookup[edge.source].x+lookup[edge.target].x)/2" :y="(lookup[edge.source].y+lookup[edge.target].y)/2-6">{{edge.predicate}}</text>
        </g>
        <g v-for="node in points" :key="node.id" data-graph-item class="kg-node" :class="{selected:node.id===selectedId,related:related.has(node.id),unresolved:node.unresolved}" :transform="`translate(${node.x} ${node.y})`" role="button" tabindex="0" :aria-label="node.name" @click="emit('select',{kind:'node',item:node})" @keydown.enter="emit('select',{kind:'node',item:node})">
          <title>{{node.name}} · {{node.type}}</title><circle r="18" :fill="node.color"/><text y="37">{{node.name.length>15?node.name.slice(0,15)+'…':node.name}}</text>
        </g>
      </g>
    </svg>
    <div v-else class="kg-canvas-empty"><slot name="empty">暂时没有可展示的节点</slot></div>
    <small class="kg-canvas-note">拖动空白区域移动 · 滚轮缩放 · 点击节点或关系查看依据<span v-if="nodes.length>150"> · 展示前150个节点，请用搜索缩小范围</span></small>
  </div>
</template>

<style scoped>
.kg-canvas{position:relative;min-height:330px;background:radial-gradient(circle at 50% 45%,#faf7ff,#fff);border-radius:14px;overflow:hidden}.kg-canvas>svg{display:block;width:100%;height:350px;touch-action:none;cursor:grab}.kg-canvas>svg:active{cursor:grabbing}.kg-canvas-tools{position:absolute;right:12px;top:12px;display:flex;gap:5px;z-index:1}.kg-canvas-tools button{display:grid;place-items:center;width:30px;height:30px;border:1px solid #e7dff0;border-radius:8px;background:#fff;color:#78559c;cursor:pointer}.kg-canvas-tools button:hover{background:#eee5f9}.kg-edge{cursor:pointer}.kg-edge line{stroke:#cbbadf;stroke-width:1.4}.kg-edge .kg-edge-hit{stroke:transparent;stroke-width:14}.kg-edge text{font-size:15px;fill:#967bad;text-anchor:middle}.kg-edge.selected line:not(.kg-edge-hit),.kg-edge:hover line:not(.kg-edge-hit){stroke:#6b21b8;stroke-width:3}.kg-node{cursor:pointer;outline:none}.kg-node circle{stroke:#fff;stroke-width:3;filter:drop-shadow(0 3px 5px #492c6b18)}.kg-node.selected circle,.kg-node.related circle,.kg-node:hover circle,.kg-node:focus-visible circle{stroke:#d9c3f3;stroke-width:6}.kg-node.unresolved circle{fill:#f2edf7;stroke:#baacca;stroke-dasharray:4 3}.kg-node text{font-size:18px;text-anchor:middle;fill:#554168;font-weight:600;paint-order:stroke;stroke:#fff;stroke-width:3;stroke-linejoin:round}.kg-canvas.dense .kg-node text{font-size:12px}.kg-canvas-note{display:block;padding:10px 14px;color:#9b8aa9;font-size:11px}.kg-canvas-empty{min-height:330px;display:grid;place-items:center;text-align:center;padding:35px;color:#9786a7;font-size:14px;line-height:1.9}
</style>
