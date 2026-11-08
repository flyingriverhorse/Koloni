import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// Slice 59c: what is known of a model comes from one lookup, for the model being picked; a
// provider not added yet is offered its catalogue's names, its service's address and key name.
// No CLI is run (Claude Code's levels are the catalogue's) and nothing leaves the machine.
const NAME = 'Facts Claude'

async function remove(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if (provider.name === NAME) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.beforeEach(async ({ request }) => {
  await remove(request)
  const made = await request.post('/api/providers', { headers: OWN, data: { name: NAME, kind: 'claude_cli', executable: 'no-such-claude-for-the-facts-test' } })
  expect(made.ok()).toBeTruthy()
})

test.afterEach(async ({ request }) => {
  await remove(request)
})

for (const theme of ['light', 'dark'] as const) {
  test(`the picker shows the levels of the model being picked; a new provider is offered its service's names (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const picker = page.getByRole('button', { name: /^Model:/ })
    await picker.click()
    // The fake model, on this machine, says no levels.
    await expect(page.getByText(/The model’s levels are not known: nothing is sent\./)).toBeVisible()
    // Another provider and model picked, not saved: their levels, from the catalogue.
    await page.getByLabel('Provider').selectOption({ label: NAME })
    await page.getByLabel('Model name').fill('opus')
    await expect(page.getByText(/Its model takes: Low, Medium, High, XHigh, Max\./)).toBeVisible()
    await expect(page.getByLabel('Thinking')).toBeEnabled()
    const panel = page.getByRole('form', { name: 'Model for this conversation' })
    await shot(panel, `59c-picker-${theme}`)
    expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await picker.click()

    // A provider not added yet, at a service's address: its models, and the name of its key.
    await rail(page, 'Models').click()
    await page.getByRole('button', { name: /Add a provider/ }).click()
    await page.getByLabel('Kind').selectOption('openai_compat')
    await page.getByLabel('Address').fill('https://api.deepseek.com')
    await page.getByLabel('Address').blur()
    await expect(page.getByLabel('API key')).toHaveAttribute('placeholder', 'Your DEEPSEEK_API_KEY')
    await expect(page.getByText(/DeepSeek calls its key DEEPSEEK_API_KEY\./)).toBeVisible()
    const list = await page.getByLabel('Default model').getAttribute('list')
    await expect(page.locator(`datalist[id="${list}"] option[value="deepseek-v4-pro"]`)).toHaveCount(1)
    await expect(page.getByText(/^Offered here: your own list, then the catalogue’s models/)).toBeVisible()
    const editor = page.locator('form').filter({ has: page.getByLabel('Address') })
    await shot(editor, `59c-new-provider-${theme}`)
    expect((await editor.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    // Nothing was saved, and nothing was asked of the service.
    expect((await (await request.get('/api/providers')).json()).some((p: { base_url: string | null }) => p.base_url?.includes('deepseek'))).toBe(false)
  })
}
