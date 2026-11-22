import { readFileSync } from 'node:fs'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Away, AwayJob, BacklogTask } from '../api/types'
import { useApp } from '../state/store'
import { conversation, convState, run } from '../test-fixtures'
import { ComposerStatus } from './ComposerStatus'

const at = { compact: false, running: false, onStop: vi.fn() }
const chat = convState({ runs: [run('r', 'completed')] })

const task = (id: string, over: Partial<BacklogTask> = {}): BacklogTask => ({
  id, title: `Task ${id}`, detail: null, criteria: null, priority: 'normal', status: 'proposed', position: 0, conversation_id: null, created_by: 'agent',
  pending: null, assessment: null, not_in: false, after: [], queued: false, stuck: null, waiting: false, created_at: '2026-11-16T10:00:00Z',
  proposed_in: 'c', ...over,
})

const job = (title: string, state: AwayJob['state']): AwayJob => ({
  title, line: null, team: null, recipe: null, task_id: title, conversation_id: null, state, why: null, assessment: null,
  kept: [], files: [], taken: [], shared: [], kept_out: [], asks: [], checks: [], now: null, spent: null,
})

const away = (jobs: AwayJob[], over: Partial<Away> = {}): Away => ({
  id: 'a1', project_id: 'p', conversation_id: 'c', run_id: 'r', status: 'running', jobs, kept_out: [], until: null, money: null,
  started_at: '2026-11-21T21:10:00Z', ended_at: null, why: null, seen_at: null, tried: [], slipped: [], job_minutes: 60, on_plan: null,
  spent: null, currency: 'USD', at_least: false, counts: {}, proposed: [], decided: [], ...over,
})

afterEach(() => useApp.setState({ away: null, backlog: null }))

test('☾ Away opens its panel: the new tasks from this chat ticked, the older one not; Move up reorders; Go away sends them in order', async () => {
  const goAway = vi.fn(async () => {})
  useApp.setState({ goAway, backlog: [task('t1'), task('t2'), task('old', { status: 'todo', proposed_in: null, title: 'README links' }), task('done', { status: 'done' })] })
  render(<ComposerStatus {...at} conv={chat} />)
  const chip = screen.getByRole('button', { name: 'Away' })
  expect(chip).toHaveAttribute('aria-haspopup', 'dialog')
  expect(chip).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(chip)
  const panel = screen.getByRole('dialog', { name: 'Away' })
  const rows = () => within(panel).getAllByRole('checkbox').map(box => [box.closest('label')!.textContent!.trim(), (box as HTMLInputElement).checked])
  expect(rows()).toEqual([['Task t1', true], ['Task t2', true], ['README links', false]])
  expect(within(panel).getByText(/^on To-do since \w+/)).toBeInTheDocument()
  expect(within(panel).getAllByText('new · from this chat')).toHaveLength(2)
  expect(within(panel).getByText('Decides for you')).toBeInTheDocument()
  expect(within(panel).getByText('Always waits for you')).toBeInTheDocument()
  await userEvent.click(within(panel).getByRole('button', { name: 'Move Task t2 up' }))
  expect(rows().map(([title]) => title)).toEqual(['Task t2', 'Task t1', 'README links'])
  await userEvent.click(within(panel).getByRole('button', { name: 'Go away' }))
  expect(goAway).toHaveBeenCalledWith('c', { task_ids: ['t2', 't1'], order: ['t2', 't1', 'old'], until: null, money: null, kept_out: [] })
})

test('in a narrow chat a task’s name takes the row’s free width; its tag and buttons go under it (340 px: one word a line)', async () => {
  const style = document.createElement('style')
  style.textContent = readFileSync('src/theme/memory.css', 'utf8') // (run from frontend/)
  document.head.append(style)
  useApp.setState({ backlog: [task('t1', { title: 'Add a bye line, 106' })] })
  render(<ComposerStatus {...at} conv={chat} />)
  await userEvent.click(screen.getByRole('button', { name: 'Away' }))
  const name = screen.getByRole('checkbox', { name: 'Add a bye line, 106' }).closest('label')!
  expect(name).toHaveClass('away-task-name')
  expect([getComputedStyle(name).flexGrow, getComputedStyle(name).minWidth]).toEqual(['1', '0px'])
  expect(getComputedStyle(name.closest('li')!).flexWrap).toBe('wrap')
  style.remove()
})

test('with nothing open on To-do the panel has no task section; Esc closes it, the focus back on the chip', async () => {
  useApp.setState({ backlog: [task('done', { status: 'done' })] })
  render(<ComposerStatus {...at} conv={chat} />)
  await userEvent.click(screen.getByRole('button', { name: 'Away' }))
  expect(screen.queryByRole('region', { name: 'Then from To-do' })).toBeNull()
  expect(screen.queryAllByRole('checkbox')).toEqual([])
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('button', { name: 'Away' })).toHaveFocus()
})

test('while away the line says where To-do stands, and the chip is I’m back', async () => {
  const comeBack = vi.fn(async () => {})
  useApp.setState({ comeBack, away: away([job('Add a bye line', 'working'), job('Say hello', 'next')], { decided: ['a', 'b', 'c'], counts: { waits: 1 } }) })
  const { container, rerender } = render(<ComposerStatus {...at} conv={chat} />)
  const line = () => container.querySelector('.composer-status')
  expect(line()).toHaveTextContent(/^Away · To-do 1 of 2: Add a bye line · 3 decided for you · 1 waits/)
  expect(line()).toHaveClass('composer-status-away')
  await userEvent.click(screen.getByRole('button', { name: 'I’m back' }))
  expect(comeBack).toHaveBeenCalledWith('a1')
  useApp.setState({ away: away([job('one', 'done'), job('two', 'waits')]) })
  rerender(<ComposerStatus {...at} conv={chat} />)
  expect(line()).toHaveTextContent(/^Away · To-do 2 of 2 looked at/)
  useApp.setState({ away: away([]) })
  rerender(<ComposerStatus {...at} conv={chat} />)
  expect(line()).toHaveTextContent(/^Away · nothing on To-do/)
})

test('no chip in a plain chat; in a chat with no turn yet it waits, saying why', () => {
  const { rerender } = render(<ComposerStatus {...at} conv={convState({ conversation: { ...conversation, project_id: null } })} />)
  expect(screen.queryByRole('button', { name: 'Away' })).toBeNull()
  rerender(<ComposerStatus {...at} conv={convState()} />)
  const chip = screen.getByRole('button', { name: 'Away' })
  expect(chip).toBeDisabled()
  expect(chip).toHaveAttribute('title', 'Write to the Orchestrator first: Away finishes this chat’s turn')
})

test('the panel says the level the tasks run at: the lower of this chat’s and the To-do page’s', async () => {
  useApp.setState({ backlog: [], backlogAuto: { permission_mode: 'ask' } as never })
  render(<ComposerStatus {...at} conv={{ ...chat, conversation: { ...conversation, permission_mode: 'full_auto' } }} />)
  await userEvent.click(screen.getByRole('button', { name: 'Away' }))
  expect(screen.getByRole('dialog', { name: 'Away' })).toHaveTextContent('The tasks run at Ask before changes - the lower of this chat’s level and the To-do page’s.')
  useApp.setState({ backlogAuto: null })
})

test('while the project is not on Test and review the panel suggests it; Use Test and review saves it; on it, nothing', async () => {
  // (This chat's project - not the one open in the app: N8.)
  const save = vi.spyOn(api, 'patch').mockResolvedValue({ id: conversation.project_id, after_change: 'check' } as never)
  useApp.setState({ backlog: [], projectId: 'another', projects: [{ id: conversation.project_id, after_change: 'tests' } as never] })
  const { unmount } = render(<ComposerStatus {...at} conv={chat} />)
  await userEvent.click(screen.getByRole('button', { name: 'Away' }))
  const panel = screen.getByRole('dialog', { name: 'Away' })
  expect(panel).toHaveTextContent('While you’re away, Test and review is suggested: tests, and a review of big or security-touching changes.')
  await userEvent.click(within(panel).getByRole('button', { name: 'Use Test and review' }))
  expect(save).toHaveBeenCalledWith(`/projects/${conversation.project_id}`, { after_change: 'check' })
  save.mockRestore()
  unmount()
  useApp.setState({ projects: [{ id: conversation.project_id, after_change: 'check' } as never] })
  render(<ComposerStatus {...at} conv={chat} />)
  await userEvent.click(screen.getByRole('button', { name: 'Away' }))
  expect(screen.queryByRole('button', { name: 'Use Test and review' })).toBeNull()
  useApp.setState({ projects: [] })
})
