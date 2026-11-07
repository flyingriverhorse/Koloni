import { expect, test } from './fixtures'
import { editRole, openFreshConversation, OWN } from './helpers'

test('a model that says no levels offers none; levels kept for a role and a conversation are shown as not sent to it, and can be taken back', async ({ page, request }) => {
  const url = `/api/conversations/${await openFreshConversation(page)}`
  const agents = page.getByRole('button', { name: 'Agents', exact: true })
  const coder = async () => (await (await request.get('/api/roles')).json()).find((r: { name: string }) => r.name === 'Coder')
  const picker = page.getByRole('button', { name: /^Model:/ })

  // The fake model (OpenAI-compatible) says no levels: the Lead's select offers none, and says why.
  await picker.click()
  await expect(page.getByText(/The model’s levels are not known: nothing is sent\./)).toBeVisible()
  await expect(page.getByLabel('Thinking')).toBeDisabled()
  await picker.click()

  // Levels kept from the app's own page are shown as they are, and as not sent to this model.
  expect((await request.patch(url, { data: { lead_effort: 'max' }, headers: OWN })).ok()).toBe(true)
  const role = `/api/roles/${(await coder()).id}`
  expect((await request.patch(role, { data: { effort: 'high', max_effort: 'xhigh' }, headers: OWN })).ok()).toBe(true)
  await page.reload()
  await picker.click()
  await expect(page.getByLabel('Thinking')).toHaveValue('max')
  await expect(page.getByLabel('Thinking').locator('option:checked')).toHaveText('Max (not sent to this model)')
  await picker.click()
  await agents.click()
  await editRole(page, 'Coder', 'tiers')
  await expect(page.getByText(/The model’s levels are not known: nothing is sent\./)).toBeVisible()
  // K-ladder: one fixed level, checked on the ladder and struck (not taken by this model); its most set earlier said below.
  const mode = (name: string) => page.getByRole('radiogroup', { name: 'Thinking' }).getByRole('radio', { name, exact: true })
  const rung = (group: string, name: string) => page.getByRole('radiogroup', { name: group }).getByRole('radio', { name, exact: true })
  await expect(mode('One fixed level')).toBeChecked()
  await expect(rung('Fixed level', 'High')).toBeChecked()
  await expect(rung('Fixed level', 'High')).toBeDisabled()
  await expect(page.getByText(/The Orchestrator may also go up to XHigh \(set earlier\)\./)).toBeVisible()

  // Its most removed, taken back to Auto on the page, and kept.
  await page.getByRole('button', { name: 'Remove the most of XHigh' }).click()
  await mode('Auto').check()
  await page.getByRole('button', { name: 'Save' }).click()
  await expect.poll(async () => [(await coder()).effort, (await coder()).max_effort]).toEqual([null, null])
  await editRole(page, 'Coder', 'tiers')
  await expect(mode('Auto')).toBeChecked()
  await expect(rung('Most the Orchestrator may pick', 'Low')).toBeDisabled()

  // Put back, so that later runs start from the defaults.
  expect((await request.post(`${role}/reset`, { headers: OWN })).ok()).toBe(true)
  expect((await request.patch(url, { data: { lead_effort: null }, headers: OWN })).ok()).toBe(true)
})
