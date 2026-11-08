import { expect, type Page, test } from './fixtures'
import { OWN, openFold, openFreshConversation, rail, shot, openAgentFold } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

test.afterEach(async ({ request }) => {
  // The backend is shared: a price written here is not left for whatever runs after.
  await request.delete('/api/prices?model_id=fake-qwen', { headers: OWN })
})

/** The window of the last agent on the canvas that is called so, opened from the inspector. */
async function openWindowOf(page: Page, name: RegExp) {
  await page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: name }) })
    .last().locator('.node-title').click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  return page.getByRole('region', { name: 'Agent window' })
}

const CACHED = /^[\d,]+ read again from the cache$/
const UNPRICED = 'Cache tokens without a price are left out of the cost.'

test('what the model server read again from its cache is in the agent window and on the Usage rows, and its price is written beside the others', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  // One model step: the scripted server reports 120 sent, 64 of them read from its cache, and 18 written.
  await page.getByLabel('Message').fill('hello from the cache spec')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()

  // The lead's own window has its sum; the server said nothing of what it wrote to its cache.
  await rail(page, 'Canvas').click()
  const own = await openWindowOf(page, /^Orchestrator/)
  // (under Details, with its model and times)
  await expect((await openAgentFold(own, 'Details')).getByText('64 read again from the cache', { exact: true })).toBeVisible()
  await shot(page, '34-agent-window-cache-light')
  await own.getByRole('button', { name: 'Close agent window' }).click()

  await rail(page, 'Usage').click()
  await page.getByLabel('Period').selectOption({ label: 'Today' })
  // Earlier specs' turns are in the same project: this turn is told by its conversation's row.
  await openFold(page, 'By conversation')
  const row = page.getByRole('table', { name: 'Usage by conversation' }).getByRole('row', { name: /hello from the cache spec/ })
  await expect(row.getByRole('cell')).toHaveText(['1', '1', '120', '18'])   // what was sent is as it was
  await expect(row.getByText('64 read again from the cache', { exact: true })).toBeVisible()
  const models = page.getByRole('table', { name: 'Usage by provider and model' })
  const local = models.getByRole('row', { name: /Local · fake-qwen/ })
  await expect(local.getByText(CACHED)).toBeVisible()

  // A price without one for the cache: the cost leaves those tokens out, and says so.
  const prices = page.getByRole('region', { name: 'Prices' })
  await openFold(page, 'Prices')
  await prices.getByLabel('Input price of fake-qwen').fill('1000')
  await prices.getByLabel('Output price of fake-qwen').fill('2000')
  await prices.getByLabel('Currency of fake-qwen').fill('USD')
  await prices.getByRole('button', { name: 'Save the price of fake-qwen' }).click()
  await expect(prices.getByRole('button', { name: 'Remove the price of fake-qwen' })).toBeVisible()
  await expect(local.getByRole('cell').last()).toHaveText(/^≥ [\d,.]+ USD$/)
  await expect(local.getByText(UNPRICED)).toBeVisible()
  await shot(page, '34-usage-cache-light')

  // With a price for what is read from the cache, the note is gone (the server writes to it for nothing).
  await prices.getByLabel('A million read from the cache, for fake-qwen').fill('100')
  await prices.getByRole('button', { name: 'Save the price of fake-qwen' }).click()
  await expect(local.getByText(UNPRICED)).toHaveCount(0)
  await expect(prices.getByLabel('A million read from the cache, for fake-qwen')).toHaveValue('100')
  await expect(prices.getByLabel('A million written to it, for fake-qwen')).toHaveValue('')
  await shot(prices, '34-prices-cache-light')

  // The same rows in the dark theme.
  await page.evaluate(() => localStorage.setItem('koloni-theme', 'dark'))
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  await rail(page, 'Usage').click()
  await page.getByLabel('Period').selectOption({ label: 'Today' })
  await openFold(page, 'By conversation')
  await expect(page.getByRole('table', { name: 'Usage by conversation' }).getByRole('row', { name: /hello from the cache spec/ })
    .getByText('64 read again from the cache', { exact: true })).toBeVisible()
  await shot(page, '34-usage-cache-dark')
})
