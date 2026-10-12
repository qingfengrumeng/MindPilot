<script setup>
import { RouterView } from 'vue-router'
import ToastMessage from '@/components/ToastMessage.vue'
import AppTooltip from '@/components/AppTooltip.vue'
</script>

<template>
  <RouterView v-slot="{ Component }">
    <Transition name="page" mode="out-in"><component :is="Component" /></Transition>
  </RouterView>
  <ToastMessage />
  <AppTooltip />
</template>
