<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] },
  label: { type: String, default: '选择选项' },
})
const emit = defineEmits(['update:modelValue'])
const trigger = ref(null)
const panel = ref(null)
const open = ref(false)
const ready = ref(false)
const activeIndex = ref(0)
const position = ref({})
const listId = `map-select-${Math.random().toString(36).slice(2)}`
const selected = computed(() => props.options.find(option => option.id === props.modelValue) || props.options[0])

function place() {
  if (!open.value || !trigger.value || !panel.value) return
  const rect = trigger.value.getBoundingClientRect()
  const width = Math.max(rect.width, 230)
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))
  const height = panel.value.getBoundingClientRect().height
  const above = rect.top > window.innerHeight - rect.bottom && rect.top >= height + 8
  position.value = { top: `${above ? rect.top - height - 6 : rect.bottom + 6}px`, left: `${left}px`, width: `${width}px` }
  ready.value = true
}
async function expand() {
  open.value = true
  ready.value = false
  activeIndex.value = Math.max(0, props.options.findIndex(option => option.id === props.modelValue))
  await nextTick()
  place()
}
function close() { open.value = false; ready.value = false }
function choose(option) { emit('update:modelValue', option.id); close(); trigger.value?.focus() }
function onKeydown(event) {
  if (event.key === 'Escape') { close(); trigger.value?.focus(); return }
  if (event.key === 'Tab') { close(); return }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) { expand(); return }
    const step = event.key === 'ArrowDown' ? 1 : -1
    activeIndex.value = (activeIndex.value + step + props.options.length) % props.options.length
    panel.value?.querySelectorAll('[role="option"]')[activeIndex.value]?.focus()
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (open.value) choose(props.options[activeIndex.value])
    else expand()
  }
}
function onPointerDown(event) {
  if (open.value && !trigger.value?.contains(event.target) && !panel.value?.contains(event.target)) close()
}
function onScroll(event) {
  if (open.value && !panel.value?.contains(event.target)) place()
}
onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  window.addEventListener('resize', place)
  window.addEventListener('scroll', onScroll, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  window.removeEventListener('resize', place)
  window.removeEventListener('scroll', onScroll, true)
})
</script>

<template>
  <div class="map-select">
    <button ref="trigger" type="button" class="map-select-trigger" role="combobox" :aria-label="label"
      :aria-expanded="open" :aria-controls="listId" aria-haspopup="listbox" @click="open ? close() : expand()" @keydown="onKeydown">
      <span>{{ selected?.label || label }}</span><ChevronDown :size="16" :class="{ rotated: open }" />
    </button>
    <Teleport to="body">
      <div v-if="open" :id="listId" ref="panel" class="map-select-panel" role="listbox" :aria-label="label"
        :style="{ ...position, visibility: ready ? 'visible' : 'hidden' }" @keydown="onKeydown">
        <button v-for="(option, index) in options" :key="option.id" type="button" role="option"
          :aria-selected="option.id === modelValue" :class="{ active: index === activeIndex, chosen: option.id === modelValue }"
          @mouseenter="activeIndex = index" @click="choose(option)">
          <span><strong>{{ option.label }}</strong><small v-if="option.description">{{ option.description }}</small></span>
          <Check v-if="option.id === modelValue" :size="16" />
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.map-select{min-width:0;width:100%;height:43px}
.map-select-trigger{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;height:100%;padding:0 13px;border:1px solid #e5d9f1;border-radius:11px;background:#fff;color:#60427d;text-align:left;font:inherit;font-size:12px;font-weight:600;cursor:pointer;transition:border-color .15s,background .15s,box-shadow .15s}
.map-select-trigger:hover,.map-select-trigger[aria-expanded=true]{border-color:#b996ed;background:#faf7ff;color:#6528be;box-shadow:0 0 0 3px #a668ed14}
.map-select-trigger:focus-visible{outline:2px solid #8b5cf6;outline-offset:2px}
.map-select-trigger span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.map-select-trigger svg{flex:none;transition:transform .15s}.map-select-trigger svg.rotated{transform:rotate(180deg)}
.map-select-panel{position:fixed;z-index:240;max-height:min(330px,calc(100vh - 20px));overflow-y:auto;padding:5px;border:1px solid #e7dcf2;border-radius:12px;background:#fff;box-shadow:0 14px 36px #33204126,0 3px 8px #3320410d}
.map-select-panel button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;min-height:38px;padding:8px 10px;border:0;border-radius:8px;background:transparent;color:#48305e;text-align:left;font:inherit;cursor:pointer}
.map-select-panel button:hover,.map-select-panel button.active,.map-select-panel button:focus-visible{outline:0;background:#f4edff;color:#6124bb}
.map-select-panel button.chosen{color:#6d28d9}
.map-select-panel button>span{min-width:0}.map-select-panel strong{display:block;font-size:12px;font-weight:650}.map-select-panel small{display:block;margin-top:3px;color:#998aa9;font-size:11px;font-weight:400;line-height:1.35}.map-select-panel svg{flex:none}
</style>
