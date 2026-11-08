import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ChatPanel } from '../chat/ChatPanel'
import { VoiceSettings as VoiceSection } from './VoiceControls'
import type { ConvState } from '../state/applyEvent'
import { resetStoreForTests, useApp } from '../state/store'
import { agent, assistantMessage, convState, run, userMessage } from '../test-fixtures'
import { DEFAULTS, useVoice, type VoiceSettings } from './voice'

// Stand-ins for the browser's two objects: what is read aloud is written down, nothing is heard.
class Utterance {
  voice: unknown = null
  lang = ''
  rate = 1
  pitch = 1
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  text: string
  constructor(text: string) {
    this.text = text
  }
}
const VOICES = [
  // (A service's voice first, as Chrome lists them: the one used when none is chosen is the computer's own.)
  { voiceURI: 'google', name: 'Google US English', lang: 'en-US', localService: false },
  { voiceURI: 'ava', name: 'Ava', lang: 'en-US', localService: true },
  { voiceURI: 'yelda', name: 'Yelda', lang: 'tr-TR', localService: true },
  { voiceURI: 'google-de', name: 'Google Deutsch', lang: 'de-DE', localService: false },
]
const synth = {
  said: [] as string[],
  queue: [] as Utterance[],
  speak(utterance: Utterance) {
    this.said.push(utterance.text)
    this.queue.push(utterance)
  },
  cancel() {
    const cut = this.queue
    this.queue = []
    cut.forEach(utterance => utterance.onerror?.())
  },
  /** Everything waiting is read to its end. */
  finish() {
    const read = this.queue
    this.queue = []
    read.forEach(utterance => utterance.onend?.())
  },
  getVoices: () => VOICES,
  addEventListener() {},
  removeEventListener() {},
}
class Recognition {
  static last: Recognition | null = null
  lang = ''
  continuous = false
  interimResults = false
  onresult: ((event: { results: { transcript: string }[][] }) => void) | null = null
  onerror: ((event: { error: string }) => void) | null = null
  onend: (() => void) | null = null
  start() {
    Recognition.last = this
  }
  stop() {
    this.onend?.()
  }
  hear(...parts: string[]) {
    act(() => this.onresult?.({ results: parts.map(transcript => [{ transcript }]) }))
  }
}

let sent: Record<string, unknown>[] = []

function voice(change: Partial<VoiceSettings> = {}) {
  useVoice.setState({ ...DEFAULTS, ...change, speaking: null, stops: 0, fromStart: {} })
}

beforeEach(() => {
  localStorage.clear()
  resetStoreForTests()
  voice()
  sent = []
  synth.said = []
  synth.queue = []
  vi.stubGlobal('speechSynthesis', synth)
  vi.stubGlobal('SpeechSynthesisUtterance', Utterance)
  vi.stubGlobal('webkitSpeechRecognition', Recognition)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url.endsWith('/messages')) sent.push(JSON.parse(String(init.body)))
      return new Response(init?.method === 'POST' ? '{}' : '[]', { status: 200 })
    }),
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** A conversation with a finished turn in it, and `then` as it goes on. */
const opened = convState({ runs: [run('r0', 'completed')], messages: [userMessage('r0', 'hi'), assistantMessage('a0', 'r0', 'Hello there. Ask me.')], agents: [agent('r0', 'completed')] })
const going = (content: string, status: 'streaming' | 'complete' = 'streaming', over: { spoken?: string | null; run?: 'running' | 'completed' } = {}): ConvState => ({
  ...opened,
  runs: [...opened.runs, run('r1', over.run ?? 'running')],
  agents: [...opened.agents, agent('r1', over.run === 'completed' ? 'completed' : 'running')],
  messages: [...opened.messages, userMessage('r1', 'how is the total worked out?'), { ...assistantMessage('a1', 'r1', content, status), spoken: over.spoken ?? null }],
})
const show = (conv: ConvState) => act(() => useApp.setState({ conv }))

test('what is said into the mic is written into the message box where the cursor is, as it is heard, and nothing is sent', async () => {
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  const box = screen.getByLabelText<HTMLTextAreaElement>('Message')
  await userEvent.type(box, 'Please  thanks')
  box.setSelectionRange(7, 7)
  await userEvent.click(screen.getByRole('button', { name: 'Dictate' }))
  expect(screen.getByRole('button', { name: 'Dictate' })).toHaveAttribute('aria-pressed', 'true')
  Recognition.last!.hear('fix the')
  expect(box.value).toBe('Please fix the thanks')
  Recognition.last!.hear('fix the', ' greeting')
  expect(box.value).toBe('Please fix the greeting thanks')
  await userEvent.click(screen.getByRole('button', { name: 'Dictate' }))
  expect(screen.getByRole('button', { name: 'Dictate' })).toHaveAttribute('aria-pressed', 'false')
  expect(sent).toEqual([])
})

test('typing while dictating stops it: what was typed is not written over', async () => {
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  const box = screen.getByLabelText<HTMLTextAreaElement>('Message')
  await userEvent.click(screen.getByRole('button', { name: 'Dictate' }))
  const listening = Recognition.last!
  listening.hear('fix the')
  await userEvent.type(box, ' greeting')
  expect(screen.getByRole('button', { name: 'Dictate' })).toHaveAttribute('aria-pressed', 'false')
  listening.hear('fix the', ' something else')
  expect(box.value).toBe('fix the greeting')
})

test('a refused microphone is said beside it', async () => {
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  await userEvent.click(screen.getByRole('button', { name: 'Dictate' }))
  act(() => {
    Recognition.last!.onerror?.({ error: 'not-allowed' })
    Recognition.last!.onend?.()
  })
  expect(screen.getByRole('alert')).toHaveTextContent('The microphone was not allowed.')
})

test('with Auto-read on a short summary the message asks for a line to say, in the language and manner chosen; otherwise it does not', async () => {
  voice({ autoRead: true, mode: 'summary', language: 'tr-TR', style: ' kısa ve sıcak ' })
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  const write = (text: string) => userEvent.type(screen.getByLabelText('Message'), `${text}{Enter}`)
  await write('one')
  act(() => useVoice.getState().set({ mode: 'whole' }))
  await write('two')
  act(() => useVoice.getState().set({ autoRead: false, mode: 'summary' }))
  await write('three')
  // A tag the server would refuse (as a browser may give one) asks for nothing, and the message goes.
  act(() => useVoice.getState().set({ autoRead: true, language: 'tr_TR' }))
  await write('four')
  expect(sent.map(body => body.spoken)).toEqual([{ language: 'tr-TR', style: 'kısa ve sıcak' }, undefined, undefined, undefined])
})

test('Auto-read of the whole answer reads it as it is written, a sentence once it is finished, a code block by its lines; what was there before is not read', async () => {
  voice({ autoRead: true })
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  show(going('The total adds'))
  expect(synth.said).toEqual([])
  show(going('The total adds the tax once. It is'))
  expect(synth.said).toEqual(['The total adds the tax once.'])
  show(going('The total adds the tax once. It is twenty percent.\n\n```py\ntotal = subtotal * 1.2\n'))
  expect(synth.said).toEqual(['The total adds the tax once.'])
  show(going('The total adds the tax once. It is twenty percent.\n\n```py\ntotal = subtotal * 1.2\n```\nDone', 'complete'))
  expect(synth.said).toEqual(['The total adds the tax once.', 'It is twenty percent.', 'Code block, 1 line.', 'Done.'])
})

test('typing stops the reading, and what is still being written of that answer is not read after it', async () => {
  voice({ autoRead: true })
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  show(going('First one. Second'))
  expect(synth.said).toEqual(['First one.'])
  await userEvent.type(screen.getByLabelText('Message'), 'w')
  expect(synth.queue).toEqual([])
  show(going('First one. Second one. Third one.', 'complete'))
  expect(synth.said).toEqual(['First one.'])
})

test('while an answer still being written is read, its ■ stops it, and no more of it is read', async () => {
  voice({ autoRead: true })
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  show(going('First one. Second'))
  await userEvent.click(screen.getByRole('button', { name: 'Stop reading' }))
  expect(synth.queue).toEqual([])
  show(going('First one. Second one. Third one.', 'complete'))
  expect(synth.said).toEqual(['First one.'])
})

test('Auto-read of a short summary: at the turn’s end the Lead’s line is read, never its code; with no line, its first two sentences, and the line says so', async () => {
  voice({ autoRead: true, mode: 'summary' })
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  show(going('It adds the tax once.\n\n```py\nx = 1\n```'))
  show(going('It adds the tax once.\n\n```py\nx = 1\n```', 'complete', { spoken: 'Twenty percent, once.' }))
  expect(synth.said).toEqual([])
  show(going('It adds the tax once.\n\n```py\nx = 1\n```', 'complete', { spoken: 'Twenty percent, once.', run: 'completed' }))
  expect(synth.said).toEqual(['Twenty percent, once.'])
  expect(screen.getByText('Twenty percent, once.')).toHaveTextContent('Said aloud: Twenty percent, once.')
  // Stop reading, from the answer's own button.
  await userEvent.click(screen.getByRole('button', { name: 'Stop reading' }))
  expect(synth.queue).toEqual([])
  expect(screen.getAllByRole('button', { name: 'Read aloud' })).toHaveLength(2)

  // A turn whose Lead wrote no line to say.
  const without: ConvState = { ...opened, runs: [...opened.runs, run('r2', 'completed')], agents: [...opened.agents, agent('r2', 'completed')], messages: [...opened.messages, assistantMessage('a2', 'r2', '```py\nx = 1\n```\nFirst. Second. Third.')] }
  show(without)
  expect(synth.said.slice(-2)).toEqual(['First.', 'Second.'])
  expect(screen.getByText('Said aloud, read from the start of the answer:').parentElement).toHaveTextContent('Said aloud, read from the start of the answer: First. Second.')
  // Sending a message cuts it off.
  await userEvent.type(screen.getByLabelText('Message'), 'next{Enter}')
  expect(synth.queue).toEqual([])
})

test('🔊 on an answer reads all of it, its code as a code block; while it reads, ■ stops it; once read, it is 🔊 again', async () => {
  useApp.setState({ conv: going('Here is the code:\n```py\nx = 1\ny = 2\n```\nSee [the rule](https://example.com).', 'complete'), projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  await userEvent.click(screen.getAllByRole('button', { name: 'Read aloud' })[1])
  expect(synth.said).toEqual(['Here is the code.', 'Code block, 2 lines.', 'See the rule.'])
  expect(screen.getByRole('button', { name: 'Stop reading' })).toBeInTheDocument()
  act(() => synth.finish())
  expect(screen.queryByRole('button', { name: 'Stop reading' })).not.toBeInTheDocument()
})

test('the Voice panel lists the voices of the language chosen, says where speech goes, and is remembered in this browser', async () => {
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  const panel = screen.getByRole('region', { name: 'Voice' })
  expect(panel).toHaveTextContent('KOLONİ keeps no sound and sends none anywhere.')
  const options = () => Array.from(screen.getByRole<HTMLSelectElement>('combobox', { name: 'Voice' }).options).map(option => option.text)
  expect(panel).toHaveTextContent('Reading aloud uses this computer’s voices; a voice marked online sends what it reads to its maker.')
  expect(screen.getByRole('group', { name: 'Auto-read reads' })).toBeInTheDocument()
  expect(options()).toEqual(['The browser’s own', 'Google US English (online)', 'Ava'])
  await userEvent.selectOptions(screen.getByLabelText('Dictation language'), 'tr-TR')
  expect(options()).toEqual(['The browser’s own', 'Yelda'])
  await userEvent.click(screen.getByLabelText(/^Short summary/))
  expect(JSON.parse(localStorage.getItem('koloni-voice') ?? '{}')).toMatchObject({ language: 'tr-TR', mode: 'summary' })
  await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
  expect(synth.said).toEqual(['This is how the answers will sound.'])
})

test('a language of the browser’s own is offered with no voice of this computer’s for it, for dictation and the Lead’s line', async () => {
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['de-DE', 'en-US'])
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  await userEvent.selectOptions(screen.getByLabelText('Dictation language'), 'de-DE')
  expect(useVoice.getState().language).toBe('de-DE')
})

test('with no voice for the language nothing is read in another’s, and it says so', async () => {
  voice({ language: 'fr-FR', autoRead: true })
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  expect(screen.getByRole('button', { name: 'Auto-read' })).toHaveAccessibleDescription('No voice on this computer reads fr-FR.')
  // (Reached by the keyboard all the same, with its reason.)
  const button = screen.getByRole('button', { name: 'Read aloud' })
  expect(button).toHaveAttribute('aria-disabled', 'true')
  expect(button).toHaveAccessibleDescription('No voice on this computer reads fr-FR.')
  await userEvent.click(button)
  show(going('A whole sentence. ', 'complete'))
  expect(synth.said).toEqual([])
  expect(screen.getByRole('region', { name: 'Voice' })).toHaveTextContent('No voice on this computer reads fr-FR: nothing is read aloud in it.')
})

test('with no voice chosen the computer’s own reads; where a language has none of its own, the browser’s is marked online and the panel says so', async () => {
  useApp.setState({ conv: going('Read me.', 'complete'), projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  await userEvent.click(screen.getAllByRole('button', { name: 'Read aloud' })[1])
  expect((synth.queue[0].voice as { name: string }).name).toBe('Ava')

  act(() => useVoice.getState().set({ language: 'de-DE' }))
  const options = Array.from(screen.getByRole<HTMLSelectElement>('combobox', { name: 'Voice' }).options).map(option => option.text)
  expect(options).toEqual(['The browser’s own (online)', 'Google Deutsch (online)'])
  expect(screen.getByRole('region', { name: 'Voice' })).toHaveTextContent('No voice of this computer’s reads de-DE: every one here is online.')
})

test('where the browser cannot write down speech there is no microphone, and the panel says why', async () => {
  vi.stubGlobal('webkitSpeechRecognition', undefined)
  useApp.setState({ conv: opened, projectId: 'p' })
  render(<><ChatPanel /><VoiceSection /></>)
  expect(screen.queryByRole('button', { name: 'Dictate' })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Voice' })).toHaveTextContent('This browser cannot write down what you say, so there is no microphone.')
  expect(screen.getByRole('region', { name: 'Voice' })).toHaveTextContent('Speech recognition is your browser’s')
})
