<script setup>
import { useUiStore } from '@/stores/ui'
import { CheckCircle2, CircleAlert, Info, TriangleAlert } from 'lucide-vue-next'
const ui = useUiStore()
const icons = { success: CheckCircle2, warning: TriangleAlert, error: CircleAlert, info: Info }
</script>
<template>
  <div class="toast-stack" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="item in ui.toasts" :key="item.id" class="toast" :class="item.type" :role="['error', 'warning'].includes(item.type) ? 'alert' : 'status'">
        <component :is="icons[item.type] || Info" :size="19" />{{ item.message }}
      </div>
    </TransitionGroup>
  </div>
</template>
