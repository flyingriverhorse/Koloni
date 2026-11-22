import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { when } from '../canvas/turns'
import { agent, assistantMessage, convState, run, userMessage } from '../test-fixtures'
import { useApp } from '../state/store'
import { DEFAULTS, useVoice } from '../voice/voice'
import { MessageList } from './MessageList'
import { AnswerActions, TurnCard } from './TurnCard'

const AT = '2026-10-26T10:42:00'
const answer = assistantMessage('m', 'r', 'It is **done**: see `a.py`.')

// The browser's speech as far as Read aloud asks: this computer has a voice for the language.
beforeEach(() => {
  useVoice.setState({ ...DEFAULTS, speaking: null, stops: 0, fromStart: {} })
  const voices = [{ voiceURI: 'ava', name: 'Ava', lang: 'en-US', localService: true }]
  vi.stubGlobal('speechSynthesis', { getVoices: () => voices, speak() {}, cancel() {}, addEventListener() {}, removeEventListener() {} })
  vi.stubGlobal('SpeechSynthesisUtterance', class {})
})
afterEach(() => {
  vi.unstubAllGlobals()
  useVoice.setState({ speaking: null })
})

const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn() }

test('the card names who answered, its model and the time of its last message; a card that waits says so in the time’s place', () => {
  const state = convState({ runs: [run('r')], agents: [agent('r')], messages: [userMessage('r', 'go'), { ...answer, created_at: AT }] })
  const card = (waits: boolean) => (
    <TurnCard state={state} run={run('r')} lead={agent('r')} answer={answer} summary={null} waits={waits}>
      the work
    </TurnCard>
  )
  const { container, rerender } = render(card(false))
  expect(screen.getByRole('article', { name: `Orchestrator, ${when(AT)}` })).toHaveTextContent(`OOrchestratorqwen${when(AT)}the work`)
  expect(container.querySelector('.turn-avatar')).toHaveAttribute('aria-hidden', 'true')
  rerender(card(true))
  expect(screen.getByRole('article', { name: 'Orchestrator, waits for you' })).toHaveTextContent('Orchestratorqwenwaits for youthe work')
  expect(container.querySelector('time')).toBeNull()
})

test('a Lead whose model Copilot’s fusion picked says so in its head, with Copilot’s own reason under it; another says nothing', () => {
  const why = 'Copilot Fusion selected GPT-6 Luna since the task has low complexity.'
  const picked = agent('r', 'running', {
    provider_name: 'Copilot',
    model_id: 'gpt-6-luna',
    model_from: 'fusion',
    effort_note: `high → none: fusion takes no level. Copilot's fusion picked gpt-6-luna: “${why}”`,
  })
  const card = (lead: typeof picked) => (
    <TurnCard state={convState({ runs: [run('r')], agents: [lead] })} run={run('r')} lead={lead} answer={undefined} summary={null} waits={false}>
      the work
    </TurnCard>
  )
  const { container, rerender } = render(card(picked))
  expect(container.querySelector('.turn-model')).toHaveTextContent(/^fusion → gpt-6-luna$/)
  // (Its own words, whole in its tooltip: a long one is cut on its line.)
  const said = container.querySelector('.turn-why')
  expect(said).toHaveTextContent(new RegExp(`^${why}$`))
  expect(said).toHaveAttribute('title', why)
  rerender(card(agent('r')))
  expect(container.querySelector('.turn-model')).toHaveTextContent(/^qwen$/)
  expect(container.querySelector('.turn-why')).toBeNull()
  // A later model said with no reason of its own is not given the one before (review, 21 Nov).
  rerender(card({ ...picked, model_id: 'gpt-7' }))
  expect(container.querySelector('.turn-model')).toHaveTextContent(/^fusion → gpt-7$/)
  expect(container.querySelector('.turn-why')).toBeNull()
})

test('the turn’s name opens its Lead’s window, by pointer or keyboard: where Tell reaches an agent at work', async () => {
  useApp.setState({ agentWindowId: null })
  const lead = agent('lead-1', 'running', { run_id: 'r' })
  render(
    <TurnCard state={convState({ runs: [run('r')], agents: [lead] })} run={run('r')} lead={lead} answer={undefined} summary={null} waits={false}>
      the work
    </TurnCard>,
  )
  const name = screen.getByRole('button', { name: 'Orchestrator' })
  expect(name).toHaveAttribute('title', 'Open its window')
  await userEvent.tab()
  expect(name).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  expect(useApp.getState().agentWindowId).toBe('lead-1')
  useApp.setState({ agentWindowId: null })
  await userEvent.click(name)
  expect(useApp.getState().agentWindowId).toBe('lead-1')
  useApp.setState({ agentWindowId: null })
})

test('the foot holds Copy and Read aloud first, what it did at its right', () => {
  const state = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [userMessage('r', 'go'), answer] })
  const { container } = render(
    <TurnCard state={state} run={run('r', 'completed')} lead={agent('r', 'completed')} answer={answer} summary={<button type="button">What it did</button>} waits={false}>
      the work
    </TurnCard>,
  )
  const foot = container.querySelector('footer.turn-foot')!
  expect(foot.firstElementChild).toHaveClass('turn-actions')
  expect(foot.lastElementChild).toHaveAccessibleName('What it did')
})

test('the Checked section stands in the foot under the answer once the turn is over', () => {
  const rows = [{ kind: 'tests', state: 'passed' as const, text: 'Tests passed: pytest -q - 4 passed', command: 'pytest -q', guessed: false, started_at: null }]
  const checked = { ...assistantMessage('k', 'r', '✓ Tests passed: pytest -q - 4 passed'), role: 'checked' as const, agent_id: null, checked: rows, created_at: '2026-10-26T11:00:00' }
  const state = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [userMessage('r', 'go'), { ...answer, created_at: AT }, checked] })
  const card = (over: boolean) => (
    <TurnCard state={state} run={run('r', over ? 'completed' : 'running')} lead={agent('r')} answer={answer} summary={over ? <span>did</span> : null} waits={false} checked={checked} wordsEnd>
      the answer
    </TurnCard>
  )
  const { container, rerender } = render(card(false))
  expect(screen.queryByRole('region', { name: 'Checked' })).toBeNull()
  rerender(card(true))
  expect(screen.getByRole('region', { name: 'Checked' })).toHaveTextContent('Tests passed: pytest -q - 4 passed')
  const text = container.textContent ?? ''
  expect(text.indexOf('the answer')).toBeLessThan(text.indexOf('Tests passed'))
  // (Its time is still the answer's; and its foot stands under the section, not laid over the answer's last line.)
  const turn = screen.getByRole('article', { name: `Orchestrator, ${when(AT)}` })
  expect(turn).not.toHaveClass('turn-words-end')
})

test('a night’s closing line, put on the turn before it, leaves that turn’s time as it was', () => {
  // (KOLONİ puts "While you were away: …" on the conversation's last turn, hours after its answer.)
  const night = { ...assistantMessage('w', 'r', 'While you were away: 2 done - on the canvas'), role: 'away' as const, agent_id: null, created_at: '2026-10-27T07:10:00' }
  const state = convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed')], messages: [userMessage('r', 'go'), { ...answer, created_at: AT }, night] })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByRole('article', { name: `Orchestrator, ${when(AT)}` })).toBeInTheDocument()
})

test('Copy writes the answer’s markdown and says Copied, once', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  const { container } = render(<AnswerActions message={answer} over />)
  const copy = screen.getByRole('button', { name: 'Copy' })
  await userEvent.click(copy)
  expect(writeText).toHaveBeenCalledWith('It is **done**: see `a.py`.')
  // Said by a live region of its own, not the button's: its words changing back to "Copy" as the focus leaves are not said.
  expect(await screen.findByRole('button', { name: 'Copied' })).toBe(copy)
  const said = container.querySelector('[aria-live="polite"]')
  expect(said).not.toBe(copy)
  expect(said).toHaveTextContent(/^Copied$/)
  await userEvent.tab()
  expect(copy).toHaveAccessibleName('Copy')
  expect(said).toBeEmptyDOMElement()
})

test('Copy and Read aloud are reachable with the keyboard', async () => {
  render(<AnswerActions message={answer} over />)
  await userEvent.tab()
  expect(screen.getByRole('button', { name: 'Copy' })).toHaveFocus()
  await userEvent.tab()
  expect(screen.getByRole('button', { name: 'Read aloud' })).toHaveFocus()
})

test('an answer still being written has no Copy; while it is read aloud its ■ stays', () => {
  useVoice.setState({ speaking: 'm' })
  render(<AnswerActions message={{ ...answer, status: 'streaming' }} over />)
  expect(screen.queryByRole('button', { name: 'Copy' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Stop reading' })).toBeInTheDocument()
})

test('while a step’s words are read and the next step is written, the ■ stays in the card’s foot; Copy waits for the turn’s end', () => {
  // (Auto-read, Whole answer: the step before is still heard; the reading moves on once the next one's first sentence is queued.)
  useVoice.setState({ speaking: 'x' })
  const state = convState({
    runs: [run('r')],
    agents: [agent('r')],
    messages: [userMessage('r', 'go'), assistantMessage('x', 'r', 'I’ll read a.py first.'), assistantMessage('y', 'r', 'It greets', 'streaming')],
  })
  render(<MessageList {...handlers} state={state} />)
  const card = screen.getByRole('article', { name: /^Orchestrator, / })
  expect(within(card).getByRole('button', { name: 'Stop reading' }).closest('footer')).toHaveClass('turn-foot')
  expect(screen.queryByRole('button', { name: 'Copy' })).toBeNull()
})

test('the ■ the keyboard is on stays the same button, focused, when the turn ends', () => {
  useVoice.setState({ speaking: 'm' })
  const state = (status: 'running' | 'completed') =>
    convState({ runs: [run('r', status)], agents: [agent('r', status)], messages: [userMessage('r', 'go'), assistantMessage('m', 'r', 'Done.')] })
  const { rerender } = render(<MessageList {...handlers} state={state('running')} />)
  const stop = screen.getByRole('button', { name: 'Stop reading' })
  stop.focus()
  rerender(<MessageList {...handlers} state={state('completed')} />)
  expect(screen.getByRole('button', { name: 'Stop reading' })).toBe(stop)
  expect(stop).toHaveFocus()
})
