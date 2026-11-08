import { defineConfig, devices } from '@playwright/test'
import { APP_URL, MODEL_URL } from './e2e/paths.mjs'

// End-to-end: the built app served by the real backend on 9480, talking to a
// scripted model server on 8081 (other ports: KOLONI_E2E_PORT, FAKE_MODEL_PORT).
// Run `npm run build` first.
export default defineConfig({
  testDir: 'e2e',
  workers: 1,
  timeout: 30_000,
  // A failed test keeps its trace, and a failed run is kept where the next run does not
  // clear it (e2e/keep-failures.mjs). No retries: a test that fails once is to be seen.
  // (The page key, slice 94: a spec's own calls carry it, e2e/fixtures.ts; a page opens from the link.)
  use: { baseURL: APP_URL, trace: 'retain-on-failure' },
  reporter: [[process.env.CI ? 'dot' : 'list'], ['./e2e/keep-failures.mjs']],
  // No real speakers: a sleeping wireless headset held audio and its 'ended' never came (32e).
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], launchOptions: { args: ['--disable-audio-output'] } } }],
  webServer: [
    {
      command: 'node e2e/fake-model.mjs',
      url: `${MODEL_URL}/v1/models`,
      reuseExistingServer: false,
    },
    {
      command: 'node e2e/start-backend.mjs',
      url: `${APP_URL}/api/health`,
      reuseExistingServer: false,
    },
  ],
})
