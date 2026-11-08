import { expect, type APIRequestContext, type Page, test } from './fixtures'
import { OWN, openFreshConversation, rail, shot } from './helpers'
import { FAKE_CLAUDE } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

// Slice 40: the team guide filled from the catalogue, a mark beside each model, and what to
// run when a CLI is not there. No real CLI is near it: Codex's command is one that is not
// there, and Claude Code is the stand-in, asked only whether it is signed in.
const NAMES = ['Catalogue Codex', 'Catalogue Claude', 'Catalogue New']
// What the catalogue proposes for Codex (models.dev's OpenAI, a model of each family and tier): read, not
// written here, so that an updated catalogue does not break the test.
const proposed = async (request: APIRequestContext): Promise<string[]> =>
  (await (await request.post('/api/providers/fill-from-catalogue', { headers: OWN, data: { kind: 'codex_cli', models: [] } })).json()).models.map(
    (m: { name: string }) => m.name,
  )

async function remove(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if (NAMES.includes(provider.name)) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.beforeEach(async ({ request }) => {
  await remove(request)
  for (const [name, kind, executable] of [
    ['Catalogue Codex', 'codex_cli', 'no-such-codex-for-the-catalogue-test'],
    ['Catalogue Claude', 'claude_cli', FAKE_CLAUDE],
  ])
    expect((await request.post('/api/providers', { headers: OWN, data: { name, kind, executable } })).ok()).toBeTruthy()
})

test.afterEach(async ({ request }) => {
  await remove(request)
})

async function openProvider(page: Page, name: string) {
  // (Another provider's window is closed first: the page behind it is not reached.)
  if (await page.getByRole('dialog').count()) await page.keyboard.press('Escape')
  await rail(page, 'Models').click()
  await page.getByRole('button', { name: new RegExp(`^${name}`) }).click()
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue(name)
}

test('Fill from catalogue proposes the known models, marks each, and they are kept only once saved', async ({ page, request }) => {
  await openFreshConversation(page)
  await openProvider(page, 'Catalogue Codex')
  // Not installed: the vendor's command to run in your own terminal, and its docs (on Connection).
  await page.getByRole('tab', { name: 'Connection' }).click()
  const card = page.getByRole('note', { name: 'How to install codex' })
  await expect(card).toBeVisible()
  await expect(card.getByRole('link', { name: 'Install docs' })).toHaveAttribute('href', /^https:\/\//)
  await page.getByRole('tab', { name: 'Models' }).click()
  await page.getByRole('button', { name: 'Fill from the catalogue' }).click()
  await expect(page.locator('.provider-dialog .model-name-text').first()).toHaveText('gpt-6-astra')
  await expect(page.getByRole('img', { name: 'Cannot be used: not installed' })).toHaveCount((await proposed(request)).length)
  await expect(page.getByRole('status').filter({ hasText: 'not saved yet' })).toBeVisible()
  const saved = async () =>
    (await (await request.get('/api/providers')).json()).find((p: { name: string }) => p.name === 'Catalogue Codex').models
  expect((await saved()) ?? []).toEqual([])
  await page.getByRole('button', { name: 'Save these models' }).click()
  const names = await proposed(request)
  await expect.poll(async () => (await saved())?.map((m: { name: string }) => m.name)).toEqual(names)
  // Claude Code is installed and signed in, but lists nothing itself: not known, never "usable".
  await openProvider(page, 'Catalogue Claude')
  await page.getByRole('button', { name: 'Fill from the catalogue' }).click()
  await expect(page.locator('.provider-dialog .model-name-text').first()).toHaveText('fable')
  await expect(page.getByRole('img', { name: /^Not known if usable/ }).first()).toBeVisible()
  await expect(page.getByRole('img', { name: 'Usable now' })).toHaveCount(0)
  await expect(page.getByRole('note', { name: /^How to/ })).toHaveCount(0)
})

// Slice 40b: a provider not added yet is filled from its kind's catalogue before Add.
test('a new provider is filled from the catalogue, and the models are saved with it', async ({ page, request }) => {
  await openFreshConversation(page)
  await rail(page, 'Models').click()
  await page.getByRole('button', { name: /Add a provider/ }).click()
  await page.getByLabel('Name', { exact: true }).fill('Catalogue New')
  await page.getByLabel('Kind').selectOption('codex_cli')
  await page.getByLabel('Path to the command').fill('no-such-codex-for-the-catalogue-test')
  await page.getByRole('button', { name: 'Fill from the catalogue' }).click()
  await expect(page.locator('.provider-dialog .model-name-text').first()).toHaveText('gpt-6-astra')
  await page.getByRole('button', { name: 'Add provider' }).click()
  await expect
    .poll(async () =>
      (await (await request.get('/api/providers')).json())
        .find((p: { name: string }) => p.name === 'Catalogue New')
        ?.models?.map((m: { name: string }) => m.name),
    )
    .toEqual(await proposed(request))
})

for (const theme of ['light', 'dark'] as const) {
  test(`shots: the team guide of slice 40, ${theme}`, async ({ page }) => {
    test.skip(!process.env.KOLONI_SHOTS, 'screenshots are taken with KOLONI_SHOTS=1')
    const guide = page.locator('.provider-dialog')
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await openProvider(page, 'Catalogue Codex')
    await page.getByRole('button', { name: 'Fill from the catalogue' }).click()
    await expect(page.locator('.provider-dialog .model-name-text').nth(3)).toBeVisible()
    await shot(guide, `40-not-installed-${theme}`)
    await openProvider(page, 'Catalogue Claude')
    await page.getByRole('button', { name: 'Fill from the catalogue' }).click()
    await expect(page.locator('.provider-dialog .model-name-text').nth(5)).toBeVisible()
    await shot(guide, `40-not-known-${theme}`)
    // The model server lists its models: what it lists is usable, what it does not is not.
    await openProvider(page, 'Local')
    for (const name of ['fake-qwen', 'gone-model']) {
      await page.getByRole('button', { name: 'Add a model' }).click()
      await page.getByLabel('New model’s name').fill(name)
      await page.getByLabel('New model’s name').press('Enter')
    }
    await expect(page.getByRole('img', { name: 'Usable now' })).toBeVisible()
    await expect(page.getByRole('img', { name: 'Cannot be used: not offered by the provider now' })).toBeVisible()
    await shot(guide, `40-listed-${theme}`)
    await page.getByRole('button', { name: 'Remove fake-qwen' }).click()
    await page.getByRole('button', { name: 'Remove gone-model' }).click()
  })
}
