import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Command } from '../api/types'
import { command } from '../test-fixtures'
import { AllowList } from './AllowList'
import { CommandApproval } from './CommandApproval'
import { CommandRow } from './CommandRow'
import { commandStatus } from './commandStatus'
import { outputPreview } from './outputPreview'

const lines = (n: number) => Array.from({ length: n }, (_, i) => `line ${i + 1}`).join('\n') + '\n'

test('short output is shown whole; long output keeps its first 20 and last 40 lines', () => {
  expect(outputPreview(lines(60))).toEqual({ head: lines(60).trimEnd(), tail: '', omitted: 0 })
  const preview = outputPreview(lines(200))
  expect(preview.omitted).toBe(140)
  expect(preview.head.split('\n')).toHaveLength(20)
  expect(preview.tail.split('\n')).toHaveLength(40)
  expect(preview.head.startsWith('line 1\n')).toBe(true)
  expect(preview.tail.endsWith('line 200')).toBe(true)
  expect(outputPreview('')).toEqual({ head: '', tail: '', omitted: 0 })
})

test.each<[Partial<Command>, string, string]>([
  [{ status: 'proposed', exit_code: null }, 'waits for you', 'warn'],
  [{ status: 'approved', exit_code: null }, 'approved — not started yet', 'muted'],
  [{ status: 'running', exit_code: null }, 'working', 'accent'],
  [{ status: 'exited', exit_code: 0 }, 'exit 0', 'ok'],
  [{ status: 'exited', exit_code: 1 }, 'exit 1', 'del'],
  [{ status: 'timed_out', exit_code: null }, 'timed out', 'del'],
  [{ status: 'killed', exit_code: null }, 'killed', 'muted'],
  [{ status: 'rejected', exit_code: null }, 'rejected', 'muted'],
  [{ status: 'failed_to_start', exit_code: null }, 'did not start', 'del'],
  // K-48: Codex's read-only sandbox refused its write, and it still exited 0
  [{ status: 'blocked', exit_code: 0 }, 'blocked: its read-only sandbox refused a write', 'del'],
  [{ status: 'interrupted', exit_code: null, started_at: '2026-10-11T10:00:00Z' }, 'interrupted', 'warn'],
  [{ status: 'interrupted', exit_code: null, started_at: null }, 'approved — the work ended before it ran', 'muted'],
])('status label for %o is "%s"', (over, label, tone) => {
  expect(commandStatus(command('k', 'r', over))).toEqual({ label, tone })
})

test('a command row shows the command and status and reveals its output', async () => {
  render(<CommandRow command={command('k', 'r', { output: lines(200), exit_code: 1 })} />)
  expect(screen.getByText('pytest -q')).toBeInTheDocument()
  expect(screen.getByText('exit 1')).toBeInTheDocument()
  expect(screen.queryByText(/line 200/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /pytest -q/ }))
  expect(screen.getByText(/line 200/)).toBeInTheDocument()
  expect(screen.getByText(/^140 lines omitted/)).toBeInTheDocument()
  // all of it a click further (the canvas's Command node had it)
  expect(screen.queryByText(/line 100\b/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show all' }))
  expect(screen.getByText(/line 100\b/)).toBeInTheDocument()
  expect(screen.queryByText(/lines omitted/)).not.toBeInTheDocument()
})

test('a server’s row has Stop while it runs (slice 42b), and a CLI’s own command’s, which ends its turn (B-357)', async () => {
  const asked = vi.fn(async () => new Response('{}', { status: 200 }))
  vi.stubGlobal('fetch', asked)
  const serving = command('k1', 'r', { command: 'npm run dev', status: 'running', exit_code: null, keep_running: true })
  const { unmount } = render(<CommandRow command={serving} />)
  await userEvent.click(screen.getByRole('button', { name: 'Stop npm run dev' }))
  expect(asked).toHaveBeenCalledWith('/api/commands/k1/stop', expect.objectContaining({ method: 'POST' }))
  vi.unstubAllGlobals()
  unmount()
  render(<CommandRow command={{ ...serving, id: 'k2', status: 'killed' }} />)
  render(<CommandRow command={command('k3', 'r', { status: 'running', exit_code: null })} />)
  expect(screen.queryByRole('button', { name: /^Stop/ })).not.toBeInTheDocument()
  render(<CommandRow command={command('k4', 'r', { origin: 'cli', status: 'approved', exit_code: null })} />)
  expect(screen.getByRole('button', { name: 'Stop pytest -q' })).toHaveAttribute('title', 'Ends the turn of the CLI that runs it')
})

test('a running command says so when it has printed nothing yet', async () => {
  render(<CommandRow command={command('k', 'r', { status: 'running', exit_code: null, output: '' })} />)
  await userEvent.click(screen.getByRole('button', { name: /pytest -q/ }))
  expect(screen.getByText('(no output yet)')).toBeInTheDocument()
})

test('the approval card names the command, the place and the rule, and sends each decision', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const proposed = command('k', 'r', { status: 'proposed', exit_code: null, command: 'git status --short', suggested_prefix: 'git status' })
  render(<CommandApproval command={proposed} onDecide={onDecide} />)
  expect(screen.getByText('git status --short')).toBeInTheDocument()
  expect(screen.getByText('This machine')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Run once' }))
  await userEvent.click(screen.getByRole('button', { name: 'Always run git status' }))
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide.mock.calls.map(c => c[0])).toEqual(['once', 'always', 'reject'])
})

test('the approval card shows the Docker image and a non-root folder', () => {
  const proposed = command('k', 'r', { status: 'proposed', location: 'docker', image: 'python:3.12', cwd: 'pkg' })
  render(<CommandApproval command={proposed} onDecide={vi.fn()} />)
  expect(screen.getByText('Docker · python:3.12')).toBeInTheDocument()
  expect(screen.getByText('in pkg')).toBeInTheDocument()
})

test('the approval card of a command whose folder is not known names no folder', () => {
  // A CLI ran it with its own shell: where, KOLONİ was not told (cwd is null, not ".").
  const unknown = command('k', 'r', { status: 'proposed', origin: 'cli', cwd: null, command: 'npm test', suggested_prefix: '' })
  const { container, unmount } = render(<CommandApproval command={unknown} onDecide={vi.fn()} />)
  const where = container.querySelector('.cmd-approval-where')
  expect(where).toHaveTextContent(/^This machine\s*run by the CLI itself, with its own shell$/)
  expect(screen.queryByText(/^in\b/)).not.toBeInTheDocument()
  expect(container).not.toHaveTextContent(/\bin (null|undefined|\.)/)
  unmount()
  // the project folder itself is known, and needs no line either
  const { container: root } = render(<CommandApproval command={command('k', 'r', { status: 'proposed' })} onDecide={vi.fn()} />)
  expect(root.querySelector('.cmd-approval-where')).toHaveTextContent(/^This machine\s*stops after 120s$/)
})

test('a command the server offers no rule for cannot be remembered', () => {
  const proposed = command('k', 'r', { status: 'proposed', command: 'pytest && rm -rf build', suggested_prefix: '' })
  render(<CommandApproval command={proposed} onDecide={vi.fn()} />)
  expect(screen.queryByRole('button', { name: /Always run/ })).not.toBeInTheDocument()
  expect(screen.getByText('This command is asked every time.')).toBeInTheDocument()
})

test('a command asked because web is off offers no rule, and says it is asked every time while web is off (K-web-komut)', () => {
  // The server's flag, with no rule offered: never read off the reason's words, which a CLI could write.
  const why = 'web is off on the Tools page (http_request is off); this command reaches the internet: curl - asked at every level'
  const proposed = command('k', 'r', { status: 'proposed', command: 'curl https://example.com', suggested_prefix: '', web_off: true })
  render(<CommandApproval command={proposed} why={why} onDecide={vi.fn()} />)
  expect(screen.getByRole('note')).toHaveTextContent(why)
  expect(screen.queryByRole('button', { name: /Always run/ })).not.toBeInTheDocument()
  expect(screen.getByText('This command is asked every time while web is off.')).toBeInTheDocument()
  // the same words from a CLI, without the flag, change nothing
  cleanup()
  render(<CommandApproval command={{ ...proposed, suggested_prefix: 'curl', web_off: false }} why={why} onDecide={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Always run curl' })).toBeInTheDocument()
})

test('a command that cannot be taken back says what it does', () => {
  const proposed = command('k', 'r', {
    status: 'proposed', command: 'rm -rf build', suggested_prefix: '', danger: 'Deletes files or disks.',
  })
  render(<CommandApproval command={proposed} onDecide={vi.fn()} />)
  expect(screen.getByRole('note')).toHaveTextContent('Deletes files or disks.')
  expect(screen.queryByRole('button', { name: /Always run/ })).not.toBeInTheDocument()
})

test('an ordinary command shows no warning', () => {
  render(<CommandApproval command={command('k', 'r', { status: 'proposed' })} onDecide={vi.fn()} />)
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})

test.each<[Partial<Command>, string, string]>([
  [{ status: 'running', exit_code: null, preview_url: null }, 'starting…', 'accent'],
  [{ status: 'running', exit_code: null, preview_url: 'http://localhost:5173/' }, 'running', 'accent'],
  [{ status: 'killed', exit_code: null }, 'stopped', 'muted'],
  [{ status: 'exited', exit_code: 1 }, 'exited 1', 'del'],
  [{ status: 'interrupted', exit_code: null }, 'stopped when KOLONİ closed', 'muted'],
])('a server (slice 42b): %o reads "%s"', (over, label, tone) => {
  expect(commandStatus(command('k', 'r', { keep_running: true, ...over }))).toEqual({ label, tone })
})

test('the card of a command that keeps running says so, and offers no rule: it is asked every time', () => {
  const server = command('k', 'r', { status: 'proposed', command: 'npm run dev', keep_running: true, suggested_prefix: '' })
  const { container } = render(<CommandApproval command={server} onDecide={vi.fn()} />)
  expect(container.querySelector('.cmd-approval-where')).toHaveTextContent(/^This machine\s*keeps running, serves a page$/)
  expect(screen.queryByRole('button', { name: /Always run/ })).not.toBeInTheDocument()
  expect(screen.getByText('This command is asked every time.')).toBeInTheDocument()
})

test('buttons lock while a decision is sent and a refusal is shown', async () => {
  const onDecide = vi.fn().mockRejectedValue({ detail: 'this command is no longer waiting for a decision' })
  render(<CommandApproval command={command('k', 'r', { status: 'proposed' })} onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('button', { name: 'Run once' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('no longer waiting')
  expect(screen.getByRole('button', { name: 'Run once' })).toBeEnabled()
})

test('the allow list shows the rules and removes one', async () => {
  const onRemove = vi.fn()
  const rules = [
    { id: 'a', conversation_id: 'c', prefix: 'pytest', danger: '', created_at: 't' },
    { id: 'b', conversation_id: 'c', prefix: 'git status', danger: '', created_at: 't' },
  ]
  render(<AllowList rules={rules} onRemove={onRemove} />)
  await userEvent.click(screen.getByRole('button', { name: '2 rules' }))
  expect(screen.getByText('pytest')).toBeInTheDocument()
  expect(screen.queryByText(/covers nothing now/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Remove rule git status' }))
  expect(onRemove).toHaveBeenCalledWith('b')
})

test('a rule kept for a command that deletes says it covers nothing now, and can be removed', async () => {
  const onRemove = vi.fn()
  const rules = [{ id: 'a', conversation_id: 'c', prefix: 'rm', danger: 'Deletes files or disks.', created_at: 't' }]
  render(<AllowList rules={rules} onRemove={onRemove} />)
  await userEvent.click(screen.getByRole('button', { name: '1 rule' }))
  expect(screen.getByText('covers nothing now - it deletes or names a secret')).toHaveAttribute('title', 'Deletes files or disks.')
  await userEvent.click(screen.getByRole('button', { name: 'Remove rule rm' }))
  expect(onRemove).toHaveBeenCalledWith('a')
})

test('with no rules the allow list draws nothing', () => {
  const { container } = render(<AllowList rules={[]} onRemove={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
})

test('a CLI’s own command whose call failed reads as failed, not "exit code not reported"', () => {
  const ended = command('k', 'r', { origin: 'cli', status: 'exited', exit_code: null })
  const { rerender } = render(<CommandRow command={ended} failed />)
  expect(screen.getByText('failed (its CLI said so)')).toBeInTheDocument()
  rerender(<CommandRow command={ended} />)
  expect(screen.getByText('ended · exit code not reported')).toBeInTheDocument()
})
