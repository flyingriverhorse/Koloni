import { expect, type APIRequestContext, test } from './fixtures'
import { contrasts, editRole, openFreshConversation, OWN, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// Slice 60d: with no model given a tier every role runs on the conversation's model; a box on Agents
// and Models says so, and one preview fills every provider's tiers from the catalogue, saved only on
// Save. Each role then says what it runs on. No CLI is run (the one added has no command on this
// machine) and nothing leaves the machine.
const NAME = 'Claude Code 60d'
type Kept = { id: string; name: string; models: unknown[]; for_agents: boolean }
let kept: Kept[] = []

async function remove(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if (provider.name === NAME) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.beforeEach(async ({ request }) => {
  await remove(request)
  // Every provider as it was, to be put back; and none with a tier, which is what the box is for.
  kept = await (await request.get('/api/providers')).json()
  for (const p of kept)
    await request.patch(`/api/providers/${p.id}`, {
      headers: OWN,
      data: { models: (p.models as { name: string }[]).map(m => ({ ...m, tier: null })) },
    })
  const made = await request.post('/api/providers', { headers: OWN, data: { name: NAME, kind: 'claude_cli', executable: 'no-such-claude-for-60d' } })
  expect(made.ok()).toBeTruthy()
})

test.afterEach(async ({ request }) => {
  await remove(request)
  for (const p of kept) await request.patch(`/api/providers/${p.id}`, { headers: OWN, data: { models: p.models, for_agents: p.for_agents } })
})

for (const theme of ['light', 'dark'] as const) {
  test(`no tier: one preview fills them, Save gives a fast model, and each role says what it runs on (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    const box = page.getByRole('region', { name: 'No model has a tier' })
    await expect(box).toHaveText('No model has a tier yet, so the Orchestrator cannot pick one: every role runs on the conversation’s model. Fill the tiers')
    // (Slice 81b, 63b: its panel says its tier rule; where it runs is said in its form.)
    await page.getByRole('complementary', { name: 'Roles' }).getByRole('button', { name: /^Summarizer/ }).click()
    await expect(page.getByRole('complementary', { name: 'Role Summarizer' })).toContainText('Which modelOrchestrator · fast–strongest')

    // The preview: every provider, its models and tiers, the tick; nothing changes before Save.
    await box.getByRole('button', { name: 'Fill the tiers' }).click()
    const preview = page.getByRole('region', { name: 'Tiers from the catalogue' })
    await expect(page.getByRole('heading', { name: 'Tiers from the catalogue' })).toBeFocused()
    // Its command is not on this machine, so it comes unticked: ticked here, by hand.
    const tick = preview.getByLabel(`Agents may choose this: ${NAME}`)
    await expect(tick).not.toBeChecked()
    await tick.check()
    await expect(preview.getByLabel(`Tier of haiku on ${NAME}`)).toHaveValue('fast')
    await shot(preview, `60d-preview-${theme}`)
    expect((await preview.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    // A window 1024 px wide: the page never scrolls sideways.
    await page.setViewportSize({ width: 1024, height: 900 })
    await shot(page, `60d-preview-1024-${theme}`)
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
    await page.setViewportSize({ width: 1440, height: 900 })
    await preview.getByRole('button', { name: 'Save these tiers' }).click()
    await expect(preview).toBeHidden()
    await expect(box).toBeHidden()
    await expect(page.getByRole('status').filter({ hasText: /^The tiers are saved/ })).toBeFocused()

    // With no tier given for the job a role runs on the balanced model now; its form says so on top, and why.
    await editRole(page, 'Summarizer', 'tiers')
    await expect(page.locator('.role-runs')).toContainText(`Runs on ${NAME} · `)
    await expect(page.locator('.role-runs')).toContainText('the first balanced model of your team guide')
    await editRole(page, 'Summarizer', 'Tools')
    await expect(page.locator('.role-tab')).toContainText('“asks”: it waits for your yes first, as the conversation’s permission level says.')
    const agents = page.locator('.paged')
    await shot(page, `60d-agents-${theme}`)
    expect((await agents.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    // Models: the catalogue it reads, each provider's state, and the table of what is known of each model.
    await rail(page, 'Models').click()
    await expect(page.getByRole('status').filter({ hasText: /^Catalogue: models\.dev, \d+ \w+ · \d+ services$/ })).toBeVisible()
    await expect(page.getByRole('button', { name: new RegExp(`^${NAME}`) })).toContainText('not installed')
    await page.getByRole('button', { name: new RegExp(`^${NAME}`) }).click()
    const table = page.getByRole('table', { name: 'Models agents and you can pick' })
    const haiku = table.getByRole('row').filter({ has: page.getByLabel('Tier of haiku') })
    await expect(haiku.getByLabel('Tier of haiku')).toHaveValue('fast')
    await expect(haiku.getByRole('switch', { name: 'Agents may use haiku' })).toBeChecked()
    await expect(haiku).toContainText('Low–Max')
    await expect(haiku).toContainText('plan')
    const models = page.locator('.provider-dialog')
    await shot(page, `60d-models-${theme}`)
    expect((await models.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await page.setViewportSize({ width: 1024, height: 900 })
    await shot(page, `60d-models-1024-${theme}`)
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false)
    expect((await models.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  })
}
