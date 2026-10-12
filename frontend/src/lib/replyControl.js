// Keep the same response open while paused; never submit the question twice.
export function createReplyControl() {
  const controller = new AbortController()
  let paused = false
  let release = null
  return {
    controller,
    pause() { paused = true },
    resume() { paused = false; release?.(); release = null },
    cancel() { controller.abort(); this.resume() },
    async wait() {
      if (controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError')
      if (paused) await new Promise(resolve => { release = resolve })
      if (controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError')
    }
  }
}
