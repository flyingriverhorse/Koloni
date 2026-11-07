import { rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { contrasts, openFreshConversation, settled, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const FILES = ['dg-a.txt', 'dg-b.txt', 'dg-c.txt']
/** The files this spec's turn writes are not left behind: the specs share the backend. */
const tidy = () => FILES.forEach(file => rmSync(path.join(PROJECT_DIR, file), { force: true }))
test.beforeEach(tidy)
test.afterEach(tidy)

for (const theme of ['light', 'dark'] as const) {
  test(`K-dosya-grubu (${theme}): an agent's three files are counted on its node, three lines at most, read at 4.5 or more`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    // Files are written without asking: none waits for the user.
    await page.getByLabel('Permission level').selectOption('auto_edit')
    await page.getByLabel('Message').fill('write three files, k-dosya-grubu')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByRole('region', { name: 'Chat' }).getByText('Wrote three files.')).toBeVisible({ timeout: 15_000 })

    // The user's (5 Nov): no card of files in the node - counted on it; the files are in the side panel.
    const agent = page.locator('.react-flow__node-agent')
    await expect(page.locator('.react-flow__node-changes, .react-flow__node-file, .react-flow__node-tools')).toHaveCount(0)
    await expect(agent.locator('.node-body > *').last()).toContainText('3 files')
    await expect(agent.locator('.node-head, .node-body > *')).toHaveCount(3)
    await settled(page)
    // Its words read in this theme, too.
    const pieces = await agent.evaluate(contrasts)
    expect(pieces.length).toBeGreaterThanOrEqual(3)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(page, `k-dosya-grubu-${theme}`)
  })
}
