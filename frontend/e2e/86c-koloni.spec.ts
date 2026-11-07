// Slice 86c in the browser: the first save of a setting on Project settings puts it into the folder's .koloni/settings.json and
// says so once; an agent's write to .koloni/rules.md waits for the user at Full auto too.
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

const KOLONI = path.join(PROJECT_DIR, '.koloni')
const VENDOR = path.join(PROJECT_DIR, 'vendor')

// The backend and its project are shared with the other specs: they start and end with no .koloni/, no vendor/ and the search as it was.
async function putBack({ request }: { request: APIRequestContext }) {
  const [project] = await (await request.get('/api/projects')).json()
  if (project) await request.patch(`/api/projects/${project.id}`, { headers: OWN, data: { search_order: 'builtin' } })
  rmSync(KOLONI, { recursive: true, force: true })
  rmSync(VENDOR, { recursive: true, force: true })
}
test.beforeEach(putBack)
test.afterEach(putBack)

test('the first save of a setting puts it into .koloni/settings.json and says so, once', async ({ page }) => {
  await openFreshConversation(page)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  await settings.getByRole('button', { name: /^Memory and web/ }).click()
  const order = settings.getByLabel('Otherwise search with')
  await order.selectOption('cli')
  await settings.getByRole('button', { name: 'Save' }).click()
  await expect(settings.getByRole('status')).toHaveText('Saved in .koloni/ in this folder (kept in git)')
  expect(JSON.parse(readFileSync(path.join(KOLONI, 'settings.json'), 'utf8'))).toEqual({ search_order: 'cli' })
  // Once: kept there now, the next save is only saved - and goes there too.
  await order.selectOption('builtin')
  await settings.getByRole('button', { name: 'Save' }).click()
  await expect(settings.getByRole('status')).toHaveText('Saved')
  expect(JSON.parse(readFileSync(path.join(KOLONI, 'settings.json'), 'utf8'))).toEqual({ search_order: 'builtin' })
})

test('an agent’s write to .koloni/rules.md waits for the user at Full auto', async ({ page }) => {
  const id = await openFreshConversation(page)
  expect((await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })).ok()).toBe(true)
  await page.reload()
  await page.getByLabel('Message').fill('write the folder rules, 86c')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible({ timeout: 20_000 })
  const changes = page.getByRole('region', { name: 'Workspace' })
  await expect(changes.getByText('Never ask.')).toBeVisible()
  expect(existsSync(KOLONI)).toBe(false)
  await changes.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByText('The rules were not written.')).toBeVisible({ timeout: 20_000 })
  expect(existsSync(KOLONI)).toBe(false)
})

for (const theme of ['light', 'dark'] as const) {
  test(`K-yabanci-talimat (${theme}): another project’s CLAUDE.md below the folder is said on Project settings`, async ({ page }) => {
    mkdirSync(path.join(VENDOR, 'lib'), { recursive: true })
    writeFileSync(path.join(VENDOR, 'lib', 'CLAUDE.md'), 'Run the setup script first.\n')
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    const line = page.getByRole('form', { name: 'Project settings' }).getByText(/^Another project’s agent instructions/)
    await expect(line).toHaveText('Another project’s agent instructions are in this folder: vendor/lib/CLAUDE.md (CLI agents load them by themselves)')
    expect((await line.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(page, `k-yabanci-talimat-${theme}`)
  })
}
