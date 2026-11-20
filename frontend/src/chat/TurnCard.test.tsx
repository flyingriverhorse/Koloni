import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { when } from '../canvas/turns'
import { agent, assistantMessage, convState, run, userMessage } from '../test-fixtures'
import { DEFAULTS, useVoice } from '../voice/voice'
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
afterEach(() => vi.unstubAllGlobals())

test('the card names who answered, its model and the time of its last message; a card that waits says so in the time’s place', () => {
  const state = convState({ runs: [run('r')], agents: [agent('r')], messages: [userMessage('r', 'go'), { ...answer, created_at: AT }] })
  const card = (waits: boolean) => (
    <TurnCard state={state} run={run('r')} lead={agent('r')} answer={answer} foot={null} waits={waits}>
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
  render(<AnswerActions message={answer} />)
  await userEvent.click(screen.getByRole('button', { name: 'Copy' }))
  expect(writeText).toHaveBeenCalledWith('It is **done**: see `a.py`.')
  expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
})

test('Copy and Read aloud are reachable with the keyboard', async () => {
  render(<AnswerActions message={answer} />)
  await userEvent.tab()
  expect(screen.getByRole('button', { name: 'Copy' })).toHaveFocus()
  await userEvent.tab()
  expect(screen.getByRole('button', { name: 'Read aloud' })).toHaveFocus()
})

test('an answer still being written has no Copy; while it is read aloud its ■ stays', () => {
  useVoice.setState({ speaking: 'm' })
  render(<AnswerActions message={{ ...answer, status: 'streaming' }} />)
  expect(screen.queryByRole('button', { name: 'Copy' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Stop reading' })).toBeInTheDocument()
})
