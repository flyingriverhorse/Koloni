// Slice 56 in the browser, on Usage since tek-ev §3: Today is Usage's first period - the day counted from the record
// (what failed and the files changed, beside the boxes the usage adds up), and the numbers said in words by a model
// of the Lead's (its first fast one, or its own), named and marked as its text.
import { expect, test } from './fixtures'
import { OWN, contrasts, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

test('the day of the project on Usage › Today: the files changed and what failed, and words the model says', async ({ page }) => {
  const TITLE = 'make the day page of slice 56'
  const id = await openFreshConversation(page)
  // (Its change is taken without asking: what reached the project is what Today counts.)
  const patched = await page.request.patch(`/api/conversations/${id}`, { data: { permission_mode: 'full_auto' }, headers: OWN })
  expect(patched.ok()).toBe(true)
  await page.getByLabel('Message').fill(TITLE)
  await page.getByRole('button', { name: 'Send' }).click()
  const last = async () => (await (await page.request.get(`/api/conversations/${id}`)).json()).runs.at(-1)?.status
  await expect.poll(last, { timeout: 20_000 }).toBe('completed')

  await rail(page, 'Usage').click()
  await expect(page.getByLabel('Period')).toHaveValue('today')
  const today = page.getByRole('region', { name: 'Today' })
  const box = (label: string) => today.locator('.usage-stats > div', { has: page.locator('dt', { hasText: label }) })
  await expect(box('Files changed').locator('.usage-stat')).toHaveText(/^[1-9]\d*$/)
  await expect(box('Failed').locator('.usage-stat')).toHaveText(/^\d+$/)
  // The usage's own boxes are there too: messages, tokens and cost.
  await expect(page.locator('.usage-stats dt', { hasText: 'Messages' })).toBeVisible()
  expect((await today.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])

  // Said in words: once, by a model of the open conversation's Lead, and marked as its text.
  await today.getByRole('button', { name: 'Say it in words' }).click()
  const said = today.getByRole('figure', { name: 'Model text' })
  await expect(said).toContainText('A day of one change. Nothing failed.')
  await expect(said).toContainText(/^Model text · /)
  await shot(page, '56-today')

  // Another period has no day of its own.
  await page.getByLabel('Period').selectOption({ label: '7 days' })
  await expect(today).toHaveCount(0)
})
