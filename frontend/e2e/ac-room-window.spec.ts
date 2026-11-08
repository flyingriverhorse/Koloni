import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { more, openFreshConversation } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

// The three states of the room's window, kept for the slice's report (outside the repo, as runtime/shots is).
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'ac-shots')
const keep = async (page: Page, name: string) => {
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) })
}

// The room changes the project's hello.py: each run starts from the greeting as it was, and leaves it so for the specs after.
const HELLO = path.join(PROJECT_DIR, 'hello.py')
let was = ''
test.beforeEach(() => {
  was ||= readFileSync(HELLO, 'utf8')
  writeFileSync(HELLO, was)
})
test.afterEach(() => writeFileSync(HELLO, was))

for (const theme of ['light', 'dark'] as const) {
  test(`AC (${theme}): a room opens as a window, — makes it a tab that says it waits for you, and once over the same window says what came of it`, async ({ page }) => {
    test.setTimeout(90_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    // (no Room tab in the chat, and Channel is Talk)
    await expect(chat.getByRole('tab')).toHaveText(['Chat', 'Talk', 'Notes'])

    await more(page)
    await chat.getByRole('button', { name: /Work together/ }).click()
    const form = chat.getByRole('form', { name: 'Work together' })
    await form.getByLabel('Goal').fill('Change the greeting together')
    await form.getByLabel('Posts by its members').fill('30')
    await form.getByRole('button', { name: 'Open the room' }).click()

    // 1 · A room opens: its own window over the canvas, which stays usable around it.
    const room = page.getByRole('dialog', { name: 'Room: Change the greeting together' })
    await expect(room).toBeVisible()
    await expect(room).toContainText('Room · Change the greeting together')
    await expect(room.getByRole('region', { name: 'The room', exact: true })).toContainText('Coder · Reviewer · opened by you')
    const waiting = room.getByRole('region', { name: 'Waits for you' })
    await expect(waiting.getByText('Shall the greeting stay hi?')).toBeVisible({ timeout: 20_000 })
    await expect(room.getByRole('group', { name: 'Said in the room' })).toHaveAttribute('open')
    await expect(room.getByRole('button', { name: 'Give it more' })).toBeVisible()
    await expect(room.getByRole('button', { name: 'End', exact: true })).toBeVisible()
    // the question is in Ready for you too: the top bar's pill counts it (tek-ev §1)
    await expect(page.locator('.ready-pill')).toHaveText(/^\d+ waits?$/)
    await keep(page, `ac-1-a-room-opens-${theme}`)

    // 2 · Made small (—): a tab at the canvas's foot that says it waits for you; the focus goes to it.
    await room.getByRole('button', { name: 'Make the room small' }).click()
    await expect(room).toHaveCount(0)
    const tab = page.getByRole('button', { name: /^Room · Change the greeting together · 1 post waits for you$/ })
    await expect(tab).toBeFocused()
    await expect(tab).toHaveClass(/asks/)
    await keep(page, `ac-2-made-small-${theme}`)
    // The tab opens it again, the focus going into it; Esc makes it small again, and × too while it runs.
    await tab.click()
    await expect(room).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(room).toHaveCount(0)
    await tab.click()
    await room.getByRole('button', { name: 'Close the room' }).click()
    await expect(tab).toBeVisible()
    await tab.click()

    // You answer; the Coder changes the greeting in the room's copy, and everybody's work is over.
    await waiting.getByLabel('Your answer').fill('Make it hi there')
    await waiting.getByRole('button', { name: 'Send answer' }).click()

    // 3 · It ended: the same window says what came of it - its line, the room's changes From you, the items, the rest folded.
    await expect(room.getByText('done · 1 of 1')).toBeVisible({ timeout: 20_000 })
    await expect(room.locator('.room-summary')).toHaveText('hello.py now says hi there.')
    const fromYou = room.getByRole('region', { name: 'From you' })
    await expect(fromYou).toContainText('hello.py')
    await expect(fromYou.getByRole('button', { name: 'Take in', exact: true })).toBeVisible()
    await expect(fromYou.getByRole('button', { name: 'Discard' })).toBeVisible()
    await expect(room.getByRole('region', { name: 'Items' })).toContainText('✓ done1. Look at the greetingCoder')
    await expect(room.getByRole('group', { name: 'Said in the room' })).not.toHaveAttribute('open')
    const reports = room.getByRole('group', { name: 'Reports' })
    await expect(reports).not.toHaveAttribute('open')
    await expect(reports.locator('summary')).toHaveText('Reports Reviewer · Coder') // in the order they reported
    await expect(room).not.toContainText('its work is over')
    await keep(page, `ac-3-it-ended-${theme}`)
    await fromYou.getByRole('button', { name: 'Take in', exact: true }).click()
    await expect(page.getByText('DONE', { exact: true })).toBeVisible({ timeout: 20_000 })
    expect(readFileSync(HELLO, 'utf8')).toBe("print('hi there')\n")

    // × closes it for good; in the chat the room is one line, which opens it again.
    await room.getByRole('button', { name: 'Close the room' }).click()
    await expect(room).toHaveCount(0)
    await expect(page.getByRole('group', { name: 'Rooms' })).toHaveCount(0)
    const line = chat.getByRole('button', { name: /^Room · Change the greeting together done · 1 of 1 · Open/ })
    await expect(line).toHaveCount(1)
    await expect(chat).not.toContainText('Looked at it: fine.')
    await line.click()
    await expect(room.locator('.room-summary')).toHaveText('hello.py now says hi there.')
  })
}
