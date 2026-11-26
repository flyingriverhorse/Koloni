// Slice 52 in the browser: the project's To-do - since 0.1.10 Ready for you's right half, each story a card. The user
// adds tasks and orders them by keyboard in a card's panel; a task the Lead proposes waits under Waiting for your word
// (and on the rail's badge) until it is approved; one waits for another (⋯, Waits for). Running tasks is Do in chat's
// since 0.1.8 (52-todo-in-chat). The page reads at 4.5 in both themes.
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, e2eProject, openFreshConversation, say, shot, story, todo } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// The backend is shared with the other theme's run and the specs after: what a run left - a failed one's proposed card
// above all, which the next run took for its own - goes.
test.afterEach(async ({ page }) => {
  const pid = await e2eProject(page)
  const left: { id: string; title: string }[] = await (await page.request.get(`/api/projects/${pid}/backlog`)).json()
  for (const task of left.filter(
    one => one.title === 'Add a farewell' || /^(Greet in (French|German)|A stuck bug) \(/.test(one.title),
  ))
    expect((await page.request.delete(`/api/backlog/${task.id}`, { headers: OWN })).ok()).toBe(true)
  const tree: { goals: { id: string; title: string }[]; stories: { id: string; title: string }[] } = await (
    await page.request.get(`/api/projects/${pid}/stories`)
  ).json()
  for (const story of tree.stories.filter(one => one.title.startsWith('A stuck story (')))
    expect((await page.request.delete(`/api/stories/${story.id}`, { headers: OWN })).ok()).toBe(true)
  for (const goal of tree.goals.filter(one => one.title.startsWith('A goal to read (')))
    expect((await page.request.delete(`/api/goals/${goal.id}`, { headers: OWN })).ok()).toBe(true)
})

/** 0.1.8: a stuck story with a note and a bug, made through the Hive keeper's way in - its rows read at 4.5 too. Its
 *  goal, made by the API as before 0.1.10, is not shown: the story stands at the top. */
async function storyRows(page: Page, theme: string) {
  const pid = await e2eProject(page)
  const tree = {
    goal: `A goal to read (${theme})`,
    stories: [
      {
        title: `A stuck story (${theme})`,
        notes: ['A note to read.'],
        tasks: [{ title: `A stuck bug (${theme})`, kind: 'bug' }],
      },
    ],
    tasks: [],
  }
  const made = await page.request.post(`/api/projects/${pid}/backlog/tree`, { headers: OWN, data: tree })
  expect(made.ok()).toBe(true)
  const [bug] = (await made.json()).task_ids
  expect((await page.request.patch(`/api/backlog/${bug}`, { headers: OWN, data: { status: 'blocked' } })).ok()).toBe(
    true,
  )
  const card = page.getByRole('button', { name: new RegExp(`^A stuck story \\(${theme}\\): 0 of 1 done$`) })
  await expect(card).toContainText('stuck')
  await expect(page.getByRole('button', { name: new RegExp(`^A goal to read`) })).toHaveCount(0)
  await reads(card, 4)
  const panel = await story(page, `A stuck story (${theme})`)
  await expect(panel).toContainText('⚠ stuck')
  await reads(panel, 6)
  await reads(panel.getByRole('listitem', { name: `A stuck bug (${theme})` }), 3)
}

async function reads(root: Locator, least: number) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.length).toBeGreaterThanOrEqual(least)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

async function add(page: Page, title: string, priority: 'high' | 'normal' | 'low', criteria = '') {
  const form = page.getByRole('form', { name: 'Add a task' })
  // (One line first: the rest opens once a title is typed.)
  await form.getByLabel('Title').fill(title)
  await form.getByLabel('Done when (optional)').fill(criteria)
  await form.getByLabel('Priority').selectOption(priority)
  await form.getByRole('button', { name: 'Add task' }).click()
  await expect(page.getByRole('list', { name: 'Stories' }).getByText(title, { exact: true })).toBeVisible()
}

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme: add and order tasks, approve a proposed one, one task waiting for another`, async ({
    page,
  }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    // The Lead proposes a task: it waits for the user, and the rail's badge counts it.
    await say(page, 'please keep the backlog', 'Proposed a task for your backlog.')
    await expect(page.locator('#rail-waiting')).toHaveText(/[1-9]\d* waiting/, { timeout: 10_000 })

    await todo(page)
    const waiting = page.getByRole('region', { name: /^Waiting for your word/ })
    const card = waiting.getByRole('group', { name: 'Proposed task: Add a farewell' }).first()
    await expect(card).toContainText('prints bye')
    await reads(card, 3)

    // Two tasks of the user's, one high: high ones come first.
    const first = `Greet in French (${theme})`
    const second = `Greet in German (${theme})`
    await add(page, first, 'high', 'prints bonjour')
    await add(page, second, 'high')
    // (A card's tasks, opened: its panel - the tasks of no story are one card.)
    const tasks = (await story(page, 'Without a story')).getByRole('list', { name: 'Tasks' })
    const titles = () => tasks.locator('.backlog-task strong').allTextContents()
    expect((await titles()).indexOf(first)).toBeLessThan((await titles()).indexOf(second))
    // Ordered from the keyboard, from its ⋯: the second goes up past the first.
    const dots = (title: string) => page.getByRole('button', { name: `${title}: more` })
    await dots(second).focus()
    await page.keyboard.press('Enter')
    await page.getByRole('menuitem', { name: 'Move up' }).press('Enter')
    await expect.poll(async () => (await titles()).indexOf(second) < (await titles()).indexOf(first)).toBe(true)
    await dots(second).click()
    await page.getByRole('menuitem', { name: 'Move down' }).click()
    await expect.poll(async () => (await titles()).indexOf(first) < (await titles()).indexOf(second)).toBe(true)
    await reads(page.locator('.ready-page'), 10)
    await storyRows(page, theme)
    if (process.env.KOLONI_SHOTS) await shot(page, `52-backlog-${theme}`)

    // Add / Edit / Reject (6 Nov): Edit opens its title and detail, and adds it as changed.
    await expect(card.getByRole('button', { name: 'Reject', exact: true })).toBeVisible()
    await card.getByRole('button', { name: 'Edit', exact: true }).click()
    await card.getByLabel('Detail').fill('prints bye, then exits')
    await card.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(card).toBeHidden()

    // The second waits for the first, chosen from its ⋯.
    await story(page, 'Without a story')
    await dots(second).click()
    await page.getByRole('menuitem', { name: 'Edit' }).click()
    await page
      .getByRole('form', { name: `Edit ${second}` })
      .getByLabel(/^Waits for/)
      .selectOption({ label: first })
    await page.getByRole('button', { name: 'Save' }).click()
    const row = (title: string) => tasks.getByRole('listitem', { name: title })
    await expect(row(second)).toContainText(`waits for: ${first}`)
  })
