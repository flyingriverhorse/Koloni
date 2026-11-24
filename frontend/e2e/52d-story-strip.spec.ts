// 0.1.8, a story's strip and notebook in the browser: a story with a note of the Hive keeper's, given to a new chat
// (Do in chat ▾ → A new chat) while Stop everything holds its queue, says itself on one line over the chat - "Story ·
// <name> · 1 / 2 · next: <task> · 📓 notes" - and its 📓 opens the notebook. Once its first task's turn has ended,
// the notebook says how (KOLONİ's result line), from the 📓 on the story's topic line too.
import { expect, test } from './fixtures'
import { OWN, e2eProject, openFreshConversation, rail } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const STAMP = Date.now().toString(36)
const STORY = `Password reset (${STAMP})`
const FIRST = `Send the reset mail (${STAMP})`
const SECOND = `Expire the link (${STAMP})`
const NOTE = 'mail goes by SMTP, not an API'

test.afterEach(async ({ page }) => {
  await page.request.post('/api/hold/resume', { headers: OWN }) // (as the spec held it, whatever came of it)
  const pid = await e2eProject(page)
  const left: { id: string; title: string }[] = await (await page.request.get(`/api/projects/${pid}/backlog`)).json()
  for (const task of left.filter(one => one.title.endsWith(`(${STAMP})`)))
    await page.request.delete(`/api/backlog/${task.id}`, { headers: OWN })
  const tree: { stories: { id: string; title: string }[] } = await (
    await page.request.get(`/api/projects/${pid}/stories`)
  ).json()
  for (const story of tree.stories.filter(one => one.title === STORY))
    await page.request.delete(`/api/stories/${story.id}`, { headers: OWN })
})

test("a story at work in a chat: the strip over it, and its notebook from the strip's 📓", async ({ page }) => {
  await openFreshConversation(page)
  const pid = await e2eProject(page)
  const tree = { stories: [{ title: STORY, notes: [NOTE], tasks: [{ title: FIRST }, { title: SECOND }] }] }
  expect((await page.request.post(`/api/projects/${pid}/backlog/tree`, { headers: OWN, data: tree })).ok()).toBe(true)
  await rail(page, 'To-do').click()
  await page
    .getByRole('list', { name: 'Tasks' })
    .getByRole('checkbox', { name: `Tick the story ${STORY}` })
    .check()
  // (Stop everything holds the queue: the strip is seen before the story's first task runs.)
  expect((await page.request.post('/api/hold', { headers: OWN })).ok()).toBe(true)
  await page
    .getByRole('region', { name: 'Selected tasks' })
    .getByRole('button', { name: /Do in chat/ })
    .click()
  await page.getByRole('menuitem', { name: 'A new chat' }).click()

  const strip = page.getByRole('region', { name: 'Story' })
  await expect(strip).toHaveText(`Story · ${STORY} · 1 / 2 · next: ${SECOND} · 📓 notes`, { timeout: 20_000 })
  const notes = strip.getByRole('button', { name: 'notes' })
  await expect(notes).toHaveAttribute('aria-expanded', 'false')
  await notes.click()
  const notebook = page.getByRole('dialog', { name: `Notebook of ${STORY}` })
  await expect(notebook).toContainText(NOTE)
  await expect(notebook).toContainText('Hive keeper')
  await page.keyboard.press('Escape')

  // Resumed: the first task runs; its end is in the notebook - from the topic line's 📓 too.
  expect((await page.request.post('/api/hold/resume', { headers: OWN })).ok()).toBe(true)
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByRole('group', { name: `Done? — “${FIRST}”` })).toBeVisible({ timeout: 20_000 })
  const line = chat
    .getByRole('separator')
    .filter({ hasText: `Topic · Story · ${STORY}` })
    .first()
  await line.getByRole('button', { name: 'notes' }).click({ timeout: 20_000 })
  await expect(page.getByRole('dialog', { name: `Notebook of ${STORY}` })).toContainText(`“${FIRST}” — done?`, {
    timeout: 20_000,
  })
})
