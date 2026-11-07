import { type Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { more, openFreshConversation, shot } from './helpers'

/** Both themes for a picture: the page's own switch is a class on the root (theme.ts). */
const dark = (page: Page, on: boolean) => page.evaluate(on => document.documentElement.classList.toggle('dark', on), on)

test('29c: you pause a running room - it says so, its member holds after the step at hand - and resume it, and it finishes', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await more(page)
  await chat.getByRole('button', { name: /Work together/ }).click()
  const form = chat.getByRole('form', { name: 'Work together' })
  await form.getByLabel('Goal').fill('Pause and go on')
  await form.getByRole('button', { name: 'Open the room' }).click()

  // The Coder asks you (its "blocked" post): the room waits on your card - pause it there.
  const room = page.getByRole('dialog', { name: 'Room: Pause and go on' })
  const waiting = room.getByRole('region', { name: 'Waits for you' })
  await expect(waiting.getByText('Shall the greeting stay hi?')).toBeVisible()
  await room.getByRole('button', { name: 'Pause', exact: true }).click()
  await expect(room.getByRole('status')).toHaveText('paused')
  await expect(room.getByRole('button', { name: 'Resume', exact: true })).toBeVisible()
  // still read, still ended: End stays where it was
  await expect(room.getByRole('button', { name: 'End', exact: true })).toBeEnabled()
  await shot(page, '29c-room-paused-light')
  await dark(page, true)
  await shot(page, '29c-room-paused-dark')
  await dark(page, false)

  // Your answer is taken; the Coder's next step waits for Resume: its item stays taken, nothing more is posted.
  await waiting.getByLabel('Your answer').fill('Yes')
  await waiting.getByRole('button', { name: 'Send answer' }).click()
  const items = room.getByRole('region', { name: 'Items' })
  await page.waitForTimeout(1500)
  await expect(items.locator('summary')).toHaveText(/^taken/)
  await expect(room.getByRole('status')).toHaveText('paused')

  // Small, its tab says it too.
  await room.getByRole('button', { name: 'Make the room small' }).click()
  const tab = page.getByRole('group', { name: 'Rooms' }).getByRole('button', { name: /Room · Pause and go on/ })
  await expect(tab).toContainText('· paused')
  await tab.click()

  await room.getByRole('button', { name: 'Resume', exact: true }).click()
  await expect(room.getByText('done · 1 of 1')).toBeVisible({ timeout: 20_000 })
  await expect(room.getByRole('status')).toBeEmpty()
  await expect(chat.getByText('The room is over')).toBeVisible({ timeout: 20_000 })
})
