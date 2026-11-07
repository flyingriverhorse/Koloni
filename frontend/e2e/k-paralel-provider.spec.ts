import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, openFreshConversation } from './helpers'
import { MODEL_URL } from './paths.mjs'

// K-paralel-saglayici: a provider's own limit holds its agents in every chat. At 1, the second reviewer of
// "have both files reviewed" waits in line, and its node says which provider is full and how full.
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'par-shots')

async function fakeModel(request: APIRequestContext) {
  const listed: { id: string; name: string; base_url: string | null }[] = await (await request.get('/api/providers')).json()
  const local = listed.find(p => p.base_url?.startsWith(MODEL_URL))
  expect(local).toBeTruthy()
  return local!
}

const limit = async (request: APIRequestContext, id: string, most: number | null) =>
  expect((await request.patch(`/api/providers/${id}`, { data: { max_running: most }, headers: OWN })).ok()).toBe(true)

// The backend is every spec's: its provider is left as it was, a test that timed out too (a hook still has its request).
test.afterEach(async ({ request }) => limit(request, (await fakeModel(request)).id, null))

for (const theme of ['light', 'dark'] as const) {
  test(`a provider full at one agent keeps the next in line, and its node says so (${theme})`, async ({ page, request }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    mkdirSync(SHOTS, { recursive: true })
    const local = await fakeModel(request)
    await limit(request, local.id, 1)
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    await page.getByLabel('Message').fill('have both files reviewed')
    await page.getByRole('button', { name: 'Send' }).click()

    const queued = page.locator('.react-flow__node-agent', { hasText: `queued · ${local.name} full (1/1)` })
    await expect(queued).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.react-flow__node-agent')).toHaveCount(3) // the Lead and both reviewers
    await queued.screenshot({ path: path.join(SHOTS, `queued-node-${theme}.png`) })
    await page.locator('.react-flow').screenshot({ path: path.join(SHOTS, `queued-canvas-${theme}.png`) })

    // Its place comes free when the first is done: both get done.
    await expect(chat.getByText('Both reviewers are done.')).toBeVisible({ timeout: 30_000 })
    await expect(queued).toHaveCount(0)
  })
}
