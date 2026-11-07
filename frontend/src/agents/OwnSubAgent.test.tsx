import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { Inspector } from '../inspector/Inspector'
import { agent, assistantMessage, command, convState, fileChange, openAgentFold, run, toolCall, userMessage } from '../test-fixtures'
import { AgentWindow } from './AgentWindow'

const cli = { origin: 'cli' as const }
// Claude Code working natively: it reads a file itself, then hands a look-around to a
// sub-agent of its own (call 2), which reads, runs a command and changes a file.
function turn(sub: Parameters<typeof toolCall>[3], result: string | null) {
  return convState({
    runs: [run('r', 'running')],
    agents: [agent('r', 'running', { provider_name: 'Claude Code' })],
    messages: [
      userMessage('r', 'fix it'),
      assistantMessage('m1', 'r', 'I will ask a helper.'),
      assistantMessage('m2', 'r', ''),
      assistantMessage('m3', 'r', 'All done.'),
    ],
    toolCalls: [
      toolCall('1', 'r', 'claude__Glob', 'succeeded', '{}', { ...cli, message_id: 'm1' }),
      toolCall('2', 'r', 'claude__Agent', sub, '{"description":"Look around","prompt":"Read hello.py and\\nsay what it prints","subagent_type":"Explore"}', {
        ...cli,
        message_id: 'm1',
        result,
      }),
      toolCall('3', 'r', 'claude__Read', 'succeeded', '{}', { ...cli, message_id: 'm2', parent_call_id: '2' }),
      toolCall('4', 'r', 'run_command', 'succeeded', '{}', { ...cli, message_id: 'm2', parent_call_id: '2' }),
      toolCall('5', 'r', 'edit_file', 'succeeded', '{"path":"hello.py"}', { ...cli, message_id: 'm2', parent_call_id: '2' }),
    ],
    commands: [command('k1', 'r', { ...cli, tool_call_id: '4', command: 'python hello.py' })],
    fileChanges: [fileChange('f1', 'r', { ...cli, tool_call_id: '5', path: 'hello.py' })],
  })
}

test('in the agent’s window its own sub-agent is one block: task, what it did, its last words', async () => {
  const onOpenChange = vi.fn()
  render(
    <AgentWindow state={turn('succeeded', 'It prints **hi**.')} agentId="r" onClose={() => {}} onOpenChange={onOpenChange} onSelectAgent={() => {}} />,
  )
  const block = screen.getByRole('group', { name: 'Own sub-agent: Look around' })
  // finished, it is closed: one line in the agent's flow
  expect(within(block).getByText('done')).toBeInTheDocument()
  expect(screen.queryByText('python hello.py')).not.toBeInTheDocument()
  // and what it did is nowhere else in the window, as if the agent had done it itself
  expect(within(await openAgentFold('Every step as recorded')).getAllByText(/claude__/).map(el => el.textContent)).toEqual(['claude__Glob'])

  await userEvent.click(within(block).getByRole('button', { name: /Look around/ }))
  expect(within(block).getByText(/Read hello\.py and\s+say what it prints/)).toBeInTheDocument()
  expect(within(block).getByText('claude__Read')).toBeInTheDocument()
  expect(within(block).getByText('python hello.py')).toBeInTheDocument()
  expect(within(block).getByText('hi')).toBeInTheDocument() // its last words, as it wrote them
  await userEvent.click(within(block).getByRole('button', { name: 'View diff' }))
  expect(onOpenChange).toHaveBeenCalledWith('f1')
  await userEvent.click(within(block).getByRole('button', { name: /Look around/ }))
  expect(screen.queryByText('python hello.py')).not.toBeInTheDocument()
})

test('a sub-agent still at work is open, and has no last words yet', () => {
  render(<AgentWindow state={turn('running', null)} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const block = screen.getByRole('group', { name: 'Own sub-agent: Look around' })
  expect(within(block).getByText('running')).toBeInTheDocument()
  expect(within(block).getByText('python hello.py')).toBeInTheDocument()
  expect(within(block).queryByText('Its report')).not.toBeInTheDocument()
})

test('a sub-agent its sub-agent opened is a block inside that block, with its own work inside it', () => {
  const state = turn('running', null)
  state.toolCalls.push(
    toolCall('6', 'r', 'claude__Agent', 'running', '{"description":"Dig deeper"}', { ...cli, message_id: 'm2', parent_call_id: '2' }),
    toolCall('7', 'r', 'claude__Grep', 'succeeded', '{}', { ...cli, message_id: 'm2', parent_call_id: '6' }),
  )
  render(<AgentWindow state={state} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  const outer = screen.getByRole('group', { name: 'Own sub-agent: Look around' })
  const inner = within(outer).getByRole('group', { name: 'Own sub-agent: Dig deeper' })
  expect(within(inner).getByText('claude__Grep')).toBeInTheDocument()
  // it is a sub-agent, not one more tool of the outer one, and its tool is nowhere else
  expect(screen.queryByText('claude__Agent')).not.toBeInTheDocument()
  expect(screen.getAllByText('claude__Grep')).toHaveLength(1)
})

test('selected on the canvas, the inspector shows its task, state, what it did and its last words', () => {
  render(<Inspector state={turn('succeeded', 'It prints **hi**.')} selectedId="subagent:2" onClose={() => {}} />)
  const inspector = screen.getByRole('complementary', { name: 'Inspector' })
  expect(within(inspector).getByText('Look around')).toBeInTheDocument()
  expect(within(inspector).getByText(/own sub-agent of Lead/)).toBeInTheDocument()
  expect(within(inspector).getByText(/Read hello\.py and\s+say what it prints/)).toBeInTheDocument()
  expect(within(inspector).getByText('Status').nextElementSibling).toHaveTextContent('done')
  expect(within(inspector).getByText('Kind').nextElementSibling).toHaveTextContent('Explore')
  expect(within(inspector).getByText('claude__Read')).toBeInTheDocument()
  expect(within(inspector).getByText('python hello.py')).toBeInTheDocument()
  expect(within(inspector).getByText('hi')).toBeInTheDocument()
})

test('the two tool nodes list their own calls: KOLONİ’s, and the CLI’s own by where they were made', () => {
  const state = turn('succeeded', 'x')
  state.toolCalls.push(toolCall('6', 'r', 'ask_user', 'succeeded', '{}', { message_id: 'm3' }))
  const names = () => screen.getAllByRole('button').map(b => b.textContent).filter(t => /done/.test(t ?? ''))
  const view = render(<Inspector state={state} selectedId="tools:r" onClose={() => {}} />)
  expect(names()).toEqual(['ask_userdone'])
  view.rerender(<Inspector state={state} selectedId="owntools:r" onClose={() => {}} />)
  expect(screen.getByText('Own tools')).toBeInTheDocument()
  expect(names()).toEqual(['claude__Globown tooldone'])
  view.rerender(<Inspector state={state} selectedId="owntools:2" onClose={() => {}} />)
  expect(names()).toEqual(['claude__Readown tooldone', 'edit_file hello.pyown tooldone'])
})
