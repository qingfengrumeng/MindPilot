import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { apiRequest, backendEnabled, refreshAccess, setAccessToken } from '@/api/http'
import { useChatStore } from '@/stores/chat'

/**
 * 默认连接后端鉴权：账户由 SQLite 管理，访问令牌只放内存，
 * 页面刷新后通过 HttpOnly 刷新 Cookie 恢复登录。
 * 显式启用离线演示模式时，演示账号和演示会话才使用 localStorage。
 */

const USERS_KEY = 'mindpilot-users'
const SESSION_KEY = 'mindpilot-session'

/** 预置演示账号，首次打开即可直接登录。 */
const demoAccount = {
  username: 'demo',
  password: '123456',
  displayName: '本地知识管理者',
  researchField: '长上下文与检索增强',
  defaultDomain: 'personal_learning',
  bio: '关注长上下文与检索增强，偏好结论先行、区分原文事实与模型推断的回答。',
  createdAt: '2026-09-01 10:00'
}

function readUsers() {
  try {
    const parsed = JSON.parse(localStorage.getItem(USERS_KEY) || 'null')
    if (Array.isArray(parsed) && parsed.length) return parsed
  } catch {
    // 存储损坏时回落到内置账号。
  }
  return [{ ...demoAccount }]
}

function writeUsers(users) {
  try {
    localStorage.setItem(USERS_KEY, JSON.stringify(users))
  } catch {
    // 存储被禁用时注册信息仅在本次会话内有效。
  }
}

/** 演示用的本地凭证，仅用于标识会话，不承载任何真实权限。 */
function issueToken() {
  return `local.${Date.now().toString(36)}.${Math.random().toString(36).slice(2, 10)}.mindpilot`
}

function publicUser(user) {
  if (!user) return null
  const { password, ...rest } = user
  return rest
}

export const useAuthStore = defineStore('auth', () => {
  const users = ref(backendEnabled ? [] : readUsers())

  // 离线演示从本地恢复；后端模式通过 restore() 验证刷新 Cookie。
  const session = (() => {
    try {
      return JSON.parse(localStorage.getItem(SESSION_KEY) || 'null')
    } catch {
      return null
    }
  })()

  const user = ref(backendEnabled ? null : session?.user || null)
  const token = ref(backendEnabled ? null : session?.token || null)
  const isLoggedIn = computed(() => Boolean(token.value && user.value))
  let restored = false
  if (backendEnabled) {
    window.addEventListener('mindpilot:auth-expired', () => {
      token.value = null
      user.value = null
      useChatStore().reset()
    })
  }

  async function restore() {
    if (!backendEnabled || restored) return
    restored = true
    try {
      const result = await refreshAccess()
      token.value = result.accessToken
      user.value = result.user
    } catch {
      token.value = null
      user.value = null
      setAccessToken(null)
    }
  }

  function persistSession() {
    try {
      if (token.value && user.value) {
        localStorage.setItem(SESSION_KEY, JSON.stringify({ token: token.value, user: user.value }))
      } else {
        localStorage.removeItem(SESSION_KEY)
      }
    } catch {
      // 忽略存储失败，会话仅在本次会话内有效。
    }
  }

  function findUser(username) {
    const key = String(username || '').trim().toLowerCase()
    return users.value.find(item => item.username.toLowerCase() === key)
  }

  async function login({ username, password, remember = true }) {
    if (backendEnabled) {
      const result = await apiRequest('post', '/auth/login', { username, password, remember })
      useChatStore().reset()
      token.value = result.accessToken
      user.value = result.user
      setAccessToken(result.accessToken)
      restored = true
      return user.value
    }
    await new Promise(resolve => setTimeout(resolve, 320))
    const account = findUser(username)
    // 统一提示，避免暴露"账号是否存在"。
    if (!account || account.password !== password) {
      throw new Error('用户名或密码不正确')
    }
    user.value = publicUser(account)
    token.value = issueToken()
    persistSession()
    return user.value
  }

  async function register({ username, password, researchField, defaultDomain }) {
    if (backendEnabled) {
      return apiRequest('post', '/auth/register', { username, password, researchField, defaultDomain })
    }
    await new Promise(resolve => setTimeout(resolve, 420))
    const name = String(username || '').trim()
    if (findUser(name)) throw new Error('该用户名已被注册')
    const account = {
      username: name,
      password,
      displayName: name,
      researchField: researchField || '未填写',
      defaultDomain: defaultDomain || 'personal_learning',
      bio: '',
      createdAt: new Date().toISOString().slice(0, 16).replace('T', ' ')
    }
    users.value = [...users.value, account]
    writeUsers(users.value)
    return publicUser(account)
  }

  async function updateProfile(payload) {
    if (backendEnabled) {
      user.value = await apiRequest('patch', '/auth/me', payload)
      return user.value
    }
    await new Promise(resolve => setTimeout(resolve, 260))
    const account = findUser(user.value?.username)
    if (!account) throw new Error('当前会话已失效，请重新登录')
    const updated = { ...account, ...payload, username: account.username, password: account.password }
    users.value = users.value.map(item => (item.username === account.username ? updated : item))
    writeUsers(users.value)
    user.value = publicUser(updated)
    persistSession()
    return user.value
  }

  async function changePassword({ currentPassword, nextPassword }) {
    if (backendEnabled) {
      await apiRequest('post', '/auth/change-password', { currentPassword, nextPassword })
      token.value = null
      user.value = null
      setAccessToken(null)
      return true
    }
    await new Promise(resolve => setTimeout(resolve, 300))
    const account = findUser(user.value?.username)
    if (!account) throw new Error('当前会话已失效，请重新登录')
    if (account.password !== currentPassword) throw new Error('当前密码不正确')
    const updated = { ...account, password: nextPassword }
    users.value = users.value.map(item => (item.username === account.username ? updated : item))
    writeUsers(users.value)
    return true
  }

  async function logout() {
    if (backendEnabled) {
      try { await apiRequest('post', '/auth/logout') } catch { /* 本地仍清除访问令牌 */ }
      setAccessToken(null)
    }
    user.value = null
    token.value = null
    useChatStore().reset()
    persistSession()
  }

  /** 供登录页展示，提示可用的演示账号。 */
  const demoHint = { username: demoAccount.username, password: demoAccount.password }

  return {
    user, token, isLoggedIn, demoHint, backendEnabled,
    restore, login, register, updateProfile, changePassword, logout
  }
})
