import { expect, test, type Page } from './fixtures'
import { openFreshConversation, editRole } from './helpers'
import { MODEL_URL } from './paths.mjs'

async function ask(page: Page, text: string) {
  await page.getByLabel('Message').fill(text)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('a second provider is added, tested, chosen for a conversation and used by its agent', async ({ page }) => {
  await openFreshConversation(page)

  await page.getByRole('button', { name: 'Models', exact: true }).click()
  await expect(page.getByRole('button', { name: /Local.*default/ })).toBeVisible()
  await page.getByRole('button', { name: /Add a provider/ }).click()
  await page.getByLabel('Name').fill('Second')
  await page.getByLabel('Address').fill(`${MODEL_URL}/v1`)
  await page.getByLabel('API key').fill('sk-e2e-secret')
  await page.getByRole('button', { name: 'Add provider' }).click()
  await page.getByRole('button', { name: /^Second/ }).click()
  await page.getByRole('tab', { name: 'Connection' }).click()
  // the key is saved but never comes back
  await expect(page.getByLabel('API key')).toHaveValue('')
  await expect(page.getByText(/A key is saved/)).toBeVisible()
  await page.getByRole('button', { name: 'Test' }).click()
  await expect(page.getByText(/Reachable · fake-qwen/)).toBeVisible()
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Canvas', exact: true }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('button', { name: /^Model: Local/ }).click()
  await chat.getByLabel('Provider').selectOption({ label: 'Second' })
  await chat.getByRole('button', { name: 'Use this model' }).click()
  await expect(chat.getByRole('button', { name: /^Model: Second/ })).toBeVisible()

  await ask(page, 'hello')
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  await page.locator('.react-flow__node-agent').click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  // (what it runs on, under its name)
  await expect(inspector.locator('.insp-sub')).toContainText('Second')

  // the choice belongs to the conversation and survives a reload
  await page.reload()
  await expect(page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: /^Model: Second/ })).toBeVisible()
})

test('a role can be given its own model on the Agents page', async ({ page }) => {
  await openFreshConversation(page)
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await editRole(page, 'Reviewer', 'tiers')
  await page.getByRole('radio', { name: 'One model' }).check()
  await page.getByLabel('Provider', { exact: true }).selectOption({ label: 'Second' })
  await page.getByRole('button', { name: 'Save' }).click()

  await page.getByRole('button', { name: 'Canvas', exact: true }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await ask(page, 'review the greeting')
  await expect(chat.getByText('The reviewer found no problems.')).toBeVisible()
  await chat.getByRole('button', { name: /Reviewer.*Review hello.py/ }).click()
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  // (what it runs on, under its name)
  await expect(inspector.locator('.insp-sub')).toContainText('Second')

  // put the role back so later runs start from the defaults
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await editRole(page, 'Reviewer', 'tiers')
  await page.getByRole('button', { name: 'Reset to default' }).click()
})
