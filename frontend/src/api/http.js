import axios from 'axios'

// 本地开发默认连接 Vite 的 /api 代理。仅显式设置 off 时使用演示数据。
const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL
export const backendEnabled = configuredBaseUrl !== 'off'

const http = axios.create({
  baseURL: backendEnabled ? (configuredBaseUrl || '/api/v1') : '',
  withCredentials: true,
  timeout: 20000
})

let accessToken = null
let refreshing = null

export function setAccessToken(token) {
  accessToken = token || null
}

export async function getAccessToken() {
  if (!accessToken) await refreshAccess()
  return accessToken
}

export function websocketUrl(path) {
  const base = http.defaults.baseURL.replace(/\/$/, '')
  const url = new URL(`${base}${path}`, window.location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

function errorMessage(error) {
  const detail = error.response?.data?.detail
  if (Array.isArray(detail)) {
    const item = detail[0] || {}
    const label = { baseUrl: '接口地址', apiKey: 'API Key', model: '模型名称', username: '用户名', password: '密码' }[item.loc?.at(-1)] || '必填信息'
    return item.type === 'missing' ? `请填写${label}` : `${label}格式不符合要求，请检查后重试`
  }
  if (typeof detail === 'string' && /[\u4e00-\u9fff]/.test(detail)) return detail
  if (error.code === 'ERR_NETWORK') return '无法连接本地后端，请确认 FastAPI 已启动'
  if (error.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  return { 401: '登录已过期，请重新登录', 403: '没有权限执行此操作', 404: '接口不存在，请检查后端地址', 422: '提交信息不完整或格式不正确', 429: '请求过于频繁，请稍后重试' }[error.response?.status] || '请求失败，请检查配置后重试'
}

export async function apiRequest(method, path, data, { retry = true, timeout, responseType } = {}) {
  try {
    const response = await http.request({
      method, url: path, data, timeout, responseType,
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {}
    })
    return response.data
  } catch (error) {
    if (retry && error.response?.status === 401 && !path.startsWith('/auth/')) {
      try {
        await refreshAccess()
        return apiRequest(method, path, data, { retry: false, timeout, responseType })
      } catch {
        setAccessToken(null)
        window.dispatchEvent(new Event('mindpilot:auth-expired'))
      }
    }
    const failure = new Error(errorMessage(error))
    failure.status = error.response?.status
    throw failure
  }
}

/** Fetch is used here because Axios buffers the whole response before returning it. */
export async function apiStream(path, data, signal, retry = true) {
  const base = http.defaults.baseURL.replace(/\/$/, '')
  const response = await fetch(`${base}${path}`, {
    method: 'POST',
    credentials: 'include',
    signal,
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {})
    },
    body: JSON.stringify(data)
  })
  if (response.status === 401 && retry) {
    await refreshAccess()
    return apiStream(path, data, signal, false)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : '语音合成请求失败')
  }
  return response
}

export async function apiJsonLines(path, data, signal, onEvent, retry = true, label = '语音对话') {
  const base = http.defaults.baseURL.replace(/\/$/, '')
  const response = await fetch(`${base}${path}`, {
    method: 'POST', credentials: 'include', signal,
    headers: {
      'Content-Type': 'application/json',
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {})
    },
    body: JSON.stringify(data)
  })
  if (response.status === 401 && retry) {
    await refreshAccess()
    return apiJsonLines(path, data, signal, onEvent, false, label)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const failure = new Error(typeof body.detail === 'string' ? body.detail : `${label}请求失败`)
    failure.status = response.status
    throw failure
  }
  if (!response.body) throw new Error(`浏览器不支持流式${label}`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.trim()) continue
        const event = JSON.parse(line)
        await onEvent(event)
        if (event.type === 'done') completed = true
        if (event.type === 'error') throw new Error(event.message || `${label}失败`)
      }
      if (done) break
    }
    if (!completed) throw new Error(`${label}连接意外中断`)
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

export async function refreshAccess() {
  if (!refreshing) {
    refreshing = http.post('/auth/refresh').then(({ data }) => {
      setAccessToken(data.accessToken)
      return data
    }).finally(() => { refreshing = null })
  }
  return refreshing
}
