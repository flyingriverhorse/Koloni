import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { when } from '../canvas/turns'
import { agent, assistantMessage, convState, run, userMessage } from '../test-fixtures'
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

test('Copy writes the answer’s markdown and says Copied', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  render(<AnswerActions message={answer} over />)
  await userEvent.click(screen.getByRole('button', { name: 'Copy' }))
  expect(writeText).toHaveBeenCalledWith('It is **done**: see `a.py`.')
  expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
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
