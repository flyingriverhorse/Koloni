import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, openFreshConversation } from './helpers'

// K-42d-sag: the top bar says how much of a plan's 5 hours is used. No CLI is run: the providers' commands do not
// exist, and their last readings are answered in the page.
const PLANS = [
  { name: 'Claude Code 42d', kind: 'claude_cli', used: 42 },
  { name: 'Codex 42d', kind: 'codex_cli', used: 8 },
]

/** No provider of this spec is left, and the triggers are not left paused: the specs after this one share the backend. */
async function clean(request: APIRequestContext) {
  await request.put('/api/triggers/paused', { headers: OWN, data: { paused: false } })
  for (const provider of await (await request.get('/api/providers')).json())
    if (PLANS.some(plan => plan.name === provider.name)) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.beforeEach(async ({ request }) => clean(request))
test.afterEach(async ({ request }) => clean(request))

test('at 700 px the top bar shows the plans used beside paused triggers and a turn, all on the screen, and opens Usage', async ({ page, request }) => {
  await page.setViewportSize({ width: 700, height: 800 })
  for (const plan of PLANS) {
    const made = await request.post('/api/providers', { headers: OWN, data: { name: plan.name, kind: plan.kind, executable: 'no-such-cli-for-42d' } })
    expect(made.ok()).toBe(true)
    const id = (await made.json()).id as string
    await page.route(
      url => url.pathname === `/api/providers/${id}/limits`,
      route =>
        route.fulfill({
          json: {
            unknown: null,
            read_at: new Date().toISOString(),
            source: null,
            plan: null,
            windows: [{ name: null, minutes: 300, used_percent: plan.used, resets_at: null, stale: false }],
            credits: null,
          },
        }),
    )
  }
  // The widest the rest of the right side gets: "Triggers paused" with its Resume, and a turn's state.
  await request.put('/api/triggers/paused', { headers: OWN, data: { paused: true } })

  await openFreshConversation(page)
  await page.getByLabel('Message').fill('say hello instead of hi')
  await page.getByRole('button', { name: 'Send' }).click()
  const bar = page.getByRole('banner')
  const use = bar.getByRole('button', { name: /^Plan use: .*Claude Code 42d 42% of 5 hours, Codex 42d 8% of 5 hours.*; open Usage$/ })
  await expect(use).toContainText('Claude Code 42d42%Codex 42d8%')
  const state = bar.locator('[data-run="waiting_approval"]')
  await expect(state).toBeVisible()
  // It fits: nothing on the right is pushed past the window's edge.
  for (const each of [use, bar.getByRole('button', { name: 'Resume' }), state, bar.getByRole('button', { name: 'Help' })]) {
    const at = (await each.boundingBox())!
    expect(at.x + at.width).toBeLessThanOrEqual(700)
  }

  // (The file is left as it was.)
  await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByText('Okay, I left hello.py unchanged.')).toBeVisible()

  await use.click()
  await expect(page.getByRole('region', { name: 'Plan limits' })).toContainText('Claude Code 42d')
})
