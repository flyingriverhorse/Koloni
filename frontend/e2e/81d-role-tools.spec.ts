import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, shot } from './helpers'

// Slice 81d: a role's Tools tab is a tile for each tool, grouped; a click turns one on or off and saves at once.
// And a role dragged onto a category's heading is put in it (slice 63b). Nothing leaves the machine.
type Saved = { id: string; name: string; tools: string[]; kind: string }
let kept: Saved[] = []

const roles = async (request: APIRequestContext) => (await (await request.get('/api/roles')).json()) as Saved[]
const one = async (request: APIRequestContext, name: string) => (await roles(request)).find(r => r.name === name)!

test.beforeEach(async ({ request }) => {
  kept = (await roles(request)).filter(r => ['Coder', 'Translator'].includes(r.name))
})

test.afterEach(async ({ request }) => {
  // Put back as they were: the Coder's tools, the Translator's kind of work.
  for (const r of kept) expect((await request.patch(`/api/roles/${r.id}`, { headers: OWN, data: { tools: r.tools, kind: r.kind } })).ok()).toBe(true)
})

for (const theme of ['light', 'dark'] as const) {
  test(`a role's tools as tiles, saved at once; a role dragged into a category (${theme})`, async ({ page, request }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Agents', exact: true }).click()

    // The Coder's tiles: what it may use solid, what it may not dashed; the writes and commands ask you.
    await page.getByRole('complementary', { name: 'Roles' }).getByRole('region', { name: 'Build' }).getByRole('button', { name: /^Coder/ }).click()
    const panel = page.getByRole('complementary', { name: 'Role Coder' })
    await panel.getByRole('tab', { name: 'Tools' }).click()
    const coder = await one(request, 'Coder')
    await expect(panel.getByText(/^May use/)).toContainText(/^May use \d+ of 36 tools · \d+ MCP servers? · \d+ (of \d+ )?skills?$/)
    await expect(panel.getByRole('button', { name: 'Write files' })).toHaveAttribute('aria-pressed', 'true')
    await expect(panel.getByRole('button', { name: 'Write files' })).toContainText('asks')
    await expect(panel.getByRole('button', { name: 'Run commands' })).toContainText('asks')
    const web = panel.getByRole('button', { name: 'Search the web' })
    await expect(web).toHaveAttribute('aria-pressed', 'false')
    await shot(panel, `81d-tools-${theme}`)
    expect((await page.locator('.paged').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    // A click turns it on, saved at once and said; from the keyboard, off again.
    await web.click()
    await expect(panel.getByRole('status')).toHaveText('Search the web: on, saved.')
    await expect.poll(async () => (await one(request, 'Coder')).tools).toContain('web_search')
    await expect(web).toContainText('asks')
    await shot(panel, `81d-tools-on-${theme}`)
    await web.focus()
    await page.keyboard.press('Space')
    await expect(panel.getByRole('status')).toHaveText('Search the web: off, saved.')
    await expect.poll(async () => (await one(request, 'Coder')).tools).toEqual(coder.tools)
    await panel.getByRole('button', { name: 'Close the role' }).click()

    // Slice 63b: the Translator dragged onto Check's heading is put in it at once, and said; its panel's Category puts it back.
    const library = page.getByRole('complementary', { name: 'Roles' })
    const check = library.getByRole('region', { name: 'Check' })
    await library.getByRole('button', { name: /^Translator/ }).dragTo(check.getByRole('heading'))
    await expect(page.getByText('Translator is in Check now.')).toBeVisible()
    await expect(check.getByRole('button', { name: /^Translator/ })).toBeVisible()
    await expect.poll(async () => (await one(request, 'Translator')).kind).toBe('check')
    await check.getByRole('button', { name: /^Translator/ }).click()
    const translator = page.getByRole('complementary', { name: 'Role Translator' })
    await translator.getByLabel("Translator's category").selectOption({ label: 'Write & keep up' })
    await expect.poll(async () => (await one(request, 'Translator')).kind).toBe('write')
    expect((await library.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

    // A category's menu: one of KOLONİ's four is not deleted, Check's roles report findings; renamed in place with
    // its colour (put away unsaved here).
    await expect(check).toContainText('Roles here report findings')
    await check.getByRole('button', { name: 'Check: more' }).click()
    await expect(check.getByRole('button', { name: 'Delete — one of KOLONİ’s four: rename it instead' })).toBeDisabled()
    await shot(library, `63b-category-menu-${theme}`)
    expect((await library.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await check.getByRole('button', { name: 'Rename…' }).click()
    await expect(check.getByLabel('Category’s name')).toHaveValue('Check')
    await expect(check.getByRole('radio', { name: 'green' })).toBeChecked()
    await shot(library, `63b-category-rename-${theme}`)
    await check.getByLabel('Category’s name').press('Escape')
    await expect(check.getByRole('heading')).toContainText('Check')
  })
}
