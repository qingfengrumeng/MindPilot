import { getAccessToken, websocketUrl } from '@/api/http'
import { createSpeechActivityDetector } from './speechActivity.js'

/** Stream microphone PCM16 to the authenticated local ASR bridge. */
export async function startLiveAsr(onPartial = () => {}, onSpeechEnd = null, { silenceMs = 750, requireSpeech = false } = {}) {
  const token = await getAccessToken()
  const socket = new WebSocket(websocketUrl('/speech/live'))
  let readyResolve
  let readyReject
  let doneResolve
  let doneReject
  let finished = false
  let stopped = false
  let finalText = ''
  let stream = null
  let context = null
  let source = null
  let processor = null
  let sampleCount = 0
  let speechStarted = 0
  let lastVoice = 0
  let endNotified = false
  const speechActivity = createSpeechActivityDetector()
  const samples = new Float32Array(1600)
  const ready = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject })
  const done = new Promise((resolve, reject) => { doneResolve = resolve; doneReject = reject })
  const readyTimeout = setTimeout(() => fail('实时语音连接超时：请确认前端开发服务器已重启，且 /api WebSocket 代理可用'), 15000)
  // The stop promise may be rejected during setup, before anyone awaits it.
  done.catch(() => {})

  function cleanupMicrophone() {
    processor?.disconnect()
    source?.disconnect()
    stream?.getTracks().forEach(track => track.stop())
    context?.close().catch(() => {})
    processor = null
    source = null
    stream = null
    context = null
  }

  function fail(message) {
    if (finished) return
    finished = true
    const error = new Error(message)
    readyReject(error)
    doneReject(error)
    cleanupMicrophone()
    socket.close()
  }

  function sendSamples(count) {
    if (!count || socket.readyState !== WebSocket.OPEN) return
    const bytes = new ArrayBuffer(count * 2)
    const view = new DataView(bytes)
    for (let i = 0; i < count; i++) {
      const value = Math.max(-1, Math.min(1, samples[i]))
      view.setInt16(i * 2, value < 0 ? value * 32768 : value * 32767, true)
    }
    socket.send(bytes)
  }

  socket.onopen = () => socket.send(JSON.stringify({ type: 'start', token }))
  socket.onerror = () => fail('实时语音识别连接失败，请检查后端与 ASR 配置')
  socket.onclose = () => { if (!finished) fail('实时语音识别连接已断开') }
  socket.onmessage = event => {
    let message
    try { message = JSON.parse(event.data) } catch { return }
    if (message.type === 'ready') readyResolve()
    else if (message.type === 'partial') {
      if (!requireSpeech || speechActivity.detected) onPartial(finalText + (message.text || ''))
    }
    else if (message.type === 'final') {
      if (!requireSpeech || speechActivity.detected) {
        finalText += message.text || ''
        onPartial(finalText)
      }
    } else if (message.type === 'done') {
      finished = true
      doneResolve(finalText.trim())
      socket.close()
    } else if (message.type === 'error') fail(message.message || '实时语音识别失败')
  }

  try {
    await ready
    clearTimeout(readyTimeout)
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    context = new AudioContext({ sampleRate: 16000 })
    if (context.sampleRate !== 16000) throw new Error('当前浏览器不支持 16 kHz 实时录音')
    source = context.createMediaStreamSource(stream)
    processor = context.createScriptProcessor(2048, 1, 1)
    processor.onaudioprocess = event => {
      const input = event.inputBuffer.getChannelData(0)
      if ((onSpeechEnd || requireSpeech) && !stopped) {
        let energy = 0
        for (let i = 0; i < input.length; i++) energy += input[i] * input[i]
        const level = Math.sqrt(energy / input.length)
        if (requireSpeech) speechActivity.observe(level, input.length / context.sampleRate * 1000)
        const current = performance.now()
        if (onSpeechEnd && !endNotified) {
          if (level > 0.018) {
            if (!speechStarted) speechStarted = current
            lastVoice = current
          } else if (speechStarted && current - speechStarted > 320 && current - lastVoice > silenceMs) {
            endNotified = true
            queueMicrotask(onSpeechEnd)
          }
        }
      }
      for (let i = 0; i < input.length; i++) {
        samples[sampleCount++] = input[i]
        if (sampleCount === samples.length) {
          sendSamples(sampleCount)
          sampleCount = 0
        }
      }
    }
    source.connect(processor)
    processor.connect(context.destination)
    await context.resume()
  } catch (error) {
    clearTimeout(readyTimeout)
    fail(error?.message || '无法启动实时语音识别')
    throw error
  }

  return {
    async stop() {
      if (requireSpeech && !speechActivity.detected) {
        this.cancel()
        return ''
      }
      if (!stopped) {
        stopped = true
        cleanupMicrophone()
        sendSamples(sampleCount)
        sampleCount = 0
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'stop' }))
      }
      const timeout = setTimeout(() => fail('等待语音识别结果超时'), 35000)
      try { return await done } finally { clearTimeout(timeout) }
    },
    cancel() {
      cleanupMicrophone()
      finished = true
      doneResolve('')
      socket.close()
    }
  }
}
