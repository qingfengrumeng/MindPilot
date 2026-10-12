<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Download, ExternalLink, FileDown, ImageDown, Pencil, Save, Send, Sparkles, X } from 'lucide-vue-next'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'
import typographyStyles from '@/styles/typography.css?inline'

const props = defineProps({ message: { type: Object, required: true }, embedded: { type: Boolean, default: false } })
const chat = useChatStore()
const ui = useUiStore()
const editorUrl = new URL(`${import.meta.env.BASE_URL}drawio/index.html?dev=1&mindpilot=1&embed=1&proto=json&configure=1&libraries=0&sidebar=0&format=1&pages=0&pv=0&grid=0&sb=0&lang=zh&noSaveBtn=1&noExitBtn=1&saveAndExit=0`, window.location.href).href
const origin = new URL(editorUrl).origin
const messageOrigin = origin === 'null' ? '*' : origin
const diagram = computed(() => props.message.diagram || props.message.metadata?.diagram || {})
const imageUrl = computed(() => diagram.value.svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(diagram.value.svg)}` : '')
const viewportSize = ref({ width: window.innerWidth, height: window.innerHeight })
const editorShellStyle = computed(() => {
  if (viewportSize.value.width <= 650) return { width: '100%', height: '100%' }
  return { width: 'calc(100vw - 8px)', height: 'calc(100vh - 8px)' }
})
const name = computed(() => diagram.value.type === 'mindmap' ? '思维导图' : '流程图')
const open = ref(false)
const menu = ref(false)
const saving = ref(false)
const sending = ref(false)
const turnError = ref('')
const workingSeconds = ref(0)
const ready = ref(false)
const loadError = ref('')
const draftXml = ref('')
const draftVersion = ref(1)
const editorRevision = ref(0)
const turnText = ref('')
const turns = ref([])
const turnList = ref(null)
const iframe = ref(null)
let pendingExport = null
let workingTimer = null
let loadMonitor = null
watch(() => turns.value.length, async () => {
  await nextTick()
  if (turnList.value) turnList.value.scrollTop = turnList.value.scrollHeight
})

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60000)
  menu.value = false
}

function downloadDrawio() {
  const xml = diagram.value.xml || ''
  if (!xml) return
  const documentXml = xml.startsWith('<mxfile') ? xml : `<mxfile host="MindPilot" version="1"><diagram name="Page-1">${xml}</diagram></mxfile>`
  downloadBlob(new Blob([documentXml], { type: 'application/xml;charset=utf-8' }), `${name.value}.drawio`)
}

async function downloadPng() {
  if (!imageUrl.value) return
  try {
    const image = new Image()
    image.src = imageUrl.value
    await image.decode()
    const canvas = document.createElement('canvas')
    const scale = Math.min(1, 4096 / Math.max(image.naturalWidth, image.naturalHeight))
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    const context = canvas.getContext('2d')
    context.fillStyle = '#ffffff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(blob => {
      if (blob) downloadBlob(blob, `${name.value}.png`)
    }, 'image/png')
  } catch { ui.toast('PNG导出失败，请下载draw.io文件', 'error') }
}

function post(action) {
  iframe.value?.contentWindow?.postMessage(JSON.stringify(action), messageOrigin)
}

function fitCanvas() {
  if (open.value && ready.value) post({ action: 'fit', border: 24, maxScale: 3 })
}

function applyEditorTypography() {
  const doc = iframe.value?.contentDocument
  if (!doc?.head || doc.getElementById('mindpilot-typography')) return
  const style = doc.createElement('style')
  style.id = 'mindpilot-typography'
  style.textContent = typographyStyles + '\nbody,button,input,textarea,select,.geMenubar,.geToolbar,.geSidebar,.geFormat,.geDialog,.gePopupMenu{font-family:"MindPilot Latin",Arial,"Microsoft YaHei UI",sans-serif!important;font-variant-ligatures:none}'
  doc.head.append(style)
}

function stopLoadMonitor() {
  if (loadMonitor) window.clearInterval(loadMonitor)
  loadMonitor = null
}

function markEditorReady() {
  if (!open.value || ready.value) return
  ready.value = true
  loadError.value = ''
  stopLoadMonitor()
  requestAnimationFrame(fitCanvas)
  window.setTimeout(fitCanvas, 160)
}

function startLoadMonitor() {
  stopLoadMonitor()
  const startedAt = Date.now()
  loadMonitor = window.setInterval(() => {
    if (!open.value || ready.value) { stopLoadMonitor(); return }
    try {
      const canvas = iframe.value?.contentDocument?.querySelector('.geDiagramContainer')
      // draw.io can finish rendering even if its postMessage(load) is missed.
      if (canvas?.querySelector('svg') && canvas.innerText.trim()) {
        markEditorReady()
        return
      }
    } catch { /* Cross-origin frames rely on the normal load event. */ }
    if (Date.now() - startedAt > 25000) {
      loadError.value = '画布加载超时，请重试。'
      stopLoadMonitor()
    }
  }, 500)
}

function retryEditorLoad() {
  ready.value = false
  loadError.value = ''
  editorRevision.value++
  nextTick(startLoadMonitor)
}

function handleEditorResize() {
  viewportSize.value = { width: window.innerWidth, height: window.innerHeight }
  requestAnimationFrame(fitCanvas)
}

function handleMessage(event) {
  if (!open.value || event.origin !== origin || event.source !== iframe.value?.contentWindow) return
  let data
  try { data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data } catch { return }
  if (data?.event === 'configure') {
    post({ action: 'configure', config: {
      hideMenus: ['file', 'edit', 'view', 'arrange', 'extras', 'help'],
      enableInlineToolbar: false, compact: true, preserveViewState: true
    } })
  } else if (data?.event === 'init') {
    post({ action: 'load', xml: draftXml.value, autosave: 1, saveAndExit: 0, noSaveBtn: 1,
      noExitBtn: 1, fit: 0, title: name.value })
  } else if (data?.event === 'load') {
    markEditorReady()
  } else if (data?.event === 'mindpilotInspector') {
    requestAnimationFrame(fitCanvas)
    window.setTimeout(fitCanvas, 100)
  } else if ((data?.event === 'autosave' || data?.event === 'save') && typeof data.xml === 'string' && data.xml) {
    draftXml.value = data.xml
  } else if (data?.event === 'export' && data.format === 'xml' && pendingExport) {
    pendingExport(data.xml || draftXml.value)
    pendingExport = null
  }
}

function openEditor() {
  if (!diagram.value.xml) return
  draftXml.value = diagram.value.xml
  draftVersion.value = Number(diagram.value.version) || 1
  turns.value = [...(props.message.editorTurns || props.message.metadata?.editorTurns || [])]
  turnText.value = ''
  turnError.value = ''
  editorRevision.value++
  ready.value = false
  loadError.value = ''
  open.value = true
  document.body.style.overflow = 'hidden'
  window.addEventListener('message', handleMessage)
  window.addEventListener('resize', handleEditorResize)
  nextTick(startLoadMonitor)
}

function closeEditor() {
  if (saving.value || sending.value) return
  open.value = false
  ready.value = false
  loadError.value = ''
  stopLoadMonitor()
  document.body.style.overflow = ''
  window.removeEventListener('message', handleMessage)
  window.removeEventListener('resize', handleEditorResize)
  if (pendingExport) { pendingExport(draftXml.value); pendingExport = null }
}

function exportedXml() {
  if (!ready.value) return Promise.resolve(draftXml.value)
  return new Promise(resolve => {
    const timer = setTimeout(() => {
      if (pendingExport === finish) pendingExport = null
      resolve(draftXml.value)
    }, 5000)
    function finish(xml) { clearTimeout(timer); resolve(xml) }
    pendingExport = finish
    post({ action: 'export', format: 'xml' })
  })
}

async function save() {
  if (saving.value || sending.value || !ready.value) return
  saving.value = true
  try {
    const xml = await exportedXml()
    await chat.saveDiagram(props.message.id, xml, draftVersion.value)
    ui.toast('图表已保存', 'success')
    saving.value = false
    closeEditor()
  } catch (error) {
    ui.toast(error.message || '图表保存失败', 'error')
    saving.value = false
  }
}

async function sendTurn() {
  const content = turnText.value.trim()
  if (!content || sending.value || saving.value || !ready.value) return
  sending.value = true
  turnError.value = ''
  workingSeconds.value = 0
  workingTimer = window.setInterval(() => { workingSeconds.value++ }, 1000)
  turns.value.push({ role: 'user', content })
  turnText.value = ''
  try {
    const xml = await exportedXml()
    const result = await chat.editDiagramTurn(props.message.id, content, xml, draftVersion.value)
    const updated = result.message.metadata || {}
    draftXml.value = updated.diagram.xml
    draftVersion.value = Number(updated.diagram.version)
    turns.value = [...(updated.editorTurns || [])]
    ready.value = false
    editorRevision.value++
  } catch (error) {
    turns.value.pop()
    turnText.value = content
    turnError.value = error.message || '图表修改失败，请重试'
    ui.toast(error.message || '图表修改失败', 'error')
  } finally {
    window.clearInterval(workingTimer)
    workingTimer = null
    sending.value = false
  }
}

onBeforeUnmount(() => {
  window.clearInterval(workingTimer)
  stopLoadMonitor()
  window.removeEventListener('message', handleMessage)
  window.removeEventListener('resize', handleEditorResize)
  if (open.value) document.body.style.overflow = ''
})
</script>

<template>
  <section class="diagram-card" :class="{ embedded }">
    <header class="diagram-card-header">
      <div class="diagram-card-heading"><span class="diagram-card-mark">◇</span><strong>{{ name }}</strong><small>可编辑 · draw.io</small></div>
      <div class="diagram-card-actions">
        <div class="diagram-download-wrap">
          <button type="button" class="diagram-tool-button" @click="menu = !menu"><Download :size="16" />下载</button>
          <div v-if="menu" class="diagram-download-menu">
            <button type="button" @click="downloadPng"><ImageDown :size="15" />PNG图片</button>
            <button type="button" @click="downloadDrawio"><FileDown :size="15" />draw.io文件</button>
          </div>
        </div>
        <button type="button" class="diagram-tool-button primary" @click="openEditor"><Pencil :size="15" />编辑</button>
      </div>
    </header>
    <div class="diagram-preview"><img v-if="imageUrl" :src="imageUrl" :alt="name" /><span v-else>图表预览不可用</span></div>
    <footer class="diagram-card-footer">
      <span><ExternalLink :size="13" />点击编辑可在当前页面打开draw.io画布</span>
    </footer>
    <Teleport to="body">
      <div v-if="open" class="diagram-editor-backdrop" role="dialog" aria-modal="true" :aria-label="`编辑${name}`">
        <div class="diagram-editor-shell" :style="editorShellStyle">
          <header class="diagram-editor-header">
            <div><strong>AI绘图工作台</strong><span>{{ name }} · 对话修改与手动调整</span></div>
            <div class="diagram-editor-actions">
              <button type="button" :disabled="saving || sending" @click="closeEditor"><X :size="17" />关闭</button>
              <button type="button" class="primary" :disabled="!ready || saving || sending" @click="save"><Save :size="17" />{{ saving ? '保存中…' : '保存画布' }}</button>
            </div>
          </header>
          <div class="diagram-workbench-body">
            <aside class="diagram-chat-panel" aria-label="AI绘图对话">
              <div class="diagram-chat-title"><span class="diagram-chat-icon"><Sparkles :size="18" /></span><div><strong>绘图助手</strong><small>描述修改，画布会同步更新</small></div></div>
              <div ref="turnList" class="diagram-chat-history">
                <div v-if="!turns.length" class="diagram-chat-empty">
                  <Sparkles :size="22" />
                  <strong>继续修改这张图</strong>
                  <p>例如：“把业务服务层背景改为红色”或“将审核失败连回提交申请”。</p>
                </div>
                <div v-for="(turn, index) in turns" :key="index" class="diagram-chat-turn" :class="turn.role">
                  <span>{{ turn.role === 'user' ? '你' : '绘图助手' }}</span>
                  <p>{{ turn.content }}</p>
                </div>
                <div v-if="sending" class="diagram-chat-working">正在分析图表并生成修改方案 · {{ workingSeconds }} 秒</div>
              </div>
              <div class="diagram-chat-composer">
                <p v-if="turnError" class="diagram-chat-error" role="alert">{{ turnError }}</p>
                <textarea v-model="turnText" rows="3" maxlength="3000" :disabled="sending || saving" placeholder="描述你想修改的节点、连线、颜色或布局…" @keydown.enter.exact.prevent="sendTurn" />
                <div><span>Enter发送 · Shift + Enter换行</span><button type="button" :disabled="!turnText.trim() || !ready || sending || saving" @click="sendTurn"><Send :size="16" />发送</button></div>
              </div>
            </aside>
            <div class="diagram-editor-area">
              <div class="diagram-editor-viewport">
                <iframe :key="editorRevision" ref="iframe" :src="editorUrl" title="draw.io图表编辑器" scrolling="no" allowfullscreen @load="applyEditorTypography" />
                <div v-if="!ready" class="diagram-editor-loading">
                  <span>{{ loadError || '正在加载draw.io画布…' }}</span>
                  <button v-if="loadError" type="button" @click="retryEditorLoad">重试加载</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.diagram-card{width:min(100%,900px);margin-top:14px;overflow:visible;border:1px solid #c7afe5;border-radius:18px;background:#fcf9ff;box-shadow:0 9px 26px rgba(72,26,128,.09)}
.diagram-card.embedded{box-sizing:border-box;width:100%;margin:0;border:1px solid #c6ace6;border-radius:16px;box-shadow:0 4px 16px rgba(65,23,116,.06)}
.diagram-card-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 16px;border-bottom:1px solid #e3d7f2}
.diagram-card-heading,.diagram-card-actions,.diagram-tool-button{display:flex;align-items:center;gap:8px}.diagram-card-heading strong{color:#36175d}.diagram-card-heading small{color:#8771a1;font-size:12px}.diagram-card-mark{color:#4e07a5;font-size:22px}
.diagram-card-actions{flex:none}.diagram-tool-button{border:1px solid #cab5e4;border-radius:9px;background:white;color:#490899;padding:8px 11px;font-size:13px;font-weight:650;cursor:pointer}.diagram-tool-button.primary{background:#4e07a5;border-color:#4e07a5;color:#fff}.diagram-tool-button:hover{filter:brightness(.96)}
.diagram-download-wrap{position:relative}.diagram-download-menu{position:absolute;right:0;top:calc(100% + 5px);z-index:5;min-width:160px;padding:5px;border:1px solid #ded3ec;border-radius:10px;background:#fff;box-shadow:0 10px 28px rgba(54,26,88,.17)}.diagram-download-menu button{display:flex;align-items:center;gap:8px;width:100%;padding:9px;border:0;border-radius:7px;background:transparent;color:#43246a;text-align:left;cursor:pointer}.diagram-download-menu button:hover{background:#f1e9fa}
.diagram-preview{min-height:250px;max-height:620px;overflow:auto;padding:18px;background:#fff;text-align:left}.diagram-preview img{display:block;width:auto;height:auto;max-width:100%;margin:0}.diagram-card-footer{display:flex;align-items:center;gap:5px;padding:8px 16px;border-top:1px solid #ece5f5;color:#8875a0;font-size:12px}.diagram-card-footer>span{display:flex;align-items:center;gap:5px}
.diagram-editor-backdrop{position:fixed;inset:0;z-index:12000;display:grid;place-items:center;padding:4px;background:rgba(26,8,49,.72)}.diagram-editor-shell{box-sizing:border-box;display:flex;flex-direction:column;width:100%;height:100%;overflow:hidden;border-radius:12px;background:#fff;box-shadow:0 24px 80px rgba(0,0,0,.34)}.diagram-editor-header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 20px;background:#f9f5fd;border-bottom:1px solid #dbccee}.diagram-editor-header>div:first-child{display:flex;align-items:baseline;gap:12px}.diagram-editor-header strong{color:#36175d}.diagram-editor-header span{color:#846e9f;font-size:12px}.diagram-editor-actions{display:flex;gap:8px}.diagram-editor-actions button{display:flex;align-items:center;gap:6px;padding:8px 13px;border:1px solid #cdbbe4;border-radius:9px;background:#fff;color:#503177;cursor:pointer}.diagram-editor-actions button.primary{background:#4e07a5;border-color:#4e07a5;color:#fff}.diagram-editor-actions button:disabled{opacity:.5;cursor:wait}
.diagram-workbench-body{display:grid;grid-template-columns:minmax(290px,320px) minmax(0,1fr);flex:1;min-height:0}.diagram-chat-panel{display:flex;flex-direction:column;min-width:0;background:#faf7fd;border-right:1px solid #e5dcf1}.diagram-chat-title{display:flex;align-items:center;gap:10px;padding:17px 18px;border-bottom:1px solid #e8dff2}.diagram-chat-title>div:last-child{display:flex;flex-direction:column;gap:2px}.diagram-chat-title strong{color:#391960;font-size:15px}.diagram-chat-title small{color:#8b78a2;font-size:11px}.diagram-chat-icon{display:grid;place-items:center;width:34px;height:34px;border-radius:11px;background:#e9ddf8;color:#4d07a3}.diagram-chat-history{flex:1;min-height:0;overflow:auto;padding:18px 14px}.diagram-chat-empty{display:flex;flex-direction:column;align-items:flex-start;gap:9px;padding:20px 14px;color:#715396}.diagram-chat-empty strong{color:#43236b;font-size:14px}.diagram-chat-empty p{margin:0;font-size:12px;line-height:1.7}.diagram-chat-turn{max-width:95%;margin-bottom:15px}.diagram-chat-turn.user{margin-left:auto;text-align:right}.diagram-chat-turn span{display:block;margin-bottom:5px;color:#8c78a5;font-size:11px}.diagram-chat-turn p{display:inline-block;margin:0;padding:10px 12px;border:1px solid #e0d4ef;border-radius:12px;background:#fff;color:#4b316b;font-size:13px;line-height:1.6;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere}.diagram-chat-turn.user p{border-color:#5210a3;background:#5210a3;color:#fff}.diagram-chat-working{padding:9px 10px;color:#4e0b9f;font-size:12px}.diagram-chat-composer{padding:12px;border-top:1px solid #e5dcf1;background:#fff}.diagram-chat-composer textarea{box-sizing:border-box;width:100%;min-height:85px;resize:vertical;padding:11px 12px;border:1px solid #d6c7e9;border-radius:10px;outline:0;background:#faf8fd;color:#422665;font:inherit;font-size:13px;line-height:1.5}.diagram-chat-composer textarea:focus{border-color:#4e07a5;box-shadow:0 0 0 3px #4e07a51c}.diagram-chat-composer>div{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:8px}.diagram-chat-composer span{color:#9f91b0;font-size:10px}.diagram-chat-composer button{display:flex;align-items:center;gap:5px;padding:7px 11px;border:0;border-radius:8px;background:#4e07a5;color:#fff;font-weight:650;cursor:pointer}.diagram-chat-composer button:disabled{opacity:.45;cursor:not-allowed}
.diagram-editor-area{display:flex;flex-direction:column;min-width:0;min-height:0;background:#fff}.diagram-editor-viewport{position:relative;flex:1;min-height:0;overflow:hidden}.diagram-editor-viewport iframe{display:block;width:100%;height:100%;border:0;overflow:hidden}.diagram-editor-loading{position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;background:#fff;color:#6d538d}.diagram-editor-loading button{padding:8px 16px;border:1px solid #c3a8e4;border-radius:9px;background:#f1e8fb;color:#4a089b;font:inherit;cursor:pointer}.diagram-editor-loading button:hover{background:#e6d9f7}
@media(max-width:900px){.diagram-workbench-body{grid-template-columns:minmax(230px,30%) minmax(0,1fr)}}@media(max-width:650px){.diagram-card-header{align-items:flex-start;flex-direction:column}.diagram-card-footer{align-items:flex-start;flex-direction:column}.diagram-editor-backdrop{padding:0}.diagram-editor-shell{height:100%;border-radius:0}.diagram-editor-header>div:first-child{flex-direction:column;gap:2px}.diagram-editor-header span{display:none}.diagram-workbench-body{display:flex;flex-direction:column}.diagram-chat-panel{flex:none;height:36%;border-right:0;border-bottom:1px solid #e5dcf1}.diagram-editor-area{flex:1}.diagram-chat-title{padding:8px 12px}.diagram-chat-history{padding:9px}.diagram-chat-composer{padding:8px}.diagram-chat-composer textarea{min-height:52px;max-height:60px}}
.diagram-chat-error{margin:0 0 9px;padding:9px 11px;border:1px solid #f0c3bd;border-radius:8px;background:#fff5f3;color:#a23b32;font-size:12px;line-height:1.5}
</style>
