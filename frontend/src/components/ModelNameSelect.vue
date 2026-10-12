<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, ChevronDown, Search } from 'lucide-vue-next'
import { matchesModelSearch } from '@/lib/modelSearch'

const props = defineProps({ id: String, modelValue: { type: String, default: '' }, options: { type: Array, default: () => [] }, optionLabels: {type:Object,default:()=>({})}, placeholder:{type:String,default:'模型名称'}, searchPlaceholder:{type:String,default:'输入名称筛选模型'}, listLabel:{type:String,default:'可用模型'}, wide:Boolean, disabled: Boolean })
const emit = defineEmits(['update:modelValue', 'open-change'])
const root = ref(null), input = ref(null), panel = ref(null), open = ref(false), query = ref(''), active = ref(-1), limit = ref(80), position = ref({})
const filtered = computed(() => props.options.filter(name => matchesModelSearch(`${name} ${props.optionLabels[name]||''}`, query.value)))
const visible = computed(() => filtered.value.slice(0, limit.value))
const hasOptions = computed(() => props.options.length > 0)
watch([hasOptions, () => props.disabled], () => { open.value = false })
watch(query, () => { active.value = -1; limit.value = 80 })
watch(open, value=>emit('open-change',value))
function place() {
  if (!open.value || !input.value) return
  const rect = input.value.getBoundingClientRect(), below = window.innerHeight - rect.bottom - 14, above = rect.top - 14
  const up = below < 180 && above > below
  const width = Math.min(rect.width, props.wide ? window.innerWidth : 620, window.innerWidth - 24)
  position.value = { width: `${width}px`, left: `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`, maxHeight: `${Math.max(120, Math.min(props.wide ? 440 : 330, up ? above : below))}px`, ...(up ? { bottom: `${window.innerHeight - rect.top + 6}px` } : { top: `${rect.bottom + 6}px` }) }
}
async function expand() {
  if (props.disabled || !hasOptions.value) return
  query.value = ''; active.value = -1; limit.value = 80; open.value = true
  await nextTick(); place()
}
function changed(event) {
  emit('update:modelValue', event.target.value)
  query.value = event.target.value; active.value = -1; limit.value = 80; open.value = hasOptions.value; place()
}
function choose(name) {
  input.value?.focus()
  emit('update:modelValue', name); open.value = false
}
async function keydown(event) {
  if (event.key === 'Escape' && open.value) { event.stopPropagation(); event.preventDefault(); open.value = false; return }
  if (event.key === 'Tab') { open.value = false; return }
  if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
    if (!hasOptions.value) return
    event.preventDefault()
    if (!open.value) await expand()
    const count = filtered.value.length
    if (!count) return
    active.value = (active.value + (event.key === 'ArrowDown' ? 1 : -1) + count) % count
    limit.value = Math.max(limit.value, active.value + 1)
    await nextTick(); panel.value?.querySelector(`[data-index="${active.value}"]`)?.scrollIntoView({ block: 'nearest' })
  } else if (event.key === 'Enter' && open.value) {
    event.preventDefault()
    if (active.value >= 0) choose(filtered.value[active.value]); else open.value = false
  }
}
function outside(event) { if (!root.value?.contains(event.target) && !panel.value?.contains(event.target)) open.value = false }
function scroll(event) {
  if (panel.value?.contains(event.target)) return
  place()
}
function more(event) { if (event.target.scrollHeight - event.target.scrollTop - event.target.clientHeight < 70) limit.value += 80 }
onMounted(() => { document.addEventListener('pointerdown', outside); window.addEventListener('resize', place); document.addEventListener('scroll', scroll, true) })
onBeforeUnmount(() => { document.removeEventListener('pointerdown', outside); window.removeEventListener('resize', place); document.removeEventListener('scroll', scroll, true) })
</script>

<template>
  <div ref="root" class="model-select">
    <input :id="id" ref="input" :value="modelValue" :placeholder="placeholder" autocomplete="off" :disabled="disabled" :role="hasOptions ? 'combobox' : undefined" :aria-autocomplete="hasOptions ? 'list' : undefined" :aria-expanded="hasOptions ? open : undefined" :aria-controls="hasOptions ? `${id}-options` : undefined" :aria-activedescendant="open && active >= 0 ? `${id}-option-${active}` : undefined" @input="changed" @focus="expand" @keydown="keydown" />
    <button v-if="hasOptions" type="button" :disabled="disabled" :aria-label="`展开${listLabel}`" :aria-expanded="open" @click="open ? open = false : expand()"><ChevronDown :size="17" /></button>
  </div>
  <Teleport to="body">
    <div v-if="open && hasOptions && !disabled" ref="panel" class="model-options-panel" :style="position">
      <header><Search :size="14" /><input v-model="query" type="search" :placeholder="searchPlaceholder" :aria-label="`搜索${listLabel}`" autocomplete="off" @keydown="keydown"/><small>{{ filtered.length }}个</small></header>
      <div :id="`${id}-options`" class="model-options-list" role="listbox" :aria-label="listLabel" @scroll="more">
        <template v-for="(name, index) in visible" :key="name"><slot name="option" :option-name="name" :index="index" :choose="choose" :selected="name===modelValue" :highlighted="index===active" :option-id="`${id}-option-${index}`"><button :id="`${id}-option-${index}`" type="button" role="option" :aria-selected="name === modelValue" :data-index="index" :class="{ selected: name === modelValue, highlighted: index === active }" tabindex="-1" @pointerdown.prevent @click="choose(name)"><span>{{ name }}<small v-if="optionLabels[name] && optionLabels[name]!==name" class="model-option-label">{{optionLabels[name]}}</small></span><Check v-if="name === modelValue" :size="16" /></button></slot></template>
        <p v-if="!filtered.length">没有匹配的选项，可手动填写。</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.model-select{position:relative;min-width:0}.model-select input{width:100%;height:43px;padding:10px 42px 10px 13px;border:1px solid #ddd6e5;border-radius:10px;background:#fff;color:#302738;font:inherit;font-size:13px;outline:none}.model-select input:focus{border-color:#a78bfa;box-shadow:0 0 0 2px #7c3aed0b}.model-select input::placeholder{color:#b1a6ba}.model-select>button{position:absolute;right:5px;top:5px;display:grid;place-items:center;width:33px;height:33px;border:0;border-radius:7px;background:transparent;color:#857b90;cursor:pointer}.model-select>button:hover{background:#f4effc;color:#7c3aed}.model-select :disabled{opacity:.55;cursor:default}.model-options-panel{position:fixed;z-index:3100;display:flex;flex-direction:column;overflow:hidden;border:1px solid #e4d9f7;border-radius:14px;background:#fff;box-shadow:0 10px 32px #27133620;font-family:var(--font-body);color:#302738}.model-options-panel header{display:flex;align-items:center;gap:7px;flex-shrink:0;padding:12px 14px;border-bottom:1px solid #f0ebf6;color:#9b8baa;font-size:11px}.model-options-panel header small{margin-left:auto;white-space:nowrap}.model-options-list{overflow:auto;min-height:0;padding:6px;scrollbar-width:thin;scrollbar-color:#d8cee6 transparent}.model-options-list button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;padding:11px 12px;border:0;border-radius:8px;background:#fff;color:#51455c;text-align:left;font:inherit;font-size:13px;cursor:pointer}.model-options-list button span{overflow-wrap:anywhere}.model-options-list button svg{flex-shrink:0}.model-options-list button:hover,.model-options-list button.highlighted{background:#faf7ff}.model-options-list button.selected{background:#f2ecff;color:#7c3aed}.model-options-list p{margin:8px;padding:12px;color:#a198aa;font-size:12px;line-height:1.7}
</style>

<style scoped>
.model-options-panel header input::-webkit-search-cancel-button{cursor:pointer}
.model-option-label{display:block;margin-top:4px;color:#9b8baa;font-size:12px}
.model-options-panel header input{flex:1;min-width:0;width:0;border:0;border-radius:6px;padding:5px 7px;background:transparent;color:#51455c;font:inherit;font-size:13px;outline:none}.model-options-panel header input::placeholder{color:#9b8baa}.model-options-panel header input:focus{background:#f7f2ff;box-shadow:0 0 0 2px #a78bfa40}
</style>
