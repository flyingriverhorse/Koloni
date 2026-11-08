import { expect, test } from './fixtures'
import { OWN, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const project = async (request: import('@playwright/test').APIRequestContext) => (await (await request.get('/api/projects')).json())[0].id as string

test.afterEach(async ({ request }) => {
  // The backend is shared: a budget left here would hold back every spec's turn after this one.
  await request.patch(`/api/projects/${await project(request)}`, { headers: OWN, data: { monthly_budget: null } })
  await request.delete('/api/prices?model_id=fake-qwen', { headers: OWN })
  // Nor a turn left at work: it would hold hello.py from the specs after this one.
  const conversations: { id: string; title: string }[] = await (await request.get(`/api/projects/${await project(request)}/conversations`)).json()
  for (const { id } of conversations.filter(c => c.title.startsWith('hello from the budget spec'))) {
    const { runs }: { runs: { id: string; status: string }[] } = await (await request.get(`/api/conversations/${id}`)).json()
    for (const run of runs.filter(r => !['completed', 'failed', 'cancelled', 'interrupted'].includes(r.status)))
      await request.post(`/api/runs/${run.id}/cancel`, { headers: OWN })
  }
})

test('a monthly budget: set in Spending, on Usage, a pill at 80% that opens Usage, and over it a turn waits for your word', async ({ page, request }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('hello from the budget spec')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible()
  const price = { model_id: 'fake-qwen', input: 1000, output: 2000, currency: 'USD' }
  expect((await request.put('/api/prices', { headers: OWN, data: price })).ok()).toBe(true)
  const pid = await project(request)
  // Earlier specs' turns of this month are in the same project: the budget is set from what is spent.
  const { spent } = await (await request.get(`/api/projects/${pid}/budget`)).json()
  expect(spent).toBeGreaterThan(0)

  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  await settings.getByRole('button', { name: /^Limits and money/ }).click()
  await settings.getByLabel('Monthly budget').fill((spent / 0.85).toFixed(6))
  await settings.getByRole('button', { name: 'Save' }).click()
  const pill = page.getByRole('banner').getByRole('button', { name: /^Budget (over · )?\d+%$/ })
  await expect(pill).toHaveAccessibleName(/^Budget 8\d%$/)
  await expect(pill).toHaveAttribute('title', /^This project has used (at least )?8\d% of its monthly budget\. Opens Usage\.$/)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()

  await pill.click()
  const section = page.getByRole('region', { name: 'This month’s budget' })
  await expect(section.getByRole('meter', { name: 'Monthly budget used' })).toBeVisible()
  await expect(section.getByText(/USD/)).toBeVisible()
  // Read here, set in the project's settings.
  await section.getByRole('button', { name: 'Change in Settings →' }).click()
  await expect(settings.getByLabel('Monthly budget')).toBeVisible()
  await rail(page, 'Usage').click()
  await shot(page, '55-usage-budget')

  // Over it: the message waits for the user's word, and goes on with it.
  expect((await request.patch(`/api/projects/${pid}`, { headers: OWN, data: { monthly_budget: spent / 2 } })).ok()).toBe(true)
  await rail(page, 'Canvas').click()
  await expect(pill).toHaveAccessibleName(/^Budget over · \d+%$/, { timeout: 10_000 })
  await expect(pill).toHaveAttribute('title', /a new message asks before its work starts/)
  await page.getByLabel('Message').fill('one more over the budget')
  await page.getByRole('button', { name: 'Send' }).click()
  const card = chat.getByRole('group', { name: 'Over this month’s budget' })
  await expect(card).toContainText('Send it anyway?')
  await shot(page, '55-over-budget')
  await card.getByRole('button', { name: 'Go on anyway' }).click()
  await expect(card).toHaveCount(0)
  // (.first(): on a CI runner the words showed twice at this moment - the message and a second place.)
  await expect(chat.getByText('one more over the budget').first()).toBeVisible()
  await expect(page.getByLabel('Message')).toHaveValue('')
})
