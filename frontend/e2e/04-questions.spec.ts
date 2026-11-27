import { expect, test, type Page } from './fixtures'
import { openFreshConversation } from './helpers'

async function ask(page: Page, text: string) {
  await page.getByLabel('Message', { exact: true }).fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('the agent asks, waits through a reload, and goes on with the chosen answer', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'which greeting do you want to use?')
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  // (0.1.5: the Orchestrator's question waits on its card over the message box.)
  const card = chat.getByRole('form', { name: 'Orchestrator asks' })
  await expect(card.getByText('Which greeting should I use?')).toBeVisible()
  await expect(page.locator('.react-flow__node-agent')).toContainText('Waits for your answer')

  // The question is a record: it is still there, still open, after a reload.
  await page.reload()
  await expect(card.getByRole('radio', { name: 'hey' })).toBeAttached()

  await card.getByRole('radio', { name: 'hey' }).check()
  await card.getByRole('button', { name: 'Submit' }).click()
  await expect(chat.getByText('Going with hey.')).toBeVisible()
  await expect(chat.getByLabel('Your answer', { exact: true })).toHaveCount(0)
  await expect(chat.getByText('Which greeting should I use?')).toBeVisible()
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()
})

test('a question can be answered in your own words', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'which greeting do you want to use?')
  const card = chat.getByRole('form', { name: 'Orchestrator asks' })
  await card.getByLabel('Your answer').fill('good morning')
  await card.getByRole('button', { name: 'Submit' }).click()
  await expect(chat.getByText('Going with good morning.')).toBeVisible()
})

test('a sub-agent’s question reaches you in the chat and its answer goes back to it', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'be careful with the greeting')
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  // (said once, on its card)
  await expect(chat.getByText('Reviewer asks')).toBeVisible()
  await expect(chat.getByText('Strict or lenient?')).toBeVisible()

  await chat.getByRole('button', { name: 'strict', exact: true }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()
  await expect(chat.getByText('Reviewer asks')).toHaveCount(0)

  // The answer went to the Reviewer: its report says so.
  await chat.getByRole('tab', { name: /Talk/ }).click()
  await expect(chat.getByText('Reviewed in strict mode.')).toBeVisible()
})
