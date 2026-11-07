// Slice 44 in the browser: a turn's timeline, a strip under the canvas. A Lead hands a file to a
// Coder that waits for you to be opened and for its change to be applied: the strip says who
// waits for you while it does, and afterwards how long; the Coder is drawn under the Lead; a
// click on its bar opens its window; the agent at work, the chat and its buttons stay clear of
// the strip; it is kept open from visit to visit; and its text reads in both themes.
import { rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Locator, type Page } from './fixtures'
import { contrasts, openFreshConversation, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const tidy = () => rmSync(path.join(PROJECT_DIR, 'farewell.py'), { force: true })
test.beforeEach(tidy)
test.afterEach(tidy)

const stripOf = (page: Page) => page.getByRole('region', { name: 'Timeline' })
const rowOf = (strip: Locator, name: string) => strip.getByRole('row').filter({ has: strip.page().getByRole('button', { name, exact: true }) })

/** Every piece of text in it against what it stands on: 4.5 or more. */
async function check(root: Locator, least: number) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThanOrEqual(least)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

async function above(upper: Locator, lower: Locator) {
  const [a, b] = [await upper.boundingBox(), await lower.boundingBox()]
  expect(a && b && a.y + a.height <= b.y + 1, 'drawn above the strip').toBe(true)
}

test('the timeline says who waits for you while it waits and how long afterwards; a sub-agent under its lead; a bar opens its window', async ({ page }) => {
  test.setTimeout(90_000)
  await openFreshConversation(page, { leadWrites: false })
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('make farewell')
  await page.getByRole('button', { name: 'Send' }).click()

  // The Coder is asked about before it starts: open the strip while it waits.
  await expect(chat.getByRole('button', { name: 'Open agent' })).toBeVisible({ timeout: 20_000 })
  const button = page.getByRole('button', { name: 'Timeline', exact: true })
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  await button.click()
  const strip = stripOf(page)
  await expect(rowOf(strip, 'Coder')).toContainText('waits for you')
  await expect(rowOf(strip, 'Orchestrator')).toBeVisible()
  // The Lead at work stays in sight above the strip; the chat stands on it.
  await expect(async () => await above(page.locator('.react-flow__node-agent').first(), strip)).toPass()
  await above(chat, strip)

  await chat.getByRole('button', { name: 'Open agent' }).click()
  // Its change, made in a working copy of its own, waits for you to apply it.
  // (A wait over within a second was none: it is left a second, as a person would.)
  await expect(rowOf(strip, 'Coder')).toContainText(/waits for you \d+s · changes to take in/, { timeout: 20_000 })
  await chat.getByRole('button', { name: 'Take in', exact: true }).click()
  await expect(chat.getByText('The coder added a farewell.')).toBeVisible({ timeout: 20_000 })

  // Over: the Coder under the Lead, done, and what it waited for you said with how long.
  const coder = rowOf(strip, 'Coder')
  await expect(coder).toHaveClass(/tl-depth-1/)
  await expect(coder).toContainText('done')
  await expect(coder.getByText(/^waits/).first()).toBeVisible()
  await expect(coder).toContainText(/\d+s/)
  await expect(strip.getByText('Agents', { exact: true })).toBeVisible()
  // The window of what changed stands clear of the strip too.
  // (under the answer's work line, in its details: slice 107)
  await chat.getByRole('button', { name: 'details ▸' }).click()
  await chat.getByRole('button', { name: 'View changes' }).click()
  await above(page.getByRole('region', { name: 'Workspace' }), strip)
  await shot(strip, '44-timeline')
  await shot(page, '44-timeline-page')

  await coder.locator('.tl-track').click()
  await expect(page.getByRole('region', { name: 'Agent window' })).toContainText('Coder')

  // Kept open from visit to visit.
  await page.reload()
  await expect(stripOf(page)).toBeVisible()
  await stripOf(page).getByRole('button', { name: 'Close timeline' }).click()
  await expect(stripOf(page)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Timeline', exact: true })).toBeFocused()
})

for (const theme of ['light', 'dark'] as const) {
  test(`in the ${theme} theme every text of the timeline stands out from what it is on (contrast 4.5 or more) - its waits too`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page, { leadWrites: false })
    const chat = page.getByRole('region', { name: 'Chat' })
    await page.getByRole('button', { name: 'Timeline', exact: true }).click()
    const strip = stripOf(page)
    await page.getByLabel('Message').fill('make farewell')
    await page.getByRole('button', { name: 'Send' }).click()
    // While the Coder waits for you, and after: its wait said in the table and on its bar.
    await expect(chat.getByRole('button', { name: 'Open agent' })).toBeVisible({ timeout: 20_000 })
    await expect(rowOf(strip, 'Coder')).toContainText('waits for you')
    await check(strip, 12)
    await chat.getByRole('button', { name: 'Open agent' }).click()
    // (A wait over within a second was none: it is left a second, as a person would.)
    await expect(rowOf(strip, 'Coder')).toContainText(/waits for you \d+s · changes to take in/, { timeout: 20_000 })
    await chat.getByRole('button', { name: 'Take in', exact: true }).click()
    await expect(chat.getByText('The coder added a farewell.')).toBeVisible({ timeout: 20_000 })
    await expect(rowOf(strip, 'Coder').locator('.tl-wait .tag')).toHaveCount(1)
    await check(strip, 14)
    await shot(page, `44-timeline-${theme}`)
  })
}

test('on a small window the strip at its tallest leaves the open chat its header, on the stage and above the strip', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await openFreshConversation(page)
  await page.getByLabel('Message').fill('review the greeting')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('The reviewer found no problems.')).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Timeline', exact: true }).click()
  const strip = stripOf(page)
  const edge = strip.getByRole('separator', { name: 'Timeline height' })
  await edge.focus()
  await page.keyboard.press('End')
  const chat = page.getByRole('region', { name: 'Chat' })
  const head = chat.locator('.chat-top')
  const [stage, top] = [await page.locator('.stage').boundingBox(), await head.boundingBox()]
  expect(top!.y).toBeGreaterThanOrEqual(stage!.y)
  await above(head, strip)
  await above(chat, strip)
  await shot(page, '44-timeline-tallest')
})
