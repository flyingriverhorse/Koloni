import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { BacklogTask, Provider } from '../api/types'
import { deriveGraph } from '../canvas/deriveGraph'
import { useApp } from '../state/store'
import { agent, conversation, convState, question, run } from '../test-fixtures'
import { WaitingList } from './MessageList'
import { decidedOf, waitingOf } from './waiting'

/** K-vekil-karar: "When you're away" in the chat's settings, and "Decided for you" in Ready for you. */

const lead = agent('r', 'running', { id: 'lead', name: 'Lead', depth: 0 })
const writer = agent('r', 'running', { id: 'spec', name: 'Spec writer', role_name: 'Spec writer', depth: 1, parent_agent_id: 'lead' })
const tester = agent('r', 'completed', { id: 'tester', name: 'Tester', role_name: 'Tester', depth: 1, parent_agent_id: 'lead' })
const decided = (id: string, over: Parameters<typeof question>[2]) =>
  question(id, 'r', { status: 'answered', answered_at: '2026-10-27T02:10:00Z', lead_why: 'The spec says newest first; by date matches it.', ...over })
const state = convState({
  runs: [run('r', 'running')],
  agents: [lead, writer, tester],
  questions: [
    decided('sort', { agent_id: 'spec', question: 'sort the list by date or by name?', options: ['by date', 'by name'], answer: 'by date' }),
    decided('ask', { agent_id: 'lead', leave: true, question: 'Ask me · Write the spec: Go on or Ask for changes?', options: ['Go on', 'Ask for changes', 'Stop'], answer: 'Go on', answered_at: '2026-10-27T02:40:00Z' }),
    decided('slow', { agent_id: 'tester', question: 'run the slow tests too?', options: ['Yes', 'No'], answer: 'No' }),
    decided('seen', { agent_id: 'spec', seen_at: '2026-10-27T08:00:00Z' }),
  ],
})
const known = { roles: [], providers: [] }
const on = {
  onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn(async () => {}), onDecideWeb: vi.fn(), onSelectAgent: vi.fn(),
  onDecideSpawn: vi.fn(), onDecideRole: vi.fn(), onDecideMerge: vi.fn(async () => {}), onCheckMerge: vi.fn(), onCommitMerge: vi.fn(),
  onAnswer: vi.fn(async () => {}),
}

afterEach(() => vi.restoreAllMocks())

test('what the Lead decided and you did not say OK to is to look at, not waiting', () => {
  expect(decidedOf(state).map(q => q.id)).toEqual(['sort', 'ask', 'slow'])
  // (answered only: one cut short, or asked again since - a Go on superseded - is no decision)
  const cut = convState({ ...state, questions: ['pending', 'interrupted', 'superseded'].map(status => decided(status, { status: status as 'pending' })) })
  expect(decidedOf(cut)).toEqual([])
  expect(waitingOf(state)).toEqual([])
})

test('Decided for you: what was asked, what the Lead chose and why, with its count and times', () => {
  render(<WaitingList state={state} on={on} onDecidePlan={vi.fn()} known={known} />)
  const section = screen.getByRole('region', { name: /Decided for you while you were away/ })
  expect(within(section).getByText(/^3 · /)).toBeInTheDocument()
  expect(within(section).getByText('Spec writer asked: sort the list by date or by name?')).toBeInTheDocument()
  expect(within(section).getAllByText('by date')[0].closest('div')).toHaveTextContent('Orchestrator chose by date')
  expect(within(section).getAllByText('“The spec says newest first; by date matches it.”')).toHaveLength(3)
  expect(screen.queryByText('Nothing waits for you.')).toBeNull()
})

test('OK takes it off; Change sends your choice while the agent is at work; else it cannot be undone', async () => {
  const ok = vi.spyOn(useApp.getState(), 'decidedOk').mockResolvedValue()
  const change = vi.spyOn(useApp.getState(), 'decidedChange').mockResolvedValue()
  render(<WaitingList state={state} on={on} onDecidePlan={vi.fn()} known={known} />)
  const [sort, ask, slow] = screen.getAllByRole('button', { name: 'OK' }).map(button => button.closest('.decided-item') as HTMLElement)
  // the Spec writer is at work: Change → the other option
  await userEvent.click(within(sort).getByRole('button', { name: 'Change → by name' }))
  expect(change).toHaveBeenCalledWith('sort', 'by name')
  // a card of KOLONİ's went on at once; the Tester has finished
  expect(within(ask).queryByRole('button', { name: /Change/ })).toBeNull()
  expect(within(ask).getByText("can't be undone: the next step ran")).toBeInTheDocument()
  expect(within(slow).queryByRole('button', { name: /Change/ })).toBeNull()
  expect(within(slow).getByText("can't be undone: Tester has finished")).toBeInTheDocument()
  await userEvent.click(within(slow).getByRole('button', { name: 'OK' }))
  expect(ok).toHaveBeenCalledWith('slow')
})

test('Change is offered where a CLI at work hears it, and sent while it works; not into Copilot’s or agy’s own (89d, B-164)', async () => {
  const providers = [
    { name: 'Claude', kind: 'claude_cli' },
    { name: 'Copilot', kind: 'copilot_cli' },
    { name: 'agy', kind: 'agy_cli' },
  ] as Provider[]
  useApp.setState({ providers })
  const change = vi.spyOn(useApp.getState(), 'decidedChange').mockResolvedValue()
  const cli = (provider_name: string, provider_mode: string, status: 'running' | 'completed' = 'running') => {
    const coder = agent('r', status, { id: 'coder', name: 'Coder', role_name: 'Coder', depth: 1, parent_agent_id: 'lead', provider_name, provider_mode })
    return convState({ ...state, agents: [lead, coder], questions: [decided('colour', { agent_id: 'coder', question: 'red or blue?', options: ['red', 'blue'], answer: 'red' })] })
  }
  const at = (provider_name: string, provider_mode: string) => render(<WaitingList state={cli(provider_name, provider_mode)} on={on} onDecidePlan={vi.fn()} known={known} />)
  for (const [name, mode] of [['Copilot', 'native'], ['agy', 'reads'], ['agy', 'native']]) {
    const { unmount } = at(name, mode)
    expect(screen.queryByRole('button', { name: /Change/ })).toBeNull()
    expect(screen.getByText("can't be undone: Coder works on in its CLI, which hears nothing more")).toBeInTheDocument()
    unmount()
  }
  for (const [name, mode] of [['Copilot', 'session'], ['Claude', 'native']]) {
    const { rerender, unmount } = at(name, mode)
    await userEvent.click(screen.getByRole('button', { name: 'Change → blue' }))
    expect(change).toHaveBeenLastCalledWith('colour', 'blue')
    expect(screen.getByRole('status')).toHaveTextContent('Sent to Coder while it works')
    // B-183: still said once that was the last one decided - Change takes it off the list
    const taken = cli(name, mode)
    rerender(<WaitingList state={{ ...taken, questions: taken.questions.map(q => ({ ...q, seen_at: '2026-10-27T08:00:00Z' })) }} on={on} onDecidePlan={vi.fn()} known={known} />)
    expect(screen.getByRole('status')).toHaveTextContent('Sent to Coder while it works')
    // (said only while it works: N3)
    rerender(<WaitingList state={cli(name, mode, 'completed')} on={on} onDecidePlan={vi.fn()} known={known} />)
    expect(screen.queryByRole('status')).toBeNull()
    unmount()
  }
  useApp.setState({ providers: [] })
})

test('with nothing decided and nothing waiting, nothing waits', () => {
  render(<WaitingList state={convState({ runs: [run('r', 'running')] })} on={on} onDecidePlan={vi.fn()} known={known} />)
  expect(screen.getByText('Nothing waits for you.')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: /Decided for you/ })).toBeNull()
})

test('the canvas’s Ready for you says what was decided for you apart from what waits', () => {
  const row = { team_id: 'web', recipe_id: null, no_recipe: false, picked_by: 'user' as const, why: null,
    state: { run_id: 'r', team: 'Web app', recipe: 'Feature', status: 'running' as const, why: null, steps: [], agents: ['spec'], ended_ready: false, passes: [] } }
  const teamed = convState({ ...state, conversation: { ...conversation, teams_mode: 'manual', teams: [row] } })
  const ready = deriveGraph(teamed).nodes.find(node => node.id === 'ready:r')
  // (to look at, beside what waits - not counted as waiting)
  expect(ready?.data).toMatchObject({ waiting: { count: 0, summary: '', mine: 0, decided: 3 } })
})

test('a night past midnight reads from its first time to its last', () => {
  const at = (day: number, hour: number, minute: number) => new Date(2026, 9, day, hour, minute).toISOString()
  const night = convState({
    runs: [run('r', 'running')],
    agents: [lead, writer],
    questions: [
      decided('late', { agent_id: 'spec', options: ['a', 'b'], answer: 'a', answered_at: at(27, 2, 40) }),
      decided('early', { agent_id: 'spec', options: ['a', 'b'], answer: 'b', answered_at: at(26, 23, 30) }),
    ],
  })
  render(<WaitingList state={night} on={on} onDecidePlan={vi.fn()} known={known} />)
  expect(screen.getByText('2 · 23:30–02:40')).toBeInTheDocument()
})

test('a follow-up task the Orchestrator decided at Full auto: OK keeps its word, Change undoes it', async () => {
  const po = (lead: 'add' | 'no') => ({ chat: state.conversation.id, why: 'the parser tests', lead, lead_why: `It said ${lead}.`, seen: false, injection: [] })
  const task = (id: string, status: 'todo' | 'proposed' | 'doing', lead: 'add' | 'no'): BacklogTask => ({
    id, title: id, detail: null, criteria: null, priority: 'normal', status, position: 0, conversation_id: null, created_by: 'agent',
    pending: null, assessment: null, not_in: false, after: [], queued: false, stuck: null, waiting: false, po: po(lead),
  })
  useApp.setState({ backlog: [task('tests', 'todo', 'add'), task('help', 'proposed', 'no'), task('docs', 'doing', 'add'), { ...task('other', 'todo', 'add'), po: { ...po('add'), chat: 'elsewhere' } }] })
  const seen = vi.spyOn(useApp.getState(), 'seenTask').mockResolvedValue()
  const decide = vi.spyOn(useApp.getState(), 'decideTask').mockResolvedValue()
  render(<WaitingList state={convState({ runs: [run('r', 'running')], agents: [lead] })} on={on} onDecidePlan={vi.fn()} known={known} />)
  const section = screen.getByRole('region', { name: /Decided for you/ })
  expect(within(section).getByText('3')).toBeInTheDocument() // (this chat's only; no times)
  const [tests, help, docs] = within(section).getAllByRole('button', { name: 'OK' }).map(button => button.closest('.decided-item') as HTMLElement)
  expect(tests).toHaveTextContent('The Assistant PO proposed a To-do task: tests')
  expect(tests).toHaveTextContent('Orchestrator chose Add')
  expect(tests).toHaveTextContent('“It said add.”')
  await userEvent.click(within(tests).getByRole('button', { name: 'OK' }))
  expect(seen).toHaveBeenCalledWith('tests')
  await userEvent.click(within(tests).getByRole('button', { name: 'Change → Reject' }))
  expect(decide).toHaveBeenLastCalledWith('tests', 'reject') // (its title remembered, not proposed again)
  // one said no to: OK lets it go, Change adds it
  await userEvent.click(within(help).getByRole('button', { name: 'OK' }))
  expect(decide).toHaveBeenLastCalledWith('help', 'reject')
  await userEvent.click(within(help).getByRole('button', { name: 'Change → Add' }))
  expect(decide).toHaveBeenLastCalledWith('help', 'approve')
  // started since: no taking it off from here
  expect(within(docs).queryByRole('button', { name: /Change/ })).toBeNull()
  expect(within(docs).getByText("can't be undone: it has started")).toBeInTheDocument()
  useApp.setState({ backlog: null })
})
