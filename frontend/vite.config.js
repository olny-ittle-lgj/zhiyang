import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

const currentDirectory = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  plugins: [vue()],
  publicDir: resolve(currentDirectory, '../stitch_prd'),
  server: {
    port: 5173,
    proxy: { '/api': process.env.VITE_API_PROXY || 'http://127.0.0.1:8000' },
  },
})
