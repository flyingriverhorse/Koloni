import { expect, type APIRequestContext, test } from './fixtures'
import { contrasts, OWN, openFreshConversation, rail, shot } from './helpers'
import { FAKE_CLAUDE } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const NAME = 'Usage Claude'
const project = async (request: APIRequestContext) => (await (await request.get('/api/projects')).json())[0].id as string

// The backend is shared: the budget, price and provider made here are not left for whatever runs after.
async function putBack(request: APIRequestContext) {
  await request.patch(`/api/projects/${await project(request)}`, { headers: OWN, data: { monthly_budget: null } })
  await request.delete('/api/prices?model_id=fake-qwen', { headers: OWN })
  for (const provider of await (await request.get('/api/providers')).json())
    if (provider.name === NAME) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.afterEach(async ({ request }) => {
  await putBack(request)
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme the Usage page reads at a glance: boxes on top, plan limits and the budget side by side, the long tables folded`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await page.getByLabel('Message').fill(`hello from the ${theme} usage page`)
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByRole('region', { name: 'Chat' }).getByText('Hello! Ask me to read or change a file.')).toBeVisible()
    // A price, and a budget twice what is spent: the month's bar is half full.
    expect((await request.put('/api/prices', { headers: OWN, data: { model_id: 'fake-qwen', input: 1000, output: 2000, currency: 'USD' } })).ok()).toBe(true)
    const pid = await project(request)
    const { spent } = await (await request.get(`/api/projects/${pid}/budget`)).json()
    expect((await request.patch(`/api/projects/${pid}`, { headers: OWN, data: { monthly_budget: spent * 2 } })).ok()).toBe(true)
    // A Claude Code whose last run said 42% of its five hours: its reading is answered here, no CLI is run.
    const made = await request.post('/api/providers', { headers: OWN, data: { name: NAME, kind: 'claude_cli', executable: FAKE_CLAUDE } })
    expect(made.ok()).toBe(true)
    const { id } = await made.json()
    const resets = new Date(Date.now() + 3600_000).toISOString()
    await page.route(`**/api/providers/${id}/limits`, route =>
      route.fulfill({
        json: {
          unknown: null,
          read_at: new Date().toISOString(),
          source: 'its last run',
          plan: null,
          windows: [{ name: 'five_hour', minutes: 300, used_percent: 42, resets_at: resets, stale: false }],
          credits: null,
        },
      }),
    )
    await page.reload()

    await rail(page, 'Usage').click()
    await page.getByLabel('Period').selectOption({ label: 'Today' })
    // Boxes on top, each a number: the usage's four, then what the day alone knows (Today, this project).
    const boxes = page.locator('.usage-stats > div')
    await expect(boxes.locator('dt')).toHaveText(['Messages', 'Tokens sent', 'Tokens written', 'Cost', 'Failed', 'Files changed'])
    await expect(boxes.filter({ hasText: 'Cost' }).locator('.usage-stat')).toHaveText(/^[≈≥] [\d,.]+ USD$/)
    // Under them, side by side at this width: what is left of the plan, with its bar, and the month's budget, with its own.
    const limits = page.getByRole('region', { name: 'Plan limits' })
    const budget = page.getByRole('region', { name: 'This month’s budget' })
    await expect(limits.getByRole('meter', { name: `${NAME}: 5 hours used` })).toHaveAttribute('value', '42')
    await expect(limits.getByRole('row', { name: new RegExp(`^${NAME}`) })).toContainText('42% of 5 hours used, resets')
    await expect(budget.getByRole('meter', { name: 'Monthly budget used' })).toBeVisible()
    const [left, right] = [await limits.boundingBox(), await budget.boundingBox()]
    expect(left!.y).toBe(right!.y)
    expect(left!.x + left!.width).toBeLessThan(right!.x)
    // The table by model is open; the others are folded, each heading with its count.
    await expect(page.getByRole('table', { name: 'Usage by provider and model' })).toBeVisible()
    for (const name of ['By conversation', 'Who started it', 'Prices']) {
      const fold = page.getByRole('region', { name }).locator('details.usage-fold')
      await expect(fold).not.toHaveAttribute('open')
      await expect(fold.locator('summary')).toContainText(/\d/)
      // The heading inside what opens it is still a heading, found by a screen reader's heading keys.
      await expect(page.getByRole('heading', { name, level: 3 })).toBeVisible()
    }
    await expect(page.getByRole('table', { name: 'Usage by conversation' })).toBeHidden()
    await page.mouse.move(0, 0)
    await shot(page, `60a-usage-${theme}`)

    // Every text on the page, folds and hints opened, stands out from what it is on.
    await page.locator('.memory-page details').evaluateAll(folds => folds.forEach(fold => ((fold as HTMLDetailsElement).open = true)))
    await page.locator('.memory-page .hint-bubble').evaluateAll(hints => hints.forEach(hint => ((hint as HTMLElement).hidden = false)))
    await expect(page.getByRole('table', { name: 'Usage by conversation' })).toBeVisible()
    const pieces = await page.locator('.memory-page').evaluate(contrasts)
    expect(pieces.length).toBeGreaterThanOrEqual(60)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])

    // In a narrow window the two are one under the other.
    await page.setViewportSize({ width: 700, height: 900 })
    expect((await budget.boundingBox())!.y).toBeGreaterThan((await limits.boundingBox())!.y)
  })
