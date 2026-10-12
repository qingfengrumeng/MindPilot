<script setup>
import { reactive, ref, computed } from 'vue'
import { useRouter, RouterLink } from 'vue-router'
import { User, LockKeyhole, Eye, EyeOff, ArrowRight, Check, UserPlus, ShieldCheck } from 'lucide-vue-next'
import AppLogo from '@/components/AppLogo.vue'; import { useAuthStore } from '@/stores/auth'; import { useUiStore } from '@/stores/ui'
const form = reactive({ username: '', password: '', confirm: '', agreement: false }); const errors = reactive({}); const show = ref(false); const loading = ref(false)
const strength = computed(() => form.password.length < 6 ? 1 : form.password.length < 10 ? 2 : /[A-Z]/.test(form.password) && /\d/.test(form.password) ? 4 : 3)
const auth = useAuthStore(); const ui = useUiStore(); const router = useRouter()
async function submit() {
  errors.username = form.username.trim().length >= 3 ? '' : '用户名至少3位'; errors.password = form.password.length >= 8 ? '' : '密码至少8位'; errors.confirm = form.confirm === form.password ? '' : '两次密码不一致'; errors.agreement = form.agreement ? '' : '请先同意用户协议'
  if (Object.values(errors).some(Boolean)) return
  loading.value = true
  try {
    await auth.register(form)
    ui.toast('注册成功，请使用新账号登录')
    router.push('/login')
  } catch (error) {
    ui.toast(error?.message || '注册失败，请重试', 'error')
  } finally { loading.value = false }
}
</script>
<template><main class="auth-page register-page"><section class="auth-brand"><AppLogo light/><div class="auth-hero"><span class="eyebrow">START YOUR KNOWLEDGE BASE</span><h1>把读过的资料，<br><em>变成问得出来的知识</em></h1><p>导入本地文档即可建立索引，MindPilot会持续编译Wiki、沉淀记忆并生成可视化。</p><div class="register-points"><div v-for="text in ['本地资料导入与索引','带引用来源的知识问答','LLM Wiki自动编译','知识域隔离与外发检查']" :key="text"><span><Check :size="16"/></span>{{ text }}</div></div></div><div class="orb orb-one"/><div class="orb orb-two"/><div class="grid-bg"/></section>
  <section class="auth-form-wrap"><form class="auth-card" @submit.prevent="submit">
    <div class="auth-card-heading"><span class="auth-heading-icon"><UserPlus :size="22"/></span><div><span class="eyebrow">CREATE ACCOUNT</span><h2>创建账号</h2></div></div>
    <p>创建一个本地账号，开始搭建你的个人知识库</p>
    <div class="auth-security-note"><ShieldCheck :size="17"/><span><strong>无需邮箱，快速开始</strong><small>仅需设置用户名和登录密码</small></span></div>
    <label class="form-label">用户名</label><div class="input-wrap"><User :size="18"/><input v-model="form.username" placeholder="你的称呼"></div><small class="field-error">{{ errors.username }}</small>
    <label class="form-label">密码</label><div class="input-wrap"><LockKeyhole :size="18"/><input v-model="form.password" :type="show ? 'text' : 'password'" placeholder="至少8位"><button type="button" @click="show=!show"><component :is="show?EyeOff:Eye" :size="18"/></button></div><div class="strength"><i v-for="n in 4" :key="n" :class="{ active: n <= strength }"/></div><small class="field-error">{{ errors.password }}</small>
    <label class="form-label">确认密码</label><div class="input-wrap"><LockKeyhole :size="18"/><input v-model="form.confirm" type="password" placeholder="再次输入密码"></div><small class="field-error">{{ errors.confirm }}</small>
    <label class="check agreement"><input v-model="form.agreement" type="checkbox"><span/>我已阅读并同意 <a>用户协议</a> 与 <a>隐私政策</a></label><small class="field-error">{{ errors.agreement }}</small>
    <button class="btn auth-submit" :disabled="loading">{{ loading ? '正在创建...' : '创建账号' }}<ArrowRight v-if="!loading" :size="18"/></button><p class="auth-switch">已有账号？<RouterLink to="/login">返回登录</RouterLink></p>
  </form></section></main></template>
