import { expect, test, type Page } from './fixtures'
import { openFreshConversation, openAgentFold, projectSettings, saveSettings, windowFromPanel } from './helpers'

async function ask(page: Page, text: string) {
  await page.getByLabel('Message').fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('the lead hands a review to a Reviewer and its report comes back', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'review the greeting')
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()

  // The chat is the lead's conversation: one row for the sub-agent, not its transcript.
  const row = chat.getByRole('button', { name: /Reviewer.*Review hello\.py/ })
  await expect(row).toContainText('done')
  await expect(chat.getByText('Looks fine.')).toHaveCount(0)

  // Two agents on the canvas, each one small node: what the Reviewer did is counted on it (the user's, 5 Nov).
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
  await expect(page.locator('.react-flow__node-agent').nth(1)).toContainText('1 tool')
  await row.click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await expect(inspector.getByText('Review hello.py')).toBeVisible()
  // K-inspector: its report on its card; in its window its raw steps, the last of which does not say it again.
  await expect(inspector.locator('.agent-report').getByText('Looks fine.')).toBeVisible()
  const own = await windowFromPanel(page)
  const steps = await openAgentFold(own, 'Every step as recorded')
  await expect(steps.getByText('Looks fine.')).toHaveCount(0)
  await expect(steps.getByText('read_file hello.py')).toBeVisible()
  await own.getByRole('button', { name: 'Close agent window' }).click()

  await chat.getByRole('tab', { name: /Talk/ }).click()
  await expect(chat.getByText('Orchestrator → Reviewer · task')).toBeVisible()
  await expect(chat.getByText('Reviewer → Orchestrator · report')).toBeVisible()
  await expect(chat.getByText('Looks fine.')).toBeVisible()

  // Reloading shows the same tree and channel from the stored records.
  await page.reload()
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
  await page.getByRole('region', { name: 'Chat' }).getByRole('tab', { name: /Talk/ }).click()
  await expect(page.getByText('Reviewer → Orchestrator · report')).toBeVisible()
})

test('with "Always ask" a sub-agent waits for approval before it starts', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // (Every chat of the project follows it: Settings › This project › Asking and away - tek-ev.)
  const settings = await projectSettings(page, /^Asking and away/)
  await settings.getByLabel('Opening a sub-agent').selectOption('always')
  await saveSettings(page)

  await ask(page, 'review the greeting')
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  await expect(chat.getByText('Open this sub-agent?')).toBeVisible()
  await expect(chat.getByText('depth 1')).toBeVisible()
  await expect(chat.getByText('Looks fine.')).toHaveCount(0)

  await chat.getByRole('button', { name: 'Open agent' }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()
  await expect(chat.getByText('Open this sub-agent?')).toHaveCount(0)
})

test('rejecting a sub-agent returns the decision to the lead', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // (Every chat of the project follows it: Settings › This project › Asking and away - tek-ev.)
  const settings = await projectSettings(page, /^Asking and away/)
  await settings.getByLabel('Opening a sub-agent').selectOption('always')
  await saveSettings(page)

  await ask(page, 'review the greeting')
  await chat.getByRole('button', { name: 'Reject' }).click()
  await expect(chat.getByText('Okay, no review then.')).toBeVisible()
  await expect(chat.getByRole('button', { name: /Reviewer.*Review hello\.py/ })).toContainText('rejected')
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
})

test('a role a sub-agent asks for is decided from the chat and lands on the Agents page', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // Defaults: the read-only Planner opens without asking, then asks for a role.
  await ask(page, 'plan the docs')
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  await expect(chat.getByText('Planner asks')).toBeVisible()
  await expect(chat.getByText('Create this role?')).toBeVisible()
  await expect(chat.getByText('Writes the docs.')).toBeVisible()

  await chat.getByRole('button', { name: 'Create role' }).click()
  await expect(chat.getByText('The plan is ready.')).toBeVisible()
  await expect(chat.getByText('Planner asks')).toHaveCount(0)

  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await page.getByRole('button', { name: /^Documenter/ }).click()
  await expect(page.getByRole('complementary', { name: 'Role Documenter' }).getByText('Created by an agent')).toBeVisible()
})
