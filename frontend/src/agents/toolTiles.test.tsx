import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { KnowledgeItem, Role, Skill } from '../api/types'
import { AgentsPage } from './AgentsPage'
import { ROLE_TOOLS } from './roleTools'

// Slice 81d: a role's Tools tab is a tile for each tool, grouped; a click turns one on or off and saves at once.
const coder: Role = {
  id: 'r1',
  name: 'Coder',
  description: 'Writes code',
  instructions: '',
  tools: ['list_dir', 'read_file', 'search', 'run_command', 'assess_task'],
  builtin: true,
  created_by_agent: false, models: null,
  provider_id: null,
  model_id: null,
  tier: null,
  tier_min: null,
  tier_max: null,
  kind: 'build',
  enabled: true,
  teams: [],
  pick_from: null,
  max_steps: null,
  max_tokens: null,
  effort: null,
  max_effort: null,
  context_window: null,
  mcp: ['github'],
  skills: ['ponytail'],
  inside_cli: false,
  knows: [],
  created_at: 't',
  updated_at: 't',
}
const handlers = () => ({
  onSave: vi.fn().mockResolvedValue(undefined),
  onCreate: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onReset: vi.fn().mockResolvedValue(undefined),
})
async function open(role: Role, onPatch = vi.fn().mockResolvedValue(undefined)) {
  render(<AgentsPage roles={[role]} picked={role.id} onPatch={onPatch} {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  return onPatch
}
const tile = (name: string) => screen.getByRole('button', { name })

test('the tiles show what the role may use, and the summary and each group count it', async () => {
  await open(coder)
  // (assess_task is the role's, but no tile's: it is not counted)
  expect(screen.getByText(/^May use/)).toHaveTextContent('May use 4 of 36 tools · 1 MCP server · 1 skill')
  expect(screen.getByRole('heading', { name: /^To-do/ })).toHaveTextContent('To-do0 of 3')
  expect(screen.getByRole('heading', { name: /^Files/ })).toHaveTextContent('Files3 of 9')
  expect(screen.getByRole('heading', { name: /^Commands/ })).toHaveTextContent('Commands1 of 1')
  expect(screen.getByRole('heading', { name: /^Web/ })).toHaveTextContent('Web0 of 2')
  expect(tile('Read files')).toHaveAttribute('aria-pressed', 'true')
  expect(tile('Read files')).toHaveAccessibleDescription('open and read')
  expect(tile('Write files')).toHaveAttribute('aria-pressed', 'false')
  expect(screen.getAllByRole('button', { pressed: true }).filter(b => b.classList.contains('tool-tile'))).toHaveLength(4)
  expect(screen.getAllByRole('button').filter(b => b.classList.contains('tool-tile'))).toHaveLength(ROLE_TOOLS.length)
  expect(screen.getByText('github')).toHaveClass('chip')
})

test('"asks" is on the tools that wait for your yes at the permission level, where they are on; the permission level is said once, behind the "?"', async () => {
  expect(ROLE_TOOLS.filter(tool => tool.asks).map(tool => tool.name)).toEqual(['write_file', 'edit_file', 'run_command', 'web_search', 'http_request', 'create_role', 'add_task', 'change_task'])
  await open({ ...coder, tools: ['read_file', 'write_file', 'run_command'] })
  expect(tile('Write files')).toHaveTextContent('asks')
  expect(tile('Run commands')).toHaveTextContent('asks')
  expect(tile('Read files')).not.toHaveTextContent('asks')
  // off, it asks nothing
  expect(tile('Edit files')).not.toHaveTextContent('asks')
  expect(screen.getByRole('button', { name: 'About this' })).toHaveAccessibleDescription(/permission level/)
  expect(screen.getAllByText(/permission level/)).toHaveLength(1)
})

test('a click saves the role’s tools at once, with the one changed, and says so', async () => {
  const onPatch = await open(coder)
  await userEvent.click(tile('Write files'))
  expect(onPatch).toHaveBeenCalledWith('r1', { tools: [...coder.tools, 'write_file'] })
  expect(tile('Write files')).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByText('Write files: on, saved.')).toHaveAttribute('role', 'status')
  await userEvent.click(tile('Run commands'))
  expect(onPatch).toHaveBeenLastCalledWith('r1', { tools: ['list_dir', 'read_file', 'search', 'assess_task', 'write_file'] })
  expect(await screen.findByText('Run commands: off, saved.')).toBeInTheDocument()
})

test('a save that fails puts the tile back as saved and says why', async () => {
  await open(coder, vi.fn().mockRejectedValue({ detail: 'unknown tool: write_file' }))
  await userEvent.click(tile('Write files'))
  expect(await screen.findByRole('alert')).toHaveTextContent('unknown tool: write_file')
  expect(tile('Write files')).toHaveAttribute('aria-pressed', 'false')
  expect(screen.getByText(/^May use/)).toHaveTextContent('May use 4 of 36')
})

test('a tile is toggled from the keyboard', async () => {
  const onPatch = await open(coder)
  tile('Search the web').focus()
  await userEvent.keyboard('{Enter}')
  expect(onPatch).toHaveBeenLastCalledWith('r1', { tools: [...coder.tools, 'web_search'] })
  await userEvent.tab()
  expect(tile('Web requests')).toHaveFocus()
  await userEvent.keyboard(' ')
  expect(onPatch).toHaveBeenLastCalledWith('r1', { tools: [...coder.tools, 'web_search', 'http_request'] })
  expect(tile('Web requests')).toHaveAttribute('aria-pressed', 'true')
})

test('the last tool stays on: a role needs one', async () => {
  const onPatch = await open({ ...coder, tools: ['read_file'] })
  expect(tile('Read files')).toBeDisabled()
  expect(tile('Read files')).toHaveAttribute('title', 'A role needs at least one tool: turn another on first')
  expect(tile('List folders')).toBeEnabled()
  await userEvent.click(tile('Read files'))
  expect(onPatch).not.toHaveBeenCalled()
})

test("0.1.0-ui: the role's MCP servers and skills are a list, each opening the Tools page on it; nothing is given here", async () => {
  const onPatch = vi.fn().mockResolvedValue(undefined)
  const onOpenTools = vi.fn()
  const onOpenSkills = vi.fn()
  render(<AgentsPage roles={[coder]} picked={coder.id} onPatch={onPatch} onOpenTools={onOpenTools} onOpenSkills={onOpenSkills} {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  // no box, no ✕, no "+ add" to give or take one here
  expect(screen.queryByRole('combobox', { name: /MCP server/ })).toBeNull()
  expect(screen.queryByRole('button', { name: /^Take / })).toBeNull()
  expect(screen.queryByRole('checkbox', { name: /^Skill / })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'github, on the Tools page' }))
  expect(onOpenTools).toHaveBeenLastCalledWith('github')
  await userEvent.click(screen.getByRole('button', { name: 'ponytail, on the Tools page' }))
  expect(onOpenSkills).toHaveBeenLastCalledWith('ponytail')
  // one heading for both, and one small way to the Tools page
  expect(screen.getByRole('heading', { name: /^Servers and skills/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'on Tools →' }))
  expect(onOpenTools).toHaveBeenLastCalledWith()
  expect(onPatch).not.toHaveBeenCalled()
})

test('a server switched off on the Tools page says off on the role, and a skill that asks for it cannot run there', async () => {
  const ponytail = { id: 'k1', name: 'ponytail', description: '', enabled: true, needs: { groups: [], mcp: ['github'], unknown: [], tools: {} } } as unknown as Skill
  render(<AgentsPage roles={[coder]} picked={coder.id} serversOff={['github']} skills={[ponytail]} onOpenTools={vi.fn()} onOpenSkills={vi.fn()} {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  expect(screen.getByRole('button', { name: 'github, off, on the Tools page' })).toHaveTextContent('github · off')
  expect(screen.getByRole('button', { name: 'ponytail, cannot run here: no MCP server github, on the Tools page' })).toHaveTextContent('⚠ ponytail')
})

test('a role with no server and no skill says none', async () => {
  render(<AgentsPage roles={[{ ...coder, mcp: [], skills: [] }]} picked={coder.id} onPatch={vi.fn()} {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  expect(screen.getAllByText('none')).toHaveLength(1)
  // with nowhere to open, no way to the Tools page
  expect(screen.queryByRole('button', { name: 'on Tools →' })).toBeNull()
})

test('0.1.0-ui: the texts the user named are gone from the Tools and Knowledge tabs', async () => {
  const knowledge = [{ id: 'k1', project_id: 'p1', knowledge: { topic: 'Stripe' }, state: { learned: null } }] as unknown as KnowledgeItem[]
  render(<AgentsPage roles={[coder]} picked={coder.id} onPatch={vi.fn()} onOpenTools={vi.fn()} onOpenSkills={vi.fn()} projectId="p1" knowledge={knowledge} onOpenKnowledge={vi.fn()} {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  const panel = screen.getByRole('complementary', { name: 'Role Coder' })
  for (const gone of ['+ add a server on Tools', 'A click turns a tool or skill on or off', 'says why']) expect(panel).not.toHaveTextContent(gone)
  for (const gone of ['MCP servers', 'Skills', '+ add']) expect(within(panel).queryByText(gone, { exact: true })).toBeNull()
  await userEvent.click(screen.getByRole('tab', { name: 'Knowledge' }))
  expect(panel).not.toHaveTextContent('+ Add knowledge on the Knowledge page')
  expect(panel).not.toHaveTextContent('A switch turns it on (as a map) or off and saves at once.')
  expect(within(panel).getByRole('button', { name: 'on Knowledge →' })).toBeInTheDocument()
})

test('a tool switched off on the Tools page is said to be, and the role keeps it (slice 61)', async () => {
  render(<AgentsPage roles={[{ ...coder, tools: [...coder.tools, 'web_search'] }]} picked="r1" off={['web_search', 'http_request']} {...handlers()} />)
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  expect(tile('Search the web')).toHaveAttribute('aria-pressed', 'true')
  expect(tile('Search the web')).toHaveAccessibleDescription(/off on the Tools page/)
  expect(tile('Search the web')).not.toHaveTextContent('asks you')
  expect(tile('Web requests')).toHaveTextContent('off on the Tools page')
  expect(tile('Read files')).not.toHaveTextContent('off on the Tools page')
})
