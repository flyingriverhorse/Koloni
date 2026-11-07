import { expect, test } from './fixtures'
import { openFreshConversation, openAgentFold } from './helpers'

test('the lead carries on with its Reviewer by sending it a message', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await page.getByLabel('Message').fill('look twice at the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('The reviewer looked twice.')).toBeVisible()

  // The message is one row in the chat: who to whom, and the reply inside.
  const row = chat.getByRole('button', { name: /Orchestrator → Reviewer.*Check the tests too\./ })
  await expect(row).toContainText('done')
  await row.click()
  await expect(chat.getByText('There are no tests to check.')).toBeVisible()

  // Still two agents: the Reviewer took another turn, nobody new was opened.
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
  // (The message and its reply, K-canvas-dili.)
  await expect(page.locator('.react-flow__edge-text', { hasText: '2 messages' })).toBeVisible()

  // The Reviewer's own window shows what it was sent, and what it then said.
  await page.locator('.react-flow__node-agent', { hasText: 'Reviewer' }).click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  const own = page.getByRole('region', { name: 'Agent window' })
  const steps = await openAgentFold(own, 'Every step as recorded')
  await expect(steps.getByText('from Orchestrator')).toBeVisible()
  await expect(steps.getByText('Check the tests too.')).toBeVisible()
  // (what it then said is its report, on top: K-inspector)
  await expect(own.locator('.agent-report').getByText('There are no tests to check.')).toBeVisible()
  await own.getByRole('button', { name: 'Close agent window' }).click()

  await chat.getByRole('tab', { name: /Talk/ }).click()
  await expect(chat.getByText('Orchestrator → Reviewer · task')).toBeVisible()
  await expect(chat.getByText('Reviewer → Orchestrator · report')).toBeVisible()
  await expect(chat.getByText('Orchestrator → Reviewer · message')).toBeVisible()
  await expect(chat.getByText('Reviewer → Orchestrator · reply')).toBeVisible()

  // A reload rebuilds the same conversation between the agents from the records.
  await page.reload()
  await page.getByRole('region', { name: 'Chat' }).getByRole('tab', { name: /Talk/ }).click()
  await expect(page.getByText('Reviewer → Orchestrator · reply')).toBeVisible()
  await expect(page.locator('.react-flow__edge-text', { hasText: '2 messages' })).toBeVisible()
})
