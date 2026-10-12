/**
 * AI 管家机械音效：全部用 Web Audio 振荡器现场合成，不依赖任何音频文件。
 * 所有函数都是「能放就放、放不了就静默」——没有 AudioContext、被自动播放
 * 策略拦截或合成抛错时，都只是不发声音，绝不影响界面流程。
 */

let ctx = null

function audio() {
  if (typeof window === 'undefined') return null
  const AC = window.AudioContext || window.webkitAudioContext
  if (!AC) return null
  if (!ctx) {
    try {
      ctx = new AC()
    } catch {
      return null
    }
  }
  if (ctx.state === 'suspended') {
    const pending = ctx.resume()
    if (pending && pending.catch) pending.catch(() => {})
  }
  return ctx
}

/**
 * 一个音：振荡器经过低通滤波器与包络送到输出，可加一段回声拖尾。
 * @param {Object} opts
 *   type 波形（sine/triangle/sawtooth/square）
 *   from/to 起始/结束频率（Hz），相同时为固定音高
 *   duration 时长（秒）
 *   volume 峰值音量 0~1
 *   attack/release 起音/释音时长
 *   delay 起始延迟（秒）
 *   filter { from, to } 低通滤波扫频
 *   echo 回声延迟时间（秒），0 表示不加回声
 */
function note({ type = 'sine', from = 440, to = 440, duration = 0.2, volume = 0.1, attack = 0.01, release = 0.18, delay = 0, filter = null, echo = 0 }) {
  const c = audio()
  if (!c) return
  try {
    const t0 = c.currentTime + delay
    const osc = c.createOscillator()
    const gain = c.createGain()
    const lowpass = c.createBiquadFilter()

    osc.type = type
    if (from === to) osc.frequency.setValueAtTime(from, t0)
    else osc.frequency.exponentialRampToValueAtTime(Math.max(20, to), t0 + duration)

    lowpass.type = 'lowpass'
    lowpass.Q.value = 6
    if (filter) {
      lowpass.frequency.setValueAtTime(Math.max(20, filter.from), t0)
      lowpass.frequency.exponentialRampToValueAtTime(Math.max(20, filter.to), t0 + duration)
    } else {
      lowpass.frequency.value = 12000
    }

    gain.gain.setValueAtTime(0.0001, t0)
    gain.gain.exponentialRampToValueAtTime(Math.max(0.0001, volume), t0 + attack)
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration + release)

    osc.connect(lowpass)
    lowpass.connect(gain)
    gain.connect(c.destination)

    if (echo) {
      const delayNode = c.createDelay(0.6)
      delayNode.delayTime.value = echo
      const wet = c.createGain()
      wet.gain.value = 0.26
      gain.connect(delayNode)
      delayNode.connect(wet)
      wet.connect(c.destination)
    }

    osc.start(t0)
    osc.stop(t0 + duration + release + 0.08)
  } catch {
    // 静默降级
  }
}

/** 进入虚拟助手：一段「凝聚成形」的上升扫频，叠几个高频星点。 */
export function playMorphIn() {
  note({ type: 'sawtooth', from: 90, to: 1500, duration: 0.9, volume: 0.11, release: 0.3, filter: { from: 220, to: 6800 } })
  note({ type: 'sine', from: 320, to: 640, duration: 0.5, volume: 0.06, delay: 0.12, echo: 0.2 })
  note({ type: 'sine', from: 880, to: 1760, duration: 0.4, volume: 0.05, delay: 0.28, echo: 0.24 })
  note({ type: 'sine', from: 1560, to: 2340, duration: 0.32, volume: 0.04, delay: 0.42 })
}

/** 退出虚拟助手：短促的双重电子继电器声，轻低频收尾。 */
export function playMechanicalShutdown() {
  note({ type: 'square', from: 760, duration: 0.025, volume: 0.035, attack: 0.002, release: 0.018, filter: { from: 2400, to: 2400 } })
  note({ type: 'square', from: 520, duration: 0.032, volume: 0.03, attack: 0.002, release: 0.02, delay: 0.075, filter: { from: 1900, to: 1900 } })
  note({ type: 'triangle', from: 155, duration: 0.065, volume: 0.055, attack: 0.006, release: 0.055, delay: 0.125, filter: { from: 520, to: 520 } })
}

/** 开始聆听：两声上扬的提示音。 */
export function playListenStart() {
  note({ type: 'sine', from: 520, to: 780, duration: 0.12, volume: 0.11, release: 0.1 })
  note({ type: 'sine', from: 1040, to: 1560, duration: 0.1, volume: 0.08, delay: 0.1, release: 0.08 })
}

/** 停止聆听：一声下沉的收尾。 */
export function playListenStop() {
  note({ type: 'sine', from: 780, to: 520, duration: 0.14, volume: 0.09, release: 0.12 })
}

/** 收到一句完整指令：轻轻「确认」一下。 */
export function playAck() {
  note({ type: 'triangle', from: 660, to: 660, duration: 0.1, volume: 0.07, release: 0.12 })
  note({ type: 'sine', from: 990, to: 1320, duration: 0.09, volume: 0.05, delay: 0.08, release: 0.1 })
}
