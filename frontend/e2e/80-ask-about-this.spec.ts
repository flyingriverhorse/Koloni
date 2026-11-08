// Slice 80 in the browser: lines selected in the Workspace's file view show "Ask about this" by them; Esc puts it
// away, the first Tab reaches it, and it puts the file's path, the lines and their text fenced into the message box.
import { rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from './fixtures'
import { openFreshConversation } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const FILE = path.join(PROJECT_DIR, 'ask80.py')
test.beforeAll(() => writeFileSync(FILE, 'def pay():\n    total = 1\n    total += 2\n    return total\n\nprint(pay())\n'))
test.afterAll(() => rmSync(FILE, { force: true }))

/** Lines 2 to 4 of the file view, selected as a drag would: from the start of one line's text to the end of another's. */
const selectLines = (page: Page) =>
  page.locator('.changes-body').evaluate(body => {
    const texts = body.querySelectorAll('.diff-text')
    const range = document.createRange()
    range.setStart(texts[1], 0)
    range.setEnd(texts[3], texts[3].childNodes.length)
    document.getSelection()!.removeAllRanges()
    document.getSelection()!.addRange(range)
  })

test('selected lines of a file are asked about: path, lines and text in the message box', async ({ page }) => {
  await openFreshConversation(page)
  await page.getByRole('button', { name: /^Workspace/ }).click()
  const files = page.getByRole('region', { name: 'Workspace' })
  await files.getByRole('tree', { name: 'Files' }).getByRole('treeitem', { name: 'ask80.py' }).click()
  await expect(files.locator('.changes-body .diff-text').nth(3)).toContainText('return total')

  const ask = page.getByRole('button', { name: 'Ask about this' })
  await selectLines(page)
  await expect(ask).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(ask).toHaveCount(0)
  await expect(files).toBeVisible() // (that Esc was the button's, not the window's)
  // (put away for this selection: a scroll does not bring it back)
  await page.evaluate(() => document.dispatchEvent(new Event('scroll')))
  await expect(ask).toHaveCount(0)

  await page.evaluate(() => document.getSelection()!.removeAllRanges())
  await selectLines(page)
  await expect(ask).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(ask).toBeFocused()
  // The first Tab only: from it on Tab goes on, a scroll between or not.
  await page.keyboard.press('Tab')
  await expect(ask).not.toBeFocused()
  await page.evaluate(() => document.dispatchEvent(new Event('scroll')))
  await page.keyboard.press('Tab')
  await expect(ask).not.toBeFocused()
  await ask.focus()
  expect(await page.evaluate(() => document.getSelection()!.toString())).toContain('total += 2')
  await page.keyboard.press('Enter')
  const box = page.getByLabel('Message')
  await expect(box).toHaveValue('ask80.py:2–4:\n```\n    total = 1\n    total += 2\n    return total\n```\n\n')
  await expect(box).toBeFocused()
  await expect(ask).toHaveCount(0)
})
