/** Fill each card's available preview space while keeping whole text lines. */
export function fitHotCardPreviews(grid) {
  let frame = 0, lastWidth = 0, stopped = false
  const update = () => {
    if (stopped) return
    cancelAnimationFrame(frame)
    frame = requestAnimationFrame(() => {
      if (stopped) return
      const cards = [...grid.querySelectorAll('.wb-hot-card')]
      // Defer writes outside ResizeObserver delivery, then measure a shared baseline.
      cards.forEach(card => card.style.removeProperty('--hot-preview-lines'))
      frame = requestAnimationFrame(() => {
        if (stopped) return
        const sizes = cards.map(card => {
          const text = card.querySelector(':scope > p'), footer = card.querySelector(':scope > footer')
          if (!text || !footer) return [card, 6]
          const lineHeight = Number.parseFloat(getComputedStyle(text).lineHeight)
          const available = footer.getBoundingClientRect().top - text.getBoundingClientRect().top
          return [card, Math.max(1, Math.floor((available + .5) / lineHeight))]
        })
        sizes.forEach(([card, lines]) => card.style.setProperty('--hot-preview-lines', lines))
      })
    })
  }
  const observer = new ResizeObserver(entries => {
    const width = entries[0]?.contentRect.width
    if (width !== lastWidth) { lastWidth = width; update() }
  })
  observer.observe(grid)
  document.fonts?.addEventListener('loadingdone', update)
  update()
  return () => { stopped = true; cancelAnimationFrame(frame); observer.disconnect(); document.fonts?.removeEventListener('loadingdone', update) }
}
