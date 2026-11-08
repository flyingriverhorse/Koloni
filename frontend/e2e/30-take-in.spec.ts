import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { OWN, openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const LINES = path.join(PROJECT_DIR, 'lines.txt')
const NUMBERS = ['one', 'two', 'three', 'four', 'five', 'six', 'seven']
const text = (lines: string[]) => lines.map(line => `${line}\n`).join('')

test.beforeEach(() => writeFileSync(LINES, text(NUMBERS)))
// The specs share the backend and its one project: neither the file nor the setting is left behind.
test.afterEach(async ({ request }) => {
  rmSync(LINES, { force: true })
  const [project] = await (await request.get('/api/projects')).json()
  await request.patch(`/api/projects/${project.id}`, { headers: OWN, data: { check_command: '' } })
})

test('the same line changed on both sides is asked about, the check runs from the card on what would be taken, and that is applied', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // The project's check command: what it does and when it runs by itself is said where it is set.
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  await settings.getByRole('button', { name: /^Checks/ }).click()
  // (What it runs, on what and where, stands under the field and is read before it is set; how it works is behind ⓘ. Both describe the field.)
  await expect(settings.getByText(/^This command runs first on the sub-agent’s changes together with what the project changed meanwhile/)).toBeVisible()
  await expect(settings.getByLabel('Test before adding')).toHaveAccessibleDescription(/^This command runs first on the sub-agent’s changes together with what the project changed meanwhile/)
  await expect(settings.getByText(/It runs by itself only where commands do: in Full auto/)).toBeVisible()
  await expect(settings.getByLabel('Test before adding')).toHaveAccessibleDescription(/It runs by itself only where commands do: in Full auto/)
  await expect(settings.getByLabel(/^Save each sub-agent’s work as a git commit/)).not.toBeChecked()
  await settings.getByLabel('Test before adding').fill('python check.py')
  await shot(settings, '30-settings')
  await settings.getByRole('button', { name: 'Save' }).click()
  // (Saved, the page stays and says so. ⚙ closes it.)
  await expect(settings.getByRole('status')).toHaveText('Saved')
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await expect(settings).toHaveCount(0)

  await page.getByLabel('Permission level').selectOption('ask')
  await expect(page.getByLabel('Permission level')).toHaveValue('ask')
  await page.getByLabel('Message').fill('a clash in lines.txt')
  await page.getByRole('button', { name: 'Send' }).click()
  await chat.getByRole('button', { name: 'Open agent' }).click()

  // The Coder has changed line two in its copy and is still at work. Meanwhile, by the user's own
  // hand, the project's file changes on the same line - and on another.
  await expect(page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Coder$/ }) })).toContainText('1 file', { timeout: 15_000 })
  writeFileSync(LINES, text(NUMBERS.map(line => ({ two: 'TWO-user', six: 'SIX-user' })[line] ?? line)))

  // One card: the lines that clash, both sides of them, when each changed and which is newer.
  await expect(chat.getByText("Take in Coder's work? · 1 file")).toBeVisible({ timeout: 20_000 })
  const clash = chat.getByRole('group', { name: 'Changed on both sides' }).getByRole('group', { name: 'lines.txt' })
  await expect(clash.locator('.diff-del')).toContainText('TWO-user')
  await expect(clash.locator('.diff-add')).toContainText('TWO-agent')
  await expect(clash.getByText('newer')).toHaveCount(1)
  await expect(clash.getByText(/^The project's file: /)).toContainText('newer')
  // Nothing is chosen for you: without your word nothing is applied and the check does not run.
  const check = chat.getByRole('group', { name: 'Test' })
  await expect(check.getByText('not run')).toBeVisible()
  await expect(chat.getByRole('button', { name: 'Take in', exact: true })).toBeDisabled()
  await expect(check.getByRole('button', { name: 'Run the test' })).toBeDisabled()
  await shot(page, '30-clash-asked')

  await clash.getByRole('radio', { name: "Take Coder's lines" }).check()
  await check.getByRole('button', { name: 'Run the test' }).click()
  // It ran in the copy, on the two sides together: the project still has the user's line.
  await expect(check.getByText('passed', { exact: true })).toBeVisible({ timeout: 20_000 })
  await expect(check.getByText('exit code 0')).toBeVisible()
  expect(readFileSync(LINES, 'utf8')).toBe(text(NUMBERS.map(line => ({ two: 'TWO-user', six: 'SIX-user' })[line] ?? line)))
  // The file is now one that went together, with the lines you chose.
  const merged = chat.getByRole('group', { name: "Merged with the project's changes" })
  await expect(merged).toContainText("lines.txt — Coder's")
  await shot(page, '30-check-passed')

  await chat.getByRole('button', { name: 'Take in', exact: true }).click()
  await expect(page.getByText('DONE', { exact: true })).toBeVisible({ timeout: 15_000 })
  // The Coder's line where they clashed; the user's own change elsewhere is kept.
  expect(readFileSync(LINES, 'utf8')).toBe(text(NUMBERS.map(line => ({ two: 'TWO-agent', six: 'SIX-user' })[line] ?? line)))
  // Decided: the card is gone. (No commit is offered: the setting is off.)
  await expect(chat.getByText("Take in Coder's work?")).toHaveCount(0)
  await expect(chat.getByRole('group', { name: "Commit of Coder's changes" })).toHaveCount(0)
})
