import { existsSync, readFileSync, rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext } from './fixtures'
import { OWN, contrasts, openFreshConversation, openTurns, ownColours, rail, shot } from './helpers'
import { APP_URL, PROJECT_DIR, REPO_ROOT } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] })

const made = path.join(PROJECT_DIR, 'made.txt')

/** No trigger is left behind, none is paused, and the file a trigger's turn wrote is gone: the specs after this one share the backend. */
async function tidy(request: APIRequestContext) {
  await request.put('/api/triggers/paused', { headers: OWN, data: { paused: false } })
  const projects: { id: string }[] = await (await request.get('/api/projects')).json()
  for (const project of projects) {
    const triggers: { id: string }[] = await (await request.get(`/api/projects/${project.id}/triggers`)).json()
    for (const trigger of triggers) await request.delete(`/api/triggers/${trigger.id}`, { headers: OWN })
  }
  rmSync(made, { force: true })
}

test.beforeEach(async ({ request }) => {
  await tidy(request)
})

test.afterEach(async ({ request }) => {
  await tidy(request)
})

test('the Triggers page takes every colour from the theme: triggers.css names none of its own', () => {
  const css = readFileSync(path.join(REPO_ROOT, 'frontend', 'src', 'theme', 'triggers.css'), 'utf8')
  expect(css).toContain('var(--surface)')
  expect(ownColours(css)).toEqual([])
})

test('a trigger is made, run now with nobody watching, refused what it does not allow, allowed it from the chat, and run again', async ({ page, request }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const list = page.getByRole('complementary', { name: 'Recent' })
  const bar = page.getByRole('banner')

  // A conversation of your own, with one turn: the trigger's turns will go into it.
  const title = 'hello from the trigger spec'
  await page.getByLabel('Message').fill(title)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible({ timeout: 15_000 })
  // With no trigger the top bar says nothing about triggers.
  await expect(bar.getByText(/triggers? on/)).toHaveCount(0)

  // --- make one: on a request from outside, allowed nothing ---------------------------------
  await rail(page, 'Triggers').click()
  await expect(page.getByText('No trigger yet. Nothing in this project starts by itself.')).toBeVisible()
  await page.getByRole('button', { name: 'New trigger' }).click()
  await page.getByRole('menuitem', { name: 'Start from blank' }).click()
  let form = page.getByRole('form', { name: 'New trigger' })
  await expect(form.getByLabel('May change files', { exact: true })).not.toBeChecked()
  await expect(form.getByLabel('May open sub-agents', { exact: true })).toHaveValue('0')
  await expect(form.getByLabel('Model steps a run', { exact: true })).toHaveValue('15')
  await expect(form.getByLabel('Minutes a run', { exact: true })).toHaveValue('10')
  await expect(form.getByLabel('Runs a day', { exact: true })).toHaveValue('24')
  await expect(form.getByLabel('Run once when KOLONİ starts if a run was missed', { exact: true })).toBeChecked()
  // What is missing is said beside its field; nothing is made.
  await form.getByRole('button', { name: 'Add trigger' }).click()
  await expect(form.getByText('Give it a name.')).toBeVisible()
  await form.getByLabel('Name', { exact: true }).fill('Nightly check')
  await form.getByLabel('Starts', { exact: true }).selectOption('webhook')
  await form.getByLabel('Conversation', { exact: true }).selectOption({ label: title })
  await form.getByLabel('Message', { exact: true }).fill('nightly check')
  await form.getByRole('button', { name: 'Add trigger' }).click()

  // Its address, with its key, is shown this once.
  const address = page.getByRole('region', { name: 'The address of Nightly check' })
  await expect(address).toContainText('This is shown once: it cannot be read back later.')
  await expect(address).toContainText('Anyone on this machine who has this address can run the trigger.')
  const shown = (await address.locator('code').textContent()) ?? ''
  expect(shown.startsWith(`${APP_URL}/api/hooks/`)).toBe(true)
  expect(shown).toMatch(/\/api\/hooks\/[\w-]{32,}$/)
  const key = shown.split('/').pop() as string
  await address.getByRole('button', { name: 'Copy the address' }).click()
  // (By its whole name: "I have copied it" is a button here too, and holds the word.)
  await expect(address.getByRole('button', { name: 'Copied', exact: true })).toBeVisible()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(shown)
  await shot(page, '18a-webhook-key-shown-once')
  const card = page.getByRole('article', { name: 'Nightly check' })
  await expect(card).toContainText('on a request from outside')
  await expect(card).toContainText(`in ${title}`)
  await expect(card).toContainText('reads only')
  await expect(card).toContainText('15 model steps and 10 minutes a run · 24 runs a day')
  await expect(card).toContainText('has not run yet')
  // Put away, the key is nowhere: not on the page, not in what the server says of the trigger.
  await address.getByRole('button', { name: 'I have copied it' }).click()
  await expect(address).toHaveCount(0)
  expect(await page.content()).not.toContain(key)
  const [project]: { id: string }[] = await (await request.get('/api/projects')).json()
  const kept = await (await request.get(`/api/projects/${project.id}/triggers`)).text()
  expect(kept).toContain('Nightly check')
  expect(kept).not.toContain(key)
  await page.reload()
  await rail(page, 'Triggers').click()
  await expect(card).toBeVisible()
  expect(await page.content()).not.toContain(key)

  // A second one, on files that are not there: it never comes due here.
  await page.getByRole('button', { name: 'New trigger' }).click()
  await page.getByRole('menuitem', { name: 'Start from blank' }).click()
  form = page.getByRole('form', { name: 'New trigger' })
  await form.getByLabel('Name', { exact: true }).fill('Docs watch')
  await form.getByLabel('Starts', { exact: true }).selectOption('files')
  await form.getByLabel('Path pattern', { exact: true }).fill('../outside/*.md')
  await form.getByLabel('Conversation', { exact: true }).selectOption({ label: title })
  await form.getByLabel('Message', { exact: true }).fill('Read what changed in the docs and say whether it still fits the code.')
  await form.getByRole('button', { name: 'Add trigger' }).click()
  await expect(form.getByLabel('Path pattern', { exact: true })).toHaveAccessibleDescription(/inside the project folder/)
  await form.getByLabel('Path pattern', { exact: true }).fill('docs/**/*.md')
  await form.getByRole('button', { name: 'Add trigger' }).click()
  await expect(form).toHaveCount(0)
  await expect(page.getByRole('article', { name: 'Docs watch' })).toContainText('when docs/**/*.md changes')
  await expect(page.getByRole('article', { name: 'Docs watch' }).getByText(/shown once/)).toHaveCount(0) // only a webhook has a key
  // The top bar says how many are on, on every page.
  await expect(bar.getByRole('button', { name: '2 triggers on' })).toBeVisible()

  // The page with two triggers and the form open, in both themes; in the dark one every
  // text stands out from what it is on.
  await card.getByRole('button', { name: 'More for Nightly check' }).click()
  await page.getByRole('menuitem', { name: 'Edit' }).click()
  form = page.getByRole('form', { name: 'Edit trigger' })
  await expect(form.getByLabel('Starts', { exact: true })).toBeDisabled()
  await expect(form.getByText('This conversation has no allowed commands yet.')).toBeVisible()
  const cards = page.getByRole('article', { name: 'Docs watch' })
  await shot(page, '18a-triggers-page-form-light')
  await cards.scrollIntoViewIfNeeded()
  await shot(page, '18a-triggers-page-cards-light')
  await page.getByRole('button', { name: 'Theme: switch to dark' }).click()
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  await expect(page.locator('html')).not.toHaveClass(/theme-switching/)
  await shot(page, '18a-triggers-page-cards-dark')
  await form.getByLabel('Name', { exact: true }).scrollIntoViewIfNeeded()
  await shot(page, '18a-triggers-page-form-dark')
  const pieces = await page.locator('.triggers-page').evaluate(contrasts)
  expect(pieces.length).toBeGreaterThan(40)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
  // a trigger's name stands out on its card as a heading did
  expect(pieces.find(piece => /trigger-name/.test(piece.cls))).toMatchObject({ color: '228,230,234', background: '26,30,38' })
  const inBar = await bar.locator('.triggers-status').evaluate(contrasts)
  expect(inBar.filter(piece => piece.ratio < 4.5)).toEqual([])
  await page.getByRole('button', { name: 'Theme: switch to light' }).click()
  await expect(page.locator('html')).not.toHaveClass(/\bdark\b/)
  await form.getByRole('button', { name: 'Cancel' }).click()

  // --- "Run now": its turn, with what it allows and nobody asked -------------------------------
  await card.getByRole('button', { name: 'Run now' }).click()
  // The canvas, with that turn: Recent lists it by the trigger's name, beside your own (slice 107).
  await expect(chat.getByText('I could not write made.txt: I would have asked you first.')).toBeVisible({ timeout: 15_000 })
  const own = list.locator('.turn-row').filter({ hasText: title })
  const scheduled = list.locator('.turn-row').filter({ hasText: 'Nightly check' })
  await openTurns(page)
  await expect(list.locator('.turn-row')).toHaveCount(2)
  await expect(own).toHaveCount(1)
  await expect(scheduled).toHaveCount(1)
  await expect(scheduled).toContainText('done')
  // Picked in the list, each turn is drawn alone: yours, then the trigger's.
  const requests = page.locator('.react-flow__node-request')
  await own.click()
  await expect(requests).toHaveCount(1)
  await expect(requests).toContainText('You')
  await expect(requests).toContainText(title)
  await openTurns(page)
  await scheduled.click()
  await openTurns(page)
  await expect(scheduled).toHaveAttribute('aria-current', 'true')
  await expect(requests).toHaveCount(1)
  await expect(requests).toContainText('Trigger')
  await expect(requests).toContainText('Nightly check · nobody watching')
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(1)
  // The write was refused: no file counted on its node, and no file on disk.
  await expect(page.locator('.react-flow__node-agent')).not.toContainText(/\d+ files?\b/)
  expect(existsSync(made)).toBe(false)

  // The chat says who started the turn, and - at its end - what it would have asked you.
  await expect(chat.getByRole('note', { name: 'Started by the trigger Nightly check' })).toContainText('nobody watching')
  const asked = chat.getByRole('group', { name: 'It would have asked you' })
  await expect(asked.getByRole('listitem')).toHaveCount(1)
  await expect(asked.getByRole('listitem')).toContainText('write made.txt')
  // Nothing waits for you: the turn is over, and nothing was put forward.
  await expect(chat.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(bar.getByText('DONE', { exact: true })).toBeVisible()
  await shot(page, '18a-chat-would-have-asked')

  // --- allow it in the trigger: the form opens with it filled in, and nothing is saved ----------
  await asked.getByRole('button', { name: 'Allow this in the trigger' }).click()
  form = page.getByRole('form', { name: 'Edit trigger' })
  await expect(form.getByLabel('Name', { exact: true })).toHaveValue('Nightly check')
  await expect(form.getByLabel('May change files', { exact: true })).toBeChecked()
  await expect(form.getByRole('status')).toContainText('Not saved yet: “May change files” was switched on from the chat. Look it over and save.')
  const permissions = async () => {
    const all: { name: string; permissions: { write: boolean } }[] = await (await request.get(`/api/projects/${project.id}/triggers`)).json()
    return all.find(t => t.name === 'Nightly check')?.permissions.write
  }
  expect(await permissions()).toBe(false)
  await expect(card).toContainText('reads only')
  await expect(card).toContainText(/last run .+ · completed/)
  await form.getByRole('button', { name: 'Save' }).click()
  await expect(form).toHaveCount(0)
  await expect(card).toContainText('may change files')
  expect(await permissions()).toBe(true)

  // --- run again: it is done ------------------------------------------------------------------
  await card.getByRole('button', { name: 'Run now' }).click()
  await expect(chat.getByText('Wrote made.txt.')).toBeVisible({ timeout: 15_000 })
  await expect.poll(() => existsSync(made) && readFileSync(made, 'utf8')).toBe('checked\n')
  await openTurns(page)
  await expect(scheduled).toHaveCount(2)
  await expect(scheduled.first()).toHaveAttribute('aria-current', 'true')
  await expect(page.locator('.react-flow__node-agent')).toContainText('1 file')
  // Only the first turn was refused anything.
  await expect(chat.getByRole('group', { name: 'It would have asked you' })).toHaveCount(1)

  // The card lists both times; one of them leads back to its turn on the canvas.
  await rail(page, 'Triggers').click()
  await card.getByRole('button', { name: 'Recent runs (2)' }).click()
  const runs = page.getByRole('list', { name: 'Recent runs of Nightly check' }).getByRole('listitem')
  await expect(runs).toHaveCount(2)
  await expect(runs.first()).toContainText('completed')
  await runs.last().getByRole('button').click()
  await openTurns(page)
  await expect(scheduled.last()).toHaveAttribute('aria-current', 'true')
  await expect(page.locator('.react-flow__node-agent')).not.toContainText(/\d+ files?\b/)

  // --- "Pause all" holds every trigger back; "Resume" lets them go on ----------------------------
  await bar.getByRole('button', { name: 'Pause all' }).click()
  await expect(bar.getByRole('button', { name: 'Triggers paused' })).toBeVisible()
  await rail(page, 'Triggers').click()
  await card.getByRole('button', { name: 'Run now' }).click()
  await expect(card.getByRole('alert')).toHaveText('all triggers are paused')
  await bar.getByRole('button', { name: 'Resume' }).click()
  await expect(bar.getByRole('button', { name: '2 triggers on' })).toBeVisible()

  // Switched off by hand it says only that it is off, and the top bar counts one fewer.
  await card.getByRole('switch', { name: 'Nightly check is on' }).click()
  await expect(card.getByRole('switch')).not.toBeChecked()
  await expect(bar.getByRole('button', { name: '1 trigger on' })).toBeVisible()
  await expect(card.getByRole('alert')).toHaveCount(0)
})

test('a command is put on the conversation’s list in the trigger’s form, ticked, and run by its turn as written; what was done to the trigger is on its record', async ({ page, request }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  const title = 'hello from the ticked-command spec'
  await page.getByLabel('Message').fill(title)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Hello! Ask me to read or change a file.')).toBeVisible({ timeout: 15_000 })

  // A trigger that allows nothing: its turn wants to run a command, and is refused.
  await rail(page, 'Triggers').click()
  await page.getByRole('button', { name: 'New trigger' }).click()
  await page.getByRole('menuitem', { name: 'Start from blank' }).click()
  let form = page.getByRole('form', { name: 'New trigger' })
  await form.getByLabel('Name', { exact: true }).fill('Nightly run')
  await form.getByLabel('Starts', { exact: true }).selectOption('webhook')
  await form.getByLabel('Conversation', { exact: true }).selectOption({ label: title })
  await form.getByLabel('Message', { exact: true }).fill('nightly run')
  await expect(form.getByText('This conversation has no allowed commands yet.')).toBeVisible()
  await form.getByRole('button', { name: 'Add trigger' }).click()
  await page.getByRole('region', { name: 'The address of Nightly run' }).getByRole('button', { name: 'I have copied it' }).click()
  const card = page.getByRole('article', { name: 'Nightly run' })
  await expect(card).toContainText('reads only')
  await card.getByRole('button', { name: 'Run now' }).click()
  await expect(chat.getByText('I could not run python check.py: I would have asked you first.')).toBeVisible({ timeout: 15_000 })
  const asked = chat.getByRole('group', { name: 'It would have asked you' })
  await expect(asked.getByRole('listitem')).toContainText('run `python check.py`')

  // Allowed from the chat: the form opens with the command in the add field - on no list, ticked nowhere, nothing saved.
  await asked.getByRole('button', { name: 'Allow this in the trigger' }).click()
  form = page.getByRole('form', { name: 'Edit trigger' })
  const add = form.getByLabel("Add a command to this conversation's list", { exact: true })
  await expect(add).toHaveValue('python check.py')
  await expect(form.getByRole('status')).toContainText('“python check.py” is not on this conversation’s list yet: add it below, then tick it.')
  const [project]: { id: string }[] = await (await request.get('/api/projects')).json()
  const kept = async () => {
    const all: { name: string; conversation_id: string; permissions: { commands: string[] }; command_lines: string[] }[] = await (
      await request.get(`/api/projects/${project.id}/triggers`)
    ).json()
    return all.find(t => t.name === 'Nightly run')!
  }
  const rules = async () => {
    const snap: { allowed_commands: { id: string; prefix: string }[] } = await (await request.get(`/api/conversations/${(await kept()).conversation_id}`)).json()
    return snap.allowed_commands
  }
  expect(await rules()).toEqual([])
  // What cannot be a rule is refused beside the field, and is on no list.
  await add.fill('python check.py && echo x')
  await form.getByRole('button', { name: 'Add to the list' }).click()
  await expect(form.getByText(/a rule is one plain command/)).toBeVisible()
  expect(await rules()).toEqual([])
  // Added: on the conversation's list at once - which is said - and not ticked for you.
  await add.fill('  python   check.py ')
  await expect(form.getByText("This also lets this conversation's own messages run it without asking.")).toBeVisible()
  await form.getByRole('button', { name: 'Add to the list' }).click()
  const rule = form.getByLabel('python check.py', { exact: true })
  await expect(rule).not.toBeChecked()
  expect((await rules()).map(r => r.prefix)).toEqual(['python check.py'])
  expect((await kept()).permissions.commands).toEqual([])
  // Ticked, and still nothing of the trigger is saved until Save.
  await rule.check()
  expect((await kept()).permissions.commands).toEqual([])
  await form.getByRole('button', { name: 'Save' }).click()
  await expect(form).toHaveCount(0)
  await expect(card).toContainText('may run: python check.py')
  const saved = await kept()
  expect(saved.command_lines).toEqual(['python check.py'])
  expect(saved.permissions.commands).toEqual((await rules()).map(r => r.id))

  // Run again: the command ran, as written, with nobody asked.
  await card.getByRole('button', { name: 'Run now' }).click()
  await expect(chat.getByText('Ran it: 2 passed.')).toBeVisible({ timeout: 20_000 })
  await expect(chat.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  const snap: { commands: { command: string; status: string; output: string }[] } = await (await request.get(`/api/conversations/${saved.conversation_id}`)).json()
  expect(snap.commands.map(c => [c.command, c.status])).toEqual([['python check.py', 'exited']])
  expect(snap.commands[0].output).toContain('2 passed')

  // The row keeps what was done to the trigger, newest first, behind its ⋯; the page keeps a deleted one's.
  await rail(page, 'Triggers').click()
  await card.getByRole('button', { name: 'More for Nightly run' }).click()
  await page.getByRole('menuitem', { name: 'Changes (2)' }).click()
  const changes = page.getByRole('list', { name: 'Changes to Nightly run' }).getByRole('listitem')
  await expect(changes).toHaveCount(2)
  await expect(changes.first()).toContainText('permissions changed: may run: python check.py')
  await expect(changes.last()).toContainText('created: on a request from outside; no end; reads only; 15 model steps and 10 minutes a run, 24 runs a day')
  await shot(page, '18a-trigger-changes')
  // Taken off the conversation's list, the command is gone from the trigger at once - and that is on its record too.
  const [only] = await rules()
  expect((await request.delete(`/api/allowed-commands/${only.id}`, { headers: OWN })).status()).toBe(204)
  await expect(card).toContainText('reads only')
  await expect(changes.first()).toContainText('permissions changed: reads only')
  // Deleted, it is still on the project's record.
  await card.getByRole('button', { name: 'More for Nightly run' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Delete' }).click()
  await expect(card).toHaveCount(0)
  await page.getByText(/^Changes of deleted triggers/).click()
  await expect(page.getByRole('list', { name: 'Changes of deleted triggers' }).getByRole('listitem').first()).toContainText('Nightly run · deleted')
})
