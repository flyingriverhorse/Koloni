import { expect, test, type Page } from './fixtures'
import { openFreshConversation } from './helpers'

async function ask(page: Page, text: string) {
  await page.getByLabel('Message').fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('the agent asks, waits through a reload, and goes on with the chosen answer', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'which greeting do you want to use?')
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  await expect(chat.getByText('Which greeting should I use?')).toBeVisible()
  await expect(page.locator('.react-flow__node-agent')).toContainText('Waits for your answer')

  // The question is a record: it is still there, still open, after a reload.
  await page.reload()
  await expect(page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'hey' })).toBeVisible()

  await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'hey' }).click()
  await expect(chat.getByText('Going with hey.')).toBeVisible()
  await expect(chat.getByLabel('Your answer')).toHaveCount(0)
  await expect(chat.getByText('Which greeting should I use?')).toBeVisible()
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()
})

test('a question can be answered in your own words', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'which greeting do you want to use?')
  await chat.getByLabel('Your answer').fill('good morning')
  await chat.getByRole('button', { name: 'Send answer' }).click()
  await expect(chat.getByText('Going with good morning.')).toBeVisible()
})

test('a sub-agent’s question reaches you in the chat and its answer goes back to it', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await ask(page, 'be careful with the greeting')
  await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
  await expect(chat.getByText('Reviewer asks')).toBeVisible()
  await expect(chat.getByText('Strict or lenient?')).toBeVisible()

  await chat.getByRole('button', { name: 'strict', exact: true }).click()
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()
  await expect(chat.getByText('Reviewer asks')).toHaveCount(0)

  // The answer went to the Reviewer: its report says so.
  await chat.getByRole('tab', { name: /Talk/ }).click()
  await expect(chat.getByText('Reviewed in strict mode.')).toBeVisible()
})
