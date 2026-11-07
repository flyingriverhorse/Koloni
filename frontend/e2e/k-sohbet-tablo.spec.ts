import { expect, test } from './fixtures'
import { openFreshConversation } from './helpers'

// B-334 (live): a seven-column table broke letter by letter ("S-t-e-p") in the 480 px chat, and
// the URL chip of the user's message stood its label U / R / L.
test('a wide table scrolls in its own box with whole words, and a long link keeps its label on one line', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill(`show me a wide table http://127.0.0.1:9/${'a'.repeat(120)}`)
  await page.getByRole('button', { name: 'Send' }).click()
  const table = chat.locator('.markdown table')
  await expect(table).toBeVisible()
  const box = await table.evaluate(t => ({ scroll: t.scrollWidth, client: t.clientWidth, overflow: getComputedStyle(t).overflowX }))
  expect(box.overflow).toBe('auto')
  expect(box.scroll).toBeGreaterThan(box.client)
  // (one line each: a word is never cut)
  for (const word of ['Step', 'engineer', 'summary']) {
    const cell = table.getByRole('columnheader', { name: word })
    const [height, line] = await cell.evaluate(c => [c.clientHeight, parseFloat(getComputedStyle(c).lineHeight)])
    expect(height).toBeLessThan(line * 2 + 8)
  }
  const label = chat.locator('.att-mini i', { hasText: 'URL' })
  const [height, width] = await label.evaluate(i => [i.getBoundingClientRect().height, i.getBoundingClientRect().width])
  expect(height).toBeLessThan(width)
})
