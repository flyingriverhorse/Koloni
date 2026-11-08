import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { OWN, openFreshConversation } from './helpers'
import { OUTSIDE_DIR } from './paths.mjs'

// The backend is shared with the other specs: the project works in no folder of its own besides, after this.
test.afterEach(async ({ request }) => {
  const [project] = await (await request.get('/api/projects')).json()
  if (project) await request.patch(`/api/projects/${project.id}`, { headers: OWN, data: { also_in: [], read_in: [] } })
})

test('a file outside the project is asked for, and its folder can be allowed for the conversation and taken back', async ({ page }) => {
  mkdirSync(OUTSIDE_DIR, { recursive: true })
  writeFileSync(path.join(OUTSIDE_DIR, 'notes.md'), 'other notes\n')
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  await page.getByLabel('Message').fill('read the outside notes')
  await page.getByRole('button', { name: 'Send' }).click()
  // Nobody named the folder: the agent's read waits for the user's word.
  await expect(chat.getByText(`Orchestrator wants to read ${path.join(OUTSIDE_DIR, 'notes.md')}, outside the project`)).toBeVisible()
  await chat.getByRole('button', { name: `Allow reading this folder: ${OUTSIDE_DIR}` }).click()
  await expect(chat.getByText('The outside notes say: other notes.')).toBeVisible()
  await expect(chat.getByRole('button', { name: 'Allow once' })).toHaveCount(0)

  // The folder is the conversation's to read in from here on, in the folder button's panel, and taken back with × (slice 86b).
  await page.getByRole('button', { name: /^Folder: / }).click()
  const also = page.getByRole('dialog', { name: 'This chat’s folders' }).getByRole('region', { name: 'Also in this chat' })
  const access = also.getByRole('button', { name: `Access to ${OUTSIDE_DIR}: read; click for read & write` })
  await expect(access).toHaveText('read')
  await also.getByRole('button', { name: `Remove ${OUTSIDE_DIR} from this chat` }).click()
  await expect(access).toHaveCount(0)
})
