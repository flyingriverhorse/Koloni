import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { CodeSeen, PackageSeen } from '../api/types'
import { ToolsPage } from './ToolsPage'
import { Seen } from './PackageLook'

afterEach(() => {
  vi.restoreAllMocks()
})

const nothing: CodeSeen = { read: 3, reaches: {}, programs: [], addresses: [], env: [], whole_env: false, hidden: [], unread: [] }
const COMMAND = ['npx', '-y', '@upstash/context7-mcp@4.4.4']

const handlers = () => ({
  onAdd: vi.fn(),
  onSave: vi.fn(),
  onDelete: vi.fn(),
  onRead: vi.fn(),
  onRoleServers: vi.fn(),
})

test('code in which nothing was seen is never called clean or safe: it says what was not seen', () => {
  const { container } = render(<Seen seen={nothing} notSeen={['Its dependencies.']} />)
  expect(container).not.toHaveTextContent(/clean|safe/i)
  expect(screen.getAllByText('none seen')).toHaveLength(4)
  expect(screen.getByText('Its dependencies.')).toBeInTheDocument()
  expect(container).toHaveTextContent('From 3 files of code read as text, none of it run. This is where to look, not a verdict')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('a card’s package is looked into on two clicks: its size asked first, then downloaded and read', async () => {
  const seen: PackageSeen = {
    ...nothing,
    registry: 'npm',
    name: '@upstash/context7-mcp',
    version: '4.4.4',
    license: 'MIT',
    size: 90_000,
    reaches: { programs: ['child_process'], network: ['https'] },
    programs: ['powershell.exe'],
    addresses: ['https://collector.example.invalid/upload'],
    env: ['GITHUB_TOKEN'],
    whole_env: true,
    hidden: ['eval in package/x.js'],
    unread: ['native code, which cannot be read as text: package/a.node'],
    on_install: ['postinstall: node setup.js'],
    dependencies: ['left-pad'],
  }
  const post = vi.spyOn(api, 'post').mockImplementation(async (path: string) =>
    path === '/mcp-servers/package' ? { registry: 'npm', name: '@upstash/context7-mcp', version: '4.4.4', size: 1_300_000, unpacked: true, license: 'MIT' } : seen,
  )
  render(<ToolsPage servers={[]} roles={[]} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Context7/ }))
  const card = screen.getByRole('region', { name: 'What does it do?' })
  // nothing is asked before the click
  expect(post).not.toHaveBeenCalled()
  await userEvent.click(within(card).getByRole('button', { name: 'Look inside…' }))
  expect(post).toHaveBeenCalledExactlyOnceWith('/mcp-servers/package', { command: COMMAND })
  const look = within(card).getByRole('button', { name: 'Look inside (downloads @upstash/context7-mcp, ~1.2 MB unpacked)' })
  expect(look).toHaveFocus()
  await userEvent.click(look)
  expect(post).toHaveBeenLastCalledWith('/mcp-servers/package/look', { command: COMMAND, version: '4.4.4' })
  expect(within(card).getByRole('alert')).toHaveTextContent('It hides what it does (eval in package/x.js): what is said below of it cannot be trusted.')
  expect(card).toHaveTextContent('It may reachStarting programs (child_process)The network (https)')
  expect(card).toHaveTextContent('powershell.exe')
  expect(card).toHaveTextContent('It reads its whole environment: every variable, keys among them.')
  expect(card).toHaveTextContent('postinstall: node setup.js')
  expect(card).toHaveTextContent('Its dependencies: npx installs and runs them too, and only @upstash/context7-mcp itself was read.')
  expect(card).toHaveTextContent('native code, which cannot be read as text: package/a.node')
  expect(card).not.toHaveTextContent(/clean|safe/i)
})

test('a command that is not npx or uvx has nothing to look inside', async () => {
  render(<ToolsPage servers={[]} roles={[]} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /^GitHub/ }))
  expect(screen.queryByRole('region', { name: 'What does it do?' })).not.toBeInTheDocument()
})
