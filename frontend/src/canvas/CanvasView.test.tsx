import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type ComponentProps, type ProviderProps, createElement, useState } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Attachment, Message } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { agent, command, conversation, convState, fileChange, run, toolCall, userMessage } from '../test-fixtures'
import { CanvasView } from './CanvasView'
import { topicOf } from './thread.fixtures'
import { type Actions, NodeActions } from './toggleGroup'

// What the canvas hands its nodes each time it is drawn: its provider is watched.
const handed: Actions[] = []
const provide = NodeActions.Provider
Object.assign(NodeActions, {
  Provider: ({ value, children }: ProviderProps<Actions>) => {
    handed.push(value)
    return createElement(provide, { value }, children)
  },
})

beforeEach(() => {
  localStorage.clear()
  // React Flow watches its pane and its nodes; jsdom has nothing to watch with.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})
// (Unmounted first: React Flow's late effects still reach for the stubbed ResizeObserver.)
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const nightly = { unattended: true, trigger_id: 'tr', trigger_name: 'Nightly look' }
const byTrigger = (runId: string, content: string): Message => ({ ...userMessage(runId, content), id: `t-${runId}`, role: 'trigger' })

/**
 * A turn that is over - a lead with a command, and a Reviewer with a tool call and a change -,
 * one a trigger started, and one of the user's at work with a tool call and a command.
 */
const state = convState({
  runs: [run('a', 'completed'), run('n', 'completed', nightly), run('b')],
  messages: [userMessage('a', 'Fix the greeting'), byTrigger('n', 'Look the project over'), userMessage('b', 'go on')],
  agents: [
    agent('a', 'completed'),
    agent('a', 'completed', { id: 'kid', parent_agent_id: 'a', role_name: 'Reviewer', depth: 1 }),
    agent('n', 'completed'),
    agent('b'),
  ],
  toolCalls: [
    toolCall('4', 'a', 'read_file', 'succeeded', '{"path":"hello.py"}', { agent_id: 'kid' }),
    toolCall('5', 'b', 'read_file', 'succeeded', '{"path":"hello.py"}'),
  ],
  commands: [command('k1', 'a'), command('k2', 'b', { output: 'collected 2 items\n2 passed\n' })],
  fileChanges: [fileChange('f2', 'a', { agent_id: 'kid' })],
})

const node = (id: string) => document.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`)
const drawn = () => Array.from(document.querySelectorAll('.react-flow__node')).map(n => n.getAttribute('data-id'))

/** The canvas with a place for its turns' button, as the top bar gives it. */
function Slotted(props: ComponentProps<typeof CanvasView>) {
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  return (
    <>
      <span ref={setSlot} />
      <CanvasView {...props} turnsIn={slot} />
    </>
  )
}

/** The canvas as the app holds it: the turn picked lives outside it. */
function Held({ conv = state, selectedId = null, first = null }: { conv?: ConvState; selectedId?: string | null; first?: string | null }) {
  const [turnId, setTurnId] = useState<string | null>(first)
  return (
    <>
      <output data-testid="picked">{turnId ?? 'none'}</output>
      <Slotted state={conv} selectedId={selectedId} onSelect={() => {}} turnId={turnId} onTurn={setTurnId} />
    </>
  )
}
/** Recent, opened from its button in the top bar where it is not open. */
const list = () => {
  if (!screen.queryByRole('complementary', { name: 'Recent' })) fireEvent.click(screen.getByRole('button', { name: /^Recent/ }))
  return screen.getByRole('complementary', { name: 'Recent' })
}
/** A message's row in Recent. */
const row = (name: RegExp) => {
  const found = Array.from(list().querySelectorAll<HTMLElement>('.turn-row')).find(button => name.test(button.textContent ?? ''))
  if (!found) throw new Error(`no row for ${name}`)
  return found
}
test('the canvas draws the message at work, and no node of any other; Recent lists every message, the trigger’s too, with its work', async () => {
  render(<Held />)
  await waitFor(() => expect(node('agent:b')).not.toBeNull())
  expect(drawn()).toEqual(['request:b', 'agent:b'])
  expect(list().querySelectorAll('.turn-row')).toHaveLength(3)
  expect(row(/Fix the greeting/)).toHaveTextContent('1 agent · 1 file')
  expect(row(/go on/)).toHaveAttribute('aria-current', 'true')
  // (the canvas has no list of its own: it is all the stage's - slice 107)
  expect(screen.queryByRole('navigation')).toBeNull()
})

test('a click on a row draws that turn alone; the trigger’s turn like any other', async () => {
  render(<Held />)
  await userEvent.click(row(/Fix the greeting/))
  await waitFor(() => expect(node('agent:a')).not.toBeNull())
  expect(drawn()).toEqual(['request:a', 'agent:a', 'agent:kid'])
  expect(row(/Fix the greeting/)).toHaveAttribute('aria-current', 'true')
  expect(row(/go on/)).not.toHaveAttribute('aria-current')
  await userEvent.click(row(/Nightly look/))
  await waitFor(() => expect(node('agent:n')).not.toBeNull())
  expect(drawn()).toEqual(['request:n', 'agent:n'])
  expect(node('request:n')).toHaveTextContent('Nightly look · nobody watching')
  expect(screen.getByTestId('picked')).toHaveTextContent('n')
})

test('a turn a trigger starts does not take the canvas: it is added to the list and the turn drawn stays', async () => {
  const { rerender } = render(<Held first="a" />)
  await waitFor(() => expect(node('agent:a')).not.toBeNull())
  const later = { ...state, runs: [...state.runs, run('m', 'running', nightly)], agents: [...state.agents, agent('m')], messages: [...state.messages, byTrigger('m', 'Look again')] }
  rerender(<Held first="a" conv={later} />)
  expect(list().querySelectorAll('.turn-row')).toHaveLength(4)
  expect(node('agent:a')).not.toBeNull()
  expect(node('agent:m')).toBeNull()
  expect(screen.getByTestId('picked')).toHaveTextContent('a')
  // nor when nothing was picked: the newest turn of the user's is still the one drawn
  render(<Slotted state={later} selectedId={null} onSelect={() => {}} />)
  expect(document.querySelectorAll('.react-flow__node[data-id="agent:m"]')).toHaveLength(0)
})

test('selecting a node of another turn - from the chat, the inspector, an agent’s window - goes to its turn and shows it selected; a file, a command or a call as its agent', async () => {
  const { rerender } = render(<Held />)
  await waitFor(() => expect(node('agent:b')).not.toBeNull())
  expect(node('agent:kid')).toBeNull()

  // the canvas is only told its id: the Reviewer's change is the Reviewer's (the user's, 5 Nov: no node of its own)
  rerender(<Held selectedId="file:f2" />)
  await waitFor(() => expect(node('agent:kid')).not.toBeNull())
  expect(screen.getByTestId('picked')).toHaveTextContent('a')
  expect(node('agent:kid')!.querySelector('.node-selected')).not.toBeNull()
  expect(node('agent:b')).toBeNull()

  // the user goes back to the latest turn while it is still selected: the canvas stays there
  await userEvent.click(row(/go on/))
  await waitFor(() => expect(node('agent:b')).not.toBeNull())
  rerender(<Held selectedId="file:f2" />)
  expect(node('agent:kid')).toBeNull()

  // a command, and one call, likewise
  rerender(<Held selectedId="command:k2" />)
  await waitFor(() => expect(node('agent:b')!.querySelector('.node-selected')).not.toBeNull())
  rerender(<Held selectedId="call:4" />)
  await waitFor(() => expect(node('agent:kid')).not.toBeNull())
  expect(node('agent:kid')!.querySelector('.node-selected')).not.toBeNull()
})

test('an event hands the nodes the same actions as before', async () => {
  const onOpenNode = vi.fn()
  const lead = agent('b', 'waiting', { id: 'lead' })
  const coder = agent('b', 'running', { id: 'kid', parent_agent_id: 'lead', role_name: 'Coder', depth: 1, provider_name: 'Codex', provider_mode: 'native' })
  const conv = (agents: (typeof lead)[]) => convState({ runs: [run('b')], messages: [userMessage('b', 'go on')], agents })
  const canvas = (state: ConvState) => <CanvasView state={state} selectedId={null} onSelect={() => {}} onOpenNode={onOpenNode} />
  const { rerender } = render(canvas(conv([lead])))
  await waitFor(() => expect(node('agent:lead')).not.toBeNull())
  const before = handed.at(-1)
  rerender(canvas(conv([lead, coder])))
  await waitFor(() => expect(node('agent:kid')).not.toBeNull())
  // every node reads the actions: a new object would draw each of them again on every event
  expect(handed.at(-1)).toBe(before)
  // (no Raw on a node: it is in the side panel's agent window - the user's, 5 Nov)
  expect(document.querySelector('.react-flow__node button[aria-label^="Raw"]')).toBeNull()
})

// --- topics (slice 18b) ------------------------------------------------------------------------

test('the canvas draws the turn picked of a topic, and nothing of its other turns', async () => {
  render(<Held conv={topicOf(3)} first="t3" />)
  await waitFor(() => expect(node('agent:t3')).not.toBeNull())
  expect(node('agent:t3')).not.toHaveTextContent('continues from')
  // Recent has every message of the chat, whatever its topic
  expect(list().querySelectorAll('.turn-row')).toHaveLength(4)
})

test('slice 107: with nothing picked, the last message with work is in front; a plain one after it is drawn when picked', async () => {
  render(<Held conv={topicOf(3)} />)
  await waitFor(() => expect(node('agent:t3')).not.toBeNull())
  expect(drawn()).toEqual(['request:t3', 'agent:t3', 'agent:coder-t3'])
  expect(row(/message 3/)).toHaveAttribute('aria-current', 'true')
  await userEvent.click(row(/Write the docs/))
  await waitFor(() => expect(node('agent:other')).not.toBeNull())
  expect(drawn()).toEqual(['request:other', 'agent:other'])
  await userEvent.click(row(/message 2/))
  await waitFor(() => expect(node('agent:t2')).not.toBeNull())
  expect(drawn()).toEqual(['request:t2', 'agent:t2', 'agent:coder-t2'])
  expect(screen.getByTestId('picked')).toHaveTextContent('t2')
})

test('a message at work is in front, even with no work yet', async () => {
  const conv = topicOf(2)
  render(<Held conv={{ ...conv, runs: [...conv.runs, run('now', 'running', { topic_id: 'tb' })], messages: [...conv.messages, userMessage('now', 'thanks')], agents: [...conv.agents, agent('now')] }} />)
  await waitFor(() => expect(node('agent:now')).not.toBeNull())
  expect(drawn()).toEqual(['request:now', 'agent:now'])
})

test('a topic is renamed from Recent', async () => {
  const onRenameTopic = vi.fn().mockResolvedValue(undefined)
  render(<Slotted state={topicOf(1)} selectedId={null} onSelect={() => {}} turnId="t1" onRenameTopic={onRenameTopic} />)
  await userEvent.click(within(list()).getByRole('button', { name: 'Rename Fix the greeting' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Topic name' }), '!{Enter}')
  expect(onRenameTopic).toHaveBeenCalledWith('ta', 'Fix the greeting!')
})

// --- the view when a panel opens beside the stage ----------------------------------------------

/** The canvas with what is selected held outside it, as the app holds it: a click on a node selects it. */
function Selecting({ conv }: { conv: ConvState }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  return <CanvasView state={conv} selectedId={selectedId} onSelect={setSelectedId} turnId="t12" />
}

/** jsdom lays nothing out: a stage given a size, nodes measured as the layout takes them, and the view as it is drawn. */
function laidOut() {
  // jsdom lays nothing out: the stage is given a size, and whoever watches it is told when it changes.
  const watchers: { element: Element; told: ResizeObserverCallback }[] = []
  vi.stubGlobal(
    'ResizeObserver',
    class {
      told: ResizeObserverCallback
      constructor(told: ResizeObserverCallback) {
        this.told = told
      }
      observe(element: Element) {
        watchers.push({ element, told: this.told })
      }
      unobserve() {}
      disconnect() {}
    },
  )
  // (React Flow reads the zoom its nodes are drawn at off the page, with a matrix jsdom has none of.)
  vi.stubGlobal('DOMMatrixReadOnly', class { m22 = 1 })
  const sized = (element: Element, width: number, height: number) => {
    for (const [name, value] of [['clientWidth', width], ['offsetWidth', width], ['clientHeight', height], ['offsetHeight', height]] as const) {
      Object.defineProperty(element, name, { configurable: true, get: () => value })
    }
  }
  /** Every node is as big as the layout takes it to be: React Flow fits nothing until it has measured them all. */
  const measure = () => {
    for (const { element, told } of watchers) {
      if (!element.matches('.react-flow__node')) continue
      const { width, height } = (element as HTMLElement).style
      sized(element, parseFloat(width) || 200, parseFloat(height) || 104)
      act(() => told([{ target: element } as ResizeObserverEntry], {} as ResizeObserver))
    }
  }
  /** The stage - and React Flow's own pane inside it - becomes this wide, 600 high, and whoever watches is told. */
  const stage = (width: number) => {
    for (const { element, told } of watchers) {
      if (element.matches('.react-flow__node')) continue
      sized(element, width, 600)
      act(() => told([], {} as ResizeObserver))
    }
  }
  const view = () => {
    const [, x, y, zoom] = /translate\((-?[\d.]+)px, ?(-?[\d.]+)px\) scale\((-?[\d.]+)\)/.exec(document.querySelector<HTMLElement>('.react-flow__viewport')!.style.transform)!.map(Number)
    return { x, y, zoom }
  }
  const moved = () => new Promise(resolve => setTimeout(resolve, 500))
  return { measure, stage, view, moved }
}

test('the inspector opening beside a node selected on the canvas does not draw the turn smaller: the zoom stays, and the node is still in view', async () => {
  const { measure, stage, view, moved } = laidOut()

  // the request, the lead and the Coder in a row - wider than the stage
  render(<Selecting conv={topicOf(12)} />)
  await waitFor(() => expect(node('agent:coder-t12')).not.toBeNull())
  stage(800)
  measure()
  await moved()
  const fitted = view()
  expect(fitted.zoom).toBeLessThan(1)

  // the Coder, at the far right of the turn, is selected by a click: the inspector opens and the stage is half as wide
  fireEvent.click(node('agent:coder-t12')!)
  await waitFor(() => expect(node('agent:coder-t12')!.querySelector('.node-selected')).not.toBeNull())
  stage(400)
  await moved()
  const narrowed = view()
  expect(narrowed.zoom).toBe(fitted.zoom)
  // only moved: the Coder, which the narrower stage would have cut off, is inside it
  const coder = node('agent:coder-t12') as HTMLElement
  const [, left] = /translate\((-?[\d.]+)px/.exec(coder.style.transform)!.map(Number)
  expect(left * fitted.zoom + fitted.x + parseFloat(coder.style.width) * fitted.zoom).toBeGreaterThan(400)
  expect(left * narrowed.zoom + narrowed.x).toBeGreaterThanOrEqual(0)
  expect(left * narrowed.zoom + narrowed.x + parseFloat(coder.style.width) * narrowed.zoom).toBeLessThanOrEqual(400)
})

test('with no turn the canvas says so, and how to start one', () => {
  render(<Slotted state={convState()} selectedId={null} onSelect={() => {}} />)
  expect(screen.getByText('No message yet. Write one to start.')).toBeInTheDocument()
  expect(document.querySelectorAll('.react-flow__node')).toHaveLength(0)
})

test('the empty canvas greets with the bee played once, muted; where motion is reduced, its still picture', () => {
  // (not while the conversation is still being read: it may have messages)
  const { rerender, unmount } = render(<Slotted state={null} selectedId={null} onSelect={() => {}} />)
  expect(document.querySelector('.canvas-empty-bee')).toBeNull()
  rerender(<Slotted state={convState()} selectedId={null} onSelect={() => {}} />)
  const video = document.querySelector('video.canvas-empty-bee') as HTMLVideoElement
  expect(video).toHaveAttribute('src', '/brand/koloni-ari.webm')
  expect(video).toHaveAttribute('aria-hidden', 'true')
  expect(video.muted && video.autoplay && !video.loop && !video.controls).toBe(true)
  unmount()
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: query === '(prefers-reduced-motion: reduce)' }))
  render(<Slotted state={convState()} selectedId={null} onSelect={() => {}} />)
  expect(document.querySelector('video')).toBeNull()
  expect(document.querySelector('img.canvas-empty-bee')).toHaveAttribute('src', '/brand/koloni_ari_vektor.png')
})

test('the legend: its button among the canvas’s opens what the states, lines and signs mean; Esc closes it, the focus back on the button', async () => {
  render(<Slotted state={state} selectedId={null} onSelect={() => {}} />)
  const button = screen.getByRole('button', { name: 'Canvas legend' })
  button.focus()
  await userEvent.keyboard('{Enter}')
  const legend = screen.getByRole('dialog', { name: 'Canvas legend' })
  expect(legend).toHaveFocus()
  expect(button).toHaveAttribute('aria-expanded', 'true')
  for (const said of ['working', 'waits for you', 'done', 'failed', 'Handed to a sub-agent', 'Waits for a file another agent holds', 'A member’s line to its discussion or room (between teams, from its frame to the lane)', 'N× same error'])
    expect(within(legend).getByText(said)).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog', { name: 'Canvas legend' })).not.toBeInTheDocument()
  expect(button).toHaveFocus()
})

test('“Follow running” keeps the agent at work in view: a move of the user’s own turns it off, its button on again - and the view goes back to the agent', async () => {
  const { measure, stage, view, moved } = laidOut()
  const busy = topicOf(12)
  // the Coder of the last turn, at the far right of it, is at work
  const conv = { ...busy, agents: busy.agents.map(a => (a.id === 'coder-t12' ? { ...a, status: 'running' as const } : a)) }
  render(<Selecting conv={conv} />)
  await waitFor(() => expect(node('agent:coder-t12')).not.toBeNull())
  stage(1400)
  measure()
  await moved()
  const follow = screen.getByRole('button', { name: 'Follow running' })
  expect(follow).toHaveAttribute('aria-pressed', 'true')
  const coder = node('agent:coder-t12') as HTMLElement
  const right = () => {
    const [, left] = /translate\((-?[\d.]+)px/.exec(coder.style.transform)!.map(Number)
    const { x, zoom } = view()
    return (left + parseFloat(coder.style.width)) * zoom + x
  }
  expect(right()).toBeLessThanOrEqual(1400)

  // the user zooms in at the left end: the Coder is out of sight, and the canvas no longer follows
  fireEvent.wheel(document.querySelector('.react-flow__pane')!, { deltaY: -800, clientX: 0, clientY: 0 })
  await moved()
  expect(follow).toHaveAttribute('aria-pressed', 'false')
  expect(right()).toBeGreaterThan(1400)

  // on again: the Coder is brought into view
  await userEvent.click(follow)
  expect(follow).toHaveAttribute('aria-pressed', 'true')
  await moved()
  expect(right()).toBeLessThanOrEqual(1400)
})

test('the zoom buttons turn “Follow running” off, as a pan does', async () => {
  render(<Slotted state={state} selectedId={null} onSelect={() => {}} />)
  const follow = screen.getByRole('button', { name: 'Follow running' })
  expect(follow).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Zoom In' }))
  expect(follow).toHaveAttribute('aria-pressed', 'false')
  await userEvent.click(follow)
  await userEvent.click(screen.getByRole('button', { name: 'Zoom Out' }))
  expect(follow).toHaveAttribute('aria-pressed', 'false')
})

test('the timeline: its button among the canvas’s opens a strip under it for the turn drawn - kept open from visit to visit; a bar opens that agent’s window', async () => {
  const onOpenNode = vi.fn()
  const { unmount } = render(<Slotted state={state} selectedId={null} onSelect={() => {}} onOpenNode={onOpenNode} />)
  const button = screen.getByRole('button', { name: 'Timeline' })
  expect(button).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('region', { name: 'Timeline' })).not.toBeInTheDocument()
  button.focus()
  await userEvent.keyboard('{Enter}')
  expect(button).toHaveAttribute('aria-expanded', 'true')
  // The turn drawn (b): its one agent, a row under the table's head.
  const strip = screen.getByRole('region', { name: 'Timeline' })
  expect(within(strip).getAllByRole('row')).toHaveLength(2)
  await userEvent.click(within(strip).getByRole('button', { name: 'Orchestrator' }))
  expect(onOpenNode).toHaveBeenCalledWith('agent', 'b')
  unmount()

  render(<Slotted state={state} selectedId={null} onSelect={() => {}} />)
  const again = screen.getByRole('region', { name: 'Timeline' })
  await userEvent.click(within(again).getByRole('button', { name: 'Close timeline' }))
  expect(screen.queryByRole('region', { name: 'Timeline' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Timeline' })).toHaveFocus()
})

test('a talk line’s words are put away by Esc, and by a selection made elsewhere; read out as they come (K-canvas-dili)', async () => {
  const said = (id: string, from: string, to: string, kind: 'message' | 'reply', content: string) => ({ id, run_id: 'a', from_agent_id: from, to_agent_id: to, kind, content, created_at: '2026-10-05T10:00:00Z' })
  const talked = { ...state, channelMessages: [said('c1', 'a', 'kid', 'message', 'Check the tests too.'), said('c2', 'kid', 'a', 'reply', 'There are none.')] }
  const onSelect = vi.fn()
  const props = { state: talked, onSelect, turnId: 'a' }
  const { rerender } = render(<CanvasView {...props} selectedId={null} />)
  const box = () => screen.queryByRole('region', { name: 'What was said' })
  act(() => handed.at(-1)!.showTalk!('agent:a>agent:kid'))
  expect(box()).toHaveTextContent('There are none.')
  expect(box()).toHaveAttribute('aria-live', 'polite')
  fireEvent.keyDown(document.querySelector('.canvas-flow')!, { key: 'Escape' })
  expect(box()).toBeNull()
  act(() => handed.at(-1)!.showTalk!('agent:a>agent:kid'))
  expect(box()).not.toBeNull()
  // Picked elsewhere - in the chat, the inspector: its words go.
  rerender(<CanvasView {...props} selectedId="agent:a" />)
  expect(box()).toHaveTextContent('There are none.') // (the Orchestrator's own talk: picked, it says it)
  // Esc in the box puts the pick away too.
  fireEvent.keyDown(within(box()!).getByRole('button', { name: 'Close what was said' }), { key: 'Escape' })
  expect(onSelect).toHaveBeenCalledWith(null)
  rerender(<CanvasView {...props} selectedId="agent:n" />)
  expect(box()).toBeNull()
})

test('picking an agent that said nothing fades the rest, and opens no box of what was said', () => {
  render(<CanvasView state={state} onSelect={() => {}} turnId="a" selectedId="agent:kid" />)
  expect(screen.queryByRole('region', { name: 'What was said' })).toBeNull()
})

test('a discussion picked lights who took part; pointed at, it fades nothing', async () => {
  // (The user, 4 Nov: pointing at one darkened the whole canvas; a click lights, as any other node's does.)
  const at = '2026-10-05T10:00:00Z'
  const conv = convState({
    runs: [run('d')],
    messages: [userMessage('d', 'talk it over')],
    agents: [agent('d'), agent('d', 'completed', { id: 'rev', parent_agent_id: 'd', role_name: 'Reviewer', depth: 1 }), agent('d', 'completed', { id: 'res', parent_agent_id: 'd', role_name: 'Researcher', depth: 1 })],
    discussions: [{ id: 't', run_id: 'd', agent_id: 'd', tool_call_id: 'x', topic: 'Keep hi?', status: 'ended', outcome: 'agreed', round: 1, max_rounds: 3, created_at: at, ended_at: at, members: ['d', 'rev'].map(agent_id => ({ agent_id, status: 'in' as const, opened_here: false })) }] as unknown as ConvState['discussions'],
  })
  const faded = (id: string) => node(id)!.classList.contains('canvas-faded')
  const { rerender } = render(<CanvasView state={conv} onSelect={() => {}} selectedId={null} />)
  await waitFor(() => expect(node('discussion:t')).not.toBeNull())
  fireEvent.mouseEnter(node('discussion:t')!)
  await act(() => new Promise(done => setTimeout(done, 50)))
  expect(['agent:d', 'agent:rev', 'agent:res'].map(faded)).toEqual([false, false, false])
  rerender(<CanvasView state={conv} onSelect={() => {}} selectedId="discussion:t" />)
  await waitFor(() => expect(faded('agent:res')).toBe(true))
  expect([faded('agent:d'), faded('agent:rev'), faded('discussion:t')]).toEqual([false, false, false])
})

test('a room picked lights who is in it, as a discussion does', async () => {
  const room = { id: 'o', run_id: 'd', agent_id: 'd', goal: 'Build it together', status: 'working', outcome: null, why: null, members: ['rev'].map(agent_id => ({ agent_id, role: 'Reviewer', status: 'in' })) }
  const conv = convState({
    runs: [run('d')],
    messages: [userMessage('d', 'work together')],
    agents: [agent('d'), agent('d', 'completed', { id: 'rev', parent_agent_id: 'd', role_name: 'Reviewer', depth: 1 }), agent('d', 'completed', { id: 'res', parent_agent_id: 'd', role_name: 'Researcher', depth: 1 })],
    rooms: [room] as unknown as ConvState['rooms'],
  })
  const faded = (id: string) => node(id)!.classList.contains('canvas-faded')
  render(<CanvasView state={conv} onSelect={() => {}} selectedId="room:o" />)
  await waitFor(() => expect(faded('agent:res')).toBe(true))
  expect([faded('agent:rev'), faded('room:o')]).toEqual([false, false])
})

/** A line's last two corners as drawn: where it comes into its card from. */
const lastLeg = (id: string) => {
  const d = document.querySelector(`.react-flow__edge[data-id="${id}"] .react-flow__edge-path`)?.getAttribute('d') ?? ''
  return [...d.matchAll(/(-?[\d.]+)[ ,](-?[\d.]+)/g)].map(m => [Number(m[1]), Number(m[2])]).slice(-2)
}

test('option A (the user’s, 21 Nov): with no team, members stacked under their discussion join one line at its right and come in there, arrowed, in their own colour', async () => {
  // (The screenshot: the Discussion over Coder and Reviewer in one column, their dotted lines out of their right dots and
  // back behind the cards into its left one.)
  const { measure, stage } = laidOut()
  const at = '2026-10-05T10:00:00Z'
  const sub = (id: string, role: string) => agent('d', 'completed', { id, parent_agent_id: 'd', role_name: role, depth: 1 })
  const conv = convState({
    runs: [run('d')],
    messages: [userMessage('d', 'talk it over')],
    agents: [agent('d'), sub('rev', 'Reviewer'), sub('res', 'Researcher')],
    discussions: [{ id: 't', run_id: 'd', agent_id: 'd', tool_call_id: 'x', topic: 'Keep hi?', status: 'ended', outcome: 'agreed', round: 1, max_rounds: 3, created_at: at, ended_at: at, members: ['rev', 'res', 'd'].map(agent_id => ({ agent_id, status: 'in' as const, opened_here: true })) }] as unknown as ConvState['discussions'],
  })
  render(<CanvasView state={conv} onSelect={() => {}} selectedId={null} />)
  await waitFor(() => expect(node('agent:res')).not.toBeNull())
  measure()
  stage(1200)
  await waitFor(() => expect(document.querySelector('.react-flow__edge[data-id="agent:res>discussion:t"]')).not.toBeNull())
  for (const id of ['agent:rev>discussion:t', 'agent:res>discussion:t']) {
    expect(look(id).slice(0, 3)).toEqual(['react-flow__edge react-flow__edge-lane nopan selectable', 'stroke: var(--member-line); stroke-width: 1.5; stroke-dasharray: 2 5;', true])
    // In from the right: its last leg runs leftward into the card.
    const [[x1], [x2]] = lastLeg(id)
    expect(x1, id).toBeGreaterThan(x2)
  }
  // The Orchestrator's own line into it, from the column before, as it was - in the members' colour; its lines to them grey.
  expect(look('agent:d>discussion:t').slice(0, 3)).toEqual(['react-flow__edge react-flow__edge-default nopan selectable', 'stroke: var(--member-line); stroke-width: 1.5; stroke-dasharray: 2 5;', false])
  const [[o1], [o2]] = lastLeg('agent:d>discussion:t')
  expect(o1).toBeLessThan(o2)
  expect(look('agent:d>agent:rev')[1]).toBe('stroke: var(--border-strong); stroke-width: 1.5; stroke-dasharray: 6 5;')
})

test('the user’s (4 Nov): a step’s earlier round is one line that opens in place; a chip picks its agent and opens its window, as its card does', async () => {
  const step = (id: string, name: string, now: boolean, group = false) => ({ id, name, state: now ? ('now' as const) : ('next' as const), round: 0, room: false, own_check: false, left_out: [], group })
  const ids = ['coder', 'rev', 'coder2', 'rev2']
  const passes = ids.map((id, at) => ({ part: at % 2 ? 'reviews' : 'build', agents: [id] }))
  const conv = convState({
    conversation: {
      ...conversation,
      teams_mode: 'manual',
      teams: [{ team_id: 'web', recipe_id: null, no_recipe: false, picked_by: 'user', why: null, state: { run_id: 't', team: 'Web app', recipe: 'Feature', status: 'running', why: null, steps: [step('build', 'Build', true), step('reviews', 'Reviews', false, true)], agents: ids, ended_ready: false, passes } }],
    },
    runs: [run('t')],
    messages: [userMessage('t', 'Build it')],
    agents: [
      agent('t'),
      ...ids.map(id =>
        agent('t', 'completed', { id, name: { coder: 'Coder', rev: 'Reviewer', coder2: 'Coder 2', rev2: 'Reviewer 2' }[id], role_name: id.startsWith('rev') ? 'Reviewer' : 'Coder', parent_agent_id: 't', depth: 1, findings: id.startsWith('rev') ? [] : null }),
      ),
    ],
  })
  const onSelect = vi.fn()
  const onOpenNode = vi.fn()
  render(<Slotted state={conv} selectedId={null} onSelect={onSelect} onOpenNode={onOpenNode} />)
  const chip = await screen.findByRole('button', { name: 'Reviewer 2: ✓' })
  fireEvent.click(chip)
  expect(onSelect).toHaveBeenCalledWith('agent:rev2')
  fireEvent.doubleClick(chip)
  expect(onOpenNode).toHaveBeenCalledWith('agent', 'rev2')
  // Round 1 of the reviews: folded, its Reviewer not drawn; a click opens it in place, another folds it.
  const line = screen.getByRole('button', { name: 'Round 1 · 1 reviewed · 0 blocking' })
  expect(line).toHaveAttribute('aria-expanded', 'false')
  expect(node('agent:rev')).toBeNull()
  fireEvent.click(line)
  await waitFor(() => expect(node('agent:rev')).not.toBeNull())
  expect(screen.getByRole('button', { name: 'Round 1 · 1 reviewed · 0 blocking' })).toHaveAttribute('aria-expanded', 'true')
  expect(onSelect).toHaveBeenCalledTimes(1) // (opening a round picks nothing)
})

/** A line as drawn: its classes, its path's style, whether it has an arrow, and its label - null for none. */
const look = (id: string) => {
  const line = document.querySelector(`.react-flow__edge[data-id="${id}"]`)
  const path = line?.querySelector('.react-flow__edge-path')
  const label = line?.querySelector('.react-flow__edge-text')
  return [line?.getAttribute('class'), path?.getAttribute('style'), path?.hasAttribute('marker-end'), label && `${label.textContent} in ${label.getAttribute('style')}`]
}

test('a line says what it is: a spawn dashed, in the accent at work; findings and talk between agents of no frame counted on it; a file handed; a wait - picked, its own lit', async () => {
  const { measure, stage } = laidOut()
  // (A label is measured with getBBox, which jsdom has none of.)
  Object.defineProperty(SVGElement.prototype, 'getBBox', { configurable: true, value: () => ({ x: 0, y: 0, width: 40, height: 10 }) })
  const said = (id: string, from: string, to: string, kind: 'message' | 'findings', content: string) => ({ id, run_id: 'r', from_agent_id: from, to_agent_id: to, kind, content, created_at: '2026-10-05T10:00:00Z' })
  const file: Attachment = { id: 'f', conversation_id: 'c', message_id: 'u-r', frame_of: null, name: 'spec.md', kind: 'text', mime: 'text/plain', size: 10, summary: '1 line', given_to: ['c'],shown_to: {}, keep_in_project: false, created_at: '2026-10-05T10:00:00Z' }
  const sub = (id: string, role: string, status: 'running' | 'completed' | 'blocked', over = {}) => agent('r', status, { id, role_name: role, parent_agent_id: 'r', depth: 1, ...over })
  const conv = convState({
    runs: [run('r')],
    messages: [userMessage('r', 'fix it')],
    agents: [agent('r'), sub('c', 'Coder', 'running'), sub('v', 'Reviewer', 'completed'), sub('w', 'Tester', 'blocked', { waiting_for: { agent_id: 'c', agent_name: 'Coder', path: 'a.txt' } })],
    attachments: [file],
    channelMessages: [said('f1', 'v', 'c', 'findings', '- one | kind: code | role: Coder'), said('m1', 'r', 'v', 'message', 'Look.')],
  })
  try {
    const { rerender } = render(<CanvasView state={conv} selectedId={null} onSelect={() => {}} />)
    await waitFor(() => expect(node('agent:w')).not.toBeNull())
    measure()
    stage(1200)
    await waitFor(() => expect(document.querySelector('.react-flow__edge[data-id="waits:agent:w>agent:c"]')).not.toBeNull())
    expect(look('agent:r>agent:c')).toEqual(['react-flow__edge react-flow__edge-default nopan animated selectable', 'stroke: var(--accent); stroke-width: 2; stroke-dasharray: 6 5;', false, null])
    // The Orchestrator's talk with its own sub-agent: square, arrowed, its 💬 a button naming the two (not "1 message").
    expect(look('agent:r>agent:v')).toEqual(['react-flow__edge react-flow__edge-lane nopan selectable', 'stroke: var(--border-strong); stroke-width: 1.5; stroke-dasharray: 6 5;', true, null])
    expect(screen.getByRole('button', { name: 'Lead ↔ Reviewer: 1 message, the last: Look.' })).toHaveTextContent('💬 1')
    // (The Coder it was handed to is at work on it.)
    expect(look('findings:f1')).toEqual(['react-flow__edge react-flow__edge-default edge-findings nopan animated selectable', 'stroke: var(--warn); stroke-width: 2; stroke-dasharray: 8 3;', false, '1 finding in fill: var(--warn); font-size: var(--text-kicker);'])
    // (The Tester waits for the Coder two cards up its column: round their right, arrowed into the Coder's side.)
    expect(look('waits:agent:w>agent:c')).toEqual(['react-flow__edge react-flow__edge-lane edge-waits nopan selectable', 'stroke: var(--border-strong); stroke-width: 1; stroke-dasharray: 3 4;', true, null])
    const [[x1], [x2]] = lastLeg('waits:agent:w>agent:c')
    expect(x1).toBeGreaterThan(x2)
    expect(look('handed:attachment:f>agent:c')).toEqual(['react-flow__edge react-flow__edge-default edge-handed nopan selectable', 'stroke: var(--accent); stroke-width: 1.5; stroke-dasharray: 5 4;', false, null])
    // The Reviewer picked: its lines lit and thick, the rest faded - its nodes too.
    rerender(<CanvasView state={conv} selectedId="agent:v" onSelect={() => {}} />)
    await waitFor(() => expect(look('findings:f1')[0]).toContain('edge-lit'))
    expect(look('findings:f1').slice(0, 2)).toEqual(['react-flow__edge react-flow__edge-default edge-findings edge-lit nopan animated selectable', 'stroke: var(--warn); stroke-width: 3; stroke-dasharray: 8 3;'])
    expect(look('waits:agent:w>agent:c')[0]).toBe('react-flow__edge react-flow__edge-lane edge-waits edge-faded nopan selectable')
    expect(['agent:r', 'agent:v', 'agent:c', 'agent:w'].map(id => node(id)?.classList.contains('canvas-faded'))).toEqual([false, false, false, true])
  } finally {
    Reflect.deleteProperty(SVGElement.prototype, 'getBBox')
  }
})

test('more files than a few are one box, folded with Collapse all and opened with Expand all; a turn with no work on record says so', async () => {
  const file = (id: string): Attachment => ({ id, conversation_id: 'c', message_id: 'u-r', frame_of: null, name: `${id}.md`, kind: 'text', mime: 'text/plain', size: 10, summary: '1 line', given_to: [],shown_to: {}, keep_in_project: false, created_at: '2026-10-05T10:00:00Z' })
  const conv = convState({ runs: [run('r')], messages: [userMessage('r', 'read these')], agents: [agent('r')], attachments: ['a', 'b', 'c', 'd', 'e'].map(file) })
  render(<CanvasView state={conv} selectedId={null} onSelect={() => {}} />)
  await waitFor(() => expect(node('files:r')).not.toBeNull())
  expect(node('attachment:a')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Expand all' }))
  await waitFor(() => expect(node('attachment:a')).not.toBeNull())
  // The files inside their box, which is as big as the layout made it.
  expect(node('files:r')).toHaveClass('parent')
  expect(node('files:r')?.style.width).toBe('248px')
  await userEvent.click(screen.getByRole('button', { name: 'Collapse all' }))
  await waitFor(() => expect(node('attachment:a')).toBeNull())
  cleanup()
  // A turn of no message and no agent.
  render(<Slotted state={convState({ runs: [run('a', 'completed')] })} selectedId={null} onSelect={() => {}} />)
  expect(screen.getByText('Nothing of this message’s work is on record yet.')).toHaveClass('canvas-empty muted')
  expect(document.querySelector('.canvas-empty-bee')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Collapse all' })).toBeNull()
})

test('a closed box of files keeps their line: one dashed line from the box to the agent handed them', async () => {
  const { measure, stage } = laidOut()
  const file = (id: string): Attachment => ({ id, conversation_id: 'c', message_id: 'u-r', frame_of: null, name: `${id}.md`, kind: 'text', mime: 'text/plain', size: 10, summary: '1 line', given_to: ['r'], shown_to: {}, keep_in_project: false, created_at: '2026-10-05T10:00:00Z' })
  const conv = convState({ runs: [run('r')], messages: [userMessage('r', 'read these')], agents: [agent('r')], attachments: ['a', 'b', 'c', 'd', 'e'].map(file) })
  render(<CanvasView state={conv} selectedId={null} onSelect={() => {}} />)
  await waitFor(() => expect(node('files:r')).not.toBeNull())
  measure()
  stage(1200)
  await waitFor(() => expect(document.querySelectorAll('.react-flow__edge.edge-handed')).toHaveLength(1))
  expect(document.querySelector('.react-flow__edge.edge-handed')?.getAttribute('data-id')).toMatch(/@files:r>agent:r$/)
})

test('findings handed out of a team’s frame to an agent outside it get their line, from under the frame', async () => {
  // (Live: "Fix the findings" opens a Coder outside the frame; only the Reviewer's card counted what it was handed.)
  const { measure, stage } = laidOut()
  const step = { id: 'review', name: 'Review', state: 'now' as const, round: 0, room: false, own_check: false, left_out: [], group: false }
  const conv = convState({
    conversation: {
      ...conversation,
      teams_mode: 'manual',
      teams: [{ team_id: 'web', recipe_id: null, no_recipe: false, picked_by: 'user', why: null, state: { run_id: 't', team: 'Web app', recipe: 'Review only', status: 'running', why: null, steps: [step], agents: ['rev'], ended_ready: false, passes: [{ part: 'review', agents: ['rev'] }] } }],
    },
    runs: [run('t')],
    messages: [userMessage('t', 'Review it')],
    agents: [agent('t'), agent('t', 'completed', { id: 'rev', role_name: 'Reviewer', parent_agent_id: 't', depth: 1 }), agent('t', 'running', { id: 'fix', role_name: 'Coder', parent_agent_id: 't', depth: 1 })],
    channelMessages: [{ id: 'f1', run_id: 't', from_agent_id: 'rev', to_agent_id: 'fix', kind: 'findings', content: '- one | kind: code | role: Coder', created_at: '2026-10-05T10:00:00Z' }],
  })
  // (Its label is measured with getBBox, which jsdom has none of.)
  Object.defineProperty(SVGElement.prototype, 'getBBox', { configurable: true, value: () => ({ x: 0, y: 0, width: 40, height: 10 }) })
  try {
    render(<CanvasView state={conv} selectedId={null} onSelect={() => {}} />)
    await waitFor(() => expect(node('agent:fix')).not.toBeNull())
    measure()
    stage(1200)
    await waitFor(() => expect(document.querySelector('.react-flow__edge[data-id="findings:f1"]')).not.toBeNull())
    expect(look('findings:f1')[1]).toBe('stroke: var(--warn); stroke-width: 2; stroke-dasharray: 8 3;')
  } finally {
    Reflect.deleteProperty(SVGElement.prototype, 'getBBox')
  }
})

test('a team’s frame is drawn behind, never dragged or picked; an agent picked dims it; Fold all and Open all fold every frame', async () => {
  const step = (id: string, name: string) => ({ id, name, state: 'now' as const, round: 0, room: false, own_check: false, left_out: [], group: false })
  const conv = convState({
    conversation: {
      ...conversation,
      teams_mode: 'manual',
      teams: [{ team_id: 'web', recipe_id: null, no_recipe: false, picked_by: 'user', why: null, state: { run_id: 't', team: 'Web app', recipe: 'Feature', status: 'running', why: null, steps: [step('spec', 'Spec'), step('build', 'Build')], agents: ['spec', 'coder'], ended_ready: false, passes: [{ part: 'spec', agents: ['spec'] }, { part: 'build', agents: ['coder'] }] } }],
    },
    runs: [run('t')],
    messages: [userMessage('t', 'Build it')],
    agents: [agent('t'), ...['spec', 'coder'].map(id => agent('t', 'running', { id, name: id, role_name: id, parent_agent_id: 't', depth: 1 }))],
  })
  const { rerender } = render(<CanvasView state={conv} selectedId={null} onSelect={() => {}} />)
  await waitFor(() => expect(node('team:t:web')).not.toBeNull())
  const frame = node('team:t:web')
  expect([frame?.classList.contains('draggable'), frame?.classList.contains('selectable'), frame?.style.zIndex]).toEqual([false, false, '-1'])
  expect(node('agent:coder')).toHaveClass('draggable selectable')
  rerender(<CanvasView state={conv} selectedId="agent:coder" onSelect={() => {}} />)
  await waitFor(() => expect(node('team:t:web')).toHaveClass('canvas-dim'))
  expect(node('agent:coder')).not.toHaveClass('canvas-faded')
  await userEvent.click(screen.getByRole('button', { name: 'Fold all' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Open all' })).toBeInTheDocument())
  expect(screen.getByRole('button', { name: 'Open Web app' })).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(screen.getByRole('button', { name: 'Open all' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Fold all' })).toBeInTheDocument())
  expect(screen.getByRole('button', { name: 'Fold Web app' })).toHaveAttribute('aria-expanded', 'true')
})

test('the box of what was said is titled by the talk line’s two, or by the agent picked', () => {
  const said = (id: string, from: string, to: string, kind: 'message' | 'reply', content: string) => ({ id, run_id: 'a', from_agent_id: from, to_agent_id: to, kind, content, created_at: '2026-10-05T10:00:00Z' })
  const talked = { ...state, channelMessages: [said('c1', 'a', 'kid', 'message', 'Check the tests too.'), said('c2', 'kid', 'a', 'reply', 'There are none.')] }
  const { rerender } = render(<CanvasView state={talked} onSelect={() => {}} turnId="a" selectedId={null} />)
  const title = () => document.querySelector('.canvas-said-title')?.textContent
  expect(title()).toBeUndefined()
  act(() => handed.at(-1)?.showTalk?.('agent:a>agent:kid'))
  expect(title()).toBe('Lead ↔ Reviewer')
  rerender(<CanvasView state={talked} onSelect={() => {}} turnId="a" selectedId="agent:kid" />)
  expect(title()).toBe('What Reviewer said and was told')
})

test('the user’s (6 Nov): talk between two agents of a team is drawn on an arc, as findings back are - in words, “💬 2 messages”, a click shows it', async () => {
  // (React Flow draws a line once its ends are measured.)
  const { measure, stage } = laidOut()
  const step = (id: string, name: string, group = false) => ({ id, name, state: 'now' as const, round: 0, room: false, own_check: false, left_out: [], group })
  const said = (id: string, from: string, to: string, kind: 'message' | 'reply', content: string) => ({ id, run_id: 't', from_agent_id: from, to_agent_id: to, kind, content, created_at: '2026-10-05T10:00:00Z' })
  const ids = ['spec', 'coder', 'tester', 'rev']
  const conv = convState({
    conversation: {
      ...conversation,
      teams_mode: 'manual',
      teams: [{ team_id: 'web', recipe_id: null, no_recipe: false, picked_by: 'user', why: null, state: { run_id: 't', team: 'Web app', recipe: 'Feature', status: 'running', why: null, steps: [step('spec', 'Spec'), step('build', 'Build'), step('check', 'Check', true)], agents: ids, ended_ready: false, passes: [{ part: 'spec', agents: ['spec'] }, { part: 'build', agents: ['coder'] }, { part: 'check', agents: ['tester', 'rev'] }] } }],
    },
    runs: [run('t')],
    messages: [userMessage('t', 'Build it')],
    agents: [agent('t'), ...ids.map(id => agent('t', 'running', { id, name: id, role_name: id, parent_agent_id: 't', depth: 1 }))],
    channelMessages: [said('c1', 'spec', 'rev', 'message', 'Is 0 right for []?'), said('c2', 'rev', 'spec', 'reply', 'Yes.')],
  })
  render(<CanvasView state={conv} selectedId={null} onSelect={() => {}} />)
  measure()
  stage(1200)
  const talk = await waitFor(() => {
    const line = document.querySelector('.react-flow__edge[data-id="talk:agent:spec>agent:rev"]')
    expect(line).not.toBeNull()
    return line!
  })
  // Out of the right of one and round, not a straight line between the two (a curve, `C`) - past the Coder between them.
  // Drawn from the Reviewer, the end further right, its arrow still points at the Reviewer, who was asked: at its start.
  const path = talk.querySelector('path')!
  expect(path.getAttribute('d')).toMatch(/ C /)
  expect(path.getAttribute('marker-start')).toMatch(/^url\(/)
  expect(path.getAttribute('marker-end')).toBeNull()
  const words = screen.getByRole('button', { name: /^(spec ↔ rev|rev ↔ spec): 2 messages, the last: Yes\.$/ })
  expect(words).toHaveTextContent('💬 2 messages')
  fireEvent.click(words)
  expect(screen.getByRole('region', { name: 'What was said' })).toHaveTextContent('Is 0 right for []?')
})
