// Slice 52 in the browser: the project's To-do page in the rail (Backlog before slice 106). The user adds tasks and
// orders them by keyboard; a task the Lead proposes waits on a card (and on the rail's badge)
// until it is approved; Run the backlog starts the todo tasks, each in a new conversation, one that waits
// for another once that is done (K-symphony); a task's end leaves it "done?" for the user to call done. The
// page reads at 4.5 in both themes.
import { expect, test, type Locator, type Page } from './fixtures'
import { OWN, contrasts, e2eProject, openFreshConversation, rail, say, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// The backend is shared with the other theme's run and the specs after: what a run left - a failed one's proposed card
// above all, which the next run took for its own - goes.
test.afterEach(async ({ page }) => {
  const pid = await e2eProject(page)
  const left: { id: string; title: string }[] = await (await page.request.get(`/api/projects/${pid}/backlog`)).json()
  for (const task of left.filter(one => one.title === 'Add a farewell' || /^Greet in (French|German) \(/.test(one.title)))
    expect((await page.request.delete(`/api/backlog/${task.id}`, { headers: OWN })).ok()).toBe(true)
})

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
  await expect(page.getByRole('list', { name: 'Tasks' }).getByText(title, { exact: true })).toBeVisible()
}

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme: add and order tasks, approve a proposed one, run the backlog, one task waiting for another`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    // The Lead proposes a task: it waits for the user, and the rail's badge counts it.
    await say(page, 'please keep the backlog', 'Proposed a task for your backlog.')
    await expect(page.locator('#rail-waiting')).toHaveText(/[1-9]\d* waiting/, { timeout: 10_000 })

    await rail(page, 'To-do').click()
    await expect(page.getByRole('heading', { name: 'To-do' })).toBeVisible()
    const waiting = page.getByRole('region', { name: 'Waiting for you' })
    const card = waiting.getByRole('group', { name: 'Proposed task: Add a farewell' }).first()
    await expect(card).toContainText('prints bye')
    await reads(card, 3)

    // Two tasks of the user's, one high: high ones come first.
    const first = `Greet in French (${theme})`
    const second = `Greet in German (${theme})`
    await add(page, first, 'high', 'prints bonjour')
    await add(page, second, 'high')
    const tasks = page.getByRole('list', { name: 'Tasks' })
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
    await reads(page.locator('.memory-page'), 10)
    if (process.env.KOLONI_SHOTS) await shot(page, `52-backlog-${theme}`)

    // Add / Edit / Reject (6 Nov): Edit opens its title and detail, and adds it as changed.
    await expect(card.getByRole('button', { name: 'Reject', exact: true })).toBeVisible()
    await card.getByRole('button', { name: 'Edit', exact: true }).click()
    await card.getByLabel('Detail').fill('prints bye, then exits')
    await card.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(card).toBeHidden()

    // The second waits for the first, chosen from its ⋯.
    await dots(second).click()
    await page.getByRole('menuitem', { name: 'Edit' }).click()
    await page.getByRole('form', { name: `Edit ${second}` }).getByLabel(/^Waits for/).selectOption({ label: first })
    await page.getByRole('button', { name: 'Save' }).click()
    const row = (title: string) => tasks.getByRole('listitem', { name: title })
    await expect(row(second)).toContainText(`waits for: ${first}`)

    // Run the backlog: the first starts in a new conversation (the page stays); the second waits for it.
    await page.getByRole('button', { name: 'Run the backlog' }).click()
    // (A task's status is under its title, opened.)
    const unfold = (title: string) => tasks.getByRole('button', { name: title, exact: true }).click()
    await unfold(first)
    const status = page.getByRole('combobox', { name: `Status of ${first}` })
    await expect(status).toHaveValue('review', { timeout: 20_000 })
    await expect(status.locator('option:checked')).toHaveText('done?')
    await expect(row(second)).toContainText(`waits for: ${first}`)
    await page.getByRole('button', { name: `Open chat · ${first}` }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    const asked = chat.locator('.msg-bubble').filter({ hasText: "(A task of the project's To-do list to work on, written by you" })
    await expect(asked.last()).toContainText(first)
    await expect(asked.last()).toContainText('prints bonjour')
    await expect(chat.getByText('Worked on the task.')).toBeVisible({ timeout: 20_000 })

    // Its turn over, it waits for the user's review; done is the user's to say.
    await rail(page, 'To-do').click()
    // It waits on a row too, as the badge counts it.
    await reads(page.getByRole('group', { name: `Done? ${first}` }), 3)
    await page.getByRole('group', { name: `Done? ${first}` }).getByRole('button', { name: 'Done', exact: true }).click()
    await unfold(first)
    await expect(status).toHaveValue('done')
    // Done: the second starts by itself, in the run Run the backlog began; a delete asks again before it deletes.
    await unfold(second)
    await expect(page.getByRole('combobox', { name: `Status of ${second}` })).toHaveValue('review', { timeout: 20_000 })
    await dots(second).click()
    await page.getByRole('menuitem', { name: 'Delete' }).click()
    await expect(page.getByRole('button', { name: `Delete “${second}”` })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(tasks.getByText(second, { exact: true })).toBeHidden()
  })
