<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { Check, Copy } from 'lucide-vue-next'
import { highlightCode, normalizeCodeLanguage } from '@/lib/codeHighlight'

const props = defineProps({ code: { type: String, default: '' }, language: { type: String, default: '' } })
const languageLabel = computed(() => normalizeCodeLanguage(props.language))
const highlighted = computed(() => highlightCode(props.code, props.language))
const copyState = ref('idle')
let resetTimer

async function copyCode() {
  clearTimeout(resetTimer)
  try {
    await navigator.clipboard.writeText(props.code)
    copyState.value = 'copied'
  } catch {
    copyState.value = 'error'
  }
  resetTimer = setTimeout(() => { copyState.value = 'idle' }, 2400)
}

onBeforeUnmount(() => clearTimeout(resetTimer))
</script>

<template>
  <section class="message-code-block" :aria-label="`${languageLabel} 代码`">
    <header class="message-code-header">
      <span class="message-code-language">{{ languageLabel }}</span>
      <span class="message-code-copy-wrap" :class="{ 'show-feedback': copyState !== 'idle' }">
        <button type="button" class="message-code-copy" :class="{ copied: copyState === 'copied' }"
          :aria-label="copyState === 'copied' ? '代码复制成功' : '复制代码'" @click="copyCode">
          <Check v-if="copyState === 'copied'" :size="17" />
          <Copy v-else :size="17" />
        </button>
        <span class="message-code-tooltip" role="status">
          {{ copyState === 'copied' ? '代码复制成功' : copyState === 'error' ? '复制失败，请重试' : '复制代码' }}
        </span>
      </span>
    </header>
    <pre><code v-html="highlighted" /></pre>
  </section>
</template>
