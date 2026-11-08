import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, type Page, test } from './fixtures'
import { OWN, contrasts, dropKnowledge, openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// K-uzman (mockup X): Agents -> New role -> Expert, from a file of the project; its Knowledge tab has it on, in full. K-bilgi
// E: on the Knowledge page, Learn reads it once and the scripted model writes the guide, kept in the project's
// .koloni/knowledge/pay/; its row says what was read, when, on what, and shows the guide. What a spec makes it takes away.
const DOCS = path.join(PROJECT_DIR, 'docs-uzman')
const KEPT = path.join(PROJECT_DIR, '.koloni', 'knowledge', 'pay')
type Named = { id: string; name: string }

test.afterEach(async ({ request }) => {
  for (const role of (await (await request.get('/api/roles')).json()) as Named[])
    if (role.name === 'Pay expert') expect((await request.delete(`/api/roles/${role.id}`, { headers: OWN })).ok()).toBe(true)
  await dropKnowledge(request, 'Pay')
  rmSync(DOCS, { recursive: true, force: true })
  rmSync(KEPT, { recursive: true, force: true })
})

const lowContrast = async (page: Page) => (await page.locator('.paged').evaluate(contrasts)).filter(piece => piece.ratio < 4.5)

for (const theme of ['light', 'dark'] as const) {
  test(`an expert made from a file of the project learns it once and its Knowledge page row says so (${theme})`, async ({ page }) => {
    test.setTimeout(60_000)
    mkdirSync(DOCS, { recursive: true })
    writeFileSync(path.join(DOCS, 'pay.md'), '# Pay\n\npay(amount) takes a payment. Amounts are in cents.\n')
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await page.setViewportSize({ width: 1440, height: 900 })
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await page.getByRole('button', { name: 'New role' }).click()
    await page.getByRole('button', { name: 'An expert', exact: true }).click()  // (not the MLflow or Databricks expert)
    await page.getByLabel('Knows').fill('Pay')
    await page.getByLabel('Sources').fill('docs-uzman/pay.md')
    await shot(page, `k-uzman-template-${theme}`)
    await page.getByRole('button', { name: 'Create expert' }).click()

    // A role as any is; its Knowledge tab has Pay on, in full - and says what it knows.
    await page.getByRole('button', { name: /^Pay expert/ }).click()
    await page.getByRole('tab', { name: 'Knowledge' }).click()
    const panel = page.getByRole('complementary', { name: 'Role Pay expert' })
    await expect(panel.getByText('knows: Pay')).toBeVisible()
    await expect(panel.getByRole('switch', { name: 'Knowledge Pay' })).toBeChecked()
    await expect(panel.getByRole('group', { name: 'Pay: how' }).getByRole('button', { name: 'Full' })).toHaveAttribute('aria-pressed', 'true')
    await expect(panel.getByLabel('Sources')).toHaveCount(0)
    await shot(page, `k-uzman-knowledge-tab-${theme}`)
    expect(await lowContrast(page)).toEqual([])

    // What it read and its guide: on the Knowledge page.
    await panel.getByRole('button', { name: 'on Knowledge →' }).click()
    const row = page.locator('.knowledge-card').filter({ hasText: 'Pay expert · full' })
    await row.getByRole('button', { name: /Pay/ }).click()
    await row.getByRole('tab', { name: 'Settings' }).click()
    const knowledge = page.locator('.knowledge-page')
    await expect(knowledge.getByLabel('Sources')).toHaveValue('docs-uzman/pay.md')
    await row.getByRole('button', { name: 'Learn', exact: true }).click()

    await expect(row).toContainText('1 of 1 pages in the guide', { timeout: 15_000 })
    await expect(row.getByRole('button', { name: 'Learn again' })).toBeEnabled()
    // Its first learning done, the open card turns to its guide.
    await expect(row.getByRole('tab', { name: 'Guide' })).toHaveAttribute('aria-selected', 'true')
    await row.getByRole('tab', { name: 'Settings' }).click()
    await expect(knowledge.getByText(/it names its folder, .koloni\/knowledge\/pay\//)).toBeVisible()
    await row.getByRole('tab', { name: /^Pages/ }).click()
    await expect(knowledge.getByText('Pages: 1 read, 0 skipped')).toBeVisible()
    await expect(knowledge.getByText('read docs-uzman/pay.md')).toBeVisible()
    await row.getByRole('tab', { name: 'Guide' }).click()
    await expect(knowledge.getByText(/^learned \d+ \w+/)).toBeVisible()
    await expect(knowledge.locator('.knowledge-guide')).toContainText('pay(amount)` takes a payment')
    await shot(page, `k-uzman-knowledge-${theme}`)
    expect((await knowledge.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  })
}

// The user's screenshot: in a narrow step, an expert's "knows: ..." sat on its name and pushed the x out of the chip. The
// name keeps one line (an ellipsis, the whole name in its title), what it knows its own line under it, the x inside.
for (const theme of ['light', 'dark'] as const) {
  test(`an expert's chip in a team's step: name, what it knows and the x do not overlap (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await page.getByRole('button', { name: /^ML Plan/, expanded: false }).click()
    const chips = page.locator('.team-mini', { has: page.locator('.chip-knows') })
    await expect(chips.first()).toBeVisible()
    for (const width of [1440, 1100, 900]) {
      await page.setViewportSize({ width, height: 900 })
      for (const chip of await chips.all()) {
        const name = chip.locator('.team-mini-open')
        await expect(name).toHaveAttribute('title', (await name.textContent())!)
        const [box, named, knows, x] = await Promise.all([chip, name, chip.locator('.chip-knows'), chip.locator('.chip-x')].map(async part => (await part.boundingBox())!))
        expect(named.height).toBeLessThan(24)  // one line
        expect(knows.y).toBeGreaterThanOrEqual(named.y + named.height - 1)
        for (const part of [named, knows, x]) {
          expect(part.x).toBeGreaterThanOrEqual(box.x)
          expect(part.x + part.width).toBeLessThanOrEqual(box.x + box.width + 0.5)
        }
      }
    }
    await shot(chips.first().locator('..'), `k-uzman-team-chip-${theme}`)
    expect(await lowContrast(page)).toEqual([])
  })
}
