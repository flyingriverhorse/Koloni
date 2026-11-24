// The To-do page's "Write it with the Hive keeper" (6 Nov; 0.1.8 as a tree): a rough note typed in its box, written by the
// scripted model as a goal, its stories and their tasks - shown to change, each story added only by the user's word, under
// the goal; and "Plan it in a chat", which opens a chat in the project whose first message asks for the Hive keeper.
import { expect, test } from './fixtures'
import { OWN, e2eProject, openFreshConversation, rail } from './helpers'

const NOTE = 'login sayfası mobilde bozuk, bir de şifre sıfırlama lazım, po'
const ADDED = 'Fix the login page (po)'
const GOAL = 'Sign-in works everywhere'
const STORY = 'Login on mobile'

test.afterEach(async ({ page }) => {
  const pid = await e2eProject(page)
  const left: { id: string; title: string }[] = await (await page.request.get(`/api/projects/${pid}/backlog`)).json()
  for (const task of left.filter(one =>
    [ADDED, 'Add a password reset', 'Rate-limit the reset form'].includes(one.title),
  ))
    expect((await page.request.delete(`/api/backlog/${task.id}`, { headers: OWN })).ok()).toBe(true)
  const tree: { goals: { id: string; title: string }[]; stories: { id: string; title: string }[] } = await (
    await page.request.get(`/api/projects/${pid}/stories`)
  ).json()
  for (const story of tree.stories.filter(one => one.title === STORY || one.title === 'Password reset'))
    expect((await page.request.delete(`/api/stories/${story.id}`, { headers: OWN })).ok()).toBe(true)
  for (const goal of tree.goals.filter(one => one.title === GOAL))
    expect((await page.request.delete(`/api/goals/${goal.id}`, { headers: OWN })).ok()).toBe(true)
})

test('a rough note is written as a goal, stories and tasks, added by your word; or planned in a chat', async ({
  page,
}) => {
  await openFreshConversation(page)
  await rail(page, 'To-do').click()
  await page
    .getByRole('toolbar', { name: 'To-do' })
    .getByRole('button', { name: 'Write it with the Hive keeper' })
    .click()
  const box = page.getByRole('form', { name: 'Write it with the Hive keeper' })
  await box.getByLabel('Your note').fill(NOTE)
  // Who writes them and what it costs, in sight.
  await expect(box.locator('#draft-who')).toContainText('writes them: one request')
  await box.getByRole('button', { name: 'Write it', exact: true }).click()
  const drafts = page.getByRole('region', { name: 'Drafted tasks' })
  await expect(drafts.getByLabel('Goal')).toHaveValue(GOAL)
  const login = drafts.getByRole('group', { name: 'Story 1' })
  await expect(login.getByLabel('Story')).toHaveValue(STORY)
  await expect(login).toContainText('The form is shared with the desktop page.')
  const first = login.getByRole('group', { name: 'Draft 1' })
  await expect(first.getByLabel('Title')).toHaveValue('Fix the login page on mobile')
  await expect(drafts.getByRole('group', { name: 'Draft 2' }).getByLabel('Title')).toHaveValue('Add a password reset')
  const tasks = page.getByRole('list', { name: 'Tasks' })
  await expect(tasks.getByText('Add a password reset')).toHaveCount(0) // nothing saved yet
  await first.getByLabel('Title').fill(ADDED)
  await login.getByRole('button', { name: 'Add', exact: true }).click()
  // In the tree: the goal, its story, the task - a bug, as the Hive keeper wrote it.
  await expect(tasks.getByRole('listitem', { name: GOAL })).toContainText('0 / 1 stories')
  await expect(tasks.getByRole('listitem', { name: STORY })).toBeVisible()
  await expect(tasks.getByRole('listitem', { name: ADDED })).toContainText('bug')
  // The other story left out, a task at a time: the draft is gone.
  await drafts.getByRole('button', { name: 'Remove draft 1' }).click()
  await drafts.getByRole('button', { name: 'Remove draft 1' }).click()
  await expect(drafts).toBeHidden()
  await expect(tasks.getByText('Add a password reset')).toHaveCount(0)

  // The other way: a chat in the project, its first message asking the Lead for the Hive keeper.
  await box.getByRole('button', { name: 'Plan it in a chat' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByText(`Have the Hive keeper break this into To-do tasks: ${NOTE}`)).toBeVisible()
  await expect(chat.getByText('I will ask the Hive keeper for tasks.')).toBeVisible({ timeout: 20_000 })
})
