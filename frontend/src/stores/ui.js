import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const useUiStore = defineStore('ui', () => {
  const toasts = ref([])
  const conversationMapReturnPath = ref('/')
  const sidebarCollapsed = ref(false)
  try { sidebarCollapsed.value = localStorage.getItem('mindpilot-sidebar-collapsed') === 'true' } catch {}
  watch(sidebarCollapsed, value => {
    try { localStorage.setItem('mindpilot-sidebar-collapsed', String(value)) } catch {}
  })

  function toast(message, type = 'success') {
    const id = Date.now() + Math.random()
    toasts.value.push({ id, message, type })
    setTimeout(() => { toasts.value = toasts.value.filter(item => item.id !== id) }, 2800)
  }

  return { toasts, toast, conversationMapReturnPath, sidebarCollapsed }
})
