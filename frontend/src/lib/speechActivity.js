/** Require sustained microphone energy before accepting a transcription. */
export function createSpeechActivityDetector({ threshold = 0.018, minSpeechMs = 240 } = {}) {
  let activeMs = 0
  let detected = false

  return {
    observe(rms, durationMs) {
      if (detected) return true
      activeMs = rms >= threshold ? activeMs + durationMs : 0
      if (activeMs >= minSpeechMs) detected = true
      return detected
    },
    get detected() { return detected }
  }
}
