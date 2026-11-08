// Slice 32e: answers read aloud by Gemini's voices. The app is stood in for by a fetch that keeps
// a key as the server would (and never gives it back), the sound by an Audio that only notes what
// it was given; the browser's own reader is a stand-in too, for when Gemini is put aside.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ChatPanel } from '../chat/ChatPanel'
import { VoiceSettings } from './VoiceControls'
import type { ConvState } from '../state/applyEvent'
import { resetStoreForTests, useApp } from '../state/store'
import { agent, assistantMessage, convState, run, userMessage } from '../test-fixtures'
import { DEFAULTS, read, stopReading, useVoice } from './voice'

const KEY = 'AIza-test-key-0123456789'

const server = {
  key: null as string | null,
  model: 'gemini-3.8-flash-tts',
  voice: 'Kore',
  style: '',
  note: null as string | null,
  put: [] as unknown[],
  said: [] as { text: string; style?: string }[],
  fail: null as null | { status: number; detail: unknown },
}
const shown = () => ({ has_key: server.key !== null, model: server.model, voice: server.voice, style: server.style, note: null })
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

class FakeAudio {
  static all: FakeAudio[] = []
  static refuse: Error | null = null
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  paused = true
  playbackRate = 1
  src: string
  constructor(src: string) {
    this.src = src
    FakeAudio.all.push(this)
  }
  play() {
    if (FakeAudio.refuse) return Promise.reject(FakeAudio.refuse)
    this.paused = false
    return Promise.resolve()
  }
  pause() {
    this.paused = true
  }
}
const synth = {
  said: [] as string[],
  speak: (u: { text: string }) => synth.said.push(u.text),
  cancel() {},
  getVoices: () => [{ voiceURI: 'ava', name: 'Ava', lang: 'en-US', localService: true }],
  addEventListener() {},
  removeEventListener() {},
}
const revoked: string[] = []
const tick = () => act(() => new Promise(resolve => setTimeout(resolve, 20)))

beforeEach(() => {
  localStorage.clear()
  resetStoreForTests()
  stopReading()
  useVoice.setState({ ...DEFAULTS, speaking: null, stops: 0, fromStart: {}, saved: null, failed: null, fallback: false })
  Object.assign(server, { key: null, style: '', note: null, put: [], said: [], fail: null })
  FakeAudio.all = []
  FakeAudio.refuse = null
  synth.said = []
  revoked.length = 0
  let made = 0
  Object.assign(URL, { createObjectURL: () => `blob:sound-${++made}`, revokeObjectURL: (url: string) => revoked.push(url) })
  vi.stubGlobal('Audio', FakeAudio)
  vi.stubGlobal('speechSynthesis', synth)
  vi.stubGlobal('SpeechSynthesisUtterance', function (this: { text: string }, text: string) {
    this.text = text
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      if (url === '/api/voice/gemini' && init?.method === 'PUT') {
        server.put.push(body)
        if (body.api_key !== undefined) server.key = body.api_key || null
        Object.assign(server, { model: body.model ?? server.model, voice: body.voice ?? server.voice, style: body.style ?? server.style })
        return json({ ...shown(), note: server.note })
      }
      if (url === '/api/voice/gemini') return json(shown())
      if (url === '/api/voice/gemini/say') {
        server.said.push(body)
        if (server.fail) return json({ detail: server.fail.detail }, server.fail.status)
        return new Response(new Blob(['RIFF'], { type: 'audio/wav' }), { status: 200 })
      }
      return json(init?.method === 'POST' ? {} : [])
    }),
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
})

const opened = convState({ runs: [run('r0', 'completed')], messages: [userMessage('r0', 'hi'), assistantMessage('a0', 'r0', 'First one. Second one.')], agents: [agent('r0', 'completed')] })
const going = (content: string, status: 'streaming' | 'complete' = 'streaming'): ConvState => ({
  ...opened,
  runs: [...opened.runs, run('r1', 'running')],
  agents: [...opened.agents, agent('r1', 'running')],
  messages: [...opened.messages, userMessage('r1', 'go on'), assistantMessage('a1', 'r1', content, status)],
})
const ended = (n: number) => act(async () => FakeAudio.all[n].onended?.())
const saidTexts = () => server.said.map(body => body.text)

async function openPanel() {
  return screen.getByRole('region', { name: 'Voice' })
}

/** The chat open with a key saved; Gemini reads. */
async function withKey(conv: ConvState = opened) {
  server.key = KEY
  useApp.setState({ conv, projectId: 'p' })
  render(<><ChatPanel /><VoiceSettings /></>)
  await waitFor(() => expect(useVoice.getState().saved?.has_key).toBe(true))
}

test('with no key the Browser tab is first, Gemini’s settings are off, and the browser reads', async () => {
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSettings /></>)
  const panel = await openPanel()
  expect(screen.getByRole('tab', { name: 'Browser' })).toHaveAttribute('aria-selected', 'true')
  expect(panel).toHaveTextContent('Reading aloud uses this computer’s voices')
  await userEvent.click(screen.getByRole('tab', { name: 'Gemini' }))
  expect(screen.getByRole('tabpanel', { name: 'Gemini' })).toHaveTextContent('Text read with Gemini is sent to Google. On the free tier Google may use it to improve its products; on a paid key it does not.')
  const reads = screen.getByRole('checkbox', { name: 'Read aloud with Gemini' })
  expect(reads).toBeDisabled()
  expect(reads).toHaveAccessibleDescription('With no key saved, this computer’s voices read.')
  expect(screen.getByLabelText('Model')).toBeDisabled()
  expect(screen.getByRole('combobox', { name: 'Voice' })).toBeDisabled()
  expect(screen.getByLabelText('How Gemini says it')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled()
  await userEvent.keyboard('{Escape}{Escape}')
  await userEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
  expect(synth.said).toEqual(['First one.', 'Second one.'])
  expect(server.said).toEqual([])
})

test('the key is given once and never shown again; saved, Gemini reads and is the first tab; removed, it is gone', async () => {
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSettings /></>)
  await openPanel()
  await userEvent.click(screen.getByRole('tab', { name: 'Gemini' }))
  const field = screen.getByLabelText('Gemini API key')
  expect(field).toHaveAttribute('type', 'password')
  await userEvent.type(field, ` ${KEY} `)
  await userEvent.click(screen.getByRole('button', { name: 'Save key' }))
  expect(await screen.findByText('A key is saved.')).toBeInTheDocument()
  expect(server.put).toEqual([{ api_key: KEY }])
  expect(document.body.innerHTML).not.toContain(KEY)
  const reads = screen.getByRole('checkbox', { name: 'Read aloud with Gemini' })
  expect(reads).toBeChecked()
  expect(reads).toHaveAccessibleDescription('When off, this computer’s voices read.')
  expect(screen.getByRole('region', { name: 'Voice' })).toHaveTextContent('Reading aloud is Gemini’s. Text read with Gemini is sent to Google. On the free tier Google may use it to improve its products; on a paid key it does not. KOLONİ keeps no sound.')
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Voice' }), 'Puck')
  await userEvent.selectOptions(screen.getByLabelText('Model'), 'Flash-Lite TTS')
  expect(server.put.slice(1)).toEqual([{ voice: 'Puck' }, { model: 'gemini-3.8-flash-lite-tts' }])
  expect(screen.getAllByRole('option').filter(o => o.closest('#gemini-voice'))).toHaveLength(30)

  await userEvent.click(screen.getByRole('button', { name: 'Remove key' }))
  expect(await screen.findByLabelText('Gemini API key')).toHaveValue('')
  expect(server.put.at(-1)).toEqual({ api_key: '' })
  expect(server.key).toBeNull()
})

test('a key that could not be checked now is saved, and the panel says so', async () => {
  server.note = 'The key is saved, but it could not be checked now: Google was not reached.'
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSettings /></>)
  await openPanel()
  await userEvent.click(screen.getByRole('tab', { name: 'Gemini' }))
  await userEvent.type(screen.getByLabelText('Gemini API key'), KEY)
  await userEvent.click(screen.getByRole('button', { name: 'Save key' }))
  // (the message box's own status line, slice 85a, is empty)
  expect(await screen.findByText(/could not be checked now/)).toHaveAttribute('role', 'status')
})

test('Gemini’s own manner is its own field, kept on the server; the Lead’s manner is not sent to it', async () => {
  useVoice.setState({ style: 'short and friendly' })
  await withKey()
  await openPanel()
  const manner = screen.getByLabelText('How Gemini says it')
  expect(manner).toHaveAttribute('maxLength', '200')
  await userEvent.type(manner, 'calm, like a radio host')
  await userEvent.tab()
  expect(server.put).toEqual([{ style: 'calm, like a radio host' }])
  await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
  await waitFor(() => expect(server.said).toEqual([{ text: 'This is how the answers will sound.' }]))
})

test('a whole answer read by Gemini goes as one request; Stop stops the sound and lets it go', async () => {
  await withKey()
  await userEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
  await waitFor(() => expect(FakeAudio.all).toHaveLength(1))
  expect(saidTexts()).toEqual(['First one. Second one.'])
  expect(FakeAudio.all[0].paused).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'Stop reading' }))
  expect(FakeAudio.all[0].paused).toBe(true)
  expect(revoked).toEqual(['blob:sound-1'])
  expect(screen.getAllByRole('button', { name: 'Read aloud' }).length).toBeGreaterThan(0)
  expect(synth.said).toEqual([])
})

test("Gemini's sound plays at the voice's rate, set in its own tab too", async () => {
  await withKey()
  const panel = await openPanel()
  const rate = within(panel).getByRole('slider', { name: 'Rate' })
  fireEvent.change(rate, { target: { value: '1.5' } })
  expect(useVoice.getState().rate).toBe(1.5)
  await userEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
  await waitFor(() => expect(FakeAudio.all).toHaveLength(1))
  expect(FakeAudio.all[0].playbackRate).toBe(1.5)
})

test('a text longer than the app takes at once is cut: sentences are joined up to 4000 characters, a longer one is cut', async () => {
  await withKey()
  const sentence = `${'word '.repeat(299)}end.` // 1499 characters
  act(() => read('long', `${sentence} ${sentence} ${sentence}`))
  await waitFor(() => expect(server.said).toHaveLength(2))
  expect(saidTexts()).toEqual([`${sentence} ${sentence}`, sentence])
  act(() => read('longer', `${'x'.repeat(9000)}.`))
  await waitFor(() => expect(server.said.length).toBeGreaterThan(2))
  expect(saidTexts().every(text => text.length <= 4000)).toBe(true)
  expect(saidTexts()[2]).toBe('x'.repeat(4000))
})

test('Auto-read asks for the next sentence only once the one before it plays; a stop after the first has not spent the rest', async () => {
  useVoice.setState({ autoRead: true })
  await withKey()
  act(() => useApp.setState({ conv: going('One here. Two here. Three here. Four') }))
  await waitFor(() => expect(FakeAudio.all).toHaveLength(1))
  // The first plays: the second is asked for, the third not yet.
  await tick()
  expect(saidTexts()).toEqual(['One here.', 'Two here.'])
  await ended(0)
  await waitFor(() => expect(FakeAudio.all).toHaveLength(2))
  await tick()
  expect(saidTexts()).toEqual(['One here.', 'Two here.', 'Three here.'])
  await userEvent.click(screen.getByRole('button', { name: 'Stop reading' }))
  await tick()
  expect(saidTexts()).toEqual(['One here.', 'Two here.', 'Three here.'])
  expect(FakeAudio.all).toHaveLength(2)
})

test('when Gemini cannot read it says why on one line and the browser reads the rest, for now only; the button makes it so and reads it again', async () => {
  server.fail = { status: 502, detail: 'Gemini could not read it: Google answered 429: Resource exhausted' }
  await withKey()
  await userEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Gemini could not read it: Google answered 429: Resource exhausted')
  expect(server.said).toHaveLength(1)
  expect(FakeAudio.all).toEqual([])
  // The browser reads what Gemini could not; Gemini is still the choice kept in this browser.
  expect(synth.said).toEqual(['First one.', 'Second one.'])
  expect(JSON.parse(localStorage.getItem('koloni-voice') ?? '{}').gemini).not.toBe(false)
  // What comes next is the browser's too, this time.
  act(() => read('next', 'Next one.', true))
  expect(synth.said.at(-1)).toBe('Next one.')
  expect(server.said).toHaveLength(1)

  synth.said = []
  await userEvent.click(screen.getByRole('button', { name: 'Use the browser’s voice' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(JSON.parse(localStorage.getItem('koloni-voice') ?? '{}')).toMatchObject({ gemini: false })
  expect(synth.said).toEqual(['First one.', 'Second one.'])
})

test('a browser that will not play sound before a click says so plainly', async () => {
  FakeAudio.refuse = Object.assign(new Error('play() failed'), { name: 'NotAllowedError' })
  await withKey()
  await userEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('The browser plays sound only after you click on the page.')
})

test('a text the app does not take is said in a sentence, not by its status', async () => {
  server.fail = { status: 422, detail: [{ loc: ['body', 'text'], msg: 'too long', type: 'string_too_long' }] }
  await withKey()
  await userEvent.click(screen.getByRole('button', { name: 'Read aloud' }))
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Gemini could not read it: the app did not take the text.')
  expect(alert).not.toHaveTextContent('422')
})
