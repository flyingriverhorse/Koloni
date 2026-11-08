/// <reference types="vitest/config" />
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// The API this page is built against, hashed as /api/health hashes its server's (app/api/health.py).
// Read once: restart the dev server after `npm run generate:api`.
const typed = readFileSync(new URL('src/api/generated.ts', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
const apiHash = createHash('sha256').update(typed).digest('hex').slice(0, 12)
// elkjs (EPL-2.0) is not shipped: it, and mermaid's ELK layout module that alone imports it, are a stub.
const noElk = fileURLToPath(new URL('./src/chat/no-elk.ts', import.meta.url))

export default defineConfig({
  plugins: [react()],
  define: { 'import.meta.env.VITE_API_HASH': JSON.stringify(apiHash) },
  resolve: {
    alias: [
      { find: /^elkjs(\/.*)?$/, replacement: noElk },
      { find: /^\.\/elk-\w+\.mjs$/, replacement: noElk },
    ],
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8790', '/guide': 'http://127.0.0.1:8790' } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
    // One module graph per worker, not per file (~3.5x faster): what a file stubs, it leaves behind for none.
    isolate: false,
    unstubGlobals: true,
    // (15 s on CI: measured for coverage there, a long RoleEditor test took 5.06 s of vitest's 5.)
    testTimeout: process.env.CI ? 15_000 : 5_000,
    // `vitest run --coverage` (PR Check, for SonarQube): LCOV with repository-relative paths, as Skyulf's.
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', ['lcovonly', { projectRoot: fileURLToPath(new URL('..', import.meta.url)) }]],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test-fixtures.ts', 'src/test-setup.ts', 'src/api/generated.ts'],
    },
  },
})
