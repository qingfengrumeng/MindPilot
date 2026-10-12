<script setup>
import { Compass } from 'lucide-vue-next'

defineProps({ compact: Boolean, light: Boolean })
</script>

<template>
  <div class="app-logo" :class="{ compact, light }">
    <span class="logo-mark"><Compass :size="21" /></span>
    <span v-if="!compact" class="logo-copy">
      <strong>MindPilot</strong>
      <small>智能知识管家</small>
    </span>
  </div>
</template>
