import { expect, test } from './fixtures'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { openFreshConversation, openTurns } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

const hello = () => readFileSync(path.join(PROJECT_DIR, 'hello.py'), 'utf8')

test('a message’s changes are undone from ↺ beside it, and the conversation restored to before a message from Recent', async ({ page }) => {
  const before = hello()
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // A turn that changes hello.py, approved.
  await page.getByLabel('Message').fill('flip the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await chat.getByRole('button', { name: 'Approve' }).click()
  await expect(chat.getByText('Updated the greeting in hello.py.')).toBeVisible()
  expect(hello()).not.toBe(before)

  // ↺ beside the message (slice 107): the card looks ahead first, saying the chat stays; nothing is done before Undo.
  const undo = chat.getByRole('button', { name: 'Undo these changes' })
  await expect(undo).toHaveCount(1)
  await undo.click()
  const card = chat.getByRole('region', { name: 'Undo these changes' })
  await expect(card.getByRole('region', { name: 'Will be reverted' })).toContainText('hello.py')
  await expect(card).toContainText('The chat stays as it is: no message is deleted.')
  expect(hello()).not.toBe(before)
  await card.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(card.getByRole('region', { name: 'Reverted', exact: true })).toContainText('hello.py')
  expect(hello()).toBe(before)
  await card.getByRole('button', { name: 'Close' }).click()
  // Its change undone, the message has no ↺ any more.
  await expect(undo).toHaveCount(0)

  // Another turn; then the conversation is put back to before it, from Recent. The chat stays.
  await page.getByLabel('Message').fill('flip the greeting once more')
  await page.getByRole('button', { name: 'Send' }).click()
  await chat.getByRole('button', { name: 'Approve' }).click()
  await expect(chat.getByText('Updated the greeting in hello.py.')).toHaveCount(2)
  expect(hello()).not.toBe(before)
  const turns = await openTurns(page)
  await turns.locator('.recent-row').first().getByRole('button', { name: 'Restore to before this' }).click()
  const restore = turns.getByRole('region', { name: /^Restore to before your .+ message$/ })
  await expect(restore.getByRole('region', { name: 'Will be reverted' })).toContainText('hello.py')
  await restore.getByRole('button', { name: 'Restore', exact: true }).click()
  await expect(restore.getByRole('region', { name: 'Reverted', exact: true })).toContainText('hello.py')
  expect(hello()).toBe(before)
  await expect(chat.getByText('flip the greeting once more')).toBeVisible()
})
