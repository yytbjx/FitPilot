import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    // api client / store 测试用 node 环境 + 手动 stub localStorage，
    // 避免引入 jsdom/happy-dom 重依赖
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
})
