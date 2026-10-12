<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, onUpdated, ref, useAttrs, useId, watch } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'
defineOptions({ inheritAttrs: false })
const props = defineProps({ modelValue: { default: undefined }, value: { default: undefined }, disabled: Boolean, multiple: Boolean, size: [String, Number], placeholder: { default: '请选择' }, modelModifiers: Object })
const emit = defineEmits(['update:modelValue', 'change'])
const attrs = useAttrs(), root = ref(null), native = ref(null), menu = ref(null), open = ref(false), options = ref([]), active = ref(0), position = ref({})
const menuId = 'select-' + useId()
const current = computed(() => props.modelValue !== undefined ? props.modelValue : props.value)
const selected = option => props.multiple ? (current.value || []).some(value => String(value) === String(option.value)) : String(current.value ?? '') === String(option.value)
const caption = computed(() => options.value.filter(selected).map(option => option.label).join('、') || props.placeholder)
const triggerAttrs = computed(() => Object.fromEntries(Object.entries(attrs).filter(([key]) => !['class', 'style'].includes(key))))
let observer, searchText = '', searchTimer
function refresh() {
  const values = [...(native.value?.options || [])].map(option => ({ value: option._value ?? option.value, label: option.textContent.trim(), disabled: option.disabled || option.parentElement?.disabled === true }))
  if (JSON.stringify(values) !== JSON.stringify(options.value)) options.value = values
}
function close(restore = false) { open.value = false; if (restore) root.value?.querySelector('button')?.focus() }
function outside(event) { if (!root.value?.contains(event.target) && !menu.value?.contains(event.target)) close() }
function place() {
  if (!open.value || !root.value) return
  const bounds = root.value.getBoundingClientRect(), width = Math.min(Math.max(bounds.width, 180), window.innerWidth - 24)
  const availableBelow = window.innerHeight - bounds.bottom - 16, availableAbove = bounds.top - 16
  const above = availableBelow < 180 && availableAbove > availableBelow
  const maxHeight = Math.max(60, Math.min(280, above ? availableAbove : availableBelow))
  const height = Math.min(maxHeight, options.value.length * 42 + 12)
  position.value = { width: width+'px', left: Math.max(12, Math.min(bounds.left, window.innerWidth-width-12))+'px', top: (above ? Math.max(8,bounds.top-height-7) : bounds.bottom+7)+'px', maxHeight:maxHeight+'px' }
}
async function show() {
  if (props.disabled) return
  refresh(); if (!options.value.length) return
  open.value = true; active.value = Math.max(0, options.value.findIndex(option => selected(option) && !option.disabled)); place()
  await nextTick(); menu.value?.focus(); scrollActive()
}
function scrollActive() { nextTick(() => menu.value?.querySelector(`[data-index="${active.value}"]`)?.scrollIntoView({block:'nearest'})) }
function choose(option) {
  if (option.disabled || props.disabled) return
  let value = option.value
  if (props.multiple) value = selected(option) ? (current.value || []).filter(item => String(item) !== String(option.value)) : [...(current.value || []), option.value]
  emit('update:modelValue', value)
  emit('change', { target: { value: props.multiple ? value : String(value ?? '') }, currentTarget: native.value })
  if (!props.multiple) close(true)
}
function keydown(event) {
  const key = event.key
  if (key === 'Escape' || key === 'Tab') { event.preventDefault(); event.stopPropagation(); close(true); return }
  if (['ArrowDown','ArrowUp','Home','End'].includes(key)) {
    event.preventDefault()
    const enabled = options.value.map((option,index) => !option.disabled ? index : -1).filter(index => index >= 0)
    if (!enabled.length) return
    const index = enabled.indexOf(active.value)
    active.value = key==='Home' ? enabled[0] : key==='End' ? enabled.at(-1) : enabled[(index+(key==='ArrowDown'?1:-1)+enabled.length)%enabled.length]
    scrollActive()
  } else if (key === 'Enter' || key === ' ') { event.preventDefault(); if(options.value[active.value]) choose(options.value[active.value]) }
  else if (key.length === 1 && !event.ctrlKey && !event.metaKey) {
    searchText += key.toLocaleLowerCase(); clearTimeout(searchTimer); searchTimer=setTimeout(()=>{searchText=''},600)
    const index=options.value.findIndex(option=>!option.disabled&&option.label.toLocaleLowerCase().startsWith(searchText));if(index>=0){active.value=index;scrollActive()}
  }
}
watch(() => props.disabled, value => {if(value) close()})
onMounted(() => { refresh(); observer=new MutationObserver(refresh); observer.observe(native.value,{childList:true,subtree:true,characterData:true,attributes:true}); window.addEventListener('pointerdown',outside);window.addEventListener('resize',place);window.addEventListener('scroll',place,true) })
onUpdated(refresh)
onBeforeUnmount(() => { observer?.disconnect();clearTimeout(searchTimer);window.removeEventListener('pointerdown',outside);window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true) })
</script>
<template>
  <span ref="root" class="app-select" :class="[attrs.class,{'is-open':open,'is-disabled':disabled}]" :style="attrs.style">
    <select ref="native" class="app-select-native" :value="current" :multiple="multiple" :disabled="disabled" tabindex="-1" aria-hidden="true"><slot /></select>
    <button v-bind="triggerAttrs" type="button" class="app-select-trigger" :disabled="disabled" aria-haspopup="listbox" :aria-expanded="open" :aria-controls="open ? menuId : undefined" @click="open ? close() : show()" @keydown.down.prevent="show" @keydown.up.prevent="show"><span>{{ caption }}</span><ChevronDown :size="16" /></button>
    <Teleport to="body"><div v-if="open" :id="menuId" ref="menu" class="app-select-menu" :style="position" role="listbox" :aria-label="attrs['aria-label'] || '选择选项'" :aria-activedescendant="menuId+'-'+active" :aria-multiselectable="multiple || undefined" tabindex="-1" @keydown="keydown"><button v-for="(option,index) in options" :id="menuId+'-'+index" :key="index" type="button" role="option" tabindex="-1" :data-index="index" :aria-selected="selected(option)" :disabled="option.disabled" :class="{'is-selected':selected(option),'is-active':active===index}" @pointermove="active=index" @click="choose(option)"><span>{{ option.label }}</span><Check v-if="selected(option)" :size="16" /></button></div></Teleport>
  </span>
</template>
<style>
.app-select{width:100%;display:inline-flex;position:relative;min-width:0;vertical-align:middle;max-width:100%}.app-select-native{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;border:0!important;opacity:0!important;pointer-events:none!important;overflow:hidden!important}.app-select .app-select-trigger{box-sizing:border-box;width:100%;display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:42px;margin:0;padding:11px 14px;border:1px solid #e4dcef;border-radius:12px;color:#604774;background:#fff;font:inherit;font-size:13px;text-align:left;cursor:pointer;transition:border-color .15s,box-shadow .15s}.app-select-trigger>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}.app-select-trigger>svg{flex-shrink:0;transition:transform .15s;color:#9c86ac}.app-select.is-open .app-select-trigger,.app-select .app-select-trigger:focus-visible{border-color:#a78bfa;box-shadow:0 0 0 3px #a78bfa18;outline:none}.app-select.is-open .app-select-trigger>svg{transform:rotate(180deg)}.app-select .app-select-trigger:hover{border-color:#bfa6e3;background:#fcfaff}.app-select.is-disabled .app-select-trigger{opacity:.5;cursor:default}.app-select-menu{box-sizing:border-box;position:fixed;z-index:1000;overflow:auto;padding:6px;border:1px solid #e7dcf3;border-radius:14px;background:#fff;box-shadow:0 12px 36px #40225322;color:#604774;outline:none;scrollbar-width:thin;scrollbar-color:#d4c5e6 transparent}.app-select-menu>button{box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:14px;width:100%;min-height:42px;padding:10px 12px;border:0;border-radius:9px;background:transparent;color:inherit;font:inherit;font-size:13px;text-align:left;cursor:pointer}.app-select-menu>button>span{flex:1;overflow-wrap:anywhere}.app-select-menu>button>svg{flex-shrink:0}.app-select-menu>button.is-active,.app-select-menu>button:hover{background:#f7f2fd}.app-select-menu>button.is-selected{background:#f0e8ff;color:#7c3aed;font-weight:500}.app-select-menu>button:disabled{opacity:.45;cursor:default}.app-select-menu>button:focus-visible{outline:2px solid #a78bfa;outline-offset:-2px}.wb-toolbar>.app-select{width:auto;min-width:130px}.wb-editor-fields label>.app-select,.profile-preferences label>.app-select,.rag-row label>.app-select,.rag-generation-grid label>.app-select{width:100%}
</style>
