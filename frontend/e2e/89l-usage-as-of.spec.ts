// 89l in the browser: the Usage page's Plan limits have one row per CLI, each with what it said, when it resets and
// the time of day it was read ("as of hh:mm"); one never read says so, never a number. Light and dark.
import os from 'node:os'
import path from 'node:path'
import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, openFreshConversation, rail } from './helpers'
import { FAKE_AGY, FAKE_CLAUDE } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const NAMES = ['Usage89 Claude', 'Usage89 agy', 'Usage89 Codex']
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'us-shots')

// The backend is shared: the providers made here are not left for whatever runs after.
async function remove(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if (NAMES.includes(provider.name)) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.beforeEach(async ({ request }) => {
  await remove(request)
  // As 25a's: stand-ins, and a Codex command that is not there (nothing is started for it).
  for (const [name, kind, executable] of [
    ['Usage89 Claude', 'claude_cli', FAKE_CLAUDE],
    ['Usage89 agy', 'agy_cli', FAKE_AGY],
    ['Usage89 Codex', 'codex_cli', 'no-such-codex-for-the-89l-test'],
  ])
    expect((await request.post('/api/providers', { headers: OWN, data: { name, kind, executable } })).ok()).toBeTruthy()
})

test.afterEach(async ({ request }) => {
  await remove(request)
})

for (const theme of ['light', 'dark'] as const)
  test(`each CLI's row says what it said and as of when, and what was never read says so, in the ${theme} theme`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await rail(page, 'Usage').click()
    const limits = page.getByRole('region', { name: 'Plan limits' })
    const rows = limits.getByRole('table', { name: 'Plan limits by provider' })
    await expect(rows.getByRole('row', { name: /^Usage89 Codex/ })).toContainText('not read yet — Check now')
    await expect(rows.getByRole('row', { name: /^Usage89 Claude/ })).toContainText('not known — not run yet')
    await limits.getByRole('button', { name: 'Check now' }).click()
    await expect(limits.getByRole('button', { name: 'Check now' })).toBeEnabled()
    // agy's /quota from its stand-in: the window, its use, when it resets, and the time of day it was read.
    const agy = rows.getByRole('row', { name: /^Usage89 agy/ })
    await expect(agy).toContainText('8% of Gemini Models this week used')
    await expect(agy).toContainText(/read just now \(as of \d{1,2}[:.]\d{2}/)
    // Nothing made up for the ones not read: no meter, no time.
    for (const name of ['Usage89 Claude', 'Usage89 Codex']) {
      const row = rows.getByRole('row', { name: new RegExp(`^${name}`) })
      await expect(row.getByRole('meter')).toHaveCount(0)
      await expect(row).not.toContainText('as of')
    }
    await expect.poll(() => page.evaluate(() => document.documentElement.classList.contains('dark'))).toBe(theme === 'dark')
    await limits.screenshot({ path: path.join(SHOTS, `89l-plan-limits-${theme}.png`) })
  })
