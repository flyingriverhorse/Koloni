import { expect, test, type Page } from './fixtures'
import { chatSheet, openFreshConversation, openTurns } from './helpers'

async function ask(page: Page, text: string) {
  await page.getByLabel('Message').fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('a command is asked for, runs once, and shows its real output and exit code', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'run the tests')
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  await expect(chat.getByText('Run this command?')).toBeVisible()
  await expect(chat.getByText('This machine')).toBeVisible()

  await chat.getByRole('button', { name: 'Run once' }).click()
  await expect(chat.getByText('The tests pass.')).toBeVisible()
  await expect(chat.getByText('exit 0')).toBeVisible()
  // On the canvas the command is counted on its agent's node (the user's, 5 Nov); in the chat its output is the program's own.
  await expect(page.locator('.react-flow__node-agent')).toContainText('1 command')
  await chat.locator('.tool-row-head').filter({ hasText: 'python check.py' }).click()
  await expect(chat.locator('.tool-row-detail')).toContainText('2 passed')
})

test('"Always run" adds a rule, the next run does not ask, and the rule can be removed', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'run the tests')
  await chat.getByRole('button', { name: 'Always run python check.py' }).click()
  await expect(chat.getByText('The tests pass.')).toHaveCount(1)
  await expect((await chatSheet(page)).getByRole('button', { name: '1 run without asking →' })).toBeVisible()
  await page.keyboard.press('Escape') // (the sheet closed again)

  await ask(page, 'run the tests again')
  await expect(chat.getByText('The tests pass.')).toHaveCount(2)
  await expect(chat.getByText('Run this command?')).toHaveCount(0)
  // The canvas draws one turn: the second, with its command. The first is a row of Recent
  // beside it; picked there, it is the one drawn, with its own command.
  const turns = page.getByRole('complementary', { name: 'Recent' }).locator('.turn-row')
  const request = page.locator('.react-flow__node-request .node-text')
  await openTurns(page)
  await expect(turns).toHaveCount(2)
  await expect(page.locator('.react-flow__node-agent')).toContainText('1 command')
  await expect(request).toHaveText('run the tests again')
  await openTurns(page)
  await expect(turns.first()).toHaveAttribute('aria-current', 'true')
  await turns.last().click()
  await expect(request).toHaveText('run the tests')
  await expect(page.locator('.react-flow__node-agent')).toContainText('1 command')
  await openTurns(page)
  await expect(turns.last()).toHaveAttribute('aria-current', 'true')

  // Removed in Settings › This project › Runs without asking, under the chat's title (tek-ev); ⚙ Chat links there.
  await (await chatSheet(page)).getByRole('button', { name: '1 run without asking →' }).click()
  const rules = page.getByRole('form', { name: 'Project settings' }).getByRole('region', { name: 'Commands and requests by chat' })
  await rules.getByRole('button', { name: 'Remove rule python check.py' }).click()
  await expect(rules.getByRole('button', { name: 'Remove rule python check.py' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Close settings' }).click()

  await ask(page, 'run the tests once more')
  await expect(chat.getByText('Run this command?')).toBeVisible()
  await chat.getByRole('button', { name: 'Reject' }).click()
  await expect(chat.getByText('rejected')).toBeVisible()
})

test('a running command streams its output, survives a reload, and Stop kills it', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'run the slow job')
  await chat.getByRole('button', { name: 'Run once' }).click()
  const row = chat.locator('.tool-row-head').filter({ hasText: 'python -u slow.py' })
  await row.click()
  const output = chat.locator('.tool-row-detail')
  await expect(output).toContainText('tick 2')

  // A reload rebuilds the live output from the server and it keeps arriving.
  await page.reload()
  await row.click()
  await expect(output).toContainText('tick 2')
  const before = ((await output.textContent()) ?? '').length
  await expect.poll(async () => ((await output.textContent()) ?? '').length).toBeGreaterThan(before)

  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect(chat.getByText('killed')).toBeVisible()
  await expect(page.getByText('STOPPED', { exact: true })).toBeVisible()
  // Stopped means stopped: no more output arrives.
  const stopped = ((await output.textContent()) ?? '').length
  await page.waitForTimeout(1500)
  expect(((await output.textContent()) ?? '').length).toBe(stopped)
})
