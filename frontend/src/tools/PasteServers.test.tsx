import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { McpServer } from '../api/types'
import { ToolsPage } from './ToolsPage'

// The Tools page's "A server, from its page" (slice 74), from its Add menu.
const fetchServer: McpServer = { id: 's1', name: 'fetch', command: ['uvx', 'mcp-server-fetch'], env_names: [], tools: [], read_at: null, read_error: null, trusted: true, enabled: true }
const handlers = () => ({
  onAdd: vi.fn().mockResolvedValue({ ...fetchServer, id: 's2', name: 'github' }),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onRead: vi.fn(),
  onRoleServers: vi.fn().mockResolvedValue(undefined),
})

const TOKEN = 'ghp_secret123456'
const block = JSON.stringify({
  mcpServers: {
    github: { command: 'npx', args: ['-y', '@modelcontextprotocol/server-github'], env: { GITHUB_PERSONAL_ACCESS_TOKEN: TOKEN } },
    fetch: { command: 'uvx', args: ['mcp-server-fetch'] },
  },
})
const card = (name: string) => within(screen.getByRole('region', { name: 'A server, from its page' })).getByRole('button', { name: new RegExp(`^${name}`) })
const form = () => within(screen.getByRole('region', { name: 'A server, by hand' }))
const textOf = () => (screen.getByRole('textbox', { name: '1 · What you pasted' }) as HTMLTextAreaElement)

async function pasteTab(h: ReturnType<typeof handlers>, servers: McpServer[] = [fetchServer]) {
  const page = render(<ToolsPage servers={servers} roles={[]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  await userEvent.click(screen.getByRole('menuitem', { name: /^A server, from its page/ }))
  await userEvent.click(textOf())
  return page
}

test('a pasted block: each server a compact card, its token put away at once, one already added skipped, and Add adds only the new one', async () => {
  const h = handlers()
  const page = await pasteTab(h)
  await userEvent.paste(block)
  // the token is in neither the text nor anything the page shows: MASK stands in its place
  expect(textOf().value).toContain('"GITHUB_PERSONAL_ACCESS_TOKEN": "••••••••"')
  expect(textOf().value).not.toContain(TOKEN)
  expect(page.container.innerHTML).not.toContain(TOKEN)
  // two servers: both closed, each a line of what matters
  expect(card('github')).toHaveAttribute('aria-expanded', 'false')
  expect(card('fetch')).toHaveAttribute('aria-expanded', 'false')
  expect(card('github')).toHaveTextContent(/^githubnpx … server-githubnew key kept secretdownloads on first read$/)
  expect(card('fetch')).toHaveTextContent('already added — will be skipped')
  expect(screen.getByRole('checkbox', { name: 'Add github' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Add fetch' })).toBeDisabled()
  expect(screen.getByRole('checkbox', { name: 'Add fetch' })).not.toBeChecked()
  // a card opens to its command, arguments and variables by name, and closes again
  await userEvent.click(card('github'))
  expect(card('github')).toHaveAttribute('aria-expanded', 'true')
  const body = document.getElementById(card('github').getAttribute('aria-controls')!)!
  expect(body).toBeVisible()
  expect(body).toHaveTextContent('Commandnpx')
  expect(body).toHaveTextContent('Arguments-y @modelcontextprotocol/server-github')
  expect(body).toHaveTextContent('VariablesGITHUB_PERSONAL_ACCESS_TOKEN kept secret')
  expect(body).toHaveTextContent('The token was in what you pasted: it is moved to the secret field and never shown again.')
  expect(body).toHaveTextContent('Downloads on first read: npx fetches @modelcontextprotocol/server-github from the internet. You are asked before it runs.')
  await userEvent.click(card('github'))
  expect(body).not.toBeVisible()
  // ticking a box does not open its card
  await userEvent.click(screen.getByRole('checkbox', { name: 'Add github' }))
  expect(card('github')).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByRole('button', { name: 'Add 0 servers' })).toBeDisabled()
  await userEvent.click(screen.getByRole('checkbox', { name: 'Add github' }))
  expect(screen.getByText('1 new server')).toBeInTheDocument()
  // Add: as the form adds - the same request, the value from the paste - and nothing is read
  await userEvent.click(screen.getByRole('button', { name: 'Add 1 server' }))
  expect(h.onAdd).toHaveBeenCalledExactlyOnceWith({
    name: 'github',
    command: ['npx', '-y', '@modelcontextprotocol/server-github'],
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: TOKEN },
  })
  expect(h.onRead).not.toHaveBeenCalled()
  // added: the new server is chosen, and what was pasted is gone with its form
  expect(screen.queryByRole('region', { name: /^A server/ })).not.toBeInTheDocument()
  expect(page.container.innerHTML).not.toContain(TOKEN)
})

test('one server alone is open and asks for its name; a value left to the reader is to be typed before adding', async () => {
  const h = handlers()
  await pasteTab(h, [])
  await userEvent.paste(JSON.stringify({ command: 'node', args: ['C:/srv/index.js'], env: { API_KEY: '${input:key}' } }))
  const head = card('no name yet')
  expect(head).toHaveAttribute('aria-expanded', 'true')
  expect(head).toHaveTextContent('node index.js')
  expect(head).toHaveTextContent('needs a value')
  expect(head).toHaveTextContent('needs a name')
  expect(screen.getByRole('checkbox', { name: 'Add this server' })).toBeDisabled()
  expect(screen.getByText(/API_KEY has no value in what you pasted/)).toBeInTheDocument()
  await userEvent.type(screen.getByRole('textbox', { name: 'Name of this server' }), 'mine')
  expect(card('mine')).not.toHaveTextContent('needs a name')
  // still no value: "Edit before adding" opens the form filled with it, the value left to type
  expect(screen.getByRole('button', { name: 'Add 0 servers' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Edit before adding' }))
  expect(screen.getByRole('heading', { name: 'A server, by hand' })).toBeInTheDocument()
  expect(form().getByLabelText('Name')).toHaveValue('mine')
  expect(form().getByLabelText('Command')).toHaveValue('node\nC:/srv/index.js')
  expect(form().getByLabelText('Variable 1')).toHaveValue('API_KEY')
  expect(form().getByLabelText('Value 1')).toHaveValue('')
  expect(form().getByRole('button', { name: 'Add server' })).toBeDisabled()
})

test('"Edit before adding" carries the pasted value into the form’s secret field; a refused server says why on its card', async () => {
  const h = handlers()
  const page = await pasteTab(h, [])
  // typed, not pasted: the value is put away when the box is left
  await userEvent.type(textOf(), `claude mcp add github -e GITHUB_PERSONAL_ACCESS_TOKEN=${TOKEN} -- npx -y @modelcontextprotocol/server-github`)
  await userEvent.tab()
  expect(textOf().value).not.toContain(TOKEN)
  expect(page.container.innerHTML).not.toContain(TOKEN)
  h.onAdd.mockRejectedValueOnce({ detail: 'this command cannot be started: % in an argument' })
  await userEvent.click(screen.getByRole('button', { name: 'Add 1 server' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('github was not added: this command cannot be started: % in an argument')
  // what was pasted is kept, to try again or to change by hand
  await userEvent.click(screen.getByRole('button', { name: 'Edit before adding' }))
  expect(form().getByLabelText('Name')).toHaveValue('github')
  expect(form().getByLabelText('Value 1')).toHaveValue(TOKEN)
  expect(form().getByLabelText('Value 1')).toHaveAttribute('type', 'password')
  // in the field's value only: never in the page's markup
  expect(page.container.innerHTML).not.toContain(TOKEN)
  await userEvent.click(form().getByRole('button', { name: 'Add server' }))
  expect(h.onAdd).toHaveBeenLastCalledWith({ name: 'github', command: ['npx', '-y', '@modelcontextprotocol/server-github'], env: { GITHUB_PERSONAL_ACCESS_TOKEN: TOKEN } })
})

test('a key in the arguments: MASK on the card and in the box, the key itself sent when the server is added', async () => {
  const h = handlers()
  const page = await pasteTab(h, [])
  await userEvent.paste(JSON.stringify({ mcpServers: { brave: { command: 'npx', args: ['-y', 'brave-mcp', '--api-key', TOKEN] } } }))
  expect(textOf().value).not.toContain(TOKEN)
  expect(page.container.innerHTML).not.toContain(TOKEN)
  expect(screen.getByText('-y brave-mcp --api-key ••••••••')).toBeInTheDocument()
  h.onAdd.mockRejectedValueOnce({ detail: 'refused' })
  await userEvent.click(screen.getByRole('button', { name: 'Add 1 server' }))
  expect(h.onAdd).toHaveBeenLastCalledWith({ name: 'brave', command: ['npx', '-y', 'brave-mcp', '--api-key', TOKEN], env: {} })
  // "Edit before adding" too: MASK in the form's box, the key sent for the line left as it was
  await userEvent.click(screen.getByRole('button', { name: 'Edit before adding' }))
  expect(form().getByLabelText('Command')).toHaveValue('npx\n-y\nbrave-mcp\n--api-key\n••••••••')
  expect(page.container.innerHTML).not.toContain(TOKEN)
  await userEvent.click(form().getByRole('button', { name: 'Add server' }))
  expect(h.onAdd).toHaveBeenLastCalledWith({ name: 'brave', command: ['npx', '-y', 'brave-mcp', '--api-key', TOKEN], env: {} })
})

test('what cannot be read says which shapes can; one reached over the network is named and the others still read', async () => {
  await pasteTab(handlers(), [])
  await userEvent.paste('npx -y something')
  expect(screen.getByRole('status')).toHaveTextContent('It reads a "mcpServers" block (Claude Desktop, Cursor)')
  await userEvent.clear(textOf())
  // its address and headers may carry a key: neither stays in the box
  await userEvent.paste(
    JSON.stringify({ servers: { notion: { type: 'http', url: 'https://mcp.example.test/?key=k1', headers: { Authorization: `Bearer ${TOKEN}` } }, fetch: { command: 'uvx', args: ['mcp-server-fetch'] } } }),
  )
  expect(screen.getByText(/Not added: notion - reached over the network \(url\)\. Only servers started by a command can be added yet\./)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Add 1 server' })).toBeEnabled()
  expect(textOf().value).not.toMatch(/ghp_|k1/)
  await userEvent.clear(textOf())
  await userEvent.paste(`claude mcp add --transport http notion https://mcp.example.test -H "Authorization: Bearer ${TOKEN}"`)
  expect(screen.getByText(/Not added: notion/)).toBeInTheDocument()
  expect(textOf().value).not.toContain(TOKEN)
})

test('JSONC with comments is read and its key put away; a block still unread says so without its key, which stays only in the box', async () => {
  const page = await pasteTab(handlers(), [])
  await userEvent.paste(`{\n  // from the README\n  "mcpServers": { "github": { "command": "npx", "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${TOKEN}", }, }, },\n}`)
  expect(textOf().value).toContain('"GITHUB_PERSONAL_ACCESS_TOKEN": "••••••••"')
  expect(page.container.innerHTML).not.toContain(TOKEN)
  await userEvent.clear(textOf())
  await userEvent.paste(`{mcpServers: {github: {command: 'npx', env: {GITHUB_PERSONAL_ACCESS_TOKEN: '${TOKEN}'}}}}`)
  const read = screen.getByRole('region', { name: '2 · What KOLONİ read from it' })
  expect(within(read).getByRole('status')).toHaveTextContent('This looks like JSON5 (a key without quotes, or a string in single quotes), which KOLONİ does not read')
  expect(read.textContent).not.toContain(TOKEN)
})

test('two new servers ticked: Add adds both, one request each', async () => {
  const h = handlers()
  h.onAdd.mockResolvedValueOnce({ ...fetchServer, id: 'a1', name: 'github' }).mockResolvedValueOnce({ ...fetchServer, id: 'a2', name: 'fetch' })
  await pasteTab(h, [])
  await userEvent.paste(block)
  await userEvent.click(screen.getByRole('button', { name: 'Add 2 servers' }))
  expect(h.onAdd.mock.calls).toEqual([
    [{ name: 'github', command: ['npx', '-y', '@modelcontextprotocol/server-github'], env: { GITHUB_PERSONAL_ACCESS_TOKEN: TOKEN } }],
    [{ name: 'fetch', command: ['uvx', 'mcp-server-fetch'], env: {} }],
  ])
})

test('servers named __proto__ or constructor, and a variable named __proto__, are read as any other', async () => {
  const h = handlers()
  const page = await pasteTab(h, [])
  await userEvent.paste('{"mcpServers": {"__proto__": {"command": "a"}, "constructor": {"command": "b", "env": {"__proto__": "v1"}}}}')
  expect(card('__proto__')).toHaveTextContent('needs a name')
  expect(card('constructor')).toHaveTextContent(/^constructorbnew key kept secret$/)
  expect(page.container.querySelector('[role="alert"]')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Add 1 server' }))
  expect(h.onAdd).toHaveBeenCalledExactlyOnceWith({ name: 'constructor', command: ['b'], env: JSON.parse('{"__proto__": "v1"}') })
  // from a claude mcp add line too
  cleanup()
  await pasteTab(handlers(), [])
  await userEvent.paste('claude mcp add x -e __proto__=v2 -- b')
  expect(card('x')).toHaveTextContent('key kept secret')
})

test('"Edit before adding" takes the server that needs a value first, though another is ticked', async () => {
  await pasteTab(handlers(), [])
  await userEvent.paste(JSON.stringify({ mcpServers: { fetch: { command: 'uvx', args: ['mcp-server-fetch'] }, brave: { command: 'npx', args: ['-y', 'brave'], env: { BRAVE_API_KEY: 'YOUR_API_KEY_HERE' } } } }))
  expect(screen.getByRole('checkbox', { name: 'Add fetch' })).toBeChecked()
  expect(card('brave')).toHaveTextContent('needs a value')
  await userEvent.click(screen.getByRole('button', { name: 'Edit before adding' }))
  expect(form().getByLabelText('Name')).toHaveValue('brave')
  expect(form().getByLabelText('Value 1')).toHaveValue('')
})
