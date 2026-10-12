<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { User, LockKeyhole, Eye, EyeOff, ArrowRight, MessagesSquare, LibraryBig, Network, ShieldCheck, KeyRound } from 'lucide-vue-next'
import AppLogo from '@/components/AppLogo.vue'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
const form = reactive({ username: '', password: '', remember: true })
const errors = reactive({}); const loading = ref(false); const show = ref(false)
const auth = useAuthStore(); const ui = useUiStore(); const route = useRoute(); const router = useRouter()
const features = [{ icon: MessagesSquare, text: '知识问答助手' }, { icon: LibraryBig, text: '本地资料索引' }, { icon: Network, text: '知识可视化' }, { icon: ShieldCheck, text: '知识域隔离' }]
async function submit() {
  errors.username = form.username.trim() ? '' : '请输入用户名'
  errors.password = !form.password ? '请输入密码' : ''
  if (errors.username || errors.password) return
  loading.value = true
  try {
    await auth.login(form)
    ui.toast('登录成功，欢迎回来')
    router.push(route.query.redirect || '/')
  } catch (error) {
    ui.toast(error?.message || '登录失败，请检查用户名和密码', 'error')
  } finally { loading.value = false }
}
function fillDemo() {
  form.username = auth.demoHint.username
  form.password = auth.demoHint.password
}
</script>
<template>
  <main class="auth-page">
    <section class="auth-brand">
      <AppLogo light />
      <div class="auth-hero"><span class="eyebrow">YOUR LOCAL KNOWLEDGE COPILOT</span><h1>让散落的资料，<br><em>变成随时可问的知识</em></h1><p>MindPilot在你的设备上管理资料、编译Wiki、回答问题并生成可视化，一切都在本地完成。</p>
        <div class="feature-grid"><div v-for="item in features" :key="item.text"><span><component :is="item.icon" :size="20" /></span>{{ item.text }}</div></div>
      </div>
      <div class="orb orb-one"/><div class="orb orb-two"/><div class="grid-bg"/>
    </section>
    <section class="auth-form-wrap"><div class="auth-mobile-logo"><AppLogo /></div><form class="auth-card" @submit.prevent="submit">
      <div class="auth-card-heading"><span class="auth-heading-icon"><User :size="22"/></span><div><span class="eyebrow">WELCOME BACK</span><h2>欢迎回来</h2></div></div>
      <p>使用本地账号登录，继续管理你的个人知识库</p>
      <div class="auth-security-note"><ShieldCheck :size="17"/><span><strong>隐私优先，数据更安心</strong><small>账号与登录状态仅保存在当前设备</small></span></div>
      <label class="form-label">用户名</label><div class="input-wrap" :class="{ invalid: errors.username }"><User :size="19"/><input v-model="form.username" autocomplete="username" placeholder="请输入用户名"></div><small class="field-error">{{ errors.username }}</small>
      <label class="form-label">密码</label><div class="input-wrap" :class="{ invalid: errors.password }"><LockKeyhole :size="18"/><input v-model="form.password" :type="show ? 'text' : 'password'" placeholder="请输入密码"><button type="button" @click="show = !show"><component :is="show ? EyeOff : Eye" :size="18"/></button></div><small class="field-error">{{ errors.password }}</small>
      <div class="form-between"><label class="check"><input v-model="form.remember" type="checkbox"><span/>记住登录状态</label><button v-if="!auth.backendEnabled" type="button" class="text-btn demo-hint-btn" @click="fillDemo"><KeyRound :size="15"/>使用演示账号</button></div>
      <div v-if="!auth.backendEnabled" class="auth-demo-hint"><span>演示账号</span><code>{{ auth.demoHint.username }}</code><i>/</i><code>{{ auth.demoHint.password }}</code><small>账号信息仅用于本地演示</small></div>
      <button class="btn auth-submit" :disabled="loading"><span v-if="loading" class="spinner"/>{{ loading ? '正在登录...' : '登录' }}<ArrowRight v-if="!loading" :size="18"/></button>
      <p class="auth-switch">还没有账号？<RouterLink to="/register">立即注册</RouterLink></p>
    </form></section>
  </main>
</template>
