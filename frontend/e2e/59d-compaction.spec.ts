import { expect, test } from './fixtures'
import { OWN, openAgentFold, openFreshConversation, rail, shot } from './helpers'

test('the working state is shown under the agent window’s context line, corrected there, and the next turn goes on from the correction', async ({ page, request }) => {
  const lead = async () => (await (await request.get('/api/roles')).json()).find((r: { name: string }) => r.name === 'Lead')
  // A window the fake model's 800 tokens fill past three quarters (the fake is no llama-server).
  expect((await request.patch(`/api/roles/${(await lead()).id}`, { data: { context_window: 1000 }, headers: OWN })).ok()).toBe(true)

  await openFreshConversation(page)
  await page.getByLabel('Message').fill('Fill the state.')
  await page.getByRole('button', { name: 'Send' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByText('Summarised, and on.')).toBeVisible()

  await rail(page, 'Canvas').click()
  await page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Orchestrator/ }) })
    .last().locator('.node-title').click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  const own = page.getByRole('region', { name: 'Agent window' })
  await openAgentFold(own, 'Details')
  await own.getByText('2 messages summarised for its model').click()
  // Its working state, under its headings, as its model wrote it.
  const state = own.locator('.working-state .summary-text')
  await expect(state).toContainText('## Goal\n- fill the state\n## Decisions\n- read hello.py first')
  await expect(state).toContainText('## Lasting facts\n- none')
  await shot(page, '59d-working-state-light')

  await own.getByRole('button', { name: 'Edit working state' }).click()
  const box = own.getByRole('textbox', { name: 'Working state' })
  await box.fill('## Goal\n- fill the state\n- say it in Turkish')
  await page.getByRole('button', { name: 'Theme: switch to dark' }).click()
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  await shot(page, '59d-working-state-edit-dark')
  await own.getByRole('button', { name: 'Save' }).click()
  await expect(box).toHaveCount(0)
  await expect(own.getByRole('button', { name: 'Edit working state' })).toBeFocused()
  await expect(state).toHaveText('## Goal\n- fill the state\n- say it in Turkish')
  await page.getByRole('button', { name: 'Theme: switch to light' }).click()

  // The next turn's lead is sent the user's words: the fake says so only when it reads them.
  await rail(page, 'Chats').click()
  await page.getByRole('button', { name: /^Fill the state\./ }).click()
  await page.getByLabel('Message').fill('And on?')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Going on from your words.')).toBeVisible()

  // Put back, so that later runs start from the defaults.
  expect((await request.post(`/api/roles/${(await lead()).id}/reset`, { headers: OWN })).ok()).toBe(true)
})
