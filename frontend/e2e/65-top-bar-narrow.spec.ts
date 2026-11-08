// Slice 65: in a narrow window the top bar's "Recent" ("Turn 1 of 1" before slice 107) and the turn's state stand apart, not one over the other.
import { expect, test, type Locator } from './fixtures'
import { openFreshConversation } from './helpers'

const box = async (target: Locator) => (await target.boundingBox())!

for (const [width, title] of [
  [700, null],
  // where all but the title still fit on one line: a long title is what gives way
  // (Wide letters: with the gear and Your data gone from the bar - tek-ev - a plain sixty fit at 900 px.)
  [900, 'A CONVERSATION WITH A TITLE FAR TOO LONG FOR THE TOP BAR OF A WINDOW THIS NARROW TO SHOW IT WHOLE'],
] as const)
  test(`at ${width} px Recent and WAITS FOR YOU do not overlap, and both are on the screen${title ? ', with a long title' : ''}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openFreshConversation(page)
    // (The first message is the conversation's title.)
    await page.getByLabel('Message').fill(title ?? 'say hello instead of hi')
    await page.getByRole('button', { name: 'Send' }).click()
    const state = page.locator('[data-run="waiting_approval"]')
    const turns = page.getByRole('button', { name: /^Recent/ })
    await expect(state).toBeVisible()
    await expect(turns).toBeVisible()
    // the title is cut short: what was too long for the line gave way
    if (title) {
      await expect.poll(() => page.locator('.topbar-title strong').evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true)
      // (a long title never takes the bar to a second line)
      expect((await box(page.locator('.topbar'))).height).toBe(52)
    }
    const [a, b] = [await box(turns), await box(state)]
    expect(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y).toBe(true)
    // (and not apart by one of them being pushed off the window)
    for (const each of [a, b]) expect(each.x + each.width).toBeLessThanOrEqual(width)

    // (The file is left as it was.)
    await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Reject' }).click()
    await expect(page.getByText('Okay, I left hello.py unchanged.')).toBeVisible()
  })
