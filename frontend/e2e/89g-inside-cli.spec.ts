import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test, type APIRequestContext, type Locator, type Page } from './fixtures'
import { OWN, editRole, openAgentFold, openFreshConversation } from './helpers'
import { FAKE_CLAUDE } from './paths.mjs'

const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'ga-shots')

/** Light and dark, as the theme button sets them (`applyTheme`). */
async function both(page: Page, target: Locator, name: string) {
  mkdirSync(SHOTS, { recursive: true })
  await target.screenshot({ path: path.join(SHOTS, `${name}-light.png`) })
  await page.evaluate(() => document.documentElement.classList.add('dark'))
  await target.screenshot({ path: path.join(SHOTS, `${name}-dark.png`) })
  await page.evaluate(() => document.documentElement.classList.remove('dark'))
}

/** The stand-in provider and the role are taken away, also after a test that failed half-way. */
async function cleanUp(request: APIRequestContext) {
  const providers: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
  for (const one of providers.filter(p => p.name === 'Claude Code')) await request.delete(`/api/providers/${one.id}`, { headers: OWN })
  const roles: { id: string; name: string }[] = await (await request.get('/api/roles')).json()
  for (const one of roles.filter(r => r.name === 'Checker')) await request.delete(`/api/roles/${one.id}`, { headers: OWN })
}

// 89g: a role the user lets run inside Claude Code is offered to a Claude Code Lead as one of its own
// sub-agents (the stand-in's sub-agent is named as KOLONİ names that role: start-backend.mjs).
test.describe('a role run inside Claude Code', () => {
  test.beforeEach(async ({ page, request }) => {
    await cleanUp(request)
    const made = await request.post('/api/roles', {
      data: { name: 'Checker', description: 'Looks over the code', instructions: 'Check it.', tools: ['read_file', 'search', 'list_dir', 'run_command'] },
      headers: OWN,
    })
    expect(made.ok()).toBe(true)
    const id = await openFreshConversation(page)
    expect((await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })).ok()).toBe(true)
    await page.getByRole('button', { name: 'Models', exact: true }).click()
    await page.getByRole('button', { name: /Add a provider/ }).click()
    await page.getByLabel('Name').fill('Claude Code')
    await page.getByLabel('Kind').selectOption({ label: 'Claude Code (CLI)' })
    await page.getByLabel('Path to the command').fill(FAKE_CLAUDE)
    await page.getByLabel('How it runs').selectOption('native')
    await page.getByRole('button', { name: 'Add provider' }).click()
    await expect(page.getByRole('button', { name: /^Claude Code/ })).toBeVisible()
    // B-385: a sub-agent runs only on a provider the user opened to agents.
    const added: { id: string; name: string }[] = await (await request.get('/api/providers')).json()
    const claude = added.find(p => p.name === 'Claude Code')!
    expect((await request.patch(`/api/providers/${claude.id}`, { headers: OWN, data: { for_agents: true } })).ok()).toBe(true)
  })

  test.afterEach(async ({ request }) => {
    await cleanUp(request)
  })

  test('its option says what it costs, and its sub-agent says whose role it runs', async ({ page }) => {
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await editRole(page, 'Checker', 'tiers')
    const panel = page.getByRole('complementary', { name: 'Role Checker' })
    const option = panel.getByRole('checkbox', { name: /Run inside the CLI/ })
    await expect(option).not.toBeChecked()
    await option.check()
    // K-rol-model: it depends on the agent that opens it running in Claude Code; its card says what it costs.
    const label = panel.locator('#role-part-inside')
    await expect(label).toContainText('Only when the agent opening it runs in Claude Code.')
    await expect(label).toContainText('cheaper')
    await label.scrollIntoViewIfNeeded()
    await both(page, label, '89g-option')
    await panel.getByRole('button', { name: 'Save' }).click()
    await expect(panel.getByRole('button', { name: 'Edit model' })).toBeVisible()

    await page.getByRole('button', { name: 'Canvas', exact: true }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('button', { name: /^Model: Local/ }).click()
    await chat.getByLabel('Provider').selectOption({ label: 'Claude Code' })
    await chat.getByRole('button', { name: 'Use this model' }).click()
    await expect(chat.getByRole('button', { name: /^Model: Claude Code/ })).toBeVisible()
    await page.getByLabel('Message').fill('what does hello.py print?')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText('The helper says it prints hi.')).toBeVisible()

    // Not an agent of KOLONİ's: counted on its Lead's node; its block in the Lead's window says which role it runs as.
    await expect(page.locator('.react-flow__node-agent')).toHaveCount(1)
    await expect(page.locator('.react-flow__node-agent')).toContainText('1 own sub-agent')
    const steps = await openAgentFold(page.getByRole('region', { name: 'Agent window' }), 'Every step as recorded')
    const sub = steps.getByRole('group', { name: /^Own sub-agent/ })
    await sub.getByRole('button').first().click()
    await expect(sub).toContainText('Checker (inside Claude Code)')
    await expect(sub).toContainText('model not reported')
    await both(page, sub, '89g-sub-agent')
  })
})
