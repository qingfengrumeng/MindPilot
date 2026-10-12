// The host owns authentication and conversation execution. No credentials enter the iframe.
(() => {
  const requestId = crypto.randomUUID()
  window.addEventListener('message', function bootstrap(event) {
    if (event.source !== parent || event.origin !== location.origin || event.data?.source !== 'dsh-synapse' || event.data.type !== 'synapse:bootstrap-result' || event.data.requestId !== requestId) return
    window.removeEventListener('message', bootstrap)
    const owner = String(event.data.owner)
    const saved = event.data.state || {}
    const get = Storage.prototype.getItem, set = Storage.prototype.setItem, remove = Storage.prototype.removeItem
    const prefix = `mindpilot:${owner}:`
    for (const key of ['card-positions', 'card-positions:v2', 'card-positions:v3', 'card-positions:v4', 'collapsed-cards:v1', 'quick-phrases:v1', 'branch-anchors', 'canvas-actions:v1']) {
      if (!Object.hasOwn(saved, `dsh-synapse:${key}`)) remove.call(localStorage, `${prefix}dsh-synapse:${key}`)
    }
    for (const [key, value] of Object.entries(saved)) if (key.startsWith('dsh-synapse:') && typeof value === 'string') set.call(localStorage, prefix + key, value)
    Storage.prototype.getItem = function(key) { return get.call(this, this === localStorage && key.startsWith('dsh-synapse:') ? prefix + key : key) }
    Storage.prototype.setItem = function(key, value) {
      if (this === localStorage && key.startsWith('dsh-synapse:')) {
        set.call(this, prefix + key, value)
        parent.postMessage({ source: 'dsh-synapse', type: 'synapse:persist', key, value: String(value) }, location.origin)
      } else set.call(this, key, value)
    }
    Storage.prototype.removeItem = function(key) {
      if (this === localStorage && key.startsWith('dsh-synapse:')) {
        remove.call(this, prefix + key)
        parent.postMessage({ source: 'dsh-synapse', type: 'synapse:persist', key, value: null }, location.origin)
      } else remove.call(this, key)
    }
    const script = document.createElement('script')
    script.src = './app.js'
    document.body.append(script)
  })
  parent.postMessage({ source: 'dsh-synapse', type: 'synapse:bootstrap', requestId }, location.origin)
})()
