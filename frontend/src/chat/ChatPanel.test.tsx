import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Provider, Role } from '../api/types'
import { resetStoreForTests, useApp } from '../state/store'
import {
  agent,
  assistantMessage,
  command,
  convState,
  question,
  run,
  toolCall,
  topic,
  userMessage,
} from '../test-fixtures'
import { ChatPanel } from './ChatPanel'

/** Two topics of the user's - the newer is "docs" - and a trigger's. */
const state = convState({
  topics: [
    topic('ta', 'Fix the greeting'),
    topic('tn', 'Look the project over', { trigger_id: 'tr' }),
    topic('tb', 'Write the docs'),
  ],
  runs: [
    run('a1', 'completed', { topic_id: 'ta' }),
    run('n1', 'completed', { topic_id: 'tn', unattended: true, trigger_id: 'tr', trigger_name: 'Nightly look' }),
    run('b1', 'completed', { topic_id: 'tb' }),
  ],
  messages: [
    userMessage('a1', 'Fix the greeting'),
    { ...userMessage('n1', 'Look the project over'), id: 't-n1', role: 'trigger' },
    userMessage('b1', 'Write the docs'),
  ],
  agents: [agent('a1', 'completed'), agent('n1', 'completed'), agent('b1', 'completed')],
})

let sent: unknown[] = []

beforeEach(() => {
  localStorage.clear()
  resetStoreForTests()
  sent = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url.endsWith('/messages')) sent.push(JSON.parse(String(init.body)))
      return new Response(init?.method === 'POST' ? '{}' : '[]', { status: 200 })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

// (No "Continuing" line: "New topic" beside the model says in its tooltip where the message goes.)
const toggle = () => screen.getByRole('button', { name: 'New topic' })
const goesOn = (title: string) =>
  expect(toggle()).toHaveAttribute('title', expect.stringContaining(`goes on with ${title}:`))
const startsOne = () => expect(screen.queryByRole('button', { name: 'New topic' })).not.toBeInTheDocument()
const write = (text: string) => userEvent.type(screen.getByLabelText('Message'), `${text}{Enter}`)

test('a message goes to the topic the line names, by its id: the one the user was last in', async () => {
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  goesOn('Write the docs')
  await write('with examples')
  expect(sent).toEqual([{ content: 'with examples', topic_id: 'tb' }])
})

test('with a turn of an earlier topic picked, the line names that topic and the message goes there', async () => {
  useApp.setState({ conv: state, projectId: 'p', turnId: 'a1' })
  render(<ChatPanel />)
  goesOn('Fix the greeting')
  await write('now in Turkish')
  expect(sent).toEqual([{ content: 'now in Turkish', topic_id: 'ta' }])
})

test('with a trigger’s turn on screen the message still goes on with the user’s own topic, and the line says so', async () => {
  useApp.setState({ conv: state, projectId: 'p', turnId: 'n1' })
  render(<ChatPanel />)
  goesOn('Write the docs')
  expect(screen.getByRole('button', { name: 'Write into Nightly look instead' })).toBeInTheDocument()
  await write('with examples')
  expect(sent).toEqual([{ content: 'with examples', topic_id: 'tb' }])
})

test('only after "Write into … instead" does the message go into the trigger’s topic; the choice is over once it is sent', async () => {
  useApp.setState({ conv: state, projectId: 'p', turnId: 'n1' })
  render(<ChatPanel />)
  await userEvent.click(screen.getByRole('button', { name: 'Write into Nightly look instead' }))
  goesOn('Nightly look, a trigger’s topic')
  expect(screen.queryByRole('button', { name: /^Write into/ })).not.toBeInTheDocument()
  // there is a way back, by the name of the topic it goes back to
  await userEvent.click(screen.getByRole('button', { name: 'Continue Write the docs instead' }))
  goesOn('Write the docs')
  await userEvent.click(screen.getByRole('button', { name: 'Write into Nightly look instead' }))
  await write('what did you find?')
  expect(sent).toEqual([{ content: 'what did you find?', topic_id: 'tn' }])
  // sent: the next one goes on with the user's own topic again
  await waitFor(() => goesOn('Write the docs'))
  await write('and now the docs')
  expect(sent[1]).toEqual({ content: 'and now the docs', topic_id: 'tb' })
})

test('the choice to write into a trigger’s topic is over when another turn is selected', async () => {
  useApp.setState({ conv: state, projectId: 'p', turnId: 'n1' })
  render(<ChatPanel />)
  await userEvent.click(screen.getByRole('button', { name: 'Write into Nightly look instead' }))
  goesOn('Nightly look, a trigger’s topic')
  act(() => useApp.getState().showTurn('a1'))
  goesOn('Fix the greeting')
  // back on the trigger's turn it has to be chosen again
  act(() => useApp.getState().showTurn('n1'))
  goesOn('Write the docs')
  await write('more')
  expect(sent).toEqual([{ content: 'more', topic_id: 'tb' }])
})

test('with only a trigger’s turns the message starts the user’s first topic, unless they choose the trigger’s', async () => {
  const only = convState({
    topics: state.topics.slice(1, 2),
    runs: state.runs.slice(1, 2),
    messages: state.messages.slice(1, 2),
    agents: state.agents.slice(1, 2),
  })
  // (nothing picked: the trigger's turn is the one on screen, the conversation having no other)
  useApp.setState({ conv: only, projectId: 'p' })
  render(<ChatPanel />)
  startsOne()
  await write('hello')
  expect(sent).toEqual([{ content: 'hello', new_topic: true }])
  await userEvent.click(screen.getByRole('button', { name: 'Write into Nightly look instead' }))
  goesOn('Nightly look, a trigger’s topic')
  // the way back is a new topic: there is none of the user's to name
  await userEvent.click(screen.getByRole('button', { name: 'Start a new topic instead' }))
  startsOne()
  await userEvent.click(screen.getByRole('button', { name: 'Write into Nightly look instead' }))
  await write('what did you find?')
  expect(sent[1]).toEqual({ content: 'what did you find?', topic_id: 'tn' })
})

test('"New topic" sends the message as a new topic, whatever turn is picked', async () => {
  useApp.setState({ conv: state, projectId: 'p', turnId: 'a1' })
  render(<ChatPanel />)
  await userEvent.click(screen.getByRole('button', { name: 'New topic' }))
  await write('something else')
  expect(sent).toEqual([{ content: 'something else', new_topic: true }])
})

test('in a conversation with no turn yet nothing is said about topics, and the message is sent plainly', async () => {
  useApp.setState({ conv: convState(), projectId: 'p' })
  render(<ChatPanel />)
  expect(screen.queryByRole('group', { name: 'Topic to go on with' })).not.toBeInTheDocument()
  await write('hello')
  expect(sent).toEqual([{ content: 'hello' }])
})

test('a draft not sent is there again when the chat is hidden and shown, and after the page changes (slice 36)', async () => {
  useApp.setState({ conv: state, projectId: 'p' })
  const { unmount } = render(<ChatPanel />)
  await userEvent.type(screen.getByLabelText('Message'), 'not yet')
  await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
  // (closed, the chat is a small box: the draft is in its one line)
  expect(screen.queryByRole('tab', { name: 'Chat' })).not.toBeInTheDocument()
  expect(screen.getByLabelText('Message')).toHaveValue('not yet')
  await userEvent.click(screen.getByRole('button', { name: /^Chat/ }))
  expect(screen.getByLabelText('Message')).toHaveValue('not yet')
  unmount() // another page in the app takes the chat's place
  render(<ChatPanel />)
  expect(screen.getByLabelText('Message')).toHaveValue('not yet')
  await userEvent.type(screen.getByLabelText('Message'), ' now{Enter}')
  await waitFor(() => expect(screen.getByLabelText('Message')).toHaveValue(''))
  expect(sent).toEqual([{ content: 'not yet now', topic_id: 'tb' }])
})

// --- the box that floats over the canvas (slice 38b) ---------------------------------------

const closed = () => localStorage.setItem('koloni-chat-open', '0')
const opener = () => screen.getByRole('button', { name: /^Chat/ })

test('closed, the chat is a small box: a line of the latest, and a one-line message box under it', () => {
  closed()
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  expect(opener()).toHaveTextContent(/^Chat · Write the docs$/)
  expect(opener()).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByLabelText('Message')).toBeVisible()
  expect(screen.getByLabelText('Message')).toHaveAttribute('rows', '1')
  // the rest of the chat is not there to be reached: its tabs, the model, Send
  expect(screen.queryByRole('tab', { name: 'Chat' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Permission level:/ })).not.toBeInTheDocument()
})

test('closed, what is typed in the small box and sent with Enter goes as from the open chat - to the same topic - and the chat stays closed', async () => {
  closed()
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  await userEvent.type(screen.getByLabelText('Message'), 'with examples{Enter}')
  expect(sent).toEqual([{ content: 'with examples', topic_id: 'tb' }])
  await waitFor(() => expect(screen.getByLabelText('Message')).toHaveValue(''))
  expect(opener()).toHaveAttribute('aria-expanded', 'false')
  expect(localStorage.getItem('koloni-chat-open')).toBe('0')
  // one line: Shift+Enter makes no new line, and sends nothing
  await userEvent.type(screen.getByLabelText('Message'), 'one{Shift>}{Enter}{/Shift}')
  expect(screen.getByLabelText('Message')).toHaveValue('one')
  expect(sent).toHaveLength(1)
})

test('closed, the small box says where a message goes when that is not the usual: a new topic, a trigger’s topic', async () => {
  useApp.setState({ conv: state, projectId: 'p', turnId: 'n1' })
  render(<ChatPanel />)
  await userEvent.click(screen.getByRole('button', { name: 'Write into Nightly look instead' }))
  await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
  expect(screen.getByRole('region', { name: 'Chat' })).toHaveTextContent('Goes to Nightly look, a trigger’s topic')
  await userEvent.click(opener())
  await userEvent.click(screen.getByRole('button', { name: 'Continue Write the docs instead' }))
  await userEvent.click(screen.getByRole('button', { name: 'New topic' }))
  await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
  expect(screen.getByRole('region', { name: 'Chat' })).toHaveTextContent('Goes to a new topic')
})

test('closed, the small box says nothing of where a message goes while it goes on as usual', () => {
  closed()
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  expect(screen.getByRole('region', { name: 'Chat' })).not.toHaveTextContent('Goes to')
})

test('a click on the line (its ▴) opens the chat itself, with what was typed in the small box', async () => {
  closed()
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  await userEvent.type(screen.getByLabelText('Message'), 'half a thought')
  await userEvent.click(opener())
  expect(screen.getByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-selected', 'true')
  // B-142: its content is the tab's panel, named by it.
  expect(screen.getByRole('tabpanel', { name: 'Chat' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-controls', 'chat-tabpanel')
  expect(screen.getByLabelText('Message')).toHaveValue('half a thought')
  expect(screen.getByLabelText('Message')).toHaveFocus()
  expect(screen.getByRole('button', { name: 'Send' })).toBeVisible()
})

test('while a turn is at work the line says who works', () => {
  closed()
  const working = convState({
    runs: [run('r', 'running')],
    messages: [userMessage('r', 'Fix it')],
    agents: [agent('r', 'running')],
  })
  useApp.setState({ conv: working, projectId: 'p' })
  render(<ChatPanel />)
  expect(opener()).toHaveTextContent(/^Chat · Orchestrator is working$/)
})

test('closed, the line says in honey how many cards wait for you', () => {
  closed()
  const asking = convState({
    runs: [run('r', 'waiting_approval')],
    messages: [userMessage('r', 'Fix it')],
    agents: [agent('r', 'waiting')],
    questions: [question('q', 'r')],
    commands: [command('k', 'r', { status: 'proposed' })],
  })
  useApp.setState({ conv: asking, projectId: 'p' })
  const { unmount } = render(<ChatPanel />)
  const waits = screen.getByText('2 wait for you')
  expect(opener()).toContainElement(waits)
  expect(waits).toHaveClass('chat-waits')
  unmount()
  useApp.setState({ conv: { ...asking, commands: [] } })
  render(<ChatPanel />)
  expect(opener()).toHaveTextContent('1 waits for you')
})

test('a click opens it upward with the focus in the message box; Esc or its ▾ closes it, and the focus goes back to the line', async () => {
  closed()
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  await userEvent.click(opener())
  expect(screen.getByLabelText('Message')).toHaveFocus()
  expect(localStorage.getItem('koloni-chat-open')).toBe('1')
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('tab', { name: 'Chat' })).not.toBeInTheDocument()
  expect(opener()).toHaveFocus()
  expect(localStorage.getItem('koloni-chat-open')).toBe('0')
  await userEvent.keyboard('{Enter}')
  await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
  expect(opener()).toHaveFocus()
})

// --- the open chat is a column at the stage's left edge (0.1.4) -----------------------------------

const chatBox = () => screen.getByRole('region', { name: 'Chat' })
const widthEdge = () => screen.getByRole('separator', { name: 'Chat width' })
/** The width the column is drawn at: what ChatPanel writes on the stage (base.css clamps it). */
const drawnAt = () => chatBox().parentElement!.style.getPropertyValue('--chat-open-w')

/** What jsdom does not lay out: a stage 1400 by 800 at the page's left, and the chat in it. */
function laidOut() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const [x, y, width, height] = this.matches('.chat') ? [0, 0, 420, 800] : [0, 0, 1400, 800]
    return { x, y, width, height, left: x, top: y, right: x + width, bottom: y + height, toJSON: () => ({}) } as DOMRect
  })
}
afterEach(() => vi.restoreAllMocks())

test('the open chat is as tall as the stage and starts at its left edge; closed, it is the one-line box in the corner as before', async () => {
  const style = document.createElement('style')
  style.textContent = readFileSync('src/theme/base.css', 'utf8') // (run from frontend/)
  document.head.append(style)
  try {
    useApp.setState({ conv: state, projectId: 'p' })
    render(<ChatPanel />)
    const open = getComputedStyle(chatBox())
    expect([open.top, open.left, open.bottom]).toEqual(['0px', '0px', 'var(--timeline-h, 0px)'])
    // Nothing moves it: no grip, no handle.
    expect(chatBox().querySelector('.move-grip')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Move chat' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
    const closed = getComputedStyle(chatBox())
    expect([closed.top, closed.left]).toEqual(['auto', '14px'])
    expect(screen.queryByRole('separator', { name: 'Chat width' })).not.toBeInTheDocument()
  } finally {
    style.remove()
  }
})

test('its right edge widens it, by pointer and by the arrow keys, between 340 and 760 px, and the width is kept', async () => {
  laidOut()
  useApp.setState({ conv: state, projectId: 'p' })
  const { unmount } = render(<ChatPanel />)
  const edge = widthEdge()
  expect(edge).toHaveAttribute('aria-orientation', 'vertical')
  expect(edge).toHaveAttribute('aria-valuenow', '420')
  expect(edge).toHaveAttribute('aria-valuemin', '340')
  // (a stage 1400 wide: 60% of it is more than 760)
  expect(edge).toHaveAttribute('aria-valuemax', '760')
  expect(drawnAt()).toBe('420px')
  edge.focus()
  await userEvent.keyboard('{ArrowRight}{ArrowRight}{ArrowRight}')
  expect(edge).toHaveAttribute('aria-valuenow', '480')
  expect(drawnAt()).toBe('480px')
  expect(localStorage.getItem('koloni-chat-width')).toBe('480')
  await userEvent.keyboard('{ArrowRight}'.repeat(20))
  expect(edge).toHaveAttribute('aria-valuenow', '760')
  await userEvent.keyboard('{ArrowLeft}'.repeat(30))
  expect(edge).toHaveAttribute('aria-valuenow', '340')
  // Dragged: as wide as from the stage's left edge to the pointer; let go, the pointer moving on changes nothing.
  fireEvent.pointerDown(edge, { pointerId: 1, button: 0, clientX: 340 })
  fireEvent.pointerMove(edge, { pointerId: 1, clientX: 512 })
  fireEvent.pointerUp(edge, { pointerId: 1, clientX: 512 })
  fireEvent.pointerMove(edge, { pointerId: 1, clientX: 900 })
  expect(edge).toHaveAttribute('aria-valuenow', '512')
  expect(drawnAt()).toBe('512px')
  expect(localStorage.getItem('koloni-chat-width')).toBe('512')
  // (a drag the browser calls off ends there too)
  fireEvent.pointerDown(edge, { pointerId: 2, button: 0, clientX: 512 })
  fireEvent.lostPointerCapture(edge, { pointerId: 2 })
  fireEvent.pointerMove(edge, { pointerId: 2, clientX: 700 })
  expect(edge).toHaveAttribute('aria-valuenow', '512')
  unmount()
  render(<ChatPanel />)
  expect(widthEdge()).toHaveAttribute('aria-valuenow', '512')
})

test('its edge is reached with Tab, the open chat’s first stop; Esc on it still hides the chat', async () => {
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  await userEvent.tab()
  expect(widthEdge()).toHaveFocus()
  await userEvent.keyboard('{ArrowRight}')
  expect(widthEdge()).toHaveAttribute('aria-valuenow', '440')
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('separator', { name: 'Chat width' })).not.toBeInTheDocument()
  expect(opener()).toHaveFocus()
})

test('on a narrow stage it is at most 60% of it, and never under 340 px', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const width = this.matches('.chat') ? 420 : 700
    return { x: 0, y: 0, width, height: 800, left: 0, top: 0, right: width, bottom: 800, toJSON: () => ({}) } as DOMRect
  })
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  expect(widthEdge()).toHaveAttribute('aria-valuemax', '420')
  widthEdge().focus()
  await userEvent.keyboard('{ArrowRight}{ArrowRight}')
  expect(widthEdge()).toHaveAttribute('aria-valuenow', '420')
})

test('a width kept from a wider stage, drawn in full once the stage has grown, is stepped from what is drawn', async () => {
  localStorage.setItem('koloni-chat-width', '600')
  let stage = 700
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const width = this.matches('.chat') ? 420 : stage
    return { x: 0, y: 0, width, height: 800, left: 0, top: 0, right: width, bottom: 800, toJSON: () => ({}) } as DOMRect
  })
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  expect(widthEdge()).toHaveAttribute('aria-valuenow', '420')
  // The window made bigger: the stage's CSS draws the kept 600 px, and an arrow widens it from there - not from 420.
  stage = 1400
  widthEdge().focus()
  await userEvent.keyboard('{ArrowRight}')
  expect(widthEdge()).toHaveAttribute('aria-valuenow', '620')
})

test('with the browser’s storage closed the chat is open at its default width, and still changes', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('closed')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('closed')
  })
  try {
    useApp.setState({ conv: state, projectId: 'p' })
    render(<ChatPanel />)
    expect(widthEdge()).toHaveAttribute('aria-valuenow', '420')
    widthEdge().focus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(widthEdge()).toHaveAttribute('aria-valuenow', '400')
    expect(drawnAt()).toBe('400px')
  } finally {
    vi.restoreAllMocks()
  }
})

test('under the message box: the model, the level, ⚙ Chat and Send; More holds Work together and Compare (Voice is The app’s, in Settings)', async () => {
  const local = {
    id: 'p1',
    name: 'Local',
    kind: 'openai_compat',
    base_url: 'http://x/v1',
    default_model: 'm',
    mode: null,
  } as Provider
  const lead = {
    id: 'Lead',
    name: 'Lead',
    description: '',
    instructions: '',
    tools: [],
    builtin: true,
    provider_id: null,
    model_id: null,
    mcp: [],
    created_at: 't',
    updated_at: 't',
  } as unknown as Role
  useApp.setState({ conv: state, projectId: 'p', providers: [local], roles: [lead] })
  render(<ChatPanel />)
  expect(screen.getByRole('button', { name: 'Model: Local · m' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Permission level: Ask before changes' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  const more = screen.getByRole('button', { name: 'More' })
  // a plain disclosure: what it opens is no menu
  expect(more).not.toHaveAttribute('aria-haspopup')
  expect(more).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('button', { name: 'Sub-agents' })).not.toBeInTheDocument()
  await userEvent.click(more)
  expect(more).toHaveAttribute('aria-expanded', 'true')
  // (The sub-agents' settings and the rules are the project's, in Settings - tek-ev: a link there.)
  expect(screen.queryByRole('button', { name: 'Sub-agents' })).not.toBeInTheDocument()
  const names = ['Work together…', 'Compare…']
  for (const name of names) expect(screen.getByRole('button', { name })).toBeVisible()
  // in that order, all in the one place More opens
  const held = Array.from(document.getElementById(more.getAttribute('aria-controls')!)!.querySelectorAll('button')).map(
    b => b.textContent,
  )
  expect(held).toEqual(names)
  // Esc closes More - and only More: the chat stays open - and the focus goes back to it
  await userEvent.keyboard('{Escape}')
  expect(more).toHaveAttribute('aria-expanded', 'false')
  expect(more).toHaveFocus()
  expect(screen.getByLabelText('Message')).toBeInTheDocument()
  // ⚙ Chat: the link asks for Settings › This project › Runs without asking, and folds the sheet.
  const sheet = screen.getByRole('button', { name: 'This chat’s settings' })
  await userEvent.click(sheet)
  await userEvent.click(
    within(screen.getByRole('dialog', { name: 'This chat' })).getByRole('button', { name: '0 run without asking →' }),
  )
  expect(useApp.getState().settingsAsked).toEqual({ section: 'rules', n: 1 })
  expect(sheet).toHaveAttribute('aria-expanded', 'false')
})

test('Esc in a panel opened from More closes that panel only; the next one closes More', async () => {
  const local = {
    id: 'p1',
    name: 'Local',
    kind: 'openai_compat',
    base_url: 'http://x/v1',
    default_model: 'm',
    mode: null,
  } as Provider
  useApp.setState({ conv: state, projectId: 'p', providers: [local] })
  render(<ChatPanel />)
  const more = screen.getByRole('button', { name: 'More' })
  await userEvent.click(more)
  await userEvent.click(screen.getByRole('button', { name: 'Compare…' }))
  expect(screen.getByRole('form', { name: 'Compare two models' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('form', { name: 'Compare two models' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Compare…' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(more).toHaveFocus()
  expect(screen.getByLabelText('Message')).toBeInTheDocument()
})

test('the number on the closed line is what the Lead and agents said since the chat was last open, not your own; opened, it is gone (spec 38 §2)', async () => {
  // (met closed, what is there counts as read: no number)
  closed()
  useApp.setState({ conv: state, projectId: 'p' })
  render(<ChatPanel />)
  expect(opener()).toHaveAccessibleName(/^Chat\s*Write the docs$/)
  // two replies and one of your own come while it is closed
  const later = (more: typeof state.messages) =>
    act(() =>
      useApp.setState({
        conv: { ...useApp.getState().conv!, messages: [...useApp.getState().conv!.messages, ...more] },
      }),
    )
  later([
    assistantMessage('m1', 'b1', 'Done.'),
    { ...assistantMessage('m2', 'b1', 'Also this.'), role: 'agent' },
    { ...userMessage('b1', 'thanks'), id: 'u2' },
  ])
  expect(opener()).toHaveAccessibleName(/^Chat\s*2 unread\s*thanks$/)
  expect(screen.getByText('2 unread')).toHaveClass('chat-unread')
  // opened, all is read; closed again, nothing until the next reply
  await userEvent.click(opener())
  await userEvent.click(screen.getByRole('button', { name: 'Hide chat' }))
  expect(opener()).not.toHaveTextContent('unread')
  later([assistantMessage('m3', 'b1', 'One more.')])
  expect(opener()).toHaveTextContent(/^Chat · 1 unread · One more\.$/)
})

/** A turn whose lead asks the user a question, in the chat. */
const asking = convState({
  runs: [run('r', 'waiting_approval')],
  messages: [userMessage('r', 'Fix it'), assistantMessage('m', 'r', 'One thing first.')],
  agents: [agent('r', 'waiting')],
  toolCalls: [toolCall('1', 'r', 'ask_user', 'running', '{"question":"Which greeting?"}')],
  questions: [question('q', 'r')],
})

test('what is typed in the chat is still there after Esc closed it and it is opened again', async () => {
  useApp.setState({ conv: asking, projectId: 'p' })
  render(<ChatPanel />)
  await userEvent.type(screen.getByLabelText('Your answer'), 'the short one')
  await userEvent.keyboard('{Escape}')
  expect(screen.getByLabelText('Your answer')).not.toBeVisible()
  // closed, nothing hidden in it is reached by Tab: from the line, the small box's message box, then out
  expect(opener()).toHaveFocus()
  await userEvent.tab()
  expect(screen.getByLabelText('Message')).toHaveFocus()
  await userEvent.tab()
  expect(screen.getByRole('region', { name: 'Chat' })).not.toContainElement(document.activeElement as HTMLElement)
  await userEvent.click(opener())
  expect(screen.getByLabelText('Your answer')).toHaveValue('the short one')
})

test('opened from its line while a card waits, the chat shows the tab the card is on', async () => {
  closed()
  useApp.setState({ conv: asking, projectId: 'p', chatTab: 'Notes' })
  render(<ChatPanel />)
  await userEvent.click(opener())
  expect(screen.getByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByLabelText('Your answer')).toBeVisible()
})

test('tek-ev §1: no Ready for you tab - its cards stay in the chat, and the panel has the list', () => {
  useApp.setState({ conv: asking, projectId: 'p' })
  render(<ChatPanel />)
  expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual(['Chat', 'Talk', 'Notes'])
  expect(screen.getByLabelText('Your answer')).toBeVisible()
})

test('tek-ev decision 2: "N more wait elsewhere" only while something waits outside this chat; Open → opens the panel', async () => {
  useApp.setState({ conv: asking, projectId: 'p' })
  const { rerender } = render(<ChatPanel />)
  // (This chat's own question is in the chat itself: no line for it.)
  expect(screen.queryByText(/more waits? elsewhere/)).toBeNull()
  const proposed = {
    id: 't1',
    title: 'Rate-limit login',
    status: 'proposed',
    not_in: false,
    pending: null,
    conversation_id: null,
  }
  act(() => useApp.setState({ backlog: [proposed, { ...proposed, id: 't2' }] as never }))
  rerender(<ChatPanel />)
  // (0.1.5: quiet words under the box, not a line of its own over it.)
  const waits = screen.getByRole('button', { name: 'Open Ready for you: 2 more wait elsewhere' })
  expect(waits.closest('.composer-below')).not.toBeNull()
  expect(document.querySelector('.chat .ready-line')).toBeNull()
  await userEvent.click(waits)
  expect(useApp.getState().readyPanel.open).toBe(true)
})

test('closed, the small box still says that commands run on this machine without asking, in Full auto', () => {
  closed()
  const auto = { ...state, conversation: { ...state.conversation, permission_mode: 'full_auto' as const } }
  useApp.setState({
    conv: auto,
    projectId: 'p',
    projects: [{ id: 'p', root_path: 'C:/work/koloni', exec_location: 'host' } as never],
  })
  render(<ChatPanel />)
  expect(screen.getByRole('note')).toHaveTextContent('Commands run on this machine without asking.')
  expect(screen.getByRole('note')).toBeVisible()
})
