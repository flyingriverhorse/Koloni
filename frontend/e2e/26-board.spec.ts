import { expect, test, type Page } from './fixtures'
import { OWN, openFreshConversation, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

test.afterEach(async ({ request }) => {
  // The backend is shared: the project's limit is not left for whatever runs after.
  for (const project of await (await request.get('/api/projects')).json()) {
    await request.patch(`/api/projects/${project.id}`, { headers: OWN, data: { max_agents: null } })
  }
})

/** A conversation opened from the Chats list, by its title. */
async function open(page: Page, title: string) {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Chats', exact: true }).click()
  await page.getByRole('searchbox', { name: 'Search conversations' }).fill(title)
  await page
    .getByRole('button', { name: new RegExp(`^${title}`) })
    .first()
    .click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText(title, { exact: true })).toBeVisible()
}

async function ask(page: Page, message: string) {
  await page.getByLabel('Message', { exact: true }).fill(message)
  await page.getByRole('button', { name: 'Send' }).click()
}

test('two conversations of one project: the limit, and the file both want', async ({ page }) => {
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
  // (Under More limits since 0.1.10, closed until opened.)
  await settings.getByText(/^More limits/).click()
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

  // The first conversation shows the same warning; its change is turned down. (0.1.10: no Board page - the Chats
  // list opens it.)
  await open(page, FIRST)
  await expect(strip).toHaveText(WANTED)
  await page.getByRole('button', { name: /^Workspace/ }).click()
  await changes.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Okay, I left hello.py unchanged.')).toBeVisible()
  // The file is the second lead's now: nobody waits for anybody, and the strip goes by itself.
  await expect(strip).toHaveCount(0)

  // The second one's change is turned down too.
  await open(page, SECOND)
  await expect(strip).toHaveCount(0)
  await page.getByRole('button', { name: /^Workspace/ }).click()
  await changes.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByRole('region', { name: 'Chat' }).getByText('Okay, I left hello.py unchanged.')).toBeVisible()
})
