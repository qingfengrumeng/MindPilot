<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const open = ref(false)
const ready = ref(false)
const text = ref('')
const placement = ref('top')
const holographic = ref(false)
const workspaceTheme = ref(false)
const position = ref({ left: '0px', top: '0px' })
const tooltip = ref()

let activeTarget = null
let showTimer = null
let observer = null

function migrateTitles(root) {
  if (!(root instanceof Element) && root !== document) return
  const elements = root === document
    ? document.querySelectorAll('[title]')
    : [root, ...root.querySelectorAll('[title]')]

  elements.forEach(element => {
    const value = element.getAttribute('title')
    if (!value) return
    element.dataset.appTooltip = value
    if (!element.getAttribute('aria-label') && !element.textContent?.trim()) {
      element.setAttribute('aria-label', value)
    }
    element.removeAttribute('title')
  })
}

function tooltipText(target) {
  if (target?.dataset?.tooltipSuppressed === 'true') return ''
  return target?.dataset?.appTooltip || target?.dataset?.tooltip || ''
}

async function show(target) {
  const value = tooltipText(target)
  if (!value || target.hasAttribute('disabled')) return

  activeTarget = target
  holographic.value = Boolean(target.closest('.jarvis'))
  workspaceTheme.value = Boolean(target.closest('.workspace-shell, .conversation-menu-floating'))
  text.value = value
  open.value = true
  ready.value = false
  await nextTick()
  if (activeTarget !== target || !tooltip.value) return

  const monitorRailIcon = target.matches('.amp-rail-handle') ? target.querySelector('svg') : null
  const targetRect = (monitorRailIcon || target).getBoundingClientRect()
  const tooltipRect = tooltip.value.getBoundingClientRect()
  const sidePlacement = Boolean(target.closest('.workspace-nav, .workspace-conversation-panel') || target.dataset.tooltipSide === 'right')
  let left
  let top

  if (monitorRailIcon) {
    placement.value = 'left'
    left = targetRect.left - tooltipRect.width - 12
    top = targetRect.top + (targetRect.height - tooltipRect.height) / 2
  } else if (sidePlacement) {
    placement.value = 'right'
    left = targetRect.right + 12
    top = targetRect.top + (targetRect.height - tooltipRect.height) / 2
    if (left + tooltipRect.width > window.innerWidth - 10) {
      placement.value = 'left'
      left = targetRect.left - tooltipRect.width - 12
    }
  } else {
    placement.value = 'top'
    left = targetRect.left + (targetRect.width - tooltipRect.width) / 2
    top = targetRect.top - tooltipRect.height - 10
    if (top < 10) {
      placement.value = 'bottom'
      top = targetRect.bottom + 10
    }
  }

  left = Math.max(10, Math.min(left, window.innerWidth - tooltipRect.width - 10))
  top = Math.max(10, Math.min(top, window.innerHeight - tooltipRect.height - 10))
  position.value = { left: `${left}px`, top: `${top}px` }
  requestAnimationFrame(() => { ready.value = true })
}

function schedule(target) {
  if (target === activeTarget && open.value) return
  clearTimeout(showTimer)
  showTimer = setTimeout(() => show(target), 320)
}

function hide() {
  clearTimeout(showTimer)
  activeTarget = null
  ready.value = false
  open.value = false
}

function findTarget(event) {
  return event.target?.closest?.('[data-app-tooltip],[data-tooltip],[title]')
}

function onPointerOver(event) {
  const target = findTarget(event)
  if (!target) return
  migrateTitles(target)
  schedule(target)
}

function onPointerOut(event) {
  if (!activeTarget) {
    clearTimeout(showTimer)
    return
  }
  if (activeTarget.contains(event.relatedTarget)) return
  hide()
}

function onFocusIn(event) {
  const target = findTarget(event)
  if (!target) return
  migrateTitles(target)
  schedule(target)
}

function onFocusOut() {
  hide()
}

onMounted(() => {
  migrateTitles(document)
  observer = new MutationObserver(records => {
    records.forEach(record => {
      if (record.type === 'attributes') {
        migrateTitles(record.target)
        if (record.target === activeTarget && open.value) show(record.target)
      }
      record.addedNodes.forEach(node => migrateTitles(node))
    })
  })
  observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['title'] })
  document.addEventListener('mouseover', onPointerOver)
  document.addEventListener('mouseout', onPointerOut)
  document.addEventListener('pointerdown', hide)
  document.addEventListener('focusin', onFocusIn)
  document.addEventListener('focusout', onFocusOut)
  window.addEventListener('scroll', hide, true)
  window.addEventListener('resize', hide)
})

onBeforeUnmount(() => {
  observer?.disconnect()
  clearTimeout(showTimer)
  document.removeEventListener('mouseover', onPointerOver)
  document.removeEventListener('mouseout', onPointerOut)
  document.removeEventListener('pointerdown', hide)
  document.removeEventListener('focusin', onFocusIn)
  document.removeEventListener('focusout', onFocusOut)
  window.removeEventListener('scroll', hide, true)
  window.removeEventListener('resize', hide)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      ref="tooltip"
      class="app-tooltip"
      :class="[placement, { ready, holographic, workspace: workspaceTheme }]"
      :style="position"
      role="tooltip"
    >
      {{ text }}
    </div>
  </Teleport>
</template>
