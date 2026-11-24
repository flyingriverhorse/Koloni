// 0.1.8, To-do in a chat, in the browser: a story of two tasks and a bug of no story are ticked on To-do and given to a
// new chat (Do in chat ▾ → A new chat); the chat shows each task as itself, under its story's topic line, asks
// "Done?" under each, runs the story's second task in the same topic, then asks "Story done?" - Close the story closes
// it on To-do; the bug runs in a topic of its own. The queue over the message box lists what waits, and Remove puts
// one back on To-do. Run the backlog, Runs by itself and Run settings are gone.
import { expect, test, type Page } from './fixtures'
import { OWN, e2eProject, openFreshConversation, rail } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

const STAMP = Date.now().toString(36)
const STORY = `Two-step sign-in (${STAMP})`
const FIRST = `Send the code (${STAMP})`
const SECOND = `Check the code (${STAMP})`
const BUG = `Footer year is wrong (${STAMP})`
const LATER = `A task for later (${STAMP})`

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

async function made(page: Page) {
  const pid = await e2eProject(page)
  const tree = {
    stories: [{ title: STORY, notes: [], tasks: [{ title: FIRST, criteria: 'a code is sent' }, { title: SECOND }] }],
    tasks: [{ title: BUG, kind: 'bug' }, { title: LATER }],
  }
  const added = await page.request.post(`/api/projects/${pid}/backlog/tree`, { headers: OWN, data: tree })
  expect(added.ok()).toBe(true)
}

test('a story and a bug ticked on To-do run in a new chat, each asked "Done?", the story closed from the chat', async ({
  page,
}) => {
  await openFreshConversation(page)
  await made(page)
  await rail(page, 'To-do').click()
  const tasks = page.getByRole('list', { name: 'Tasks' })
  for (const gone of ['Run settings', 'Runs by itself', 'Run the backlog'])
    await expect(page.getByText(gone)).toHaveCount(0)

  // Tick the story (its open tasks), the bug and one for later; the dock says how many and what happens.
  await tasks.getByRole('checkbox', { name: `Tick the story ${STORY}` }).check()
  await tasks.getByRole('listitem', { name: BUG }).getByRole('checkbox').first().check()
  await tasks.getByRole('listitem', { name: LATER }).getByRole('checkbox').first().check()
  const dock = page.getByRole('region', { name: 'Selected tasks' })
  await expect(dock).toContainText('4 selected')
  await expect(dock).toContainText('Each story goes into its own topic')
  // (Stop everything holds the queue: what waits in it is seen before it runs.)
  expect((await page.request.post('/api/hold', { headers: OWN })).ok()).toBe(true)
  await dock.getByRole('button', { name: /Do in chat/ }).click()
  await page.getByRole('menuitem', { name: 'A new chat' }).click()

  // The new chat, held: the queue over the box - Remove puts the one for later back on To-do - then Resume.
  const chat = page.getByRole('region', { name: 'Chat' })
  const queue = page.getByRole('region', { name: 'To-do queue' })
  await expect(queue).toContainText('4 wait', { timeout: 20_000 })
  await expect(queue).toContainText('+ your message goes first when you send one')
  await queue.getByRole('button', { name: `Remove “${LATER}” from the queue` }).click()
  await expect(queue).toContainText('3 wait')
  expect((await page.request.post('/api/hold/resume', { headers: OWN })).ok()).toBe(true)
  // The story's topic line, its first task as itself.
  await expect(chat.getByText(`Topic · Story · ${STORY} · 📓 notes`).first()).toBeVisible({ timeout: 20_000 })
  await expect(chat.getByRole('group', { name: 'From To-do · task 1 / 2' })).toContainText(FIRST)
  await expect(chat.getByRole('group', { name: 'From To-do · task 1 / 2' })).toContainText('a code is sent')

  // Done? under the first task: Yes, done - and the second has run in the same topic meanwhile.
  const done = (title: string) => chat.getByRole('group', { name: `Done? — “${title}”` })
  await done(FIRST).getByRole('button', { name: 'Yes, done' }).click({ timeout: 20_000 })
  await expect(chat.getByRole('group', { name: 'From To-do · task 2 / 2' })).toContainText(SECOND, { timeout: 20_000 })
  await done(SECOND).getByRole('button', { name: 'Yes, done' }).click({ timeout: 20_000 })
  // Every task of the story done: Story done? - Close the story.
  const storyDone = chat.getByRole('group', { name: `Story done? — “${STORY}”` })
  await storyDone.getByRole('button', { name: 'Close the story' }).click({ timeout: 20_000 })
  // The bug in a topic of its own.
  await expect(chat.getByRole('group', { name: 'From To-do · bug' })).toContainText(BUG, { timeout: 20_000 })

  await rail(page, 'To-do').click()
  await expect(tasks.getByRole('listitem', { name: STORY })).toContainText('✓ done', { timeout: 20_000 })
  await expect(tasks.getByRole('listitem', { name: LATER })).not.toContainText('queued')
})
