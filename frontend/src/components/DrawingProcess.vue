<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ChevronDown, CircleDashed, Network } from 'lucide-vue-next'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  live: { type: Boolean, default: false },
  xml: { type: String, default: '' }
})
const expanded = ref(true)
const expandedDetails = ref({})
const elapsed = ref(0)
let timer = null

const legacyCatalog = computed(() => {
  if (!props.xml || typeof DOMParser === 'undefined') return null
  const documentXml = new DOMParser().parseFromString(props.xml, 'application/xml')
  if (documentXml.querySelector('parsererror')) return null
  const cells = [...documentXml.querySelectorAll('mxCell')]
  if (!cells.length) return null
  const clean = value => String(value || '').replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim()
  const nodes = new Map(cells.filter(cell => cell.getAttribute('vertex') === '1')
    .map(cell => [cell.getAttribute('id'), clean(cell.getAttribute('value'))]))
  return {
    nodes: [...nodes.values()],
    decisions: cells.filter(cell => cell.getAttribute('vertex') === '1' && (cell.getAttribute('style') || '').includes('rhombus'))
      .map(cell => clean(cell.getAttribute('value'))).filter(Boolean),
    connections: cells.filter(cell => cell.getAttribute('edge') === '1').map(cell => ({
      source: nodes.get(cell.getAttribute('source')) || '节点',
      target: nodes.get(cell.getAttribute('target')) || '节点',
      label: clean(cell.getAttribute('value'))
    }))
  }
})

function pathFromText(value) {
  const match = String(value).match(/^(.*?)\s*→\s*(.*?)(?:（([^）]+)）)?$/)
  return match ? { source: match[1].trim(), target: match[2].trim(), label: match[3] || '' }
    : { source: String(value), target: '', label: '' }
}

function normalizeStep(step) {
  const detail = String(step.detail || '')
  const lines = detail.split('\n').map(line => line.trim()).filter(Boolean)
  const kind = step.kind || (step.title?.includes('规划节点') ? 'nodes'
    : step.title?.includes('分支与连接') ? 'connections' : 'text')
  if (kind === 'nodes') {
    const items = Array.isArray(step.items) ? step.items : legacyCatalog.value?.nodes ||
      lines.filter(line => /^[•·-]\s*/.test(line)).map(line => line.replace(/^[•·-]\s*/, ''))
    const count = Number(step.count ?? detail.match(/(?:确定|共)\s*(\d+)\s*个节点/)?.[1] ?? items.length)
    return { ...step, kind, items, count }
  }
  if (kind === 'connections') {
    const items = (Array.isArray(step.items) ? step.items : legacyCatalog.value?.connections || lines.filter(line => /^[•·-]\s*/.test(line))
      .map(line => line.replace(/^[•·-]\s*/, ''))).map(item => typeof item === 'string' ? pathFromText(item) : item)
    const count = Number(step.count ?? detail.match(/(?:建立|共)\s*(\d+)\s*条连接/)?.[1] ?? items.length)
    const decisions = Array.isArray(step.decisions) ? step.decisions : legacyCatalog.value?.decisions ||
      (lines.find(line => line.startsWith('关键判断：')) || '').replace('关键判断：', '').split('、').filter(Boolean)
    return { ...step, kind, items, count, decisions }
  }
  return { ...step, kind }
}

const viewSteps = computed(() => props.steps.map(normalizeStep))
function limitFor(step) { return step.kind === 'nodes' ? 8 : 5 }
function visibleItems(step, index) {
  return expandedDetails.value[index] ? step.items : step.items.slice(0, limitFor(step))
}
function remainingCount(step, index) { return expandedDetails.value[index] ? 0 : Math.max(0, step.items.length - limitFor(step)) }
function toggleDetails(index) { expandedDetails.value = { ...expandedDetails.value, [index]: !expandedDetails.value[index] } }

onMounted(() => {
  if (props.live) timer = window.setInterval(() => { elapsed.value += 0.1 }, 100)
})
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })
</script>

<template>
  <section v-if="live && steps.length" class="drawing-process live">
    <button type="button" class="drawing-process-heading" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="drawing-process-symbol"><Network :size="17" /></span>
      <span class="drawing-process-title"><strong>构图过程</strong><small>节点规划 · 分支与连接 · 图表生成</small></span>
      <span class="drawing-process-meta">{{ live ? `实时更新 · ${elapsed.toFixed(1)} 秒` : `${steps.length} 个步骤` }}</span>
      <ChevronDown :size="18" class="drawing-process-chevron" :class="{ expanded }" />
    </button>
    <div v-if="expanded" class="drawing-process-list">
      <div v-for="(step, index) in viewSteps" :key="`${index}-${step.title}`" class="drawing-process-step">
        <span class="drawing-process-step-icon">
          <CircleDashed v-if="step.status === 'running'" :size="14" class="drawing-process-spin" />
          <Check v-else :size="14" />
        </span>
        <div class="drawing-step-content">
          <strong class="drawing-step-title">{{ step.title }}</strong>
          <p v-if="step.status === 'running'" class="drawing-step-description">{{ step.detail }}</p>
          <template v-else-if="step.kind === 'nodes'">
            <div class="drawing-step-summary"><b>{{ step.count }}</b><span>个节点已规划</span></div>
            <div v-if="step.items.length" class="drawing-node-list">
              <span v-for="(node, nodeIndex) in visibleItems(step, index)" :key="`${nodeIndex}-${node}`" class="drawing-node-chip">{{ node }}</span>
            </div>
            <button v-if="remainingCount(step, index)" type="button" class="drawing-detail-toggle" @click="toggleDetails(index)">查看其余 {{ remainingCount(step, index) }} 个节点</button>
            <button v-else-if="expandedDetails[index] && step.items.length > limitFor(step)" type="button" class="drawing-detail-toggle" @click="toggleDetails(index)">收起节点</button>
            <span v-if="step.count > step.items.length" class="drawing-detail-note">另有 {{ step.count - step.items.length }} 个节点可在图表中查看</span>
          </template>
          <template v-else-if="step.kind === 'connections'">
            <div class="drawing-step-summary"><b>{{ step.count }}</b><span>条连接已建立</span></div>
            <div v-if="step.decisions?.length" class="drawing-decision-row"><span class="drawing-list-label">关键判断</span><span v-for="decision in step.decisions" :key="decision" class="drawing-decision-chip">{{ decision }}</span></div>
            <div v-if="step.items.length" class="drawing-path-section">
              <span class="drawing-list-label">主要路径</span>
              <div class="drawing-path-list">
                <div v-for="(path, pathIndex) in visibleItems(step, index)" :key="pathIndex" class="drawing-path-row">
                  <span>{{ path.source }}</span><span class="drawing-path-arrow">→</span><span>{{ path.target }}</span><em v-if="path.label">{{ path.label }}</em>
                </div>
              </div>
            </div>
            <button v-if="remainingCount(step, index)" type="button" class="drawing-detail-toggle" @click="toggleDetails(index)">查看其余 {{ remainingCount(step, index) }} 条连接</button>
            <button v-else-if="expandedDetails[index] && step.items.length > limitFor(step)" type="button" class="drawing-detail-toggle" @click="toggleDetails(index)">收起连接</button>
            <span v-if="step.count > step.items.length" class="drawing-detail-note">另有 {{ step.count - step.items.length }} 条连接可在图表中查看</span>
          </template>
          <p v-else class="drawing-step-description">{{ step.detail }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.drawing-process{box-sizing:border-box;width:100%;overflow:hidden;border:1px solid #c6ace6;border-radius:16px;background:#fff;color:#4d3170;box-shadow:0 4px 16px rgba(65,23,116,.05)}
.drawing-process-heading{box-sizing:border-box;display:flex;align-items:center;gap:12px;width:100%;min-height:70px;padding:13px 16px;border:0;background:#fbf8fe;color:#471287;text-align:left;cursor:pointer}
.drawing-process-heading:hover{background:#f5f0fb}.drawing-process-symbol{display:grid;flex:none;place-items:center;width:30px;height:30px;border-radius:9px;background:#ece2f8;color:#4e07a5}
.drawing-process-title{display:flex;min-width:0;flex:1;flex-direction:column;gap:2px}.drawing-process-title strong{font-size:15px;line-height:1.35;color:#3c1868}.drawing-process-title small{color:#8c78a5;font-size:11px;line-height:1.3}
.drawing-process-meta{flex:none;padding:5px 9px;border-radius:8px;background:#f0e9f9;color:#6e5390;font-size:12px;white-space:nowrap}.drawing-process-chevron{flex:none;color:#6d528e;transition:transform .2s}.drawing-process-chevron.expanded{transform:rotate(180deg)}
.drawing-process-list{max-height:460px;overflow:auto;padding:6px 20px 12px;border-top:1px solid #e9e1f2;background:#fff}.drawing-process-step{display:grid;grid-template-columns:28px minmax(0,1fr);gap:12px;padding:15px 0;line-height:1.6}.drawing-process-step+.drawing-process-step{border-top:1px solid #eee9f4}
.drawing-process-step-icon{display:grid;place-items:center;width:26px;height:26px;border-radius:8px;background:#eae1f4;color:#4d09a1}.drawing-step-content{min-width:0}.drawing-step-title{display:block;margin:1px 0 7px;color:#412663;font-size:14px}.drawing-step-description{margin:0;color:#715b8b;font-size:13px;line-height:1.7;overflow-wrap:anywhere}.drawing-step-summary{display:flex;align-items:baseline;gap:5px;margin:0 0 10px;color:#7f6999;font-size:12px}.drawing-step-summary b{color:#4b089c;font-size:19px;line-height:1}
.drawing-node-list{display:flex;flex-wrap:wrap;gap:7px}.drawing-node-chip{max-width:100%;padding:5px 9px;border:1px solid #daccec;border-radius:8px;background:#f6f2fb;color:#4f366d;font-size:12px;line-height:1.3;overflow-wrap:anywhere}.drawing-detail-toggle{display:inline-flex;margin-top:10px;padding:5px 0;border:0;background:none;color:#4e07a5;font-size:12px;font-weight:650;cursor:pointer}.drawing-detail-toggle:hover{text-decoration:underline}.drawing-detail-note{display:block;margin-top:6px;color:#9584aa;font-size:11px}
.drawing-decision-row{display:flex;align-items:center;flex-wrap:wrap;gap:7px;margin:2px 0 11px}.drawing-list-label{color:#8b79a2;font-size:11px;font-weight:700;white-space:nowrap}.drawing-decision-chip{padding:4px 8px;border-radius:7px;background:#fff3df;color:#a16919;font-size:11px}.drawing-path-section>.drawing-list-label{display:block;margin-bottom:6px}.drawing-path-list{display:grid;gap:5px}.drawing-path-row{display:flex;align-items:center;flex-wrap:wrap;gap:7px;min-width:0;padding:7px 10px;border-radius:8px;background:#f9f7fc;color:#5a4179;font-size:12px;overflow-wrap:anywhere}.drawing-path-arrow{color:#520ba9;font-weight:800}.drawing-path-row em{padding:2px 6px;border-radius:6px;background:#efe9f6;color:#786292;font-size:11px;font-style:normal}
.drawing-process-spin{animation:draw-spin 1.4s linear infinite}@keyframes draw-spin{to{transform:rotate(360deg)}}.drawing-process.live{width:min(720px,calc(100% - 48px));margin:12px 0 0 48px}
@media(max-width:600px){.drawing-process.live{width:100%;margin-left:0}.drawing-process-heading{gap:9px;padding:12px;min-height:64px}.drawing-process-title small{display:none}.drawing-process-meta{font-size:11px;padding:4px 6px}.drawing-process-list{padding:4px 12px 9px}.drawing-process-step{gap:9px}.drawing-node-chip{font-size:11px}}
</style>
