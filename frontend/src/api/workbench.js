import { apiRequest } from './http'

const queryString = params => new URLSearchParams(
  Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null)
).toString()

export const workbenchApi = {
  removeMany: ids => apiRequest('post', '/workbench/items/batch-delete', { ids }),
  syncHot: () => apiRequest('post', '/workbench/hot-sync'),
  hotSyncStatus: () => apiRequest('get', '/workbench/hot-sync'),
  hotPreferences: () => apiRequest('get', '/workbench/hot-preferences'),
  saveHotPreferences: payload => apiRequest('put', '/workbench/hot-preferences', payload),
  markViewed: id => apiRequest('post', `/workbench/items/${encodeURIComponent(id)}/viewed`),
  linkCandidates: () => apiRequest('get', '/workbench/link-candidates'),
  system: () => apiRequest('get', '/workbench/system'),
  items: (params = {}) => apiRequest('get', `/workbench/items?${queryString(params)}`),
  get: id => apiRequest('get', `/workbench/items/${encodeURIComponent(id)}`),
  create: payload => apiRequest('post', '/workbench/items', payload),
  update: (id, payload) => apiRequest('patch', `/workbench/items/${encodeURIComponent(id)}`, payload),
  remove: id => apiRequest('delete', `/workbench/items/${encodeURIComponent(id)}`)
}
