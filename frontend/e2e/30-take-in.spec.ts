import { readFileSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { level, openFreshConversation, OWN, shot } from './helpers'
import { PROJECT_DIR, PYTHON } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const LINES = path.join(PROJECT_DIR, 'lines.txt')
// The Coder's own test (fake-model.mjs), and a pytest config of the project's own: the e2e project
// sits under the repository, whose pyproject.toml pytest would read otherwise.
const OWN_TEST = path.join(PROJECT_DIR, 'test_lines.py')
const PYTEST_INI = path.join(PROJECT_DIR, 'pytest.ini')
const NUMBERS = ['one', 'two', 'three', 'four', 'five', 'six', 'seven']
const text = (lines: string[]) => lines.map(line => `${line}\n`).join('')

test.beforeEach(() => {
  writeFileSync(LINES, text(NUMBERS))
  writeFileSync(PYTEST_INI, '[pytest]\n')
})
// The specs share the backend and its one project: neither the files nor the test command is left behind.
test.afterEach(async ({ request }) => {
  for (const file of [LINES, OWN_TEST, PYTEST_INI]) rmSync(file, { force: true })
  const [project] = await (await request.get('/api/projects')).json()
  await request.delete(`/api/projects/${project.id}/map/test?path=./`, { headers: OWN })
})

test('the same line changed on both sides is asked about, the Coder’s own test runs from the card on what would be taken, and that is applied', async ({
  page,
}) => {
  // (the Coder stays at work a while after each of its two writes)
  test.setTimeout(60_000)
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // What runs before a sub-agent's work is added is said where the project's checks are: its own tests, no field (0.1.7).
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  await settings.getByRole('button', { name: /^Checks/ }).click()
  await expect(
    settings.getByText(/^Before its work is added, the tests the sub-agent wrote or changed run in its working copy/),
  ).toBeVisible()
  await expect(settings.getByText(/with KOLONİ’s guess the card waits for your Run the test/)).toBeVisible()
  await expect(settings.getByLabel('Test before adding')).toHaveCount(0)
  await expect(settings.getByLabel(/^Save each sub-agent’s work as a git commit/)).not.toBeChecked()
  // The whole project's test command, on the project map: what the check narrows to the tests the Coder writes.
  await settings.getByRole('button', { name: /^This folder/ }).click()
  const command = settings.getByRole('table', { name: 'Parts of this folder' }).getByLabel('Test command for ./')
  await command.fill(`${PYTHON} -m pytest -q`)
  await command.press('Enter')
  await expect(settings.getByRole('status')).toHaveText('Saved')
  await shot(settings, '30-settings')
  // (⚙ closes it.)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await expect(settings).toHaveCount(0)

  await level(page, 'ask')
  await page.getByLabel('Message').fill('a clash in lines.txt')
  await page.getByRole('button', { name: 'Send' }).click()
  await chat.getByRole('button', { name: 'Open agent' }).click()

  // The Coder has changed line two in its copy and is still at work. Meanwhile, by the user's own
  // hand, the project's file changes on the same line - and on another.
  await expect(
    page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Coder$/ }) }),
  ).toContainText('1 file', { timeout: 15_000 })
  writeFileSync(LINES, text(NUMBERS.map(line => ({ two: 'TWO-user', six: 'SIX-user' })[line] ?? line)))

  // One card: the lines that clash, both sides of them, when each changed and which is newer - and the Coder's test.
  await expect(chat.getByText("Take in Coder's work? · 2 files")).toBeVisible({ timeout: 30_000 })
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
  // Its own test ran in the copy, on the two sides together (it asks for both lines): the project still has the user's line.
  await expect(check.getByText('passed', { exact: true })).toBeVisible({ timeout: 20_000 })
  await expect(check.getByText('exit code 0')).toBeVisible()
  expect(readFileSync(LINES, 'utf8')).toBe(
    text(NUMBERS.map(line => ({ two: 'TWO-user', six: 'SIX-user' })[line] ?? line)),
  )
  // The file is now one that went together, with the lines you chose.
  const merged = chat.getByRole('group', { name: "Merged with the project's changes" })
  await expect(merged).toContainText("lines.txt — Coder's")
  await shot(page, '30-check-passed')

  await chat.getByRole('button', { name: 'Take in', exact: true }).click()
  await expect(page.getByText('DONE', { exact: true })).toBeVisible({ timeout: 15_000 })
  // The Coder's line where they clashed; the user's own change elsewhere is kept - and the Coder's test is in.
  expect(readFileSync(LINES, 'utf8')).toBe(
    text(NUMBERS.map(line => ({ two: 'TWO-agent', six: 'SIX-user' })[line] ?? line)),
  )
  expect(readFileSync(OWN_TEST, 'utf8')).toContain("assert 'TWO-agent' in said and 'SIX-user' in said")
  // Decided: the card is gone. (No commit is offered: the setting is off.)
  await expect(chat.getByText("Take in Coder's work?")).toHaveCount(0)
  await expect(chat.getByRole('group', { name: "Commit of Coder's changes" })).toHaveCount(0)
})
