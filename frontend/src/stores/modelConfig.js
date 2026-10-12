import { defineStore } from 'pinia'
import { ref } from 'vue'
import { configApi } from '@/api'

export const useModelConfigStore = defineStore('model-config', () => {
  const items = ref([])
  const saved = ref(true)
  const testing = ref(false)
  async function load() {
    const result = await configApi.get()
    items.value = result.items || []
  }
  return { items, saved, testing, load }
})
