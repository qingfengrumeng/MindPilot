/** Feed MP3 response chunks to MediaSource as they arrive. */
export function createMp3Output(audio, signal) {
  const streaming = typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported('audio/mpeg')
  let objectUrl = null
  let mediaSource = null
  let sourceReady = null
  if (streaming) {
    mediaSource = new MediaSource()
    objectUrl = URL.createObjectURL(mediaSource)
    audio.src = objectUrl
    sourceReady = new Promise((resolve, reject) => {
      mediaSource.addEventListener('sourceopen', () => resolve(mediaSource.addSourceBuffer('audio/mpeg')), { once: true })
      signal.addEventListener('abort', () => reject(new DOMException('已取消', 'AbortError')), { once: true })
    })
    sourceReady.catch(() => {})
  }

  return {
    streaming,
    async consume(response, onFirstChunk = () => {}) {
      if (!response.body) throw new Error('浏览器不支持流式音频响应')
      const reader = response.body.getReader()
      const sourceBuffer = streaming ? await sourceReady : null
      const buffered = []
      let received = false
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        if (signal.aborted) throw new DOMException('已取消', 'AbortError')
        if (!value?.length) continue
        const first = !received
        received = true
        if (sourceBuffer) {
          await new Promise((resolve, reject) => {
            const done = () => {
              sourceBuffer.removeEventListener('error', failed)
              resolve()
            }
            const failed = () => {
              sourceBuffer.removeEventListener('updateend', done)
              reject(new Error('音频流播放失败'))
            }
            sourceBuffer.addEventListener('updateend', done, { once: true })
            sourceBuffer.addEventListener('error', failed, { once: true })
            sourceBuffer.appendBuffer(value)
          })
          if (first) onFirstChunk()
        } else buffered.push(value)
      }
      if (!received) throw new Error('语音合成没有返回音频')
      if (sourceBuffer) {
        if (mediaSource.readyState === 'open') mediaSource.endOfStream()
      } else if (!signal.aborted) {
        objectUrl = URL.createObjectURL(new Blob(buffered, { type: 'audio/mpeg' }))
        audio.src = objectUrl
        await audio.play()
      }
    },
    cleanup() {
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }
}
