/** Decode a browser recording and encode 16 kHz mono PCM16 for Qwen ASR. */
export async function recordingToPcmBase64(blob) {
  const audioContext = new AudioContext()
  try {
    const decoded = await audioContext.decodeAudioData(await blob.arrayBuffer())
    if (decoded.duration < 0.1 || decoded.duration > 60) {
      throw new Error('录音时长需在 0.1 至 60 秒之间')
    }
    const frameCount = Math.min(16000 * 60, Math.floor(decoded.duration * 16000))
    const offline = new OfflineAudioContext(1, frameCount, 16000)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start()
    const resampled = await offline.startRendering()
    const samples = resampled.getChannelData(0)
    const bytes = new Uint8Array(samples.length * 2)
    const view = new DataView(bytes.buffer)
    for (let i = 0; i < samples.length; i++) {
      const sample = Math.max(-1, Math.min(1, samples[i]))
      view.setInt16(i * 2, sample < 0 ? sample * 32768 : sample * 32767, true)
    }
    let binary = ''
    for (let i = 0; i < bytes.length; i += 8192) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
    }
    return btoa(binary)
  } finally {
    await audioContext.close()
  }
}
