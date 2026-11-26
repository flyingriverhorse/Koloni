// To-do's rough note (6 Nov; 0.1.8 as a tree; 0.1.10 always in sight under To-do's cards, its button Split into tasks):
// a rough note typed in its box, written by the scripted model as stories and their tasks - shown to change, each story
// added only by the user's word (a goal the model names is not taken: 0.1.10); and "Plan it in a chat", which opens a
// chat in the project whose first message asks for the Hive keeper.
import { expect, test } from './fixtures'
import { OWN, e2eProject, openFreshConversation, story, todo } from './helpers'

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

test('a rough note is written as stories and tasks, added by your word; or planned in a chat', async ({ page }) => {
  await openFreshConversation(page)
  const half = await todo(page)
  const box = half.getByRole('form', { name: 'Your rough note' })
  await box.getByLabel('Your rough note').fill(NOTE)
  // Who writes them and what it costs, in sight.
  await expect(box.locator('#draft-who')).toContainText('writes them: one request')
  await box.getByRole('button', { name: 'Split into tasks', exact: true }).click()
  const drafts = page.getByRole('region', { name: 'Drafted tasks' })
  await expect(drafts.getByLabel('Goal')).toHaveCount(0)
  const login = drafts.getByRole('group', { name: 'Story 1' })
  await expect(login.getByLabel('Story')).toHaveValue(STORY)
  await expect(login).toContainText('The form is shared with the desktop page.')
  const first = login.getByRole('group', { name: 'Draft 1' })
  await expect(first.getByLabel('Title')).toHaveValue('Fix the login page on mobile')
  await expect(drafts.getByRole('group', { name: 'Draft 2' }).getByLabel('Title')).toHaveValue('Add a password reset')
  const cards = half.getByRole('list', { name: 'Stories' })
  await expect(cards.getByText('Add a password reset')).toHaveCount(0) // nothing saved yet
  await expect(box.getByLabel('Your rough note')).toHaveValue(NOTE)
  await first.getByLabel('Title').fill(ADDED)
  await login.getByRole('button', { name: 'Add', exact: true }).click()
  // A card of its own: the story - no goal over it - and the task, a bug, as the Hive keeper wrote it.
  await expect(cards.getByRole('button', { name: `${STORY}: 0 of 1 done` })).toBeVisible()
  await expect(cards.getByRole('button', { name: new RegExp(`^${GOAL}`) })).toHaveCount(0)
  // The other story left out, a task at a time: the draft is gone.
  await drafts.getByRole('button', { name: 'Remove draft 1' }).click()
  await drafts.getByRole('button', { name: 'Remove draft 1' }).click()
  await expect(drafts).toBeHidden()
  await expect(cards.getByText('Add a password reset')).toHaveCount(0)
  const panel = await story(page, STORY)
  await expect(panel.getByRole('listitem', { name: ADDED })).toContainText('bug')
  await panel.getByRole('button', { name: `Close ${STORY}` }).click()

  // The other way: a chat in the project, its first message asking the Lead for the Hive keeper.
  await box.getByRole('button', { name: 'Plan it in a chat' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByText(`Have the Hive keeper break this into To-do tasks: ${NOTE}`)).toBeVisible()
  await expect(chat.getByText('I will ask the Hive keeper for tasks.')).toBeVisible({ timeout: 20_000 })
})
