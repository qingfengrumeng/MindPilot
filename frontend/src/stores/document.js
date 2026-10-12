import { defineStore } from 'pinia'
import { ref } from 'vue'
import { documentsApi } from '@/api'

export const useDocumentStore = defineStore('document', () => {
  const items = ref([])
  const category = ref('全部文档')
  const uploading = ref(false)
  async function load() {
    const result = await documentsApi.list()
    items.value = result.items || []
  }
  return { items, category, uploading, load }
})
