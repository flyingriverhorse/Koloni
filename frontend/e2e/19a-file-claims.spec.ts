import { existsSync, readFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const NOTES = path.join(PROJECT_DIR, 'notes.txt')
/** The file this spec's turn writes is not left behind: the specs share the backend. */
const tidy = () => rmSync(NOTES, { force: true })
test.beforeEach(tidy)
test.afterEach(tidy)

test('two agents want one file: the second waits for the first, the canvas says so, and both changes are in the file', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const agents = page.locator('.react-flow__node-agent')
  const box = (name: RegExp) => agents.filter({ has: page.locator('.node-title', { hasText: name }) })
  const line = page.locator('.react-flow__edge.edge-waits')
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  // Files are written without asking, so that nothing in this turn waits for the user.
  await expect(page.getByRole('button', { name: 'This chat’s settings' })).toBeAttached() // (⚙ Chat: there with a chat)
  await page.getByLabel('Permission level').selectOption('auto_edit')
  await expect(page.getByLabel('Permission level')).toHaveValue('auto_edit')

  await page.getByLabel('Message').fill('two coders share a file')
  await page.getByRole('button', { name: 'Send' }).click()

  // The first Coder has written notes.txt and is still at work; the second reaches for the
  // same file. It is not refused: it waits, and its box says for whom and for which file.
  await expect(box(/^Coder 2$/)).toContainText('waits for Coder · notes.txt', { timeout: 15_000 })
  await expect(box(/^Coder$/)).not.toContainText('waits for')
  // A line joins the one that waits to the one that holds; the holder's node counts the file (who holds it is in the side panel).
  await expect(line).toHaveCount(1)
  await expect(box(/^Coder$/)).toContainText('1 file')
  await expect(chat.getByRole('button', { name: /Coder 2.*Add to notes\.txt slowly/ })).toContainText('waiting for a file')
  // Waiting for a file asks nothing of the user: the turn runs, and nothing is marked.
  await expect(page.getByText(/WORKING/)).toBeVisible()
  await expect(page.locator('[data-run="waiting_approval"]')).toHaveCount(0)
  await expect(page.getByText(/waits for you|waiting for you/i)).toHaveCount(0)
  // What the first one wrote is in its working copy: the project gets it when its work is over.
  expect(existsSync(NOTES)).toBe(false)
  await page.waitForTimeout(400) // the canvas moves its view over a fifth of a second
  await shot(page, '19a-agent-waits-for-file')

  // The inspector says the same of the agent that waits, and what the other one holds.
  await box(/^Coder 2$/).locator('.node-head').click()
  await expect(inspector.getByRole('note')).toContainText('Waits for Coder to finish with notes.txt')
  await box(/^Coder$/).locator('.node-head').click()
  await expect(inspector.getByRole('list', { name: 'Files it holds' })).toContainText('notes.txt')

  // The first is done: the second is told to look again, reads the file and adds its line.
  await expect(chat.getByText('Both coders are done.')).toBeVisible({ timeout: 25_000 })
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()
  await expect(line).toHaveCount(0)
  await expect(page.getByText(/held by/)).toHaveCount(0)
  await expect(page.getByText(/waits for Coder/)).toHaveCount(0)
  // Neither wrote over the other.
  expect(readFileSync(NOTES, 'utf8')).toBe('first\nsecond\n')
})
