import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Merge } from '../api/types'
import { agent, assistantMessage, command, convState, fileChange, question, run, toolCall, userMessage } from '../test-fixtures'
import { QuestionRow } from '../agents/QuestionCard'
import { MessageList, WaitingList } from './MessageList'
import { waitingOf, waitingSummary } from './waiting'

/** K-bekleyenler: everything that waits for you in one list, answered from it; a question no longer asked is grey. */

const READY = 'Ready for you: Web app (Feature): ready. Take the work into the project?'
const merge = (id: string, over: Partial<Merge> = {}): Merge => ({
  id,
  run_id: 'r',
  agent_id: 'lead',
  status: 'pending',
  files: [{ path: 'config/app.yaml', kind: 'changed', state: 'conflict', whole: true, diff: null, additions: null, deletions: null, note: null }],
  kept_in: null,
  check: null,
  commit: null,
  created_at: '2026-10-27T10:00:00Z',
  decided_at: null,
  ...over,
})
const kept = { path: '', kind: 'changed', state: 'refused', whole: true, diff: null, additions: null, deletions: null, note: 'kept' } as Merge['files'][number]
const lead = agent('r', 'running', { id: 'lead', name: 'Lead', depth: 0 })
const coder = agent('r', 'running', { id: 'coder', name: 'Coder', role_name: 'Coder', depth: 1, parent_agent_id: 'lead' })
const state = convState({
  runs: [run('old', 'completed'), run('r', 'waiting_approval')],
  agents: [lead, coder],
  questions: [
    // An earlier turn's never answered: not current, and not this turn's - not listed.
    question('gone', 'old', { status: 'cancelled', question: 'Older?' }),
    question('q', 'r', { agent_id: 'coder', options: ['hello', 'hey'] }),
    question('late', 'r', { agent_id: 'coder', status: 'interrupted', question: 'Which colour?', options: ['red', 'blue'] }),
    question('ready', 'r', { agent_id: 'lead', leave: true, question: READY, options: ['Take in', 'Ask for changes'] }),
  ],
  commands: [command('cmd', 'r', { agent_id: 'coder', command: 'npm test', status: 'proposed', started_at: null })],
  // (What the turn's copy holds: the Ready for you card is a copy to take in.)
  fileChanges: [fileChange('fc', 'r', { agent_id: 'coder', status: 'in_copy' })],
  // B-128: a Take in that met a clash waits on the Lead's card; an earlier copy is kept for Take in.
  merges: [merge('clash'), merge('kept', { run_id: 'old', agent_id: 'coder', status: 'interrupted', kept_in: 'C:/copies/x', files: [{ ...kept, path: 'a.py' }] })],
})
const on = {
  onOpenChange: vi.fn(),
  onDecide: vi.fn(),
  onDecideCommand: vi.fn(async () => {}),
  onDecideWeb: vi.fn(),
  onSelectAgent: vi.fn(),
  onDecideSpawn: vi.fn(),
  onDecideRole: vi.fn(),
  onDecideMerge: vi.fn(async () => {}),
  onCheckMerge: vi.fn(),
  onCommitMerge: vi.fn(),
  onAnswer: vi.fn(async () => {}),
}
const known = { roles: [], providers: [] }

test('the three kinds, in order: questions, decisions, ready - the last turn’s lost question not current', () => {
  expect(waitingOf(state).map(row => [row.kind, row.what, row.key, row.current])).toEqual([
    ['question', 'question', 'q', true],
    ['question', 'question', 'late', false],
    ['decision', 'command', 'cmd', true],
    ['decision', 'merge', 'clash', true],
    ['ready', 'question', 'ready', true],
    ['ready', 'merge', 'kept', true],
  ])
  expect(waitingOf(convState())).toEqual([])
})

test('B-156: a copy that changed nothing is no copy to take in - its Ready for you card still asks, as a decision', () => {
  const empty = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [lead],
    questions: [question('ready', 'r', { agent_id: 'lead', leave: true, question: READY, options: ['Take in', 'Ask for changes'] })],
    merges: [merge('kept', { status: 'interrupted', kept_in: 'C:/copies/x', files: [] })],
  })
  expect(waitingOf(empty).map(row => [row.kind, row.key])).toEqual([['decision', 'ready']])
  expect(waitingSummary(waitingOf(empty))).toBe('1 question')
  // what its copy holds, as the records say: a change in it, or a command that ran there (what it wrote is known at Take in)
  for (const holds of [{ fileChanges: [fileChange('fc', 'r', { status: 'in_copy' })] }, { commands: [command('c', 'r')] }]) {
    expect(waitingSummary(waitingOf({ ...empty, ...holds }))).toBe('1 copy to take in')
  }
})

test('each is answered from the list, at its own card; a question no longer asked is not on it (the panel counts what can be answered)', async () => {
  render(<WaitingList state={state} on={on} onDecidePlan={vi.fn()} known={known} />)
  // (sample A: a question and a yes or no are both what needs your answer)
  const questions = screen.getByRole('region', { name: 'Needs your answer' })
  await userEvent.click(within(questions).getByRole('button', { name: 'hey' }))
  expect(on.onAnswer).toHaveBeenCalledWith('q', 'hey')
  // (once for its question - the one no longer asked is not listed - and once for its command)
  expect(within(questions).getAllByText('Coder asks')).toHaveLength(2)
  expect(screen.queryByText('Which colour?')).toBeNull()

  const decisions = questions
  await userEvent.click(within(decisions).getByRole('button', { name: 'Run once' }))
  expect(on.onDecideCommand).toHaveBeenCalledWith('cmd', 'once')
  // B-128: the clash's card is here, with whose file to take.
  expect(within(decisions).getByRole('radiogroup', { name: /config\/app\.yaml/ })).toBeInTheDocument()

  const ready = screen.getByRole('region', { name: 'Ready to take in' })
  await userEvent.click(within(ready).getByRole('button', { name: 'Take in' }))
  expect(on.onAnswer).toHaveBeenCalledWith('ready', 'Take in')
  expect(within(ready).getByText(/kept in/)).toBeInTheDocument()
  cleanup()

  render(<WaitingList state={convState()} on={on} onDecidePlan={vi.fn()} known={known} />)
  expect(screen.getByText('Nothing waits for you.')).toBeInTheDocument()
})

test('B-128: in the chat, a Take in that met a clash is not answered - its card is under the turn’s last Take in, once', () => {
  // Two Take ins in one turn (one spawn call each): the clash's card is under the later alone.
  const spawned = (id: string) => toolCall(id, 'r', 'spawn_agent', 'succeeded', '{}', { agent_id: 'lead' })
  const ready = (id: string, call: string, text: string, at: string) =>
    question(id, 'r', { agent_id: 'lead', tool_call_id: call, leave: true, question: text, status: 'answered', answer: 'Take in', created_at: at })
  const chat = convState({
    runs: [run('r', 'waiting_approval')],
    messages: [userMessage('r', 'build it'), assistantMessage('m', 'r', '')],
    toolCalls: [spawned('s1'), spawned('s2')],
    agents: [lead, { ...coder, status: 'completed', tool_call_id: 's1' }, { ...coder, id: 'coder2', status: 'completed', tool_call_id: 's2' }],
    questions: [ready('in2', 's2', `${READY} Later.`, '2026-10-27T10:05:00Z'), ready('in1', 's1', READY, '2026-10-27T10:00:00Z')],
    merges: [merge('clash')],
  })
  render(<MessageList state={chat} onRemoveQueued={vi.fn()} onOpenChange={vi.fn()} onDecide={vi.fn()} onDecideCommand={vi.fn()} />)
  const [apply] = screen.getAllByRole('button', { name: 'Take in' })
  expect(screen.getAllByRole('button', { name: 'Take in' })).toHaveLength(1)
  // (Each Take in one line in the chat, K-hazir-satir: the later one is s2's, the second.)
  const lines = screen.getAllByText("Teams' work is ready")
  expect(lines).toHaveLength(2)
  expect(lines[1].compareDocumentPosition(apply) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

test('a question asked again because its files changed waits for nothing; in the chat it says why', () => {
  const again = question('old', 'r', { agent_id: 'lead', leave: true, question: 'Go on?', status: 'superseded', answer: 'Go on' })
  expect(waitingOf(convState({ runs: [run('r', 'waiting_approval')], questions: [again] }))).toEqual([])
  render(<QuestionRow question={again} />)
  expect(screen.getByText('Go on')).toBeInTheDocument()
  expect(screen.getByText('asked again: its files changed since')).toBeInTheDocument()
})

test('slice 69: a trigger an agent proposed waits as a decision with its card, until it is decided', () => {
  const proposal = { id: 'tp', conversation_id: 'c1', run_id: 'r', name: 'Dependencies', kind: 'schedule' as const, config: { every_minutes: 60 }, message: 'Look.', ends: { runs: 10 }, status: 'proposed' as const, trigger_id: null, created_at: 't' }
  const with69 = convState({ runs: [run('r', 'completed')], triggerProposals: [proposal, { ...proposal, id: 'done', status: 'approved' }] })
  expect(waitingOf(with69).map(row => [row.kind, row.what, row.key])).toEqual([['decision', 'trigger', 'tp']])
  render(<WaitingList state={with69} on={on} onDecidePlan={vi.fn()} known={known} />)
  const card = screen.getByRole('region', { name: 'Proposed trigger: Dependencies' })
  expect(within(card).getByRole('button', { name: 'Approve' })).toBeEnabled()
  expect(card).toHaveTextContent('every 60 minutes · ends after 10 runs')
})
