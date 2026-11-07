import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { type Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { more, openFreshConversation } from './helpers'

const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'oi-shots')
/** Both themes for a picture: the page's own switch is a class on the root (theme.ts). */
const dark = (page: Page, on: boolean) => page.evaluate(on => document.documentElement.classList.toggle('dark', on), on)

test('K-oda-izle: a room you open is not followed by the Lead until you let it - then your word to it has it end the room', async ({ page }) => {
  mkdirSync(SHOTS, { recursive: true })
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await more(page)
  await chat.getByRole('button', { name: /Work together/ }).click()
  const form = chat.getByRole('form', { name: 'Work together' })
  await form.getByLabel('Goal').fill('Let the Lead follow it')
  await form.getByRole('button', { name: 'Open the room' }).click()

  const room = page.getByRole('dialog', { name: 'Room: Let the Lead follow it' })
  const follow = room.getByRole('switch', { name: /Let the Orchestrator follow/ })
  await expect(follow).not.toBeChecked()
  await expect(follow).toHaveAccessibleDescription(/^Off: the Orchestrator takes no part/)
  // B-195: what following spends comes in sight on the switch's own line - End stays where it was, the line one line.
  const end = room.getByRole('button', { name: 'End', exact: true })
  const row = room.locator('.room-follow')
  const [endBefore, rowBefore] = [await end.boundingBox(), await row.boundingBox()]
  await follow.click()
  await expect(follow).toBeChecked()
  await expect(follow).toHaveAccessibleDescription(/^On: the Orchestrator reads what is said here/)
  await expect(room.getByText('Its steps count toward the room’s tokens.')).toBeVisible()
  expect(await end.boundingBox()).toEqual(endBefore)
  expect((await row.boundingBox())!.height).toBe(rowBefore!.height)
  for (const theme of ['light', 'dark'] as const) {
    await dark(page, theme === 'dark')
    await room.screenshot({ path: path.join(SHOTS, `room-follow-${theme}.png`) })
  }
  await dark(page, false)

  // What you say in the room wakes the Lead that follows it: it ends the room with a sentence, and answers you.
  await room.getByLabel('Say something in the room').fill('End it, Lead.')
  await room.getByRole('button', { name: 'Post', exact: true }).click()
  await expect(room.getByText(/^the Orchestrator ended it/)).toBeVisible({ timeout: 20_000 })
  await expect(follow).toHaveCount(0)
  await expect(chat.getByText('The room is over: the Lead ended it.')).toBeVisible({ timeout: 20_000 })
})
