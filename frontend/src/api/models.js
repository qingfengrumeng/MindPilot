import { apiJsonLines, apiRequest } from './http'

export const modelsApi = {
  list: () => apiRequest('get', '/model-configs'),
  save: (id, payload) => apiRequest('put', `/model-configs/${encodeURIComponent(id)}`, payload),
  add: payload => apiRequest('post', '/model-configs', payload),
  activate: (category, providerId) => apiRequest('put', `/model-configs/active/${category}`, { providerId }),
  fetchModels: (id, category) => apiRequest('get', `/model-configs/${encodeURIComponent(id)}/models/${category}`),
  discover: (id, category, payload) => apiRequest('post', `/model-configs/${encodeURIComponent(id)}/models/${category}`, payload, { timeout: 60000 }),
  voices: (id, model) => apiRequest('post', `/model-configs/${encodeURIComponent(id)}/voices/tts`, {model}, {timeout: 45000}),
  previewVoice: (id, payload, signal) => apiRequest('post', `/model-configs/${encodeURIComponent(id)}/voices/tts/preview`, payload, {responseType:'blob',timeout:60000,signal}),
  test: (id, category, payload) => apiRequest('post', `/model-configs/${encodeURIComponent(id)}/test/${category}`, payload, { timeout: 90000 }),
  compare: (payload, signal, onEvent) => apiJsonLines('/model-configs/compare', payload, signal, onEvent, true, '模型测试')
}
