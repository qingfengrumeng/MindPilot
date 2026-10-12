<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Activity, Bot, Check, ChevronLeft, ChevronRight, CircleSlash2, Clock3, Eye, FileText, Globe2, LoaderCircle, MessageSquare, Search, ShieldCheck, Sparkles, Wrench, X } from 'lucide-vue-next'

const props = defineProps({ trace: { type: Object, default: null }, generating: { type: Boolean, default: false } })
const monitorPreferenceKey = 'mindpilot-agent-monitor'
const panelOpen = ref(localStorage.getItem(monitorPreferenceKey) === 'expanded')
function setPanelOpen(open) {
  panelOpen.value = open
  localStorage.setItem(monitorPreferenceKey, open ? 'expanded' : 'collapsed')
}
const selectedId = ref(null)
const stages = computed(() => props.trace?.stages || [])
const selected = computed(() => stages.value.find(stage => stage.id === selectedId.value))
const kinds = {
  input: { label: '需求分析', icon: MessageSquare }, agent: { label: 'Agent', icon: Bot },
  domain: { label: '功能域', icon: Activity },
  retrieval: { label: 'RAG检索', icon: Search }, tool: { label: '工具调用', icon: Wrench },
  skill: { label: 'Skill', icon: Sparkles }, model: { label: '模型调用', icon: Sparkles },
  reflection: { label: '反思Agent', icon: ShieldCheck }, output: { label: '输出', icon: Check }
}
const labels = {
  question: '本轮问题', attachments: '附件', deepThinking: '深度思考', decision: '调度决策',
  query: '检索查询', strategy: '检索策略', tool: '工具名称', result: '工具结果',
  skill: '能力名称', model: '模型', answer: '生成内容', accuracy: '准确性',
  completeness: '完整性', safety: '安全性', relevance: '相关性', score: '加权评分',
  threshold: '通过阈值', approved: '评估结果', suggestions: '修正建议',
  evidenceCount: '引用片段', attempts: '生成轮次', error: '错误信息',
  taskId: '任务ID', requestArtifactId: '请求记录ID', response_artifact_id: '响应记录ID',
  arguments: '调用参数', findings: '发现的问题与修改建议', issues: '检查问题',
  canvas: '画布尺寸', nodes: '节点数', edges: '连线数',
  result: '工具结果', purpose: '调用用途', latency_ms: '耗时（毫秒）'
}
watch(() => props.trace?.runId, () => { selectedId.value = null })
function display(value) {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value) || (value && typeof value === 'object')) {
    return Array.isArray(value) && !value.length ? '无' : JSON.stringify(value, null, 2)
  }
  return value == null || value === '' ? '无' : String(value)
}
function safeSourceUrl(value) {
  try {
    const url = new URL(String(value || ''))
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null
  } catch { return null }
}
function sourceDate(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}))?/)
  return match ? `${match[1]}年${match[2]}月${match[3]}日${match[4] ? `${match[4]}时` : ''}` : String(value || '')
}
function formatDuration(value) {
  const milliseconds = Number(value)
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return '—'
  if (milliseconds === 0) return '历史耗时未记录'
  if (milliseconds >= 1000) return `约 ${(milliseconds / 1000).toFixed(1)} 秒`
  return `约 ${Math.max(1, Math.round(milliseconds))} ms`
}
function closeOnEscape(event) { if (event.key === 'Escape') selectedId.value = null }
onMounted(() => window.addEventListener('keydown', closeOnEscape))
onUnmounted(() => window.removeEventListener('keydown', closeOnEscape))
</script>

<template>
  <aside class="agent-monitor" :class="{ collapsed: !panelOpen }">
    <button v-if="!panelOpen" class="rail-handle" type="button" aria-label="展开运行监控" @click="setPanelOpen(true)">
      <Activity :size="19" /><span>运行监控</span><ChevronLeft :size="15" />
    </button>
    <template v-else>
      <header class="monitor-head">
        <span class="head-icon"><Activity :size="20" /></span>
        <div class="head-copy"><strong>运行监控</strong><small>本轮Agent执行链路</small></div>
        <button class="head-collapse" type="button" aria-label="收起运行监控" @click="setPanelOpen(false)"><ChevronRight :size="19" /></button>
      </header>
      <template v-if="trace">
        <div class="run-overview">
          <div class="overview-top">
            <span class="run-type">{{ trace.domain === 'drawing' ? '绘图域' : `知识问答 · ${trace.deepThinking ? '深度思考' : '普通问答'}` }}</span>
            <span class="run-status" :class="trace.status">
              <LoaderCircle v-if="trace.status === 'running'" :size="13" class="spin" />
              <CircleSlash2 v-else-if="trace.status === 'error'" :size="13" />
              <Check v-else :size="13" />
              {{ trace.status === 'running' ? '运行中' : trace.status === 'error' ? '失败' : '已完成' }}
            </span>
          </div>
          <p :title="trace.query">{{ trace.query || '附件消息' }}</p>
          <small>{{ stages.length }} 个步骤<span v-if="trace.durationMs"> · {{ (trace.durationMs / 1000).toFixed(1) }} 秒</span></small>
        </div>
        <div class="stage-list">
          <article v-for="(stage, index) in stages" :key="stage.id" class="stage">
            <div class="stage-rail">
              <span class="stage-icon" :class="[stage.kind, stage.status]"><component :is="kinds[stage.kind]?.icon || Activity" :size="15" /></span>
              <i v-if="index < stages.length - 1" />
            </div>
            <div class="stage-main">
              <div class="stage-kicker"><span>{{ kinds[stage.kind]?.label || '执行步骤' }}</span><span>第 {{ index + 1 }} 步</span></div>
              <div class="stage-title"><strong>{{ stage.title }}</strong><LoaderCircle v-if="stage.status === 'running'" :size="13" class="spin" /></div>
              <p>{{ stage.summary }}</p>
              <div class="stage-foot">
                <span v-if="stage.status === 'running'"><LoaderCircle :size="12" class="spin" />计时中</span>
                <span v-else-if="stage.durationMs != null"><Clock3 :size="12" />{{ formatDuration(stage.durationMs) }}</span>
                <span v-else-if="stage.duration"><Clock3 :size="12" />{{ stage.duration }}</span>
                <button type="button" @click="selectedId = stage.id"><Eye :size="13" />查看详情</button>
              </div>
            </div>
          </article>
        </div>
      </template>
      <div v-else class="empty-monitor">
        <LoaderCircle v-if="generating" :size="28" class="spin" /><Activity v-else :size="28" />
        <strong>{{ generating ? '正在启动本轮工作流' : '尚无运行记录' }}</strong>
        <p>{{ generating ? '接下来会逐步显示检索、工具调用和Agent执行信息。' : '发送消息后，当前这轮的检索、工具调用和Agent步骤会显示在这里。' }}</p>
      </div>
    </template>
  </aside>

  <Teleport to="body">
    <div v-if="selected" class="trace-backdrop" @click.self="selectedId = null">
      <section class="trace-dialog" role="dialog" aria-modal="true" :aria-label="`${selected.title}的详细信息`">
        <header class="dialog-head">
          <div><small>{{ kinds[selected.kind]?.label || '执行步骤' }}</small><h2>{{ selected.title }}</h2></div>
          <button type="button" aria-label="关闭详情" @click="selectedId = null"><X :size="21" /></button>
        </header>
        <div class="dialog-body">
          <p class="dialog-summary">{{ selected.summary }}</p>
          <div v-for="(value, key) in selected.detail" :key="key">
            <template v-if="key === 'results'">
              <h3>召回内容 · {{ value.length }} 个片段</h3>
              <div v-if="!value.length" class="detail-empty">本轮没有检索到可引用的知识资料。</div>
              <article v-for="(item, index) in value" :key="index" class="result-card">
                <div class="result-heading"><FileText :size="16" /><strong>{{ item.filename || item.title || '资料' }}</strong><span v-if="item.page">第 {{ item.page }} 页</span></div>
                <p>{{ item.text }}</p>
              </article>
            </template>
            <template v-else-if="key === 'sources'">
              <h3>网页来源 · {{ value.length }} 个</h3>
              <div v-if="!value.length" class="detail-empty">没有可引用的网页来源。</div>
              <a v-for="source in value" :key="source.sourceNumber" class="web-result-card"
                :href="safeSourceUrl(source.url) || undefined" target="_blank" rel="noopener noreferrer">
                <div class="web-result-title">
                  <img v-if="safeSourceUrl(source.icon)" :src="safeSourceUrl(source.icon)" alt="" @error="$event.target.style.display = 'none'" />
                  <Globe2 v-else :size="17" />
                  <strong>{{ source.title }}</strong>
                </div>
                <div v-if="source.date" class="web-result-date">{{ sourceDate(source.date) }}</div>
                <div class="web-result-url">{{ source.url }}</div>
              </a>
            </template>
            <template v-else-if="!['agent', 'attempt'].includes(key)">
              <h3>{{ labels[key] || key }}</h3><pre class="detail-value">{{ display(value) }}</pre>
            </template>
          </div>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.agent-monitor{flex:0 0 390px;width:390px;height:100%;min-height:0;display:flex;flex-direction:column;color:#3a2455;background:#fcfbfe;border-left:1px solid #e9e3f1}.agent-monitor.collapsed{flex-basis:44px;width:44px}button{font:inherit;cursor:pointer}
.rail-handle{display:flex;flex-direction:column;align-items:center;gap:10px;flex:1;border:0;background:#fcfbfe;color:#490898;padding:17px 0}.rail-handle span{writing-mode:vertical-rl;font-size:12px;font-weight:700;letter-spacing:.12em}
.monitor-head{display:flex;align-items:center;gap:11px;padding:15px 16px;border-bottom:1px solid #eee9f5}.head-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:13px;background:#4d09a1;color:white;box-shadow:0 8px 18px #540bad25}.head-copy{display:grid;gap:2px;flex:1}.head-copy strong{font-size:17px;color:#2f174d}.head-copy small{font-size:11px;color:#7b6694}.head-collapse{display:grid;place-items:center;width:33px;height:33px;border:1px solid #ded0f1;border-radius:10px;background:#f4effb;color:#400984}
.run-overview{margin:15px 15px 7px;padding:13px 14px;border:1px solid #e0d4ef;border-radius:14px;background:#fff}.overview-top{display:flex;justify-content:space-between;align-items:center;gap:8px}.run-type{font-size:12px;font-weight:750;color:#441282}.run-status{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:#4b178b}.run-status.running{color:#4b0a9a}.run-status.error{color:#b95c50}.run-overview p{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:9px 0 5px;font-size:13px}.run-overview small{font-size:11px;color:#7a919c}
.stage-list{flex:1;min-height:0;overflow:auto;padding:11px 17px 30px}.stage{display:flex;gap:11px}.stage-rail{width:27px;flex:none;display:flex;align-items:center;flex-direction:column}.stage-icon{display:grid;place-items:center;flex:none;width:27px;height:27px;border-radius:9px;background:#e6daf5;color:#4a0b98}.stage-icon.model,.stage-icon.output{background:#e4d8f2;color:#481488}.stage-icon.reflection{background:#e4eafa;color:#5874a0}.stage-icon.empty{background:#fff0d6;color:#aa751e}.stage-icon.error{background:#fde8e4;color:#bf5b51}.stage-rail i{display:block;width:1px;flex:1;min-height:16px;background:#d5c7e7}.stage-main{flex:1;min-width:0;padding:2px 0 21px}.stage-kicker{display:flex;justify-content:space-between;font-size:10px;font-weight:700;letter-spacing:.04em;color:#85729c}.stage-title{display:flex;align-items:center;gap:7px;margin-top:5px}.stage-title strong{font-size:13px;color:#3c2855}.stage-title svg{color:#4d0b9e}.stage-main p{margin:6px 0 8px;font-size:12px;line-height:1.55;color:#73608a;overflow-wrap:anywhere}.stage-foot{display:flex;align-items:center;justify-content:space-between;gap:8px}.stage-foot span,.stage-foot button{display:inline-flex;align-items:center;gap:4px;font-size:11px;color:#7d949d}.stage-foot button{border:0;background:transparent;color:#4a089a;font-weight:700;padding:3px 0}.stage-foot button:hover{text-decoration:underline}
.empty-monitor{flex:1;display:flex;align-items:center;justify-content:center;flex-direction:column;text-align:center;padding:28px;color:#623e8e}.empty-monitor strong{margin-top:14px;font-size:14px}.empty-monitor p{max-width:240px;font-size:12px;line-height:1.6;color:#7b6595}.spin{animation:rotate 1s linear infinite}@keyframes rotate{to{transform:rotate(360deg)}}
.trace-backdrop{position:fixed;inset:0;z-index:10000;display:grid;place-items:center;padding:24px;background:#321851a8;backdrop-filter:blur(7px)}.trace-dialog{width:min(760px,100%);max-height:min(82vh,900px);display:flex;flex-direction:column;overflow:hidden;border:1px solid #dcceec;border-radius:20px;background:#faf8fd;box-shadow:0 30px 90px #31175060}.dialog-head{display:flex;justify-content:space-between;align-items:center;padding:20px 24px;border-bottom:1px solid #e5dcf0;background:white}.dialog-head small{font-size:11px;color:#50129b;font-weight:750}.dialog-head h2{margin:4px 0 0;font-size:19px;color:#392453}.dialog-head button{border:0;background:transparent;color:#6e578b;display:grid;place-items:center}.dialog-body{overflow:auto;padding:20px 24px 27px}.dialog-summary{margin:0 0 18px;color:#66537d;font-size:13px;line-height:1.6}.dialog-body h3{margin:18px 0 8px;font-size:12px;color:#4d2e74}.detail-value{margin:0;padding:13px 15px;white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;font-size:13px;line-height:1.7;color:#442d60;background:white;border:1px solid #e7dff1;border-radius:11px}.detail-empty{padding:20px;color:#8b7b9e;text-align:center}.result-card{padding:14px 16px;margin-top:9px;border:1px solid #e1d6ee;border-radius:12px;background:#fff}.result-heading{display:flex;align-items:center;gap:8px;color:#4f1498}.result-heading strong{flex:1;overflow-wrap:anywhere;font-size:13px}.result-heading span{font-size:11px;color:#796591;white-space:nowrap}.result-card p{margin:11px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;color:#4b3566;font-size:13px;line-height:1.75}
.stage-foot button{margin-left:auto}
.web-result-card{display:block;margin-top:9px;padding:13px 15px;border:1px solid #e1d6ee;border-radius:12px;background:#fff;color:#442d60;text-decoration:none;min-width:0}.web-result-card:hover{border-color:#bb9ddf;background:#fbf9fe}.web-result-title{display:flex;align-items:center;gap:6px;min-width:0}.web-result-title img{width:17px;height:17px;flex:none;object-fit:contain;border-radius:3px}.web-result-title svg{flex:none;color:#5415a1}.web-result-title strong{min-width:0;overflow-wrap:anywhere;font-size:13px}.web-result-date{margin-top:6px;padding-left:23px;color:#837198;font-size:12px}.web-result-url{margin-top:8px;color:#685284;font-size:12px;overflow-wrap:anywhere;word-break:break-word}
@media(max-width:1180px){.agent-monitor{flex-basis:340px;width:340px}}@media(max-width:900px){.agent-monitor{position:absolute;inset:0;z-index:40;width:auto;flex-basis:auto;border-left:0}.agent-monitor.collapsed{width:44px}.trace-backdrop{padding:12px}.trace-dialog{max-height:90vh}}
</style>
