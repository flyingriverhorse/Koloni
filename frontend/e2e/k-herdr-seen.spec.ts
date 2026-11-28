// herdr's "done, not seen" (28 Nov 2026): a chat whose turn ended while you were on another page says so on Chats,
// until you open it; one that ended on screen does not.
import { expect, test } from './fixtures'
import { OWN, messageBox, openFreshConversation } from './helpers'

test('a chat whose turn ended while you were on Chats says "not seen" there until it is opened', async ({ page }) => {
  const id = await openFreshConversation(page)
  const title = `herdr seen ${Date.now()}`
  expect((await page.request.patch(`/api/conversations/${id}`, { data: { title }, headers: OWN })).ok()).toBe(true)
  const chat = page.getByRole('region', { name: 'Chat' })

  // Its turn ends on screen: seen.
  await messageBox(page).fill('hello')
  await messageBox(page).press('Enter')
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible({ timeout: 20_000 })
  const chats = page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Chats', exact: true })
  await chats.click()
  const row = page.getByRole('button', { name: new RegExp(`^${title}`) })
  await expect(row).toContainText('Done', { timeout: 20_000 })
  await expect(row).not.toContainText('not seen')

  // Its next turn ends while you are here, on Chats: not seen - and Now puts it before what is only done.
  const sent = await page.request.post(`/api/conversations/${id}/messages`, {
    data: { content: 'hello again' },
    headers: OWN,
  })
  expect(sent.ok()).toBe(true)
  await expect(row).toContainText('Done · not seen', { timeout: 20_000 })
  const now = page.getByRole('complementary', { name: 'Now every folder' })
  await expect(now.getByRole('img', { name: `“${title}”: done · not seen` })).toBeVisible()

  // Opened, it is seen.
  await row.click()
  await expect(chat.getByText('hello again', { exact: true })).toBeVisible()
  await chats.click()
  await expect(row).toContainText('Done', { timeout: 20_000 })
  await expect(row).not.toContainText('not seen', { timeout: 20_000 })
})
