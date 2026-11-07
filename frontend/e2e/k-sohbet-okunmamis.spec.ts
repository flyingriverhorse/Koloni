// The closed chat's number is what came unread (spec 38 §2): a reply that arrives while the chat
// is folded is counted on its line, in both themes readable, and opening the chat clears it.
import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test } from './fixtures'
import { contrasts, openFreshConversation } from './helpers'

const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'ur-shots')

test.use({ viewport: { width: 1440, height: 900 } })

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme a reply that comes while the chat is closed is "1 unread" on its line, gone once it is opened`, async ({ page }) => {
    mkdirSync(SHOTS, { recursive: true })
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    const line = chat.getByRole('button', { name: /^Chat/ })
    // nothing unread yet; your own message is not counted
    await chat.getByLabel('Message').fill('hello, while it is closed')
    await chat.getByLabel('Message').press('Enter')
    await expect(line).toContainText('Hello! Ask me to read or change a file.', { timeout: 20_000 })
    const unread = line.getByText('1 unread')
    await expect(unread).toBeVisible()
    await expect(line).toHaveAccessibleName(/1 unread/)
    const pieces = await unread.evaluate(contrasts)
    expect(pieces).toHaveLength(1)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    await chat.screenshot({ path: path.join(SHOTS, `closed-unread-${theme}.png`) })

    await line.click()
    await expect(chat.getByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-selected', 'true')
    await chat.getByRole('button', { name: 'Hide chat' }).click()
    await expect(line).not.toContainText('unread')
    await chat.screenshot({ path: path.join(SHOTS, `closed-read-${theme}.png`) })
  })
