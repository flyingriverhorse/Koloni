import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// Slice 81c: a plan's gauge says what is left, an API key's says what it spent against its daily limit, the
// provider window's Limits tab sets them, Copilot's own model server is folded away, and a turn whose Lead runs
// on a provider past its limit asks first. No CLI is run: Claude Code's reading is answered here, as 60a's is.
const CLI = 'Claude Code 81c'
const PAID = 'Paid 81c'

async function local(request: APIRequestContext) {
  return ((await (await request.get('/api/providers')).json()) as { id: string; name: string }[]).find(p => p.name === 'Local')!.id
}

async function clean(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if ([CLI, PAID].includes(provider.name) || provider.kind === 'copilot_cli') await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
  // The backend is shared: a limit left on Local would hold back every spec's turn after this one.
  await request.patch(`/api/providers/${await local(request)}`, { headers: OWN, data: { day_limit: null } })
  await request.delete('/api/prices?model_id=fake-qwen', { headers: OWN })
}

test.beforeEach(async ({ request }) => clean(request))
test.afterEach(async ({ request }) => clean(request))

for (const theme of ['light', 'dark'] as const) {
  test(`plan gauges say what is left, the Limits tab sets a provider's, and Copilot's server folds away (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const made = await request.post('/api/providers', { headers: OWN, data: { name: CLI, kind: 'claude_cli', executable: 'no-such-claude-for-81c' } })
    expect(made.ok()).toBe(true)
    const paid = await request.post('/api/providers', {
      headers: OWN,
      data: { name: PAID, kind: 'openai_compat', base_url: 'https://api.example.invalid/v1', api_key: 'sk-81c' },
    })
    expect(paid.ok()).toBe(true)
    // As Claude Code said it on 23 Oct: its session 67% used, its week 84%, Fable's week 3%.
    const resets = new Date(Date.now() + 3600_000).toISOString()
    await page.route(`**/api/providers/${(await made.json()).id}/limits`, route =>
      route.fulfill({
        json: {
          unknown: null,
          read_at: new Date().toISOString(),
          source: 'its last run',
          plan: null,
          windows: [
            { name: 'five_hour', minutes: 300, used_percent: 67, resets_at: resets, stale: false },
            { name: 'seven_day', minutes: 10080, used_percent: 84, resets_at: null, stale: false },
            { name: 'seven_day_fable', minutes: null, used_percent: 3, resets_at: null, stale: false },
          ],
          credits: null,
        },
      }),
    )
    await openFreshConversation(page)
    await rail(page, 'Models').click()

    const cli = page.getByRole('button', { name: new RegExp(`^${CLI}`) })
    await expect(cli).toContainText('16% left this week')
    // The plan's other windows, behind its card's ⓘ.
    await expect(cli.locator('..').locator('.hint')).toContainText(/Session 33% left · resets .+ · Fable this week 97% left/)
    const card = page.getByRole('button', { name: new RegExp(`^${PAID}`) })
    await expect(card).toContainText('$0 today')

    // The API key's Limits: a day's most, saved; its card fills to it.
    await card.click()
    const dialog = page.getByRole('dialog', { name: PAID })
    await dialog.getByRole('tab', { name: 'Limits' }).click()
    await expect(dialog.getByLabel('This key is a plan: count no money')).not.toBeChecked()
    await dialog.getByLabel('At most $ … a day').fill('5')
    await dialog.getByRole('button', { name: 'Save limits' }).click()
    await expect(dialog.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible()
    await shot(page, `81c-limits-key-${theme}`)
    expect((await dialog.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await page.keyboard.press('Escape')
    await expect(card).toContainText('$0 / $5 today')

    // The subscription's: a step down.
    await cli.click()
    const its = page.getByRole('dialog', { name: CLI })
    await its.getByRole('tab', { name: 'Limits' }).click()
    await its.getByLabel('Step down a tier at … % of the plan').fill('80')
    await its.getByRole('button', { name: 'Save limits' }).click()
    await expect(its.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible()
    await shot(page, `81c-limits-plan-${theme}`)
    await page.keyboard.press('Escape')
    const saved = (await (await request.get('/api/providers')).json()) as { name: string; day_limit: number | null; step_down_at: number | null }[]
    expect(saved.find(p => p.name === PAID)?.day_limit).toBe(5)
    expect(saved.find(p => p.name === CLI)?.step_down_at).toBe(80)
    await shot(page, `81c-models-${theme}`)
    expect((await page.locator('.paged').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await page.setViewportSize({ width: 1280, height: 900 })
    expect(await page.locator('.provider-card *:not(.visually-hidden)').evaluateAll(all => all.filter(one => one.scrollWidth > one.clientWidth + 1).map(one => one.className))).toEqual([])
    await page.setViewportSize({ width: 1440, height: 900 })

    // Copilot: the key is optional (its own gh sign-in is used without one), a model server of your
    // own folded away. Not added here: adding one would have the real Copilot asked whether it is
    // signed in.
    await page.getByRole('button', { name: /Add a provider/ }).click()
    const add = page.getByRole('dialog', { name: 'Add a provider' })
    await add.getByLabel('Name').fill('Copilot 81c')
    await add.getByLabel('Kind').selectOption('copilot_cli')
    await expect(add.getByLabel('API key')).toBeVisible()
    await expect(add.getByText(/Leave empty to use your own GitHub sign-in \(gh\)/)).toBeVisible()
    await expect(add.getByLabel('Model server address')).toBeHidden()
    await shot(page, `81c-copilot-${theme}`)
    await add.getByText('Use a model server of your own instead (optional)').click()
    await expect(add.getByLabel('Model server address')).toBeVisible()
    await page.keyboard.press('Escape')
  })
}

test('a turn whose Lead runs on a provider past its limit asks first, and goes on with your word', async ({ page, request }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('hello from the limits spec')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  // A price, and a day's limit on Local under what that turn spent.
  expect((await request.put('/api/prices', { headers: OWN, data: { model_id: 'fake-qwen', input: 1000, output: 2000, currency: 'USD' } })).ok()).toBe(true)
  expect((await request.patch(`/api/providers/${await local(request)}`, { headers: OWN, data: { day_limit: 0.01 } })).ok()).toBe(true)
  await page.getByLabel('Message').fill('one more past the limit')
  await page.getByRole('button', { name: 'Send' }).click()
  const card = chat.getByRole('group', { name: /^Over Local's limit of 0\.01 USD a day/ })
  await expect(card).toContainText(/spent today\)\. Send it anyway\?/)
  await shot(page, '81c-over-limit')
  await card.getByRole('button', { name: 'Go on anyway' }).click()
  await expect(card).toHaveCount(0)
  await expect(chat.getByText('one more past the limit')).toBeVisible()
  // The turn goes on to change hello.py: turned down, so its hold on the file goes with it (the backend is shared,
  // and a later spec's room changes hello.py).
  await chat.getByRole('button', { name: 'Reject' }).click()
  await expect(chat.getByText('Okay, I left hello.py unchanged.')).toBeVisible()
})
