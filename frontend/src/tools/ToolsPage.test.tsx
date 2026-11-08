import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { McpServer, McpTool, Role } from '../api/types'
import { ToolsPage } from './ToolsPage'

const tool = (name: string, over: Partial<McpTool> = {}): McpTool => ({
  name,
  description: `Does ${name}.`,
  input_schema: { type: 'object', properties: {} },
  mark: 'ask',
  unusable: null,
  chars: 300,
  ...over,
})
const server = (over: Partial<McpServer> = {}): McpServer => ({
  id: 's1',
  name: 'rea',
  command: ['rea-agents', '--stdio'],
  env_names: ['REA_TOKEN'],
  tools: [tool('scan', { chars: 1200 }), tool('patch', { mark: 'free' }), tool('wipe', { mark: 'off' }), tool('bad name!', { unusable: 'its name has characters other than letters, digits, _ and -', chars: null })],
  read_at: '2026-10-12T10:00:00Z',
  read_error: null,
  trusted: true,
  enabled: true,
  ...over,
})
const role = (id: string, name: string, mcp: string[] = []) => ({ id, name, mcp }) as Role
const handlers = () => ({
  onAdd: vi.fn().mockResolvedValue(server({ id: 's2', name: 'new', tools: [], read_at: null })),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onRead: vi.fn().mockResolvedValue({ server: server(), new: ['scan'], changed: ['patch'], gone: ['old'] }),
  onRoleServers: vi.fn().mockResolvedValue(undefined),
})
/** One of the Add menu's ways, opened from its button. */
const add = async (way: RegExp) => {
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  await userEvent.click(screen.getByRole('menuitem', { name: way }))
}
const edit = () => userEvent.click(screen.getByRole('button', { name: 'Edit' }))

test('a server shows its command, its variables by name only and what each tool costs a step', async () => {
  render(<ToolsPage servers={[server()]} roles={[]} {...handlers()} />)
  // its command on the unfolded row's first line; its name, command and variables behind Edit
  expect(screen.getByTitle('rea-agents --stdio')).toHaveTextContent('rea-agents --stdio')
  expect(screen.queryByLabelText('Name')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Edit' })).toHaveAttribute('aria-expanded', 'false')
  await edit()
  expect(screen.getByRole('button', { name: 'Edit' })).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByLabelText('Name')).toHaveValue('rea')
  expect(screen.getByLabelText('Name')).toHaveAttribute('readonly')
  expect(screen.getByLabelText('Command')).toHaveValue('rea-agents\n--stdio')
  // the value of a saved variable is not here to show: an empty field, written as a password
  expect(screen.getByText('REA_TOKEN')).toBeInTheDocument()
  expect(screen.getByLabelText('New value of REA_TOKEN')).toHaveValue('')
  expect(screen.getByLabelText('New value of REA_TOKEN')).toHaveAttribute('type', 'password')
  const row = (name: string) => within(screen.getByRole('row', { name: new RegExp(`^${name}`) }))
  // the description is the server's, and said to be - and so are a tool's inputs, which can be opened
  expect(screen.getByRole('columnheader', { name: 'The server’s own description and inputs' })).toBeInTheDocument()
  expect(row('scan').getByText('“Does scan.”')).toBeInTheDocument()
  expect(row('scan').getByText('Its inputs, as an agent is given them').closest('details')).toHaveTextContent('"type": "object"')
  expect(row('bad name!').queryByText(/Its inputs/)).not.toBeInTheDocument()
  expect(row('scan').getByText('about 1,200 characters')).toBeInTheDocument()
  expect(row('patch').getByRole('combobox')).toHaveValue('free')
  // one that cannot be offered says why, and has no mark to set
  expect(row('bad name!').getByText(/Not offered: its name has characters other than/)).toBeInTheDocument()
  expect(row('bad name!').queryByRole('combobox')).not.toBeInTheDocument()
  // the sum counts what is on: not the one switched off, not the one that cannot be offered
  expect(screen.getByText(/2 tools on: about 1,500 characters added to every model step/)).toBeInTheDocument()
  // and it is said above the table too, in sight before the table is read to its end
  const above = screen.getByText(/^2 of 4 tools on · about 1,500 characters added to every model step$/)
  expect(above.compareDocumentPosition(screen.getByRole('table')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

const names = () => screen.queryAllByRole('rowheader').map(th => th.textContent)

test('a search box lists the tools whose name or description has what is typed, as it is typed', async () => {
  const tools = [tool('scan', { chars: 1200 }), tool('patch', { description: 'Changes a file in place.' }), tool('wipe', { mark: 'off' }), tool('listing', { description: 'Scans a folder.' })]
  render(<ToolsPage servers={[server({ tools })]} roles={[]} {...handlers()} />)
  const find = screen.getByRole('searchbox', { name: 'Find a tool' })
  expect(names()).toEqual(['scan', 'patch', 'wipe', 'listing'])
  // by name, whatever the case
  await userEvent.type(find, 'PAT')
  expect(names()).toEqual(['patch'])
  expect(screen.getByText(/· 1 shown$/)).toBeInTheDocument()
  // by description: "scan" is one tool's name and in another's description
  await userEvent.clear(find)
  await userEvent.type(find, 'scan')
  expect(names()).toEqual(['scan', 'listing'])
  // a mark is still set from a row that was found
  expect(screen.getByLabelText('When an agent calls listing')).toHaveValue('ask')
  // what is on is counted over all of the server's tools, not over the ones shown
  expect(screen.getByText(/^3 of 4 tools on · about 1,800 characters added to every model step · 2 shown$/)).toBeInTheDocument()
  expect(screen.getByText(/3 tools on: about 1,800 characters added to every model step/)).toBeInTheDocument()
  // nothing found is said, in place of an empty table
  await userEvent.type(find, 'zzz')
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  expect(screen.getByText('No tool has “scanzzz” in its name or description.')).toBeInTheDocument()
  // emptied, every tool is listed again
  await userEvent.clear(find)
  expect(names()).toEqual(['scan', 'patch', 'wipe', 'listing'])
})

test('all of a server’s tools that can be offered are set to Ask or to Off in one request - never to "Runs without asking"', async () => {
  const h = handlers()
  render(<ToolsPage servers={[server()]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Set all to Off' }))
  // one request, with every tool that has a mark: not the one that cannot be offered
  expect(h.onSave).toHaveBeenCalledExactlyOnceWith('s1', { marks: { scan: 'off', patch: 'off', wipe: 'off' } })
  await userEvent.click(screen.getByRole('button', { name: 'Set all to Ask' }))
  expect(h.onSave).toHaveBeenLastCalledWith('s1', { marks: { scan: 'ask', patch: 'ask', wipe: 'ask' } })
  // all is all: a search narrows what is listed, not what "all" means
  await userEvent.type(screen.getByRole('searchbox', { name: 'Find a tool' }), 'scan')
  expect(names()).toEqual(['scan'])
  await userEvent.click(screen.getByRole('button', { name: 'Set all to Off' }))
  expect(h.onSave).toHaveBeenLastCalledWith('s1', { marks: { scan: 'off', patch: 'off', wipe: 'off' } })
  expect(h.onSave).toHaveBeenCalledTimes(3)
  // leave to run without asking is given tool by tool, never to all at once
  expect(screen.getAllByRole('button', { name: /^Set all to / }).map(button => button.textContent)).toEqual(['Set all to Ask', 'Set all to Off'])
  expect(screen.queryByRole('button', { name: /without asking/i })).not.toBeInTheDocument()
  // what "all" means is behind the ⓘ beside them, and describes it
  const why = screen.getByText(/^Each sets every one of this server’s 3 tools that can be offered/)
  expect(why).not.toBeVisible()
  expect(why).toHaveTextContent('and not only the 1 shown. It cannot be undone.')
})

test('a refused "set all" says why, and a server none of whose tools can be offered has nothing to set', async () => {
  const h = handlers()
  h.onSave.mockRejectedValueOnce({ detail: 'the server was removed' })
  const { unmount } = render(<ToolsPage servers={[server()]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Set all to Ask' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('the server was removed')
  unmount()
  render(<ToolsPage servers={[server({ tools: [tool('bad name!', { unusable: 'its name has characters other than letters', chars: null })] })]} roles={[]} {...h} />)
  expect(screen.getByRole('button', { name: 'Set all to Ask' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Set all to Off' })).toBeDisabled()
})

test('a server with 170 tools: the first 8 and "+ 162 more", none of their inputs open; a search lists every one it finds', async () => {
  const many = Array.from({ length: 170 }, (_, n) => tool(`tool_${n + 1}`, { description: n % 10 === 0 ? 'Reads a listing.' : 'Writes a contract.' }))
  render(<ToolsPage servers={[server({ tools: many })]} roles={[]} {...handlers()} />)
  expect(names()).toEqual(['tool_1', 'tool_2', 'tool_3', 'tool_4', 'tool_5', 'tool_6', 'tool_7', 'tool_8'])
  expect(document.querySelectorAll('details[open]')).toHaveLength(0)
  expect(screen.getByText(/^170 of 170 tools on · about 51,000 characters added to every model step$/)).toBeInTheDocument()
  // typed: every one found, past the first 8
  await userEvent.type(screen.getByRole('searchbox', { name: 'Find a tool' }), 'listing')
  expect(names()).toHaveLength(17)
  expect(screen.queryByRole('button', { name: /more$/ })).not.toBeInTheDocument()
  await userEvent.clear(screen.getByRole('searchbox', { name: 'Find a tool' }))
  expect(names()).toHaveLength(8)
  // "+ N more" lists them all, every column and mark with them
  await userEvent.click(screen.getByRole('button', { name: '+ 162 more' }))
  expect(names()).toHaveLength(170)
  expect(screen.getByLabelText('When an agent calls tool_170')).toHaveValue('ask')
  expect(screen.queryByRole('button', { name: /more$/ })).not.toBeInTheDocument()
})

test('the Servers tab says in one line what a server is; that it runs with your rights and what it is not held to are behind its ⓘ', async () => {
  render(<ToolsPage servers={[]} roles={[]} {...handlers()} />)
  const panel = screen.getByRole('tabpanel', { name: /^Servers/ })
  const lead = panel.querySelector('.tools-lead')!
  expect(lead).toHaveTextContent(/^Programs that give agents more tools\. A new one asks before every call until you trust it\./)
  // the rest, all of it there, behind a button that can be focused and is described by it, closed
  const about = within(panel).getAllByRole('button', { name: 'About this' })[0]
  const more = document.getElementById(about.getAttribute('aria-describedby')!)!
  expect(more).not.toBeVisible()
  expect(about).toHaveAccessibleDescription(/A server runs with your rights on this machine\./)
  about.focus()
  expect(about).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  expect(more).toBeVisible()
  expect(more).toHaveTextContent('A server you add is watched: every call asks, at every level, until you trust it.')
  expect(more).toHaveTextContent('It is not held to the project folder, to working copies or to the permission level')
  expect(more).toHaveTextContent('“Runs without asking” is your word: KOLONİ cannot check that a tool only reads.')
  expect(more).toHaveTextContent('is not put on record as a change')
  expect(more).toHaveTextContent('put a secret in a variable')
  expect(more).toHaveTextContent('It is started in an empty folder of KOLONİ’s own, never in a project or a working copy')
  expect(more).toHaveTextContent('Its tools are given full paths')
  expect(more).toHaveTextContent(
    'a CLI that works with its own tools (native), for a trigger’s message, in a project that runs its commands in Docker, or when an agent works only to answer another agent’s message or to speak in a discussion',
  )
  // what "How this works" said, and nothing else says, is in the fold
  expect(more).toHaveTextContent('Only the servers added here are started by KOLONİ: a project’s .mcp.json is not read.')
  expect(screen.queryByText('How this works')).not.toBeInTheDocument()
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})

test('one layout whatever is open: the heading with Add, the tabs, the servers each a row across the page, the open one under its row', async () => {
  const servers = [server(), server({ id: 's2', name: 'fetch', command: ['uvx', 'mcp-server-fetch'], env_names: [], tools: [], read_at: null })]
  const { container } = render(<ToolsPage servers={servers} roles={[]} {...handlers()} />)
  const page = container.firstElementChild!
  const parts = (of: Element) => Array.from(of.children).map(child => child.className || child.tagName)
  // no column beside: the heading, the tabs, the tab open; in it its line, then the list (no form to add one until asked)
  expect(container.querySelector('.agents-list, .agents-page, .composer-warning')).not.toBeInTheDocument()
  expect(parts(page)).toEqual(['conv-head', 'tabs tools-tabs', 'tools-panel'])
  const panel = screen.getByRole('tabpanel', { name: /^Servers/ })
  expect(parts(panel)).toEqual(['muted provider-note tools-lead', 'tools-servers'])
  // the first is open under its row: each row a disclosure of what it controls
  const row = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) })
  const under = (name: string) => document.getElementById(row(name).getAttribute('aria-controls')!)!
  expect(row('rea')).toHaveAttribute('aria-expanded', 'true')
  expect(under('rea').querySelector('form')).toBeVisible()
  expect(row('fetch')).toHaveAttribute('aria-expanded', 'false')
  expect(under('fetch')).not.toBeVisible()
  // another row opens its server under it, in place of the one open, and is scrolled into sight
  // (jsdom lays nothing out and has no scrollIntoView: only that it was asked of that row)
  const scrolled = vi.fn()
  Element.prototype.scrollIntoView = scrolled
  try {
    await userEvent.click(row('fetch'))
    expect(scrolled.mock.contexts).toEqual([row('fetch')])
    expect(scrolled).toHaveBeenCalledWith({ block: 'nearest' })
  } finally {
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
  }
  expect(row('fetch')).toHaveAttribute('aria-expanded', 'true')
  expect(under('fetch').querySelector('form')).toBeVisible()
  expect(container.querySelectorAll('form')).toHaveLength(1)
  // the open row clicked again closes it
  await userEvent.click(row('fetch'))
  expect(row('fetch')).toHaveAttribute('aria-expanded', 'false')
  expect(container.querySelectorAll('form')).toHaveLength(0)
  // a way chosen from Add: its form above the list, its heading with the focus; ✕ puts it away
  await add(/^A server, ready-made/)
  expect(screen.getByRole('region', { name: 'Start from a common server' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'A server, ready-made' })).toHaveFocus()
  expect(parts(panel)).toEqual(['muted provider-note tools-lead', 'role-editor tools-editor', 'tools-servers'])
  await userEvent.click(screen.getByRole('button', { name: 'Stop adding a server' }))
  expect(screen.queryByRole('region', { name: 'Start from a common server' })).toBeNull()
  expect(parts(page)).toEqual(['conv-head', 'tabs tools-tabs', 'tools-panel'])
})

test('a server’s switch turns it off for every agent and its row says so; its marks stay, and a refused switch says why', async () => {
  const h = handlers()
  const roles = [role('r1', 'Lead', ['rea']), role('r2', 'Coder')]
  const { rerender } = render(<ToolsPage servers={[server()]} roles={roles} {...h} />)
  const on = screen.getByRole('switch', { name: 'rea on' })
  const row = () => screen.getByRole('button', { name: /^rea/ })
  expect(on).toBeChecked()
  // beside the row's button, not in it; the row says its state, what it has, and the roles that may use it
  expect(row()).not.toContainElement(on)
  expect(row()).toHaveTextContent(/^rea trusted4 tools · 1 asks first · read \d+ (d|h|min) agoLead$/)
  await userEvent.click(on)
  expect(h.onSave).toHaveBeenCalledExactlyOnceWith('s1', { enabled: false })
  rerender(<ToolsPage servers={[server({ enabled: false })]} roles={roles} {...h} />)
  expect(screen.getByRole('switch', { name: 'rea on' })).not.toBeChecked()
  expect(row()).toHaveTextContent('off: given to no agent · 4 tools')
  expect(screen.getByLabelText('When an agent calls patch')).toHaveValue('free')
  h.onSave.mockRejectedValueOnce(new Error('refused'))
  await userEvent.click(screen.getByRole('switch', { name: 'rea on' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('refused')
})

test('a server deleted: the next row is open and has the focus; the last one deleted, Add has it and the common servers are the page', async () => {
  const h = handlers()
  const two = [server(), server({ id: 's2', name: 'fetch', command: ['uvx', 'mcp-server-fetch'], env_names: [] })]
  const { rerender } = render(<ToolsPage servers={two} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Delete server' }))
  rerender(<ToolsPage servers={[two[1]]} roles={[]} {...h} />)
  expect(screen.getByRole('button', { name: /^fetch/ })).toHaveFocus()
  expect(screen.getByRole('button', { name: /^fetch/ })).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Delete server' }))
  rerender(<ToolsPage servers={[]} roles={[]} {...h} />)
  expect(screen.getByRole('button', { name: 'Add' })).toHaveFocus()
  expect(screen.getByRole('region', { name: 'Start from a common server' })).toBeVisible()
})

test('added from a card and deleted in one visit: the page with none again, and Fill by hand empty, not the old card', async () => {
  const h = handlers()
  const github = server({ id: 's9', name: 'github', env_names: ['GITHUB_PERSONAL_ACCESS_TOKEN'], tools: [], read_at: null })
  h.onAdd.mockResolvedValueOnce(github)
  const { rerender } = render(<ToolsPage servers={[]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^GitHub/ }))
  await userEvent.type(screen.getByLabelText('Value 1'), 'a-token')
  await userEvent.click(screen.getByRole('button', { name: 'Add server' }))
  rerender(<ToolsPage servers={[github]} roles={[]} {...h} />)
  expect(screen.queryByRole('region', { name: /^A server/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Delete server' }))
  rerender(<ToolsPage servers={[]} roles={[]} {...h} />)
  expect(screen.getByRole('heading', { name: 'A server, ready-made' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Start from a common server' })).toBeVisible()
  await add(/^A server, by hand/)
  expect(screen.getByLabelText('Name')).toHaveValue('')
  expect(screen.queryByLabelText('Variable 1')).not.toBeInTheDocument()
})

test('the form says what is true of the command line and of the name', async () => {
  render(<ToolsPage servers={[]} roles={[]} {...handlers()} />)
  await add(/^A server, by hand/)
  // what is true of the command line: a launcher is read by the command interpreter
  // what saving refuses is in sight; why is behind ⓘ, closed, and still describes the field
  const note = screen.getByText(/^The program, then each argument on a line of its own \(at most 20\)\./)
  expect(note).toHaveTextContent('For a .cmd or .bat program (npx on Windows is one), saving refuses % ! ^ & | < > in its path and its arguments.')
  expect(note.closest('.hint')).toBeNull()
  const why = screen.getByText(/^A bare name is looked for on PATH/)
  expect(why).not.toBeVisible()
  expect(why).toHaveTextContent('A .cmd or .bat file is the exception: the Windows command interpreter runs it and would act on those characters.')
  expect(screen.getByLabelText('Command')).toHaveAccessibleDescription(/at most 20\)\. For a \.cmd or \.bat program .* A bare name is looked for on PATH/)
  expect(screen.getByText(/1 to 16 of a-z, 0-9 and -, starting with a letter\. It cannot be changed later/)).toBeInTheDocument()
})

test('a new server is sent with one argument a line and its variables', async () => {
  const h = handlers()
  render(<ToolsPage servers={[]} roles={[]} {...h} />)
  await add(/^A server, by hand/)
  await userEvent.type(screen.getByLabelText('Name'), 'new')
  await userEvent.type(screen.getByLabelText('Command'), 'python{Enter}  server.py  {Enter}{Enter}--stdio')
  await userEvent.click(screen.getByRole('button', { name: 'Add a variable' }))
  await userEvent.type(screen.getByLabelText('Variable 1'), 'TOKEN')
  await userEvent.type(screen.getByLabelText('Value 1'), 'secret-value')
  expect(screen.getByLabelText('Value 1')).toHaveAttribute('type', 'password')
  await userEvent.click(screen.getByRole('button', { name: 'Add server' }))
  expect(h.onAdd).toHaveBeenCalledWith({ name: 'new', command: ['python', 'server.py', '--stdio'], env: { TOKEN: 'secret-value' } })
})

test('saving sends only what changed: a new value, a variable taken away, another command', async () => {
  const h = handlers()
  render(<ToolsPage servers={[server({ env_names: ['KEEP', 'REA_TOKEN', 'OLD'] })]} roles={[]} {...h} />)
  await edit()
  await userEvent.type(screen.getByLabelText('New value of REA_TOKEN'), 'another')
  await userEvent.click(screen.getByRole('button', { name: 'Remove OLD' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  // the variable that was not touched is not named, and the command that did not change is not sent
  expect(h.onSave).toHaveBeenCalledWith('s1', { env: { REA_TOKEN: 'another', OLD: null } })
  expect(await screen.findByLabelText('New value of REA_TOKEN')).toHaveValue('')
  await userEvent.type(screen.getByLabelText('Command'), '{Enter}--verbose')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('s1', { command: ['rea-agents', '--stdio', '--verbose'] })
})

test('a mark is saved as it is chosen, and a role is given the server by its box', async () => {
  const h = handlers()
  const roles = [role('r1', 'Lead', ['rea', 'other']), role('r2', 'Coder', ['other'])]
  render(<ToolsPage servers={[server()]} roles={roles} {...h} />)
  await userEvent.selectOptions(screen.getByLabelText('When an agent calls scan'), 'Runs without asking')
  expect(h.onSave).toHaveBeenCalledWith('s1', { marks: { scan: 'free' } })
  expect(screen.getByLabelText('Lead')).toBeChecked()
  expect(screen.getByLabelText('Coder')).not.toBeChecked()
  await userEvent.click(screen.getByLabelText('Coder'))
  expect(h.onRoleServers).toHaveBeenCalledWith('r2', ['other', 'rea'])
  await userEvent.click(screen.getByLabelText('Lead'))
  expect(h.onRoleServers).toHaveBeenLastCalledWith('r1', ['other'])
})

test('reading its tools says what that reading found', async () => {
  const h = handlers()
  render(<ToolsPage servers={[server()]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
  // (not a package of npm's or PyPI's: osv.dev is not asked)
  expect(h.onRead).toHaveBeenCalledWith('s1', false)
  expect(await screen.findByRole('status')).toHaveTextContent(
    '4 tools read. New: scan. Changed: patch - one that ran without asking is asked about again. Gone: old.',
  )
})

test('a server that runs a file from a project is started only once the user says so (97)', async () => {
  const h = handlers()
  // (a name that turns the text around: written out, and sent back as it is)
  const files = { 'C:\\proj\\tools\\server\u202eyp.py': 'a'.repeat(64) }
  h.onRead.mockResolvedValueOnce({ server: server(), new: [], changed: [], gone: [], in_project: files })
  render(<ToolsPage servers={[server()]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
  const card = await screen.findByRole('region', { name: 'Start it anyway?' })
  expect(card).toHaveTextContent('This server runs C:\\proj\\tools\\server\\u202eyp.py from your project, which agents can change.')
  expect(screen.queryByRole('status')).not.toBeInTheDocument() // nothing was read
  await userEvent.click(within(card).getByRole('button', { name: 'Cancel' }))
  expect(h.onRead).toHaveBeenCalledTimes(1)
  h.onRead.mockResolvedValueOnce({ server: server(), new: [], changed: [], gone: [], in_project: files })
  await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Start it anyway' }))
  // the files as the user was told them go back: changed since, they are asked about again
  expect(h.onRead).toHaveBeenLastCalledWith('s1', false, files)
  expect(await screen.findByRole('status')).toHaveTextContent('4 tools read.')
  expect(screen.queryByRole('region', { name: 'Start it anyway?' })).not.toBeInTheDocument()
})

test('the start card names a few files and says when it is asked every time', async () => {
  const h = handlers()
  const files = { 'C:\\p\\a': 'h', 'C:\\p\\b': 'h', 'C:\\p\\c': 'h', 'C:\\p\\d': null, 'C:\\p\\e': 'h' }
  h.onRead.mockResolvedValueOnce({ server: server(), new: [], changed: [], gone: [], in_project: files })
  render(<ToolsPage servers={[server()]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
  const card = await screen.findByRole('region', { name: 'Start it anyway?' })
  expect(card).toHaveTextContent('runs C:\\p\\a, C:\\p\\b, C:\\p\\c and 2 more (a folder of it holds more than 2000 files')
  expect(card).toHaveTextContent('you are asked every time it starts')
})

test('a server that could not be read says why, and one never read says no agent is offered any', () => {
  const failed = server({ id: 's3', name: 'broken', tools: [], read_error: 'The server could not be started: the program nope was not found.' })
  const { unmount } = render(<ToolsPage servers={[failed]} roles={[]} {...handlers()} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Its tools could not be read. The server could not be started: the program nope was not found.')
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  unmount()
  render(<ToolsPage servers={[server({ tools: [], read_at: null })]} roles={[]} {...handlers()} />)
  expect(screen.getByText(/Its tools have not been read yet: no agent is offered any\./)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^rea/ })).toHaveTextContent('not read yet')
})

test('slice 92: a server not yet trusted says on its row that every call asks, and is trusted by its button', async () => {
  const h = handlers()
  const { unmount } = render(<ToolsPage servers={[server({ trusted: false })]} roles={[]} {...h} />)
  expect(screen.getByRole('button', { name: /^rea/ })).toHaveTextContent(/^rea watching4 tools · every call asks until you trust it/)
  expect(screen.getByText('Watching: every call asks')).toBeInTheDocument()
  // one line in sight; the rest behind its ⓘ
  expect(screen.getByText('Every call asks until you trust it.', { exact: false })).toBeVisible()
  expect(screen.getByText(/at every level, Full auto too, and “Runs without asking” waits/)).not.toBeVisible()
  // its tools are listed with the server's words, as for any server
  expect(screen.getByText('“Does scan.”')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Trust this server' }))
  expect(h.onSave).toHaveBeenCalledWith('s1', { trusted: true })
  unmount()
  // one trusted (every server added before slice 92) says none of it
  render(<ToolsPage servers={[server()]} roles={[]} {...handlers()} />)
  expect(screen.getByRole('button', { name: /^rea/ })).toHaveTextContent(/^rea trusted4 tools · 1 asks first/)
  expect(screen.queryByText('Watching: every call asks')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Trust this server' })).toBeNull()
})

test('slice 92: there is nothing to trust before its tools are read, and a package that updates itself says so', () => {
  const { unmount } = render(<ToolsPage servers={[server({ trusted: false, tools: [], read_at: null })]} roles={[]} {...handlers()} />)
  expect(screen.getByRole('button', { name: 'Trust this server' })).toBeDisabled()
  unmount()
  const latest = server({ trusted: false, command: ['npx', '-y', '@scope/srv'] })
  const { unmount: gone } = render(<ToolsPage servers={[latest]} roles={[]} {...handlers()} />)
  expect(screen.getByRole('button', { name: 'Trust this server' })).toHaveAccessibleDescription(
    '@scope/srv updates itself: trust covers future versions',
  )
  gone()
  render(<ToolsPage servers={[server({ trusted: false, command: ['npx', '-y', '@scope/srv@1.2.0'] })]} roles={[]} {...handlers()} />)
  expect(screen.queryByText(/updates itself/)).toBeNull()
})

test('with no server the common servers are the page; Add is a menu button that works from the keyboard', async () => {
  const { container } = render(<ToolsPage servers={[]} roles={[]} {...handlers()} />)
  // the page's width, not a list beside a form (slice 66)
  expect(container.querySelector('.tools-page')).toBeInTheDocument()
  expect(container.querySelector('.agents-list, .composer-warning')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Name')).not.toBeVisible()
  const cards = within(screen.getByRole('region', { name: 'Start from a common server' })).getAllByRole('button')
  expect(cards.map(card => card.querySelector('.tools-card-title')?.textContent)).toEqual([
    'Filesystem',
    'GitHub',
    'Browser (Playwright)',
    'Fetch',
    'REA (reverse engineering)',
    'Context7',
    'Chrome DevTools',
    'Git',
  ])
  // one whose command downloads what it runs says so
  expect(cards[0]).toHaveTextContent('May download @modelcontextprotocol/server-filesystem when it starts')
  expect(screen.getByRole('heading', { name: 'A server, ready-made' })).toBeInTheDocument()
  // nothing to put away: they are the page with none
  expect(screen.queryByRole('button', { name: 'Stop adding a server' })).toBeNull()
  // Enter opens the menu on its first way; the arrow keys, Home and End move along it; Esc closes it back on its button
  const button = screen.getByRole('button', { name: 'Add' })
  expect(button).toHaveAttribute('aria-haspopup', 'menu')
  expect(button).toHaveAttribute('aria-expanded', 'false')
  button.focus()
  await userEvent.keyboard('{Enter}')
  expect(button).toHaveAttribute('aria-expanded', 'true')
  const items = () => within(screen.getByRole('menu', { name: 'Add' })).getAllByRole('menuitem')
  expect(items().map(item => item.textContent)).toEqual(['A server, ready-made · from KOLONİ’s list', 'A server, from its page · paste its setup text', 'A server, by hand'])
  expect(items()[0]).toHaveFocus()
  await userEvent.keyboard('{ArrowUp}')
  expect(items()[2]).toHaveFocus()
  await userEvent.keyboard('{Home}{ArrowDown}')
  expect(items()[1]).toHaveFocus()
  await userEvent.keyboard('{End}')
  expect(items()[2]).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('menu')).toBeNull()
  expect(button).toHaveFocus()
  // chosen with Enter: that way's form in place of the common servers, its heading with the focus
  await userEvent.keyboard('{Enter}{ArrowDown}{Enter}')
  expect(screen.queryByRole('menu')).toBeNull()
  expect(screen.getByRole('heading', { name: 'A server, from its page' })).toHaveFocus()
  expect(screen.getByRole('textbox', { name: '1 · What you pasted' })).toBeVisible()
  expect(screen.queryByRole('region', { name: 'Start from a common server' })).toBeNull()
  // a click elsewhere, or the focus gone on, closes it
  await userEvent.click(button)
  expect(screen.getByRole('menu')).toBeInTheDocument()
  await userEvent.click(document.body)
  expect(screen.queryByRole('menu')).toBeNull()
  await userEvent.click(button)
  await userEvent.tab()
  expect(screen.queryByRole('menu')).toBeNull()
})

test('a card fills the form - its name, its command, its variables with no value - and nothing is added until you say so', async () => {
  const h = handlers()
  render(<ToolsPage servers={[]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^GitHub/ }))
  expect(screen.getByLabelText('Name')).toHaveValue('github')
  expect(screen.getByLabelText('Command')).toHaveValue('docker\nrun\n-i\n--rm\n-e\nGITHUB_PERSONAL_ACCESS_TOKEN\nghcr.io/github/github-mcp-server')
  expect(screen.getByLabelText('Variable 1')).toHaveValue('GITHUB_PERSONAL_ACCESS_TOKEN')
  // the token is yours to type: the field is empty, a password's, and has the focus
  expect(screen.getByLabelText('Value 1')).toHaveValue('')
  expect(screen.getByLabelText('Value 1')).toHaveAttribute('type', 'password')
  expect(screen.getByLabelText('Value 1')).toHaveFocus()
  expect(screen.getByRole('heading', { name: 'A server, by hand' })).toBeInTheDocument()
  expect(h.onAdd).not.toHaveBeenCalled()
  // another card fills the form anew; one with no variable leaves the command to finish
  const ready = () => add(/^A server, ready-made/)
  await ready()
  await userEvent.click(screen.getByRole('button', { name: /^Filesystem/ }))
  expect(screen.getByLabelText('Name')).toHaveValue('filesystem')
  expect(screen.getByLabelText('Command')).toHaveValue('npx\n-y\n@modelcontextprotocol/server-filesystem\nFULL-PATH-OF-A-FOLDER')
  expect(screen.getByLabelText('Command')).toHaveFocus()
  expect(screen.queryByLabelText('Variable 1')).not.toBeInTheDocument()
  // another way and back: the form is as it was left; the way chosen again changes nothing
  await userEvent.type(screen.getByLabelText('Command'), '{Enter}C:/work')
  await ready()
  await add(/^A server, from its page/)
  await add(/^A server, by hand/)
  await add(/^A server, by hand/)
  // the way already open chosen again: the focus is not lost, it is on Add
  expect(screen.getByRole('button', { name: 'Add' })).toHaveFocus()
  expect(screen.getByLabelText('Name')).toHaveValue('filesystem')
  expect(screen.getByLabelText('Command')).toHaveValue('npx\n-y\n@modelcontextprotocol/server-filesystem\nFULL-PATH-OF-A-FOLDER\nC:/work')
  // only "Add server" adds it
  await ready()
  await userEvent.click(screen.getByRole('button', { name: /^Fetch/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Add server' }))
  expect(h.onAdd).toHaveBeenCalledExactlyOnceWith({ name: 'fetch', command: ['uvx', 'mcp-server-fetch'], env: {} })
  expect(h.onRead).not.toHaveBeenCalled()
})

test('a server whose command may download what it runs asks before each reading of its tools; one that downloads nothing does not', async () => {
  const h = handlers()
  const fetch = server({ name: 'fetch', command: ['uvx', 'mcp-server-fetch'], env_names: [], tools: [], read_at: null })
  const { unmount } = render(<ToolsPage servers={[fetch]} roles={[]} {...h} />)
  const read = screen.getByRole('button', { name: 'Read its tools' })
  await userEvent.click(read)
  const ask = screen.getByRole('region', { name: 'Read its tools?' })
  expect(ask).toHaveTextContent('It may download mcp-server-fetch from the internet before it starts. The server runs on this machine with your rights.')
  expect(within(ask).getByRole('button', { name: 'Download and read' })).toHaveFocus()
  expect(h.onRead).not.toHaveBeenCalled()
  // answered either way, the focus is back on the button that asked
  await userEvent.click(within(ask).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('region', { name: 'Read its tools?' })).not.toBeInTheDocument()
  expect(read).toHaveFocus()
  expect(h.onRead).not.toHaveBeenCalled()
  await userEvent.click(read)
  // osv.dev is asked first, unless taken off: the name it is sent is said
  const osv = screen.getByRole('checkbox', { name: 'First look for it in osv.dev’s known-malware records' })
  expect(osv).toBeChecked()
  expect(osv).toHaveAccessibleDescription(expect.stringContaining('Sends the name mcp-server-fetch to osv.dev.'))
  await userEvent.click(screen.getByRole('button', { name: 'Download and read' }))
  expect(h.onRead).toHaveBeenCalledExactlyOnceWith('s1', true)
  await userEvent.click(read)
  await userEvent.click(screen.getByRole('checkbox', { name: /osv\.dev/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Download and read' }))
  expect(h.onRead).toHaveBeenLastCalledWith('s1', false)
  unmount()
  // read before, and its command since changed to another package: asked again, whatever was read
  const asks = async (command: string[], what: string) => {
    render(<ToolsPage servers={[server({ command })]} roles={[]} {...h} />)
    await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
    expect(screen.getByRole('region', { name: 'Read its tools?' })).toHaveTextContent(`It may download ${what} from the internet`)
    cleanup()
  }
  await asks(['npx', '-y', '@scope/other-server'], '@scope/other-server')
  // a launcher by its full path (a .cmd on Windows), behind cmd /c, or a container runner
  await asks(['C:\\Program Files\\nodejs\\npx.cmd', '-y', 'x'], 'x')
  await asks(['cmd', '/c', 'npx', '-y', 'y'], 'y')
  await asks(['podman', 'run', '-i', 'quay.io/some/server'], 'the image it names')
  // a program that downloads nothing: nothing is asked
  h.onRead.mockClear()
  render(<ToolsPage servers={[server({ command: ['python', 'server.py'] })]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
  expect(h.onRead).toHaveBeenCalledOnce()
  expect(screen.queryByRole('region', { name: 'Read its tools?' })).not.toBeInTheDocument()
})

test('a card’s variable is what its server needs to start: it is not added until its value is typed', async () => {
  const h = handlers()
  render(<ToolsPage servers={[]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^GitHub/ }))
  const add = screen.getByRole('button', { name: 'Add server' })
  expect(add).toBeDisabled()
  expect(add).toHaveAccessibleDescription('Type the value of GITHUB_PERSONAL_ACCESS_TOKEN first: the server cannot start without it.')
  await userEvent.type(screen.getByLabelText('Value 1'), 'a-token')
  expect(add).toBeEnabled()
  expect(add).not.toHaveAccessibleDescription()
  await userEvent.click(add)
  expect(h.onAdd).toHaveBeenCalledWith(expect.objectContaining({ name: 'github', env: { GITHUB_PERSONAL_ACCESS_TOKEN: 'a-token' } }))
})

test('what osv.dev said of the package is said beside what the reading found', async () => {
  const h = handlers()
  const fetch = server({ name: 'fetch', command: ['uvx', 'mcp-server-fetch'], env_names: [] })
  h.onRead.mockResolvedValueOnce({ server: fetch, new: [], changed: [], gone: [], malware: { package: 'mcp-server-fetch', records: [], error: null } })
  render(<ToolsPage servers={[fetch]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
  await userEvent.click(screen.getByRole('button', { name: 'Download and read' }))
  expect(await screen.findByRole('status')).toHaveTextContent('osv.dev lists no known-malware record for mcp-server-fetch.')
  h.onRead.mockResolvedValueOnce({ server: fetch, new: [], changed: [], gone: [], malware: { package: 'mcp-server-fetch', records: [], error: 'api.osv.dev could not be reached' } })
  await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
  await userEvent.click(screen.getByRole('button', { name: 'Download and read' }))
  expect(await screen.findByText(/osv\.dev could not be asked \(api\.osv\.dev could not be reached\): it was started without that check\./)).toBeInTheDocument()
})

test('a pinned card shows its licence and source, and fills the form with its variable already set', async () => {
  const h = handlers()
  render(<ToolsPage servers={[]} roles={[]} {...h} />)
  const rea = screen.getByRole('button', { name: /^REA/ })
  expect(rea).toHaveTextContent('May download rea-agents@6.8.0 when it starts')
  expect(rea).toHaveTextContent('MIT')
  // the link is beside the card's button, not in it
  const source = screen.getByRole('link', { name: 'Its source: github.com/morluto/rea' })
  expect(source).toHaveAttribute('href', 'https://github.com/morluto/rea')
  expect(rea).not.toContainElement(source)
  await userEvent.click(rea)
  expect(screen.getByLabelText('Command')).toHaveValue('npx\n-y\nrea-agents@6.8.0\nmcp')
  expect(screen.getByLabelText('Variable 1')).toHaveValue('REA_MCP_INPUT_SCHEMA_PROFILE')
  // nothing to type: it is added as it is, and nothing is read or downloaded by it
  await userEvent.click(screen.getByRole('button', { name: 'Add server' }))
  expect(h.onAdd).toHaveBeenCalledExactlyOnceWith({
    name: 'rea',
    command: ['npx', '-y', 'rea-agents@6.8.0', 'mcp'],
    env: { REA_MCP_INPUT_SCHEMA_PROFILE: 'compact' },
  })
  expect(h.onRead).not.toHaveBeenCalled()
})

test('a card’s variable that came with its value is not required: taken away, the server is still added', async () => {
  const h = handlers()
  render(<ToolsPage servers={[]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^REA/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Remove variable 1' }))
  const add = screen.getByRole('button', { name: 'Add server' })
  expect(add).toBeEnabled()
  expect(add).not.toHaveAccessibleDescription()
  await userEvent.click(add)
  expect(h.onAdd).toHaveBeenCalledWith(expect.objectContaining({ name: 'rea', env: {} }))
})

test('osv.dev is offered only for a package it would be asked about', async () => {
  const h = handlers()
  render(<ToolsPage servers={[server({ command: ['npx', '-y', './local-folder'] })]} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Read its tools' }))
  // still asked, as it may download: but no name would be sent, so none is offered
  expect(screen.getByRole('region', { name: 'Read its tools?' })).toBeInTheDocument()
  expect(screen.queryByRole('checkbox', { name: /osv\.dev/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'What does it do?' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Download and read' }))
  expect(h.onRead).toHaveBeenCalledWith('s1', false)
})

test('the Built-in group: each of KOLONİ’s own tools with what it does and a named switch (slice 61)', async () => {
  const onSwitchTool = vi.fn().mockResolvedValue(undefined)
  const builtin = [{ name: 'web_search', on: true }, { name: 'http_request', on: false }, { name: 'git_status', on: true }]
  render(<ToolsPage servers={[]} roles={[]} {...handlers()} builtin={builtin} onSwitchTool={onSwitchTool} />)
  await userEvent.click(screen.getByRole('tab', { name: /^Built-in/ }))
  const group = within(screen.getByRole('region', { name: 'Built-in tools' }))
  expect(group.getByRole('switch', { name: 'Search the web' })).toBeChecked()
  expect(group.getByRole('switch', { name: 'Search the web' })).toHaveAccessibleDescription(/^Looks things up on the web/)
  expect(group.getByRole('switch', { name: 'Web requests' })).not.toBeChecked()
  // one the server lists that the page has no words for yet: by its name
  expect(group.getByRole('switch', { name: 'git_status' })).toBeChecked()
  // what web off does to commands (K-web-komut): behind the tab's ⓘ
  expect(screen.getByRole('tabpanel', { name: /^Built-in/ })).toHaveTextContent(/KOLONİ’s own tools; one switched off is given to no agent\. One you switch off/)
  expect(within(screen.getByRole('tabpanel', { name: /^Built-in/ })).getByText(/While Search the web or Web requests is off, a command that reaches the internet \(curl,\s+git clone, an https address\) asks you on a card at every level, Full auto too\./)).toBeInTheDocument()
  await userEvent.click(group.getByRole('switch', { name: 'Search the web' }))
  expect(onSwitchTool).toHaveBeenCalledWith('web_search', false)
  await userEvent.click(group.getByRole('switch', { name: 'Web requests' }))
  expect(onSwitchTool).toHaveBeenCalledWith('http_request', true)
})

test('a switch that could not be saved says why', async () => {
  const onSwitchTool = vi.fn().mockRejectedValue(new Error('down'))
  render(<ToolsPage servers={[]} roles={[]} {...handlers()} builtin={[{ name: 'web_search', on: true }]} onSwitchTool={onSwitchTool} picked="builtin" />)
  await userEvent.click(screen.getByRole('switch', { name: 'Search the web' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('down')
})

const skillActions = () => ({
  onPreviewSkill: vi.fn(),
  onAddSkill: vi.fn(),
  onSkillLeave: vi.fn(),
  onSkillOn: vi.fn(),
  onDeleteSkill: vi.fn(),
  onSkillRecord: vi.fn().mockResolvedValue([]),
})

test('three tabs, each with its count: a tablist the arrow keys move along, one tab stop; picked opens the right one', async () => {
  const builtin = [{ name: 'web_search', on: true }, { name: 'http_request', on: false }]
  const page = (picked?: string) => (
    <ToolsPage servers={[server()]} roles={[]} {...handlers()} builtin={builtin} onSwitchTool={vi.fn()} skillActions={skillActions()} picked={picked} />
  )
  render(page())
  const tabs = screen.getByRole('tablist', { name: 'Kinds of tools' })
  expect(within(tabs).getAllByRole('tab').map(tab => tab.textContent)).toEqual(['Built-in 2', 'Servers 1', 'Skills 0'])
  expect(screen.getByRole('tab', { name: /^Servers/ })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getAllByRole('tabpanel')).toEqual([screen.getByRole('tabpanel', { name: /^Servers/ })])
  screen.getByRole('tab', { name: /^Servers/ }).focus()
  await userEvent.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: /^Skills/ })).toHaveFocus()
  expect(screen.getByRole('tabpanel', { name: /^Skills/ })).toHaveTextContent('No skill yet.')
  await userEvent.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: /^Built-in/ })).toHaveFocus()
  expect(screen.getByRole('tabpanel', { name: /^Built-in/ })).toBeVisible()
  expect(screen.getAllByRole('tab').map(tab => tab.tabIndex)).toEqual([0, -1, -1])
  await userEvent.keyboard('{End}')
  expect(screen.getByRole('tab', { name: /^Skills/ })).toHaveAttribute('aria-selected', 'true')
  // from Ctrl+K or a role: a skill opens Skills, a server Servers with its row open
  cleanup()
  render(page('skill:none'))
  expect(screen.getByRole('tab', { name: /^Skills/ })).toHaveAttribute('aria-selected', 'true')
  cleanup()
  render(page('s1'))
  expect(screen.getByRole('tab', { name: /^Servers/ })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('button', { name: /^rea/ })).toHaveAttribute('aria-expanded', 'true')
})

test('K-skill-uyum: "A skill" in the Add menu opens Skills with its add form', async () => {
  render(<ToolsPage servers={[server()]} roles={[]} skillActions={skillActions()} {...handlers()} />)
  expect(screen.queryByRole('button', { name: 'Add a skill' })).toBeNull()
  expect(screen.queryByLabelText('Skill folder')).toBeNull()
  await add(/^A skill/)
  const skills = screen.getByRole('tabpanel', { name: /^Skills/ })
  expect(within(skills).getByText('No skill yet.')).toBeVisible()
  expect(within(skills).getByLabelText('Skill folder')).toBeVisible()
  expect(within(skills).getByLabelText('Skill folder')).toHaveFocus()
  // its heading is no fold that put it away when clicked (the user's, 6 Nov); Cancel does
  await userEvent.click(within(skills).getByText('Add a skill'))
  expect(within(skills).getByLabelText('Skill folder')).toBeVisible()
  await userEvent.click(within(skills).getByRole('button', { name: 'Cancel' }))
  expect(within(skills).queryByLabelText('Skill folder')).toBeNull()
  expect(within(skills).getByText('No skill yet.')).toBeVisible()
})
