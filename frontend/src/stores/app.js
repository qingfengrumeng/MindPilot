import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { domainsApi } from '@/api'

/**
 * 全局静态数据：知识域、任务类型与工具池。
 * 这些内容在多个页面复用（资料、Wiki、授权、运行面板、账户设置），集中加载一次。
 */
export const useAppStore = defineStore('app', () => {
  const domains = ref([])
  const taskProfiles = ref([])
  const toolPools = ref([])
  const quickActions = ref([])
  const loaded = ref(false)
  let pending = null

  async function load() {
    if (loaded.value) return
    // 多个页面同时挂载时只发起一次加载。
    if (!pending) {
      pending = Promise.all([
        domainsApi.list(),
        domainsApi.taskProfiles(),
        domainsApi.quickActions()
      ]).then(([domainResult, profileResult, actionResult]) => {
        domains.value = domainResult.items
        taskProfiles.value = profileResult.items
        toolPools.value = profileResult.pools
        quickActions.value = actionResult.items
        loaded.value = true
      }).finally(() => {
        pending = null
      })
    }
    return pending
  }

  const domainMap = computed(() => Object.fromEntries(domains.value.map(item => [item.id, item])))

  function domain(id) {
    return domainMap.value[id] || null
  }

  function domainLabel(id) {
    return domainMap.value[id]?.label || '未分类'
  }

  function taskProfile(id) {
    return taskProfiles.value.find(item => item.id === id) || null
  }

  return {
    domains, taskProfiles, toolPools, quickActions, loaded,
    load, domain, domainLabel, taskProfile
  }
})
