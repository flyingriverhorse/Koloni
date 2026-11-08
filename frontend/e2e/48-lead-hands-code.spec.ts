import { rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { openFreshConversation, projectSettings, saveSettings } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

const tidy = () => rmSync(path.join(PROJECT_DIR, 'farewell.py'), { force: true })
test.beforeEach(tidy)
test.afterEach(tidy)

test('in a new conversation the Lead hands code to a Coder; switched to doing it itself and saved, that is kept', async ({ page, request }) => {
  const url = `/api/conversations/${await openFreshConversation(page, { leadWrites: false })}`
  // Files are written without asking: neither the Coder nor its change waits for a decision.
  await page.getByLabel('Permission level').selectOption('auto_edit')
  await expect(page.getByLabel('Permission level')).toHaveValue('auto_edit')

  // (Every chat of the project follows it: Settings › This project › Agents - tek-ev.)
  const settings = await projectSettings(page, /^Agents/)
  await expect(settings.getByLabel('Who changes the files')).toHaveValue('delegates')
  await page.getByRole('button', { name: 'Close settings' }).click()

  await page.getByLabel('Message').fill('make farewell')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('The coder added a farewell.')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('.react-flow__node-agent').filter({ hasText: 'Coder' })).toHaveCount(1)

  const snap = await (await request.get(url)).json()
  const coder = snap.agents.find((a: { role_name: string }) => a.role_name === 'Coder')
  expect(snap.file_changes.map((c: { path: string; agent_id: string }) => [c.path, c.agent_id])).toEqual([['farewell.py', coder.id]])

  await projectSettings(page, /^Agents/)
  await settings.getByLabel('Who changes the files').selectOption('itself')
  await saveSettings(page)
  await expect.poll(async () => (await (await request.get(url)).json()).conversation.lead_hands_code).toBe(false)
  // opened again, it starts from what is saved
  await projectSettings(page, /^Agents/)
  await expect(settings.getByLabel('Who changes the files')).toHaveValue('itself')
})
