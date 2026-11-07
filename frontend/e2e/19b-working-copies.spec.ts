import { existsSync, readFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { openFreshConversation, shot, agentFold } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const ALPHA = path.join(PROJECT_DIR, 'alpha.txt')
const BETA = path.join(PROJECT_DIR, 'beta.txt')
/** The files this spec's turn writes are not left behind: the specs share the backend. */
const tidy = () => [ALPHA, BETA].forEach(file => rmSync(file, { force: true }))
test.beforeEach(tidy)
test.afterEach(tidy)

test('two agents work in copies of their own: nothing is in the project until you say so, once per agent', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const agents = page.locator('.react-flow__node-agent')
  const box = (name: RegExp) => agents.filter({ has: page.locator('.node-title', { hasText: name }) })
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  // The Workspace window (slice 42c): the project's tree, and what this conversation changed in it.
  const counter = page.getByRole('button', { name: /^Workspace/ })
  const files = page.getByRole('region', { name: 'Workspace' })
  const tree = files.getByRole('tree', { name: 'Files' })
  // The user is asked before files change.
  await expect(page.getByRole('button', { name: 'This chat’s settings' })).toBeAttached() // (⚙ Chat: there with a chat)
  await page.getByLabel('Permission level').selectOption('ask')
  await expect(page.getByLabel('Permission level')).toHaveValue('ask')

  await page.getByLabel('Message').fill('two coders in their own copies')
  await page.getByRole('button', { name: 'Send' }).click()
  // Agents that may change things are asked about before they open, at this level.
  for (const _ of [1, 2]) await chat.getByRole('button', { name: 'Open agent' }).first().click()

  // Each wrote its file - in its copy. Nothing was asked change by change; the quick one is
  // done, and ONE card asks whether the project gets what it changed. The other is at work.
  const card = chat.getByText("Take in Coder 2's work? · 1 file")
  await expect(card).toBeVisible({ timeout: 15_000 })
  // (Where each works, and whose copy a file is in, the side panel says: the node is three lines - the user's, 5 Nov.)
  await expect(box(/^Coder$/)).toContainText('1 file')
  await expect(box(/^Coder 2$/)).toContainText('1 file')
  await expect(box(/^Coder 2$/)).toContainText('Waits for your OK')
  await expect(chat.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(chat.getByRole('button', { name: 'Take in', exact: true })).toHaveCount(1)
  // The top bar names the agent that waits for you, not the one still at work.
  await expect(page.locator('[data-run="waiting_approval"]')).toHaveText(/^Coder 2$/)
  // Neither file is in the project, and Workspace marks what is.
  expect(existsSync(ALPHA)).toBe(false)
  expect(existsSync(BETA)).toBe(false)
  await counter.click()
  await expect(tree.getByRole('treeitem', { name: /^hello\.py/ })).toBeVisible()
  await expect(tree.getByRole('treeitem', { name: /^(alpha|beta)\.txt/ })).toHaveCount(0)
  await files.getByRole('button', { name: 'Close workspace' }).click()

  // The inspector shows the same card with the agent it is of: the file, with its diff.
  await box(/^Coder 2$/).locator('.node-head').click()
  await expect(inspector.getByText("Take in Coder 2's work? · 1 file")).toBeVisible()
  await inspector.getByText('beta.txt').first().click()
  await expect(inspector.locator('.diff-add')).toContainText('beta')
  await page.waitForTimeout(400) // the canvas moves its view over a fifth of a second
  await shot(page, '19b-one-card-for-an-agent')

  // Apply: the project has the file, and it is a change like any other.
  await chat.getByRole('button', { name: 'Take in', exact: true }).click()
  await expect.poll(() => existsSync(BETA) && readFileSync(BETA, 'utf8')).toBe('beta\n')
  await counter.click()
  await expect(tree.getByRole('treeitem', { name: 'beta.txt added, Applied' })).toBeVisible()
  await expect(tree.getByRole('treeitem', { name: /^alpha\.txt/ })).toHaveCount(0)
  await files.getByRole('button', { name: 'Close workspace' }).click()
  // (its Changes are open from the start, on its card)
  await expect(agentFold(inspector, 'Changes').locator('.chat-change', { hasText: 'beta.txt' })).toContainText('Applied')
  expect(existsSync(ALPHA)).toBe(false)

  // The other one is done later, and is asked about by itself. Discard: nothing of it is taken.
  await expect(chat.getByText("Take in Coder's work? · 1 file")).toBeVisible({ timeout: 15_000 })
  await chat.getByRole('button', { name: 'Discard' }).click()
  await expect(chat.getByText('Both coders are done; not all of it was applied.')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()
  expect(existsSync(ALPHA)).toBe(false)
  expect(readFileSync(BETA, 'utf8')).toBe('beta\n')
})
