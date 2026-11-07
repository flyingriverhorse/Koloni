import { expect, test } from './fixtures'
import { OWN, openFreshConversation, rail, openFold, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

test.afterEach(async ({ request }) => {
  // The backend is shared: a price written here is not left for whatever runs after.
  await request.delete('/api/prices?model_id=fake-qwen', { headers: OWN })
})

test('a turn’s tokens are on the Usage page, its conversation opens from there, and a price you write becomes a cost', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  // One model step: the scripted model reports 120 tokens sent and 18 written for it.
  await page.getByLabel('Message').fill('hello from the usage spec')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()

  await rail(page, 'Usage').click()
  await expect(page.getByLabel('Projects')).toHaveValue('this')
  await page.getByLabel('Period').selectOption({ label: 'Today' })
  // Earlier specs' turns are in the same project: this turn is told by its conversation's row,
  // under its folded heading (slice 60a).
  await openFold(page, 'By conversation')
  await openFold(page, 'Who started it')
  const talks = page.getByRole('table', { name: 'Usage by conversation' })
  const row = talks.getByRole('row', { name: /hello from the usage spec/ })
  await expect(row.getByRole('cell')).toHaveText(['1', '1', '120', '18'])
  const models = page.getByRole('table', { name: 'Usage by provider and model' })
  const local = models.getByRole('row', { name: /Local · fake-qwen/ })
  await expect(local).toBeVisible()
  // No price was written: no money is shown, and the page says where one is written, once: by the Cost box.
  await expect(local.getByRole('cell').last()).toHaveText('–')
  await expect(page.getByText(/^Cost shows for a model with a price: yours, or else models\.dev’s/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'set prices' })).toHaveCount(1)
  await expect(page.getByRole('table', { name: 'Usage by who sent the message' }).getByRole('row', { name: /^You/ })).toBeVisible()
  await shot(page, '21-usage')

  // A price for the model the agents ran on is written on the same page, under the tables: the Cost box opens it.
  const prices = page.getByRole('region', { name: 'Prices' })
  await page.getByRole('button', { name: 'set prices' }).click()
  await prices.getByLabel('Input price of fake-qwen').fill('1000')
  await prices.getByLabel('Output price of fake-qwen').fill('2000')
  await prices.getByLabel('Currency of fake-qwen').fill('USD')
  await prices.getByRole('button', { name: 'Save the price of fake-qwen' }).click()
  await expect(prices.getByRole('button', { name: 'Remove the price of fake-qwen' })).toBeVisible()
  await shot(page, '21-prices')

  // The usage is read again: the cost is there without leaving the page.
  // (The row adds up every spec's turns of today: one that was stopped mid-step makes it "at least".)
  await expect(local.getByRole('cell').last()).toHaveText(/^[≈≥] [\d,.]+ USD$/)
  await expect(page.getByText(/from the prices you entered\. Cache reads and writes are counted at the cache prices you gave/)).toBeVisible()
  await shot(page, '21-usage-with-a-cost')

  // The row opens its conversation.
  await page.getByRole('table', { name: 'Usage by conversation' }).getByRole('button', { name: 'hello from the usage spec' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Hello! Ask me to read or change a file.')).toBeVisible()
})
