import { readFileSync } from 'node:fs'
import { expect, test } from './fixtures'
import { editRole, openFreshConversation, rail, shot } from './helpers'
import { FAKE_MCP, MCP_PLAN, MCP_RECORD, PROJECT_DIR, PYTHON } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

/** What the stand-in server wrote down: each time it started, and each call it got. */
const recorded = () =>
  readFileSync(MCP_RECORD, 'utf8')
    .split('\n')
    .filter(Boolean)
    .map(line => JSON.parse(line) as { event: string; cwd?: string; files?: string[]; name?: string; arguments?: unknown })

test('an MCP server is added on the Tools page, read, given to the Lead, and a call of its tool is asked about', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // The user adds a program that speaks MCP: its command a line an argument, its plan in a variable.
  await rail(page, 'Tools').click()
  // The Servers tab's one line; that a server runs with your rights, and the rest, are behind its ⓘ.
  const servers = page.getByRole('tabpanel', { name: /^Servers/ })
  const about = servers.locator('.tools-lead').getByRole('button', { name: 'About this' })
  await expect(servers.getByText('“Runs without asking” is your word: KOLONİ cannot check that a tool only reads.')).toBeHidden()
  await about.click()
  await expect(servers.getByText('“Runs without asking” is your word: KOLONİ cannot check that a tool only reads.')).toBeVisible()
  await expect(servers.locator('.tools-lead')).toContainText('A server runs with your rights on this machine.')
  await expect(servers.locator('.tools-lead')).toContainText('It is started in an empty folder of KOLONİ’s own, never in a project or a working copy')
  await page.keyboard.press('Escape')
  // With no server the page offers common ones; your own is added by hand, from the Add menu.
  await expect(page.getByRole('region', { name: 'Start from a common server' }).getByRole('button')).toHaveCount(8)
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await page.getByRole('menuitem', { name: /^A server, by hand/ }).click()
  const form = page.locator('form.tools-editor')
  await form.getByLabel('Name', { exact: true }).fill('fake')
  await form.getByLabel('Command', { exact: true }).fill(`${PYTHON}\n${FAKE_MCP}`)
  await page.getByRole('button', { name: 'Add a variable' }).click()
  await form.getByLabel('Variable 1', { exact: true }).fill('FAKE_MCP_PLAN')
  await form.getByLabel('Value 1', { exact: true }).fill(MCP_PLAN)
  await page.getByRole('button', { name: 'Add server' }).click()
  // Saved: the variable is there by its name (behind Edit), and its value is not shown back.
  await form.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(page.getByLabel('New value of FAKE_MCP_PLAN')).toHaveValue('')
  await expect(page.getByText(/Its tools have not been read yet: no agent is offered any\./)).toBeVisible()

  // Its tools are read once - the server is started for that, and ended - and are listed as the server describes them.
  await page.getByRole('button', { name: 'Read its tools' }).click()
  await expect(form.getByRole('status')).toContainText('8 tools read. New: echo, where, boom, picture, big, hang, die, sample.')
  await shot(page, '28b-tools-form')
  const echo = page.getByRole('row', { name: /^echo/ })
  await expect(echo).toContainText('“Says back what it is given.”')
  await expect(echo).toContainText(/about [\d,]+ characters/)
  await expect(echo.getByRole('combobox')).toHaveValue('ask')
  // its inputs are the server's words too, and can be read before a mark is given
  await echo.getByText('Its inputs, as an agent is given them').click()
  await expect(echo.locator('pre')).toContainText('"required"')
  await expect(page.getByText(/8 tools on: about [\d,]+ characters added to every model step/)).toBeVisible()
  // Slice 92: a server added is watched - every call asks, at every level - until it is trusted.
  await expect(page.getByText('Watching: every call asks')).toBeVisible()
  await expect(page.getByRole('button', { name: /^fake/ })).toContainText('watching8 tools · every call asks until you trust it')
  // Switched off it is given to no agent, and says so; on again, as it was.
  await page.getByRole('switch', { name: 'fake on' }).click()
  await expect(page.getByRole('button', { name: /^fake/ })).toContainText('off: given to no agent')
  await page.getByRole('switch', { name: 'fake on' }).click()
  await expect(page.getByRole('switch', { name: 'fake on' })).toBeChecked()
  await expect(page.getByRole('button', { name: /^fake/ })).not.toContainText('off: given to no agent')
  // One the user does not want offered is switched off, and the sum counts one fewer.
  await page.getByLabel('When an agent calls hang').selectOption('Off')
  await expect(page.getByText(/7 tools on: /)).toBeVisible()

  // The Lead may use it; the role's own page names it. (The box is ticked once the role is saved.)
  await page.getByLabel('Lead', { exact: true }).click()
  await expect(page.getByLabel('Lead', { exact: true })).toBeChecked()
  await page.getByRole('table', { name: 'Tools of fake' }).scrollIntoViewIfNeeded()
  await shot(page, '28b-tools-page')
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await editRole(page, 'Lead', 'Tools')
  await expect(page.getByRole('button', { name: 'fake, on the Tools page' })).toBeVisible()
  await expect(page.getByText(/^May use/)).toContainText('· 1 MCP server ·')

  // The Lead calls the tool: the user is asked first, with the server, the tool and what it would be given.
  await rail(page, 'Canvas').click()
  await page.getByLabel('Message').fill('echo through the server')
  await page.getByRole('button', { name: 'Send' }).click()
  // the question is KOLONİ's own, under a title of its own with its words whole, and Allow and Reject are all there is to say to it
  await expect(chat.getByText(/May the tool "echo" of the MCP server "fake" run\? It would be given: \{"text": "hi from the page"\}/)).toBeVisible()
  await expect(chat.getByText('KOLONİ asks')).toBeVisible()
  await expect(chat.getByText('Allow this?', { exact: true })).toBeVisible()
  // watched: the card says so, with the server's tools and its own words for this one
  await expect(chat.getByText(/This server is watched: every call of it asks you, at every level/)).toBeVisible()
  await expect(chat.getByText(/Its tools: echo, where, boom/)).toBeVisible()
  await expect(chat.getByText(/What the server says of echo \(its words, not KOLONİ's\): "Says back what it is given\."/)).toBeVisible()
  await expect(chat.getByLabel('Your answer')).toHaveCount(0)
  // the call is named by its server and its tool, and it waits: it does not run
  await expect(chat.getByText('fake · echo: waits for your answer')).toBeVisible()
  // nothing ran before the yes: the server was started once, to read its tools, and never called
  expect(recorded().map(e => e.event)).toEqual(['start'])
  await shot(page, '28b-asked')
  await chat.getByRole('button', { name: 'Allow', exact: true }).click()
  await expect(chat.getByText('The server echoed it.')).toBeVisible()
  await expect(page.getByText('DONE', { exact: true })).toBeVisible()
  await expect(chat.getByRole('button', { name: /^fake · echo\s*done$/ })).toBeVisible()
  // it ran in an empty folder of KOLONİ's own - not in the project - and got what the user was shown
  const [, started, called] = recorded()
  expect(started.event).toBe('start')
  expect(started.files).toEqual([])
  expect(started.cwd?.toLowerCase().startsWith(PROJECT_DIR.toLowerCase())).toBe(false)
  expect(called).toMatchObject({ event: 'call', name: 'echo', arguments: { text: 'hi from the page' } })

  // Put back, so that later runs start without it: deleting the server takes it from the Lead too.
  await rail(page, 'Tools').click()
  // trusted, it is watched no more (its calls go back to the marks and the level)
  await page.getByRole('button', { name: 'Trust this server' }).click()
  await expect(page.getByText('Watching: every call asks')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^fake/ })).not.toContainText('watching')
  await page.getByRole('button', { name: 'Delete server' }).click()
  // none left: the page offers the common servers again
  await expect(page.getByRole('region', { name: 'Start from a common server' })).toBeVisible()
  await page.getByRole('button', { name: 'Agents', exact: true }).click()
  await editRole(page, 'Lead', 'Tools')
  await expect(page.getByText(/^May use/)).toContainText('· 0 MCP servers ·')
})
