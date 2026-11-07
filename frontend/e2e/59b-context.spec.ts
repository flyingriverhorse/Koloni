import { expect, test } from './fixtures'
import { editRole, openFreshConversation, OWN, rail, openAgentFold } from './helpers'

test('a window set in the Lead role is used: past three quarters its older part is summarised, said with the summary to read, and the record is whole', async ({ page, request }) => {
  await openFreshConversation(page)
  const lead = async () => (await (await request.get('/api/roles')).json()).find((r: { name: string }) => r.name === 'Lead')

  // The fake model is no llama-server: its window is not found, and the user sets one.
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await editRole(page, 'Lead', 'tiers')
  await expect(page.getByText('Found automatically: unknown.')).toBeVisible()
  await page.getByText('Set by hand').click()
  await page.getByLabel('Context window').fill('1000')
  await expect(page.getByText(/Set by you; empty it to use the one found\./)).toBeVisible()
  await page.getByRole('button', { name: 'Save' }).click()
  await expect.poll(async () => (await lead()).context_window).toBe(1000)

  // Its second step sends 800 of 1000: before the third, the older part is summarised.
  await openFreshConversation(page)
  await page.getByLabel('Message').fill('Fill the context.')
  await page.getByRole('button', { name: 'Send' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByText('Summarised, and on.')).toBeVisible()

  await rail(page, 'Canvas').click()
  await page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Orchestrator/ }) })
    .last().locator('.node-title').click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  const own = page.getByRole('region', { name: 'Agent window' })
  await openAgentFold(own, 'Details')
  await expect(own.locator('dt', { hasText: 'Context' }).locator('xpath=following-sibling::dd[1]')).toHaveText(/^12% · 120 in \/ \d+ out$/) // its last step: 120 of 1000
  await own.getByText('2 messages summarised for its model').click()
  await expect(own.getByText('SUMMARY: hello.py prints hi.')).toBeVisible()
  // The record is whole: both calls are in its steps.
  const steps = await openAgentFold(own, 'Every step as recorded')
  await expect(steps.getByText(/read_file/).first()).toBeVisible()
  await expect(steps.getByText(/list_dir/).first()).toBeVisible()

  // Put back, so that later runs start from the defaults.
  expect((await request.post(`/api/roles/${(await lead()).id}/reset`, { headers: OWN })).ok()).toBe(true)
})
