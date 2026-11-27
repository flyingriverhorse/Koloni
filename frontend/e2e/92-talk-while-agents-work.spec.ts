import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { OWN, openFreshConversation, setProject } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

/** The project's files and what each holds: the same before and after, as nothing of the Coder reached it. */
const files = () =>
  Object.fromEntries(
    readdirSync(PROJECT_DIR)
      .filter(name => name.endsWith('.py'))
      .map(name => [name, readFileSync(path.join(PROJECT_DIR, name), 'utf8')]),
  )

// 0.1.11: the turn stays open while the Orchestrator's agent works in the background - you write to it with Send now
// and it answers in the same turn, the line over the chat says who is at work, and Stop on the agent's node stops it
// alone. The stand-in model holds the Coder's step till it is stopped (fake-model.mjs, `talk92`).
test('92: Send now into the open turn, the line over the chat, and Stop on one agent', async ({ page }) => {
  await setProject(page, { spawn_approval: 'never' })
  const id = await openFreshConversation(page)
  const patched = await page.request.patch(`/api/conversations/${id}`, {
    data: { permission_mode: 'full_auto' },
    headers: OWN,
  })
  expect(patched.ok()).toBe(true)
  const before = files()
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByRole('textbox', { name: 'Message' }).fill('talk while agents work')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  await expect(chat.getByText('Coder is at work on it.')).toBeVisible()
  const line = chat.getByRole('button', { name: /^1 agent at work/ })
  await expect(line).toBeVisible()

  // Your word while the Coder works: into this turn, answered in it.
  await page.getByRole('textbox', { name: 'Message' }).fill('how is it going?')
  await chat.getByRole('button', { name: 'Send now' }).click()
  await expect(chat.getByText('Coder is still at work.')).toBeVisible()
  await expect(line).toBeVisible()

  await line.click()
  const panel = chat.getByRole('region', { name: 'At work in this turn' })
  await expect(panel).toContainText(/Coder · working · since \d\d:\d\d/)
  await expect(panel.getByRole('button', { name: 'Message Coder' })).toBeVisible()

  // Stop on the Coder's node stops it alone: the chat says so, the Orchestrator hears it and the turn ends.
  const coder = page
    .locator('.react-flow__node-agent')
    .filter({ has: page.locator('.node-title', { hasText: /^Coder$/ }) })
  await coder.getByRole('button', { name: 'Stop Coder' }).click()
  await expect(
    chat.getByText('You stopped Coder. Its work so far is kept for your Take in; nothing of it is in the project.'),
  ).toBeVisible()
  await expect(chat.getByText('Coder is stopped; I will not open it again.')).toBeVisible()
  await expect(line).toBeHidden()
  expect(files()).toEqual(before)
  const snap = await (await page.request.get(`/api/conversations/${id}`)).json()
  expect(snap.runs).toHaveLength(1) // (answered in the turn at work: no turn of its own)
})
