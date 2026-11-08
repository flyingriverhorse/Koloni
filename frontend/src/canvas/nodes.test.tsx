import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import type { ReactNode } from 'react'
import { expect, test, vi } from 'vitest'
import { type AgentData, type DiscussionData, type PoData, type RequestData, type RoomData, type RoundData, statusWords } from './deriveGraph'
import { AgentNode, DiscussionNode, PoNode, RequestNode, RoomNode, RoundNode } from './nodes'
import { NodeActions, ToggleGroup } from './toggleGroup'

/** A node as the canvas draws it, outside any canvas: only what the node itself shows. */
function draw(node: ReactNode) {
  render(<ReactFlowProvider>{node}</ReactFlowProvider>)
}
/** What the canvas hands a node, as far as a node reads it. */
const props = <T,>(id: string, data: T) =>
  ({ id, data, selected: false }) as unknown as NodeProps<Node<T & Record<string, unknown>>>

/** The lines a node shows: its head, and each line under it. */
const lines = () => Array.from(document.querySelectorAll('.node-head, .node-body > *'), line => line.textContent)

test('what started a turn says who: you, or a trigger by its name with nobody watching', () => {
  const asked: RequestData = { text: 'Look the project over', time: '2026-10-05T10:00:00Z', queued: false, trigger: null }
  draw(<RequestNode {...props('request:a', asked)} />)
  expect(screen.getByText('You')).toBeInTheDocument()
  expect(screen.queryByText(/nobody watching/)).not.toBeInTheDocument()
  draw(<RequestNode {...props('request:n', { ...asked, trigger: 'Nightly look' })} />)
  expect(screen.getByText('Trigger')).toBeInTheDocument()
  expect(screen.getByText('Nightly look · nobody watching')).toBeInTheDocument()
})

const coder: AgentData = {
  role: 'Coder', name: 'Coder 3', parentId: 'lead', provider: 'Codex', modelId: 'gpt-6.1', modelFrom: null, status: 'completed', activity: 'Completed', since: null,
  sign: null, signStopped: false, findings: null, inside: 0, summary: '3 tools · 2 commands · 1 file', attention: false, finished: true, open: true,
}

test('the user’s (5 Nov): an agent’s node is three lines - name and model, its state in plain words, what it did counted', () => {
  draw(<AgentNode {...props('agent:kid', coder)} />)
  expect(lines()).toEqual(['Coder 3 · Codex · gpt-6.1', 'Done ✓', '3 tools · 2 commands · 1 file'])
  // the model muted beside the name; both in full under the pointer
  expect(screen.getByText('· Codex · gpt-6.1')).toHaveClass('node-where')
  expect(screen.getByTitle('Coder 3 · Codex · gpt-6.1')).toBeInTheDocument()
  // its state's colour, by the label a state has everywhere
  expect(screen.getByText('Done ✓')).toHaveClass('status')
  expect(screen.getByText('Done ✓').style.color).toBe('var(--ok)')
  // nothing counted: no third line; no sub-cards, no tokens, no tier, no Raw on the node
  cleanup()
  draw(<AgentNode {...props('agent:kid', { ...coder, summary: '', provider: null, modelId: null })} />)
  expect(lines()).toEqual(['Coder 3 · model unknown', 'Done ✓'])
  expect(screen.queryByRole('button')).toBeNull()
  expect(document.body).not.toHaveTextContent(/tokens|balanced|Raw/)
  // what it spent, where its provider counts so, ends the counts
  cleanup()
  draw(<AgentNode {...props('agent:kid', { ...coder, spent: '0.45 AI credits' })} />)
  expect(lines()[2]).toBe('3 tools · 2 commands · 1 file · 0.45 AI credits')
  // asked for Copilot's auto: the model it picked, as that
  cleanup()
  draw(<AgentNode {...props('agent:kid', { ...coder, provider: 'Copilot', modelId: 'gpt-6-luna', modelFrom: 'auto' })} />)
  expect(lines()[0]).toBe('Coder 3 · Copilot · auto → gpt-6-luna')
})

test('its state in plain words: working at what, waiting for your OK (lit), done with what it found, failed with why, stopped', () => {
  const said = (status: AgentData['status'], activity: string, findings: AgentData['findings'] = null) => statusWords({ status, activity, findings })
  expect(said('running', 'editing a.py')).toBe('Working · editing a.py')
  expect(said('running', 'Thinking…')).toBe('Working · thinking…')
  expect(said('waiting_approval', 'Waits for your approval')).toBe('Waits for your OK')
  expect(said('waiting_approval', 'Waits for your answer')).toBe('Waits for your answer')
  expect(said('completed', 'Completed')).toBe('Done ✓')
  expect(said('completed', 'Completed', { line: '2 findings → Coder', detail: '' })).toBe('Done · 2 findings → Coder')
  expect(said('completed', 'Completed', { line: 'no findings', detail: '' })).toBe('Done ✓')
  expect(said('failed', 'Codex: quota reached')).toBe('Failed: Codex: quota reached')
  expect(said('failed', 'Stopped at its step limit')).toBe('Stopped at its step limit')
  expect(said('cancelled', 'Stopped')).toBe('Stopped')
  expect(said('waiting', 'Waiting for Coder')).toBe('Waiting for Coder')
  draw(<AgentNode {...props('agent:kid', { ...coder, status: 'waiting_approval', activity: 'Waits for your approval', attention: true, finished: false })} />)
  expect(document.querySelector('.node')).toHaveClass('node-approval')
  expect(screen.getByText('Waits for your OK')).toBeInTheDocument()
})

test('an agent at work says on one line what it does now, with a blinking dot and for how long; done, neither (slice 84d)', () => {
  vi.useFakeTimers({ now: Date.parse('2026-10-05T10:00:15Z') })
  try {
    const at = { ...coder, status: 'running' as const, finished: false, activity: 'pytest tests/test_mail.py', since: '2026-10-05T10:00:03Z' }
    draw(<AgentNode {...props('agent:kid', at)} />)
    const line = screen.getByTitle('Working · pytest tests/test_mail.py')
    expect(line).toHaveClass('node-now')
    // the time first, so that a long command is what gets cut off
    expect(line).toHaveTextContent(/^12s · Working · pytest tests\/test_mail\.py$/)
    act(() => void vi.advanceTimersByTime(50_000))
    expect(line).toHaveTextContent(/^1m 02s · Working/)
    cleanup()
    draw(<AgentNode {...props('agent:kid', coder)} />)
    expect(screen.getByTitle('Done ✓')).not.toHaveClass('node-now')
  } finally {
    vi.useRealTimers()
  }
})

test('a discussion and a room are three lines too: what about, then who speaks or takes part - or that it waits for you', () => {
  const data: DiscussionData = { topic: 'Keep hi?', line: 'Ended: agreed', members: ['Lead', 'Web app lead', 'Docs lead'], last: [{ who: 'Lead', text: 'yes' }], speaking: null, running: false }
  draw(<DiscussionNode {...props('discussion:t', data)} />)
  expect(lines()).toEqual(['DiscussionEnded: agreed', 'Keep hi?', 'Lead · Web app lead · Docs lead'])
  cleanup()
  draw(<DiscussionNode {...props('discussion:t', { ...data, speaking: 'Docs lead' })} />)
  expect(lines()[2]).toBe('Docs lead is speaking…')
  cleanup()
  const room: RoomData = { goal: 'Ship it', line: 'round 2', members: ['Coder', 'Tester'], watched: 'Lead watches', items: '1 of 3 items done', last: [], running: true, attention: false }
  draw(<RoomNode {...props('room:r', room)} />)
  expect(lines()).toEqual(['Roomround 2', 'Ship it', '1 of 3 items done'])
  cleanup()
  draw(<RoomNode {...props('room:r', { ...room, attention: true })} />)
  expect(lines()[2]).toBe('Waits for you')
})

test('the user’s (4 Nov): a finished agent of a step’s newest round is a chip - a button named by it and how it ended -, an earlier round a line that opens and folds', async () => {
  draw(<AgentNode {...props('agent:rev2', { ...coder, name: 'Reviewer 2', chip: { said: '1 blocking', colour: 'var(--warn)' } })} />)
  const chip = screen.getByRole('button', { name: 'Reviewer 2: 1 blocking' })
  expect(chip).toHaveTextContent(/^Reviewer 21 blocking$/)
  expect(screen.getByText('1 blocking').style.color).toBe('var(--warn)')
  // (Nothing of its card: its model, its tokens.)
  expect(screen.queryByText('Local · qwen')).toBeNull()
  cleanup()
  const toggle = vi.fn()
  const round: RoundData = { said: 'Round 2 · 4 reviewed', result: '2 blocking', colour: 'var(--warn)', inside: 4, summary: '', attention: false, finished: true, open: false }
  render(
    <ReactFlowProvider>
      <ToggleGroup.Provider value={toggle}>
        <RoundNode {...props('round:x', round)} />
      </ToggleGroup.Provider>
    </ReactFlowProvider>,
  )
  const line = screen.getByRole('button', { name: 'Round 2 · 4 reviewed · 2 blocking' })
  expect(line).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(line)
  expect(toggle).toHaveBeenCalledWith('round:x')
  cleanup()
  // Something in it waits for the user: said, in the warn colour, and in its name.
  render(
    <ReactFlowProvider>
      <RoundNode {...props('round:x', { ...round, attention: true, open: true })} />
    </ReactFlowProvider>,
  )
  expect(screen.getByRole('button', { name: 'Round 2 · 4 reviewed · waits for you · 2 blocking' })).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByText('waits for you · 2 blocking').style.color).toBe('var(--warn)')
})

test('the user’s (7 Nov): the Assistant PO’s node says the model, what came of it and what it spent, and opens the To-do page', async () => {
  const po: PoData = { provider_name: 'Fast', model_id: 'gpt-6-luna', heard: true, input_tokens: 2900, output_tokens: 200, proposed: 2, dropped: [], dropped_more: 0 }
  const openTodo = vi.fn()
  render(
    <ReactFlowProvider>
      <NodeActions.Provider value={{ openTodo }}>
        <PoNode {...props('po:r', po)} />
      </NodeActions.Provider>
    </ReactFlowProvider>,
  )
  expect(lines()).toEqual(['Assistant POgpt-6-luna', '2 proposed', '3k tokens To-do →'])
  await userEvent.click(screen.getByRole('button', { name: 'To-do →' }))
  expect(openTodo).toHaveBeenCalledOnce()
  cleanup()
  // with ones dropped; sent and not heard out, nothing said of what it spent - not 0
  draw(<PoNode {...props('po:r', { ...po, dropped: [{ title: 'Docs', why: 'like the open task' }] })} />)
  expect(lines()[1]).toBe('2 proposed · 1 dropped')
  cleanup()
  draw(<PoNode {...props('po:r', { ...po, heard: false, model_id: null, input_tokens: null, output_tokens: null, proposed: 0 })} />)
  expect(lines()).toEqual(['Assistant POmodel not known', 'Sent, not heard out', '– tokens To-do →'])
  expect(screen.getByText('Sent, not heard out').style.color).toBe('var(--warn)')
})
