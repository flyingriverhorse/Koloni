import { expect, test } from './fixtures'
import { openFreshConversation, projectSettings, saveSettings } from './helpers'

test('two sub-agents opened in one step work at the same time', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await page.getByLabel('Message').fill('have both files reviewed')
  await page.getByRole('button', { name: 'Send' }).click()

  // Both are at work at once: the top bar counts them, and the chat has a row for each.
  await expect(page.getByText(/WORKING · 2 agents/)).toBeVisible()
  await expect(chat.getByRole('button', { name: /Reviewer 2.*Review check\.py slowly/ })).toContainText('working')
  await expect(chat.getByRole('button', { name: /Reviewer Review hello\.py slowly/ })).toContainText('working')
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(3)

  await expect(chat.getByText('Both reviewers are done.')).toBeVisible({ timeout: 15_000 })
  await expect(chat.getByRole('button', { name: /Reviewer 2.*Review check\.py slowly/ })).toContainText('done')
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()
})

test('with one agent at a time the second waits for a free slot', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  // (Every chat of the project follows it: Settings › This project › Limits and money - tek-ev.)
  const settings = await projectSettings(page, /^Limits and money/)
  await settings.getByLabel('Agents at the same time').fill('1')
  await saveSettings(page)

  await page.getByLabel('Message').fill('have both files reviewed')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByRole('button', { name: /Reviewer 2.*Review check\.py slowly/ })).toContainText(
    'waiting for a slot',
  )
  await expect(page.getByText('Waiting for a slot', { exact: true })).toBeVisible()
  await expect(chat.getByText('Both reviewers are done.')).toBeVisible({ timeout: 20_000 })
})
