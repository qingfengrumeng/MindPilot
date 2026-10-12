import { apiJsonLines, apiRequest } from './http'
const path = '/model-evaluations/rag'
export const evaluationsApi = {
  sample:()=>apiRequest('get',`${path}/samples/golden-dataset`),
  editDocument:(id,document,revision,value)=>apiRequest('put',`${path}/${id}/documents/${document}`,{...value,revision}),
  create: () => apiRequest('post', path),
  get: id => apiRequest('get', `${path}/${id}`),
  clear: id => apiRequest('delete', `${path}/${id}`),
  import: (id, revision, dataset) => apiRequest('post', `${path}/${id}/import`, { ...dataset, revision }),
  upload(id, file) { const form = new FormData(); form.append('file', file); return apiRequest('post', `${path}/${id}/documents`, form, { timeout: 90000 }) },
  removeDocument: (id, document) => apiRequest('delete', `${path}/${id}/documents/${document}`),
  gold: (id, revision, questions) => apiRequest('put', `${path}/${id}/gold`, { revision, questions }),
  run: (id, payload, signal, onEvent) => apiJsonLines(`${path}/${id}/run`, payload, signal, onEvent, true, 'RAG 评测'),
  rescore: (id, report) => apiRequest('post', `${path}/${id}/reports/${report}/rescore`)
}
export const evaluationReportsApi={
  save:value=>apiRequest('post','/model-evaluations/reports',value),
  list:()=>apiRequest('get','/model-evaluations/reports'),
  get:id=>apiRequest('get',`/model-evaluations/reports/${id}`),
  remove:id=>apiRequest('delete',`/model-evaluations/reports/${id}`)
}
