// The To-do page's "Write it with the Product owner" (6 Nov): the rough note typed in Add a task, written as tasks by the
// scripted model - shown to change, each added only by the user's word; and "Plan it in a chat", which opens a chat in the project
// whose first message asks for the Product owner.
import { expect, test } from './fixtures'
import { OWN, e2eProject, openFreshConversation, rail } from './helpers'

const NOTE = 'login sayfası mobilde bozuk, bir de şifre sıfırlama lazım, po'
const ADDED = 'Fix the login page (po)'

test.afterEach(async ({ page }) => {
  const pid = await e2eProject(page)
  const left: { id: string; title: string }[] = await (await page.request.get(`/api/projects/${pid}/backlog`)).json()
  for (const task of left.filter(one => one.title === ADDED || one.title === 'Add a password reset'))
    expect((await page.request.delete(`/api/backlog/${task.id}`, { headers: OWN })).ok()).toBe(true)
})

test('a rough note is written as tasks, each added by your word; or planned in a chat', async ({ page }) => {
  await openFreshConversation(page)
  await rail(page, 'To-do').click()
  const form = page.getByRole('form', { name: 'Add a task' })
  await form.getByLabel('Title').fill(NOTE)
  const write = form.getByRole('button', { name: 'Write it with the Product owner' })
  // Who writes them and what it costs, in sight.
  await expect(form.locator('#draft-who')).toContainText('writes them: one request')
  await write.click()
  const drafts = page.getByRole('region', { name: 'Drafted tasks' })
  const first = drafts.getByRole('group', { name: 'Draft 1' })
  await expect(first.getByLabel('Title')).toHaveValue('Fix the login page on mobile')
  await expect(drafts.getByRole('group', { name: 'Draft 2' }).getByLabel('Title')).toHaveValue('Add a password reset')
  const tasks = page.getByRole('list', { name: 'Tasks' })
  await expect(tasks.getByText('Add a password reset')).toHaveCount(0) // nothing saved yet
  await first.getByLabel('Title').fill(ADDED)
  await first.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(tasks.getByText(ADDED, { exact: true })).toBeVisible()
  await drafts.getByRole('button', { name: 'Remove draft 1' }).click()
  await expect(drafts).toBeHidden()
  await expect(tasks.getByText('Add a password reset')).toHaveCount(0)

  // The other way: a chat in the project, its first message asking the Lead for the Product owner.
  await form.getByRole('button', { name: 'Plan it in a chat' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByText(`Have the Product owner break this into To-do tasks: ${NOTE}`)).toBeVisible()
  await expect(chat.getByText('I will ask the Product owner for tasks.')).toBeVisible({ timeout: 20_000 })
})
