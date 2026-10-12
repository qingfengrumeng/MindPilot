<script setup>
import AppSelect from '@/components/AppSelect.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Camera, Check, ChevronDown, LoaderCircle, RefreshCw, Save, User, X } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import { useUiStore } from '@/stores/ui'
import { loadProfileStatistics } from '@/api/profile'
import { SKILLS } from '@/skills'

const emit = defineEmits(['close', 'saved'])
const auth = useAuthStore(), app = useAppStore(), ui = useUiStore()
const profile = reactive({ displayName: auth.user?.displayName || auth.user?.username || '', avatar: auth.user?.avatar || '',
  researchField: auth.user?.researchField || '', defaultDomain: auth.user?.defaultDomain || 'personal_learning', bio: auth.user?.bio || '' })
const stats = ref(null), loading = ref(true), error = ref(''), saving = ref(false), processingAvatar = ref(false)
const editing = ref(false), preferencesOpen = ref(false), fileInput = ref(null)
let disposed = false
const initials = computed(() => (profile.displayName || auth.user?.username || 'M').slice(0, 2).toUpperCase())
const displayNumber = value => new Intl.NumberFormat('zh-CN').format(value || 0)
const duration = value => {
  if (!value) return '—'
  const seconds = Math.max(1, Math.round(value / 1000))
  if (seconds < 60) return `${seconds} 秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor(seconds % 3600 / 60)} 分`
}
const metrics = computed(() => [
  { label: '已记录Token', value: displayNumber(stats.value?.totalTokens) },
  { label: '单轮Token峰值', value: displayNumber(stats.value?.peakTokens) },
  { label: '创建会话', value: displayNumber(stats.value?.conversationCount) },
  { label: '最长连续使用', value: `${stats.value?.longestStreak || 0} 天` },
  { label: '当前连续使用', value: `${stats.value?.currentStreak || 0} 天` }
])
const features = computed(() => {
  const recorded = new Map((stats.value?.features || []).map(item => [item.id, item]))
  const items = SKILLS.map(skill => ({ id: skill.id, label: skill.label, icon: skill.icon, count: recorded.get(skill.id)?.count || 0 }))
  for (const feature of recorded.values()) if (!items.some(item => item.id === feature.id)) items.push({ ...feature, icon: User })
  return items.sort((a, b) => b.count - a.count)
})
const peakFeature = computed(() => Math.max(1, ...features.value.map(item => item.count)))
async function refresh() {
  loading.value = true
  error.value = ''
  try { const result = await loadProfileStatistics(); if (!disposed) stats.value = result }
  catch (failure) { if (!disposed) error.value = failure.message || '统计加载失败' }
  finally { if (!disposed) loading.value = false }
}
async function changeAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) { ui.toast('请选择PNG、JPEG或WebP图片', 'error'); return }
  if (file.size > 10 * 1024 * 1024) { ui.toast('头像图片不能超过10 MB', 'error'); return }
  processingAvatar.value = true
  const url = URL.createObjectURL(file)
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 256
    const context = canvas.getContext('2d')
    context.fillStyle = '#f4edff'
    context.fillRect(0, 0, 256, 256)
    const side = Math.min(image.width, image.height)
    context.drawImage(image, (image.width - side) / 2, (image.height - side) / 2, side, side, 0, 0, 256, 256)
    if (!disposed) { profile.avatar = canvas.toDataURL('image/jpeg', .85); editing.value = true }
  } catch { ui.toast('无法读取这张图片，请换一张重试', 'error') }
  finally { URL.revokeObjectURL(url); processingAvatar.value = false }
}
async function save() {
  if (saving.value || processingAvatar.value) return
  if (!profile.displayName.trim()) { ui.toast('请填写个人名称', 'error'); return }
  saving.value = true
  try {
    await auth.updateProfile({ ...profile, displayName: profile.displayName.trim() })
    emit('saved')
    emit('close')
  } catch (failure) { ui.toast(failure.message || '资料保存失败', 'error') }
  finally { saving.value = false }
}
function keydown(event) { if (event.key === 'Escape' && !saving.value) emit('close') }
onMounted(() => { refresh(); window.addEventListener('keydown', keydown) })
onBeforeUnmount(() => { disposed = true; window.removeEventListener('keydown', keydown) })
</script>

<template>
  <div class="modal-mask personal-profile-mask" @click.self="!saving && emit('close')">
    <section class="personal-profile" role="dialog" aria-modal="true" aria-labelledby="personal-profile-title">
      <header class="profile-topbar"><div><span class="profile-kicker">MINDPILOT</span><h2 id="personal-profile-title">个人资料</h2></div><button type="button" class="profile-icon-button" aria-label="关闭个人资料" :disabled="saving" @click="emit('close')"><X :size="20" /></button></header>
      <div class="profile-scroll">
        <div class="profile-identity">
          <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/webp" hidden @change="changeAvatar" />
          <button class="profile-avatar-button" type="button" aria-label="更换头像" :disabled="processingAvatar || saving" @click="fileInput.click()">
            <img v-if="profile.avatar" :src="profile.avatar" alt="个人头像" /><span v-else>{{ initials }}</span>
            <i><LoaderCircle v-if="processingAvatar" class="profile-spin" :size="17" /><Camera v-else :size="17" /></i>
          </button>
          <button v-if="profile.avatar" class="profile-text-button" type="button" @click="profile.avatar = ''; editing = true">恢复默认头像</button>
          <form v-if="editing" class="profile-name-edit" @submit.prevent="editing = false"><input v-model="profile.displayName" maxlength="80" aria-label="个人名称" autofocus /><button type="submit" aria-label="完成名称编辑"><Check :size="18" /></button></form>
          <button v-else class="profile-name" type="button" title="编辑个人名称" @click="editing = true">{{ profile.displayName }}<span>编辑</span></button>
          <p class="profile-handle">@{{ auth.user?.username }}</p>
        </div>
        <div v-if="error" class="profile-load-error" role="alert">{{ error }}<button type="button" @click="refresh">重新加载</button></div>
        <div class="profile-metrics" :aria-busy="loading">
          <div v-for="metric in metrics" :key="metric.label"><strong>{{ !stats ? '—' : metric.value }}</strong><span>{{ metric.label }}</span></div>
        </div>
        <div class="profile-section-heading"><h3>使用概览</h3><button class="profile-text-button" type="button" :disabled="loading" @click="refresh"><RefreshCw :size="13" :class="{ 'profile-spin': loading }" />刷新统计</button></div>
        <div v-if="stats" class="profile-overview">
          <div><span>输入 / 输出Token</span><strong>{{ displayNumber(stats?.inputTokens) }} <small>/</small> {{ displayNumber(stats?.outputTokens) }}</strong></div>
          <div><span>发送消息</span><strong>{{ displayNumber(stats?.messageCount) }} <small>条</small></strong></div>
          <div><span>最长回复耗时</span><strong>{{ duration(stats?.longestTaskMs) }}</strong></div>
          <div><span>活跃天数</span><strong>{{ stats?.activeDays || 0 }} <small>天</small></strong></div>
        </div>
        <div class="profile-section-heading"><h3>功能使用统计</h3><span v-if="stats">{{ stats.featureCallCount }} 次使用 · {{ stats.toolCallCount }} 次工具调用</span></div>
        <div v-if="stats" class="profile-features"><div v-for="feature in features" :key="feature.id" class="profile-feature"><div><span class="profile-feature-icon"><component :is="feature.icon" :size="17" /></span><span>{{ feature.label }}</span><strong>{{ feature.count }} <small>次</small></strong></div><span class="profile-feature-track"><i :style="{ width: `${feature.count / peakFeature * 100}%` }" /></span></div></div>
        <p class="profile-stat-note">统计基于已保存的会话记录；功能使用按所选功能发送的消息计数，Token仅汇总已返回的用量。<template v-if="stats?.missingUsageCount">有 {{ stats.missingUsageCount }} 条回复未记录Token用量。</template><template v-if="!auth.backendEnabled">当前为演示数据。</template></p>
        <button class="profile-preferences-toggle" type="button" :aria-expanded="preferencesOpen" @click="preferencesOpen = !preferencesOpen">知识与回答偏好<ChevronDown :size="16" :class="{ expanded: preferencesOpen }" /></button>
        <div v-if="preferencesOpen" class="profile-preferences"><label>研究方向<input v-model="profile.researchField" maxlength="160" /></label><label>默认知识域<AppSelect v-model="profile.defaultDomain"><option v-for="domain in app.domains" :key="domain.id" :value="domain.id">{{ domain.label }}</option></AppSelect></label><label class="profile-bio">回答偏好<textarea v-model="profile.bio" maxlength="2000" rows="3" /></label></div>
      </div>
      <footer class="profile-footer"><span>头像与名称将在侧栏同步显示</span><button type="button" class="btn secondary" :disabled="saving" @click="emit('close')">取消</button><button type="button" class="btn" :disabled="saving || processingAvatar" @click="save"><LoaderCircle v-if="saving" class="profile-spin" :size="16" /><Save v-else :size="16" />{{ saving ? '保存中…' : '保存资料' }}</button></footer>
    </section>
  </div>
</template>

<style scoped>
.personal-profile-mask{padding:22px}
.personal-profile{width:min(920px,100%);max-height:calc(100dvh - 44px);display:flex;flex-direction:column;overflow:hidden;border:1px solid #e7def2;border-radius:24px;background:#fff;box-shadow:0 24px 90px #44236b30;color:#39284b}
.profile-topbar{display:flex;align-items:center;justify-content:space-between;padding:20px 28px 10px}.profile-topbar>div{display:flex;align-items:center;gap:12px}.profile-kicker{font-size:10px;font-weight:800;letter-spacing:.16em;color:#a28cba}.profile-topbar h2{font-size:16px;margin:0}.profile-icon-button{width:32px;height:32px;display:grid;place-items:center;border:0;border-radius:10px;color:#9585a5;background:#f8f5fc}.profile-icon-button:hover{color:#7c3aed;background:#f0e8fc}
.profile-scroll{padding:0 28px 22px;overflow:auto;min-height:0}.profile-identity{display:flex;flex-direction:column;align-items:center;padding:10px 0 26px;gap:9px;background:radial-gradient(ellipse at 50% 20%,#f8f3ff,transparent 65%)}
.profile-avatar-button{position:relative;display:grid;place-items:center;width:100px;height:100px;padding:0;border:3px solid #fff;border-radius:50%;background:linear-gradient(135deg,#a78bfa,#6d28d9);color:white;box-shadow:0 0 0 1px #e6d8f7,0 10px 26px #7c3aed20;font-size:32px;font-weight:650;cursor:pointer}.profile-avatar-button img{width:100%;height:100%;border-radius:50%;object-fit:cover}.profile-avatar-button i{position:absolute;right:-1px;bottom:0;width:29px;height:29px;display:grid;place-items:center;border:2px solid white;border-radius:50%;background:#f0e7fd;color:#7c3aed}
.profile-name{display:flex;align-items:center;gap:8px;padding:3px 0;border:0;background:transparent;font-size:25px;font-weight:650;color:#30213e;cursor:pointer;max-width:100%;overflow-wrap:anywhere}.profile-name span{font-size:10px;color:#9b81b5;font-weight:400}.profile-handle{margin:0;color:#a397b0;font-size:13px}.profile-text-button{display:flex;align-items:center;justify-content:center;gap:5px;border:0;background:transparent;color:#9675b9;font:inherit;font-size:11px;cursor:pointer}.profile-text-button:hover{color:#7c3aed}.profile-name-edit{display:flex;gap:5px;max-width:100%}.profile-name-edit input{width:230px;max-width:100%;padding:7px 10px;border:1px solid #d5c1f1;border-radius:9px;text-align:center;font-size:18px;color:#39284b;outline:none}.profile-name-edit button{border:0;background:#f1e8ff;color:#7c3aed;border-radius:8px}
.profile-metrics{display:grid;grid-template-columns:repeat(5,1fr);padding:20px 0;border:1px solid #e8e0f0;border-radius:17px;background:#fdfbff}.profile-metrics>div{display:flex;align-items:center;flex-direction:column;gap:7px;padding:0 6px;min-width:0}.profile-metrics>div+div{border-left:1px solid #e8e0f0}.profile-metrics strong{font-size:19px;font-weight:650;color:#4f2b79;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.profile-metrics span{font-size:11px;color:#94849f}
.profile-section-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:23px 0 12px}.profile-section-heading h3{margin:0;font-size:13px;font-weight:700}.profile-section-heading>span{font-size:10px;color:#a292af}.profile-overview{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;gap:12px}.profile-overview>div{display:flex;flex-direction:column;gap:10px;padding:15px;border-radius:13px;background:#f8f5fc}.profile-overview span{font-size:10px;color:#9c8ca9}.profile-overview strong{font-size:16px;font-weight:600;font-variant-numeric:tabular-nums}.profile-overview small{font-size:11px;color:#a391b1;font-weight:400}
.profile-features{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.profile-feature{padding:12px;border:1px solid #eee7f5;border-radius:13px}.profile-feature>div{display:flex;align-items:center;gap:8px;font-size:11px}.profile-feature-icon{display:grid;place-items:center;width:28px;height:28px;flex:none;border-radius:8px;background:#f3edfd;color:#9866d7}.profile-feature strong{margin-left:auto;font-size:13px;font-weight:600;color:#775198;white-space:nowrap}.profile-feature small{font-size:10px;font-weight:400;color:#a794b6}.profile-feature-track{display:block;height:3px;margin-top:11px;border-radius:3px;background:#f3edf9;overflow:hidden}.profile-feature-track i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,#c5a6f5,#8b5cf6)}
.profile-stat-note{font-size:10px;color:#a99ab5;line-height:1.7;margin:14px 0 0}.profile-preferences-toggle{display:flex;justify-content:space-between;align-items:center;width:100%;margin-top:20px;padding:12px 0;border:0;border-top:1px solid #f0eaf6;background:transparent;color:#847291;font-size:12px;cursor:pointer}.profile-preferences-toggle svg{transition:transform .15s}.profile-preferences-toggle .expanded{transform:rotate(180deg)}.profile-preferences{display:grid;grid-template-columns:1fr 1fr;gap:12px}.profile-preferences label{display:grid;gap:6px;font-size:11px;color:#8f7c9e}.profile-preferences input,.profile-preferences select,.profile-preferences textarea{padding:10px;border:1px solid #e8dff1;border-radius:10px;outline:none;background:#fdfbff;color:#4c385e;font:inherit;font-size:12px}.profile-preferences :is(input,select,textarea):focus{border-color:#a78bfa}.profile-bio{grid-column:1/-1}.profile-bio textarea{resize:vertical}
.profile-footer{display:flex;align-items:center;gap:10px;padding:16px 28px;border-top:1px solid #eee6f5;background:#fdfbff}.profile-footer>span{flex:1;font-size:10px;color:#a493b2}.profile-footer .btn{font-size:12px;min-height:37px;padding:8px 15px}.profile-load-error{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px;margin-bottom:12px;border-radius:10px;background:#fff3f5;color:#bc4770;font-size:12px}.profile-load-error button{border:0;background:transparent;color:inherit;text-decoration:underline;cursor:pointer}.profile-spin{animation:profile-spin 1s linear infinite}@keyframes profile-spin{to{transform:rotate(360deg)}}
button:focus-visible{outline:2px solid #a78bfa;outline-offset:3px}button:disabled{opacity:.6;cursor:default}
@media(max-width:640px){.personal-profile-mask{padding:10px}.personal-profile{max-height:calc(100dvh - 20px);border-radius:18px}.profile-topbar{padding:16px 17px 8px}.profile-scroll{padding:0 17px 17px}.profile-identity{padding-top:12px}.profile-metrics{grid-template-columns:repeat(3,1fr);gap:18px 0}.profile-metrics>div+div{border-left:0}.profile-metrics strong{font-size:17px}.profile-metrics span{font-size:10px}.profile-overview{grid-template-columns:1fr 1fr}.profile-features{grid-template-columns:1fr 1fr;gap:8px}.profile-section-heading{align-items:flex-start}.profile-section-heading>span{max-width:50%;text-align:right;line-height:1.5}.profile-footer{padding:12px 17px}.profile-footer>span{display:none}.profile-footer .btn{flex:1}.profile-preferences{grid-template-columns:1fr}}
</style>
