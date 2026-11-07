import { render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { AgentWindow } from '../agents/AgentWindow'
import { MessageList } from '../chat/MessageList'
import { toolSummary } from '../chat/toolSummary'
import { agent, assistantMessage, convState, memoryRecord, openAgentFold, projectMemory, run, toolCall } from '../test-fixtures'

const fact = memoryRecord('f1', {
  tier: 'fact',
  text: 'The greeting is spelled merhaba.',
  source: { path: 'notes.md', start: 3, end: 4 },
  source_state: 'changed', // as it stands now, which is not how it stood when it was given
})
const own = memoryRecord('f2', { tier: 'fact', origin: 'user', text: 'Commits are signed off.' })
const replaced = memoryRecord('f3', { tier: 'fact', text: 'The port is 8000.', status: 'superseded' })
const memory = projectMemory({ core: [fact, own], past: [replaced] })

const FOUND =
  'On record in this project’s memory.\n- "The greeting is spelled merhaba." (noted by the agent "Reviewer" on 2026-10-05; source "notes.md:3-4"; source unchanged since noted)'

const state = convState({
  runs: [run('r', 'completed')],
  agents: [
    agent('r', 'completed', { id: 'lead', facts_given: ['f1', 'f2', 'f3', 'gone'] }),
    agent('r', 'completed', { id: 'kid', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1, facts_given: [] }),
    agent('r', 'completed', { id: 'old', parent_agent_id: 'lead', role_name: 'Planner', depth: 1, facts_given: null }),
  ],
  messages: [{ ...assistantMessage('m1', 'r', 'Looking.'), agent_id: 'kid' }],
  toolCalls: [
    toolCall('1', 'r', 'recall', 'succeeded', '{"query":"how is the greeting spelled"}', { agent_id: 'kid', message_id: 'm1', result: FOUND }),
    toolCall('2', 'r', 'recall', 'succeeded', '{"query":"database"}', { agent_id: 'kid', message_id: 'm1', result: 'nothing on record about that.' }),
    toolCall('3', 'r', 'recall', 'running', '{"query":"port"}', { agent_id: 'kid', message_id: 'm1' }),
  ],
})

/** An agent's window, its steps opened: what it was given and looked up is at their head. */
async function windowOf(agentId: string, withMemory: typeof memory | null = memory) {
  render(<AgentWindow state={state} memory={withMemory} agentId={agentId} onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  await openAgentFold('Every step as recorded')
}

test('an agent’s window lists what it was given from memory, each with its source and how that stands now', async () => {
  await windowOf('lead')
  const given = screen.getByRole('group', { name: 'Given from memory' })
  const items = within(given).getAllByRole('listitem')
  expect(items).toHaveLength(4)
  expect(items[0]).toHaveTextContent('The greeting is spelled merhaba.')
  expect(items[0]).toHaveTextContent('notes.md:3-4')
  // how it stood when it was given is not on record: what is said is about now, and says so
  expect(items[0]).toHaveTextContent('now: source changed since noted: check again')
  expect(items[1]).toHaveTextContent('Commits are signed off.')
  expect(items[1]).toHaveTextContent('written by you, no file behind it')
  expect(items[1]).not.toHaveTextContent('now:') // no file: nothing that could have changed
  // since replaced: still on record, and shown as what it was given
  expect(items[2]).toHaveTextContent('The port is 8000.')
  expect(items[2]).toHaveTextContent('now: no longer in the core')
  // not hidden when the record cannot be found
  expect(items[3]).toHaveTextContent('a fact that is no longer on record')
  // never "then", and never surer than the record
  expect(given).not.toHaveTextContent(/\b(was|fresh|verified|valid|true)\b/i)
})

test('each state of a source is said as it stands now, in the words used everywhere else', async () => {
  const at = (id: string, source_state: 'unchanged' | 'moved') =>
    memoryRecord(id, { tier: 'fact', source: { path: 'a.md', start: 1, end: 2 }, source_state })
  const lead = agent('r', 'completed', { id: 'lead', facts_given: ['u', 'm'] })
  render(
    <AgentWindow
      state={convState({ runs: [run('r', 'completed')], agents: [lead] })}
      memory={projectMemory({ core: [at('u', 'unchanged'), at('m', 'moved')] })}
      agentId="lead"
      onClose={() => {}}
      onOpenChange={() => {}}
      onSelectAgent={() => {}}
    />,
  )
  await openAgentFold('Every step as recorded')
  const [same, moved] = within(screen.getByRole('group', { name: 'Given from memory' })).getAllByRole('listitem')
  expect(same).toHaveTextContent('a.md:1-2 · now: source unchanged since noted')
  expect(moved).toHaveTextContent('a.md:1-2 · now: source moved since noted: check again')
})

test('until the memory has been read, nothing is called gone', async () => {
  await windowOf('lead', null)
  const given = screen.getByRole('group', { name: 'Given from memory' })
  expect(given).toHaveTextContent('4 facts; reading the project’s memory…')
  expect(given).not.toHaveTextContent('no longer on record')
})

test('an agent given nothing has no such section, and its lookups show what it asked and what came back', async () => {
  await windowOf('kid')
  expect(screen.queryByRole('group', { name: 'Given from memory' })).not.toBeInTheDocument()
  const looked = screen.getByRole('group', { name: 'Looked up in memory' })
  const items = within(looked).getAllByRole('listitem')
  expect(items[0]).toHaveTextContent('how is the greeting spelled')
  expect(items[0]).toHaveTextContent('"The greeting is spelled merhaba."')
  expect(items[0]).toHaveTextContent('source "notes.md:3-4"; source unchanged since noted')
  expect(items[1]).toHaveTextContent('database')
  expect(items[1]).toHaveTextContent('nothing on record about that.')
  expect(items[2]).toHaveTextContent('port')
  expect(items[2]).toHaveTextContent('no result yet')
})

test('an agent from before memory, or one that did nothing with it, shows neither section', async () => {
  await windowOf('old')
  expect(screen.queryByRole('group', { name: 'Given from memory' })).not.toBeInTheDocument()
  expect(screen.queryByRole('group', { name: 'Looked up in memory' })).not.toBeInTheDocument()
})

test('its window’s raw steps show the two sections, each agent its own', async () => {
  const shown = (id: string) => <AgentWindow state={state} memory={memory} agentId={id} onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />
  const { rerender } = render(shown('lead'))
  await openAgentFold('Every step as recorded')
  const given = screen.getByRole('group', { name: 'Given from memory' })
  expect(within(given).getAllByRole('listitem')).toHaveLength(4)
  expect(given).toHaveTextContent('a fact that is no longer on record')
  expect(screen.queryByRole('group', { name: 'Looked up in memory' })).not.toBeInTheDocument()
  rerender(shown('kid'))
  await openAgentFold('Every step as recorded')
  expect(screen.queryByRole('group', { name: 'Given from memory' })).not.toBeInTheDocument()
  expect(screen.getByRole('group', { name: 'Looked up in memory' })).toHaveTextContent('how is the greeting spelled')
})

test('what KOLONİ told an agent about a fact it was given reads as KOLONİ’s word, not as the agent’s', async () => {
  const WORDS =
    'Earlier in this turn you were given the note "The greeting is spelled merhaba." from memory. Its source changed since this turn began: do not rely on it without reading the source again.'
  const told = { ...assistantMessage('t1', 'r', WORDS), agent_id: 'kid', role: 'memory' as const }
  const toLead = { ...told, id: 't2', agent_id: 'lead' }
  const withTold = { ...state, messages: [...state.messages, told, toLead] }
  const { unmount } = render(
    <AgentWindow state={withTold} memory={memory} agentId="kid" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />,
  )
  // in its story, as KOLONİ's reminder, and in its raw steps the same
  expect(screen.getByRole('heading', { name: 'KOLONİ reminded it' })).toBeInTheDocument()
  const inStory = screen.getByRole('note', { name: 'Told by KOLONİ about its memory' })
  expect(inStory).toHaveTextContent('Its source changed since this turn began')
  const steps = await openAgentFold('Every step as recorded')
  expect(within(steps).getByRole('note', { name: 'Told by KOLONİ about its memory' })).toHaveTextContent('do not rely on it')
  unmount()
  // in the chat, which is the lead's conversation: the lead's own, not the sub-agent's
  render(
    <MessageList state={withTold} onDecide={vi.fn()} onDecideCommand={vi.fn()} onOpenChange={() => {}} onRemoveQueued={() => {}} />,
  )
  expect(screen.getAllByRole('note', { name: 'Told by KOLONİ about its memory' })).toHaveLength(1)
})

test('the two memory tools read as what they did, in one line', () => {
  expect(toolSummary({ name: 'recall', arguments: '{"query":"the greeting"}' })).toBe('recall "the greeting"')
  expect(toolSummary({ name: 'remember', arguments: '{"text":"x","about":"greeting","file":"notes.md","start_line":3}' })).toBe('remember greeting')
  expect(toolSummary({ name: 'remember', arguments: '{"text":"The port is 8790."}' })).toBe('remember')
})
