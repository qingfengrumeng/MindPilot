import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { createReadStream } from 'node:fs'
import { copyFile, cp, stat } from 'node:fs/promises'
import { extname, resolve, sep } from 'node:path'

const drawioRoot = resolve(fileURLToPath(new URL('./vendor/drawio/src/main/webapp/', import.meta.url)))
const drawioTypes = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.xml': 'application/xml', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.gif': 'image/gif', '.ico': 'image/x-icon', '.webp': 'image/webp',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf',
  '.eot': 'application/vnd.ms-fontobject', '.wasm': 'application/wasm',
  '.txt': 'text/plain', '.map': 'application/json'
}

function localDrawio() {
  let outDir
  return {
    name: 'mindpilot-local-drawio',
    configResolved(config) { outDir = resolve(config.root, config.build.outDir) },
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        let pathname
        try { pathname = decodeURIComponent(new URL(req.url || '/', 'http://localhost').pathname) }
        catch { return next() }
        if (!pathname.startsWith('/drawio/')) return next()
        const relative = pathname.slice('/drawio/'.length) || 'index.html'
        const file = resolve(drawioRoot, relative)
        if (!file.startsWith(drawioRoot + sep)) return next()
        try {
          if (!(await stat(file)).isFile()) return next()
          const type = drawioTypes[extname(file).toLowerCase()] || 'application/octet-stream'
          res.setHeader('Content-Type', type.startsWith('text/') || type === 'application/json' || type === 'application/xml' ? `${type}; charset=utf-8` : type)
          createReadStream(file).pipe(res)
        } catch { next() }
      })
    },
    async writeBundle() {
      await cp(drawioRoot, resolve(outDir, 'drawio'), { recursive: true })
      await copyFile(resolve(drawioRoot, '../../../LICENSE'), resolve(outDir, 'drawio/LICENSE'))
    }
  }
}

export default defineConfig(({ mode }) => ({
  base: mode === 'desktop' ? './' : '/',
  plugins: [vue(), localDrawio()],
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, ws: true } } },
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } }
}))
