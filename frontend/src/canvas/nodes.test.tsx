import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import type { ReactNode } from 'react'
import { expect, test, vi } from 'vitest'
import {
  type AgentData,
  type DiscussionData,
  type PoData,
  type RequestData,
  type RoundData,
  statusWords,
} from './deriveGraph'
import { AgentNode, AttachmentNode, DiscussionNode, PlanNode, PoNode, RequestNode, RoundNode } from './nodes'
import { useApp } from '../state/store'
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
  const asked: RequestData = {
    text: 'Look the project over',
    time: '2026-10-05T10:00:00Z',
    queued: false,
    trigger: null,
  }
  draw(<RequestNode {...props('request:a', asked)} />)
  expect(screen.getByText('You')).toBeInTheDocument()
  expect(screen.queryByText(/nobody watching/)).not.toBeInTheDocument()
  draw(<RequestNode {...props('request:n', { ...asked, trigger: 'Nightly look' })} />)
  expect(screen.getByText('Trigger')).toBeInTheDocument()
  expect(screen.getByText('Nightly look · nobody watching')).toBeInTheDocument()
})

const coder: AgentData = {
  role: 'Coder',
  name: 'Coder 3',
  parentId: 'lead',
  provider: 'Codex',
  modelId: 'gpt-6.1',
  modelFrom: null,
  status: 'completed',
  activity: 'Completed',
  since: null,
  wrote: null,
  kind: null,
  sign: null,
  signStopped: false,
  findings: null,
  inside: 0,
  summary: '3 tools · 2 commands · 1 file',
  attention: false,
  finished: true,
  open: true,
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
  // (Its one button: its window's.)
  expect(screen.getAllByRole('button').map(button => button.getAttribute('aria-label'))).toEqual([
    "Open Coder 3's window",
  ])
  expect(document.body).not.toHaveTextContent(/tokens|balanced|Raw/)
  // what it spent, where its provider counts so, ends the counts
  cleanup()
  draw(<AgentNode {...props('agent:kid', { ...coder, spent: '0.45 AI credits' })} />)
  expect(lines()[2]).toBe('3 tools · 2 commands · 1 file · 0.45 AI credits')
  // asked for Copilot's auto: the model it picked, as that
  cleanup()
  draw(
    <AgentNode {...props('agent:kid', { ...coder, provider: 'Copilot', modelId: 'gpt-6-luna', modelFrom: 'auto' })} />,
  )
  expect(lines()[0]).toBe('Coder 3 · Copilot · auto → gpt-6-luna')
})

test('the user’s (21 Nov): an agent’s node opens its window from an icon at its head’s right - one action, by pointer or keyboard', async () => {
  useApp.setState({ agentWindowId: null })
  const picked = vi.fn()
  render(
    <ReactFlowProvider>
      {/* (As the canvas's own handlers would: picking the node, or its double click, is not done too.) */}
      <div onClick={picked} onDoubleClick={picked} onKeyDown={picked}>
        <AgentNode {...props('agent:kid', coder)} />
      </div>
    </ReactFlowProvider>,
  )
  const open = screen.getByRole('button', { name: "Open Coder 3's window" })
  expect(open).toHaveAttribute('title', "Open Coder 3's window")
  expect(open.closest('.node-head')?.lastElementChild).toBe(open)
  expect(open).toHaveClass('nodrag')
  await userEvent.click(open)
  expect(useApp.getState().agentWindowId).toBe('kid')
  useApp.setState({ agentWindowId: null })
  open.focus()
  await userEvent.keyboard('{Enter}')
  expect(useApp.getState().agentWindowId).toBe('kid')
  expect(picked).not.toHaveBeenCalled()
  cleanup()
  // A finished agent's chip has it too, beside its button.
  draw(
    <AgentNode
      {...props('agent:rev2', { ...coder, name: 'Reviewer 2', chip: { said: '1 blocking', colour: 'var(--warn)' } })}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: "Open Reviewer 2's window" }))
  expect(useApp.getState().agentWindowId).toBe('rev2')
  cleanup()
  // Nothing but an agent has one.
  draw(
    <RequestNode
      {...props('request:a', { text: 'Look', time: '2026-10-05T10:00:00Z', queued: false, trigger: null })}
    />,
  )
  expect(screen.queryByRole('button', { name: /window/ })).toBeNull()
  useApp.setState({ agentWindowId: null })
})

test('its state in plain words: working at what, waiting for your OK (lit), done with what it found, failed with why, stopped', () => {
  const said = (status: AgentData['status'], activity: string, findings: AgentData['findings'] = null) =>
    statusWords({ status, activity, findings })
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
  draw(
    <AgentNode
      {...props('agent:kid', {
        ...coder,
        status: 'waiting_approval',
        activity: 'Waits for your approval',
        attention: true,
        finished: false,
      })}
    />,
  )
  expect(document.querySelector('.node')).toHaveClass('node-approval')
  expect(screen.getByText('Waits for your OK')).toBeInTheDocument()
  // Waiting for your answer it says so; what it asks is under the pointer (0.1.4).
  cleanup()
  const asks = 'Should mean() of an empty list raise ZeroDivisionError, or return 0?'
  draw(
    <AgentNode
      {...props('agent:kid', {
        ...coder,
        status: 'waiting_approval',
        activity: 'Waits for your answer',
        asks,
        attention: true,
        finished: false,
      })}
    />,
  )
  expect(screen.getByTitle(asks)).toHaveTextContent(/^Waits for your answer$/)
})

test('an agent at work says what it does, how long it has worked, the tokens it wrote and its tier, each fact its own piece: they give way before the command', () => {
  vi.useFakeTimers({ now: Date.parse('2026-10-05T10:00:15Z') })
  try {
    const at = {
      ...coder,
      status: 'running' as const,
      finished: false,
      activity: 'pytest tests/test_mail.py',
      since: '2026-10-05T10:00:03Z',
      wrote: 1234,
      kind: 'Fast',
    }
    draw(<AgentNode {...props('agent:kid', at)} />)
    // (In full under the pointer, with the same facts as the line.)
    const line = screen.getByTitle('Working · pytest tests/test_mail.py · 12s · ↓ 1.2k tokens · Fast')
    expect(line).toHaveClass('node-now')
    expect(line).toHaveTextContent(/^pytest tests\/test_mail\.py · 12s · ↓ 1\.2k tokens · Fast$/)
    // The facts after what it does are pieces, the tier last: where the box is narrow, they go before it is cut.
    expect(line.querySelector('.node-live-what')).toHaveTextContent(/^pytest tests\/test_mail\.py$/)
    expect(Array.from(line.querySelectorAll('.live-facts > span'), piece => piece.textContent)).toEqual([
      ' · 12s',
      ' · ↓ 1.2k tokens',
      ' · Fast',
    ])
    act(() => void vi.advanceTimersByTime(50_000))
    expect(line).toHaveTextContent(/ · 1m 02s · /)
    expect(line).toHaveAttribute('title', 'Working · pytest tests/test_mail.py · 1m 02s · ↓ 1.2k tokens · Fast')
    // A CLI that does not say its tokens: no count, never a made-up one.
    cleanup()
    draw(<AgentNode {...props('agent:kid', { ...at, wrote: null })} />)
    expect(screen.getByTitle(/^Working · pytest tests\/test_mail\.py · \d+m? ?\d+s · Fast$/)).not.toHaveTextContent(
      /tokens/,
    )
    cleanup()
    draw(<AgentNode {...props('agent:kid', coder)} />)
    expect(screen.getByTitle('Done ✓')).not.toHaveClass('node-now')
    expect(document.querySelector('.live-facts')).toBeNull()
  } finally {
    vi.useRealTimers()
  }
})

test('the user’s (4 Nov): a finished agent of a step’s newest round is a chip - a button named by it and how it ended -, an earlier round a line that opens and folds', async () => {
  draw(
    <AgentNode
      {...props('agent:rev2', { ...coder, name: 'Reviewer 2', chip: { said: '1 blocking', colour: 'var(--warn)' } })}
    />,
  )
  const chip = screen.getByRole('button', { name: 'Reviewer 2: 1 blocking' })
  expect(chip).toHaveTextContent(/^Reviewer 21 blocking$/)
  expect(screen.getByText('1 blocking').style.color).toBe('var(--warn)')
  // (Nothing of its card: its model, its tokens.)
  expect(screen.queryByText('Local · qwen')).toBeNull()
  cleanup()
  const toggle = vi.fn()
  const round: RoundData = {
    said: 'Round 2 · 4 reviewed',
    result: '2 blocking',
    colour: 'var(--warn)',
    inside: 4,
    summary: '',
    attention: false,
    finished: true,
    open: false,
  }
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
  expect(screen.getByRole('button', { name: 'Round 2 · 4 reviewed · waits for you · 2 blocking' })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
  expect(screen.getByText('waits for you · 2 blocking').style.color).toBe('var(--warn)')
})

test('a card shows only the dots a line uses (21 Nov): every dot kept, the unused one hidden', () => {
  /** The sides of the dots that show (`found-handle`: one hidden). */
  const shown = () =>
    Array.from(document.querySelectorAll('.react-flow__handle:not(.found-handle)'), dot =>
      dot.getAttribute('data-handlepos'),
    )
  const asked: RequestData = { text: 'Look', time: '2026-10-05T10:00:00Z', queued: false, trigger: null }
  const talk: DiscussionData = {
    topic: 'Keep hi?',
    line: 'Ended',
    members: ['Lead'],
    last: [],
    speaking: null,
    running: false,
  }
  const po: PoData = {
    provider_name: 'Fast',
    model_id: 'gpt-6-luna',
    heard: true,
    input_tokens: 2900,
    output_tokens: 200,
    proposed: 2,
    dropped: [],
    dropped_more: 0,
  }
  const cards: [ReactNode, string[]][] = [
    // (Nothing comes into a message or a file; every line to a discussion goes into it; a plan and the Scout have
    // their straight line.)
    [<RequestNode key="request" {...props('request:a', asked)} />, ['right']],
    [
      <AttachmentNode
        key="file"
        {...props('attachment:f', { name: 'a.ts', label: 'TS', colour: '--file-code', meta: '1 line' })}
      />,
      ['right'],
    ],
    [<DiscussionNode key="discussion" {...props('discussion:t', talk)} />, ['left']],
    [<PlanNode key="plan" {...props('plan:p', { status: 'proposed', by: null })} />, []],
    [<PoNode key="po" {...props('po:r', po)} />, []],
    // (An agent keeps both.)
    [<AgentNode key="agent" {...props('agent:kid', coder)} />, ['left', 'right']],
  ]
  for (const [card, sides] of cards) {
    draw(card)
    expect(shown()).toEqual(sides)
    cleanup()
  }
})

test('the user’s (7 Nov): the Scout’s node says the model, what came of it and what it spent, and opens the To-do page', async () => {
  const po: PoData = {
    provider_name: 'Fast',
    model_id: 'gpt-6-luna',
    heard: true,
    input_tokens: 2900,
    output_tokens: 200,
    proposed: 2,
    dropped: [],
    dropped_more: 0,
  }
  const openTodo = vi.fn()
  render(
    <ReactFlowProvider>
      <NodeActions.Provider value={{ openTodo }}>
        <PoNode {...props('po:r', po)} />
      </NodeActions.Provider>
    </ReactFlowProvider>,
  )
  expect(lines()).toEqual(['Scoutgpt-6-luna', '2 proposed', '3k tokens To-do →'])
  await userEvent.click(screen.getByRole('button', { name: 'To-do →' }))
  expect(openTodo).toHaveBeenCalledOnce()
  cleanup()
  // with ones dropped; sent and not heard out, nothing said of what it spent - not 0
  draw(<PoNode {...props('po:r', { ...po, dropped: [{ title: 'Docs', why: 'like the open task' }] })} />)
  expect(lines()[1]).toBe('2 proposed · 1 dropped')
  cleanup()
  draw(
    <PoNode
      {...props('po:r', { ...po, heard: false, model_id: null, input_tokens: null, output_tokens: null, proposed: 0 })}
    />,
  )
  expect(lines()).toEqual(['Scoutmodel not known', 'Sent, not heard out', '– tokens To-do →'])
  expect(screen.getByText('Sent, not heard out').style.color).toBe('var(--warn)')
})
