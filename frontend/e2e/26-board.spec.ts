import { expect, test, type Page } from './fixtures'
import { OWN, openFreshConversation, rail, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

test.afterEach(async ({ request }) => {
  // The backend is shared: the project's limit is not left for whatever runs after.
  for (const project of await (await request.get('/api/projects')).json()) {
    await request.patch(`/api/projects/${project.id}`, { headers: OWN, data: { max_agents: null } })
  }
})

async function ask(page: Page, message: string) {
  await page.getByLabel('Message').fill(message)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('two conversations of one project: the limit, the board, and the file both want', async ({ page }) => {
  const FIRST = 'flip the greeting, a first time'
  const SECOND = 'flip the greeting, a second time'
  const WANTED = `hello.py: held by Orchestrator in «${FIRST}», waited for by Orchestrator in «${SECOND}»`
  const strip = page.getByRole('status', { name: 'Another conversation wants the same file' })
  const changes = page.getByRole('region', { name: 'Workspace' })

  // The project lets one agent work at a time.
  await openFreshConversation(page)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  await settings.getByRole('button', { name: /^Limits and money/ }).click()
  await settings.getByLabel('At most this many agents at work in this project').fill('1')
  await settings.getByRole('button', { name: 'Save' }).click()
  // (Saved, the page stays and says so. ⚙ closes it.)
  await expect(settings.getByRole('status')).toHaveText('Saved')
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await expect(settings).toHaveCount(0)

  // Its lead proposes a change to hello.py.
  await ask(page, FIRST)
  await expect(changes.getByRole('button', { name: 'Approve' })).toBeVisible()

  // It waits for you, so it holds no place: with a limit of one, the second conversation's lead
  // works all the same - until it wants the file the first one holds.
  await openFreshConversation(page)
  await ask(page, SECOND)
  await expect(strip).toHaveText(WANTED, { timeout: 15_000 })
  await shot(page, '26-strip')

  // The board: both conversations, who waits for what, and the file both want on top.
  await rail(page, 'Board').click()
  await expect(page.getByText('0 of 1 agents at work')).toBeVisible()
  await expect(page.getByText(/^“Re-run the ones that failed” sends a new message/)).toBeVisible()
  await expect(page.getByRole('list', { name: 'Two conversations want one file' }).locator('li > span')).toHaveText(WANTED)
  // What the first asks is on Ready for you: one line here leads there.
  await expect(page.getByRole('button', { name: 'Open Ready for you →' })).toBeVisible()
  // Both at work: the first waits for you, holding the file; the second waits for the file.
  const first = page.getByRole('region', { name: 'At work' }).getByRole('listitem', { name: FIRST, exact: true })
  const second = page.getByRole('region', { name: 'At work' }).getByRole('listitem', { name: SECOND, exact: true })
  await expect(first.getByRole('listitem')).toContainText('waits for you')
  await expect(first.getByRole('listitem')).toContainText('holds hello.py')
  await expect(second.getByRole('listitem')).toContainText('waiting for a file')
  await expect(second.getByRole('listitem')).toContainText('hello.py, held by Orchestrator')
  await shot(page, '26-board')

  // A row opens its conversation, which shows the same warning; its change is turned down.
  await first.getByRole('button', { name: FIRST }).click()
  await expect(strip).toHaveText(WANTED)
  await page.getByRole('button', { name: /^Workspace/ }).click()
  await changes.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Okay, I left hello.py unchanged.')).toBeVisible()
  // The file is the second lead's now: nobody waits for anybody, and the board says so by itself.
  await expect(strip).toHaveCount(0)
  await rail(page, 'Board').click()
  await expect(page.getByRole('list', { name: 'Two conversations want one file' })).toHaveCount(0)
  // The second waits for you now; the first one's turn ended today.
  const asking = page.getByRole('region', { name: 'At work' }).getByRole('listitem', { name: SECOND, exact: true })
  await expect(asking.getByRole('listitem')).toContainText('waits for you')
  await expect(page.getByRole('region', { name: 'Ended today' }).getByRole('button', { name: FIRST })).toBeVisible()

  // The second one's change is turned down too.
  await asking.getByRole('button', { name: SECOND }).click()
  await page.getByRole('button', { name: /^Workspace/ }).click()
  await changes.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Okay, I left hello.py unchanged.')).toBeVisible()
})
