import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// Slice 81a: the Models page - a card for each provider with a gauge of what is known now, each tier's models
// in the order they are tried (moved and saved at once), and a provider's models, connection and limits in a
// window of its own. No CLI is run (the one added has no command on this machine) and nothing leaves the
// machine: the API provider's address is never asked.
const CLI = 'Claude Code 81a'
const PAID = 'Paid 81a'
const MANY = 'Many 81a'
const CODEX = 'Codex 81a'

async function remove(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if ([CLI, PAID, MANY, CODEX].includes(provider.name)) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.beforeEach(async ({ request }) => {
  await remove(request)
  const cli = await request.post('/api/providers', {
    headers: OWN,
    data: {
      name: CLI,
      kind: 'claude_cli',
      executable: 'no-such-claude-for-81a',
      for_agents: true,
      models: [
        { name: 'opus', tier: 'strongest' },
        { name: 'sonnet', tier: 'balanced', note: 'Most coding work.' },
        { name: 'haiku', tier: 'fast' },
        { name: 'claude-opus-4-1', tier: null },
      ],
    },
  })
  expect(cli.ok()).toBeTruthy()
  const paid = await request.post('/api/providers', {
    headers: OWN,
    data: { name: PAID, kind: 'openai_compat', base_url: 'https://api.example.invalid/v1', models: [{ name: 'paid-chat', tier: 'balanced' }] },
  })
  expect(paid.ok()).toBeTruthy()
})

test.afterEach(async ({ request }) => {
  await remove(request)
})

const balanced = async (request: APIRequestContext) =>
  ((await (await request.get('/api/tiers')).json()).balanced as { model: string }[]).map(one => one.model).filter(model => ['sonnet', 'paid-chat'].includes(model))

for (const theme of ['light', 'dark'] as const) {
  test(`cards say what is known, a tier's order is the user's, and a provider opens in a window (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await rail(page, 'Models').click()

    // The cards: how each is paid for, what its gauge knows, its models by tier.
    const local = page.getByRole('button', { name: /^Local/ })
    await expect(local).toContainText('this machine · default')
    await expect(local).toContainText('running')
    const cli = page.getByRole('button', { name: new RegExp(`^${CLI}`) })
    await expect(cli).toContainText('subscription')
    // Why its use is not known yet, in short (81a-2).
    await expect(cli).toContainText('Known after its first run here')
    await expect(cli).toContainText('not installed')
    await expect(cli).toContainText('of 4 models')
    await expect(page.getByRole('button', { name: new RegExp(`^${PAID}`) })).toContainText(/API key.*today/)
    await expect(page.getByRole('button', { name: /Add a provider/ })).toBeVisible()
    await expect(page.getByText(/so the Orchestrator cannot pick one/)).toHaveCount(0)
    await expect(page.getByText('How this works')).toHaveCount(0)

    // The slots: a model of a CLI that is not there says so, greyed.
    const opus = page.getByRole('region', { name: 'Strongest' }).getByRole('listitem').filter({ hasText: 'opus' })
    await expect(opus).toContainText(`${CLI} · not installed`)
    await expect(opus).toHaveClass(/tier-item-down/)
    // Moved with its arrow, saved at once.
    expect(await balanced(request)).toEqual(['sonnet', 'paid-chat'])
    await page.getByRole('button', { name: 'Move paid-chat up' }).click()
    await expect.poll(() => balanced(request)).toEqual(['paid-chat', 'sonnet'])

    const paged = page.locator('.paged')
    await shot(page, `81a-models-${theme}`)
    expect((await paged.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await page.setViewportSize({ width: 1280, height: 900 })
    await shot(page, `81a-models-1280-${theme}`)
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
    // No card's words are cut.
    expect(await page.locator('.provider-card *:not(.visually-hidden)').evaluateAll(all => all.filter(one => one.scrollWidth > one.clientWidth + 1).map(one => one.className))).toEqual([])
    await page.setViewportSize({ width: 1440, height: 900 })

    // Its switch is on its card: off, greyed and said, its window not opened; on again.
    const enabled = async () => ((await (await request.get('/api/providers')).json()) as { name: string; enabled: boolean }[]).find(p => p.name === PAID)?.enabled
    const paidCard = page.getByRole('button', { name: new RegExp(`^${PAID}`) })
    await page.getByRole('switch', { name: `${PAID} on` }).click()
    await expect.poll(enabled).toBe(false)
    await expect(paidCard).toHaveClass(/provider-off/)
    await expect(paidCard).toContainText('switched off')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await shot(page, `81a-models-off-${theme}`)
    await page.getByRole('switch', { name: `${PAID} on` }).click()
    await expect.poll(enabled).toBe(true)
    await expect(paidCard).not.toHaveClass(/provider-off/)

    // The window: its models first, each row unfolding to what is known of it and from where.
    await cli.click()
    const dialog = page.getByRole('dialog', { name: CLI })
    await expect(dialog.getByRole('tab', { name: 'Models' })).toHaveAttribute('aria-selected', 'true')
    const table = dialog.getByRole('table', { name: 'Models agents and you can pick' })
    // Read first: names are text; a tier and whether agents may use a model are switched in the row.
    await expect(dialog.getByRole('textbox')).toHaveCount(0)
    const sonnet = table.getByRole('row').filter({ has: page.getByLabel('Tier of sonnet') })
    await expect(sonnet).toContainText('plan')
    await sonnet.getByRole('button', { name: 'What is known of sonnet' }).click()
    const facts = table.locator('.model-facts')
    await expect(facts).toContainText(/Context window[\d,]+ tokensfrom models\.dev/)
    await expect(facts).toContainText(/Thinking levels.*from/)
    await expect(dialog.getByLabel('Note of sonnet')).toHaveValue('Most coding work.')
    await dialog.getByRole('switch', { name: 'Agents may use opus' }).uncheck()
    await expect(dialog.getByRole('status').filter({ hasText: 'Agents may not use opus now.' })).toBeVisible()
    await expect
      .poll(async () => ((await (await request.get('/api/tiers')).json()).strongest as { model: string; agents: boolean }[]).find(one => one.model === 'opus')?.agents)
      .toBe(false)
    // The model without a tier is last, faded.
    await expect(table.getByRole('row').last()).toHaveClass(/model-untiered/)
    await shot(page, `81a-dialog-${theme}`)
    expect((await dialog.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await page.setViewportSize({ width: 1280, height: 900 })
    await shot(page, `81a-dialog-1280-${theme}`)
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
    await page.setViewportSize({ width: 1440, height: 900 })

    await dialog.getByRole('tab', { name: 'Connection' }).click()
    await expect(dialog.getByLabel('Path to the command')).toHaveValue('no-such-claude-for-81a')
    // The provider's own settings and actions are here, with its install note.
    await expect(dialog.getByRole('note', { name: 'How to install claude' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Delete provider' })).toBeVisible()
    await shot(page, `81a-connection-${theme}`)
    await dialog.getByRole('tab', { name: 'Limits' }).click()
    await expect(dialog).toContainText('Step down a tier at')
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(cli).toBeFocused()
    // The slot says it: kept in its place, passed over.
    await expect(opus).toContainText(`${CLI} · not installed · off for agents`)
  })
}

// Slice 81a-2: a tier shows its first five, the rest on "+N more"; Codex's card says its plan is not read yet and
// offers to read it (not pressed here: that would start Codex).
test('a long tier folds after five, and Codex’s card says why its use is not known', async ({ page, request }) => {
  const models = ['m1', 'm2', 'm3', 'm4', 'm5', 'm6'].map(name => ({ name, tier: 'strongest' }))
  for (const data of [
    { name: MANY, kind: 'openai_compat', base_url: 'https://api.example.invalid/v1', models },
    { name: CODEX, kind: 'codex_cli', executable: 'no-such-codex-for-81a' },
  ])
    expect((await request.post('/api/providers', { headers: OWN, data })).ok()).toBeTruthy()
  // Its command does not exist: it is said to be there, as a CLI not installed has no Read now.
  const codexId = ((await (await request.get('/api/providers')).json()) as { id: string; name: string }[]).find(p => p.name === CODEX)!.id
  await page.route(
    url => url.pathname === `/api/providers/${codexId}/availability`,
    route => route.fulfill({ json: { installed: true, signed_in: true, models: [] } }),
  )
  const strongest = ((await (await request.get('/api/tiers')).json()).strongest as unknown[]).length
  await openFreshConversation(page)
  await rail(page, 'Models').click()

  const slot = page.getByRole('region', { name: 'Strongest' })
  await expect(slot.getByRole('listitem')).toHaveCount(5)
  await slot.getByRole('button', { name: `+${strongest - 5} more` }).click()
  await expect(slot.getByRole('listitem')).toHaveCount(strongest)
  await expect(slot.getByRole('button', { name: 'Move m6 up' })).toBeEnabled()
  await slot.getByRole('button', { name: 'Show fewer' }).click()
  await expect(slot.getByRole('listitem')).toHaveCount(5)

  const codex = page.getByRole('button', { name: new RegExp(`^${CODEX}`) })
  await expect(codex).toContainText('Not read yet')
  await expect(page.getByRole('button', { name: `Read ${CODEX}’s plan now` })).toBeVisible()
  await shot(page, '81a2-models')
})
