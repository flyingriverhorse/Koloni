import { Microphone, SpeakerHigh, Stop, X } from '@phosphor-icons/react'
import { type FormEvent, useEffect, useId, useState, useSyncExternalStore } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { api, errorText } from '../api/client'
import type { GeminiVoice, Message } from '../api/types'
import { engine } from './engine'
import { cannotRead, geminiOn, read, readAnswer, reader, stopReading, useVoice } from './voice'

const HEARD = 'Speech recognition is your browser’s: in Chrome and Edge what you say is sent to Google’s or Microsoft’s service to be written down.'
const KEPT = 'KOLONİ keeps no sound and sends none anywhere.'
const PRIVACY = `${HEARD} Reading aloud uses this computer’s voices; a voice marked online sends what it reads to its maker. ${KEPT}`
const GEMINI_PRIVACY = 'Text read with Gemini is sent to Google. On the free tier Google may use it to improve its products; on a paid key it does not.'
// From Google's page (ai.google.dev/gemini-api/docs/speech-generation, 18 October 2026); the server checks the same names (app/speech.py).
const GEMINI_MODELS = [
  ['gemini-3.8-flash-tts', 'Flash TTS'],
  ['gemini-3.8-flash-lite-tts', 'Flash-Lite TTS'],
] as const
const GEMINI_VOICES = 'Zephyr Puck Charon Kore Fenrir Leda Orus Aoede Callirrhoe Autonoe Enceladus Iapetus Umbriel Algieba Despina Erinome Algenib Rasalgethi Laomedeia Achernar Alnilam Schedar Gacrux Pulcherrima Achird Zubenelgenubi Vindemiatrix Sadachbia Sadaltager Sulafat'.split(' ')
const SAMPLE = 'This is how the answers will sound.'
// shortcut: the sample is in English whatever the language; upgrade to a sample per language if one is asked for.

// The voices' version: one more each time the browser's list changes (Chrome fills it after the page has loaded).
let version = 0
const subscribe = (listener: () => void) =>
  engine.onVoices(() => {
    version += 1
    listener()
  })

/** The browser's voices that speak `language` (all without one), as they are now. */
function useVoices(language?: string) {
  useSyncExternalStore(subscribe, () => version)
  return engine.voices(language)
}

/** 🔊 over an answer of the Lead's: reads it all aloud; ■ while it reads - Auto-read's too, while it is still written. */
export function ReadAloud({ id, content, written }: { id: string; content: string; written: boolean }) {
  const speaking = useVoice(s => s.speaking === id)
  const reason = useId()
  useVoices() // (what can be read changes with the voices)
  useVoice(geminiOn) // (and with the reader)
  if (!reader().canSpeak || (!written && !speaking)) return null
  const why = cannotRead()
  return (
    <button
      type="button"
      className="icon-btn read-aloud"
      aria-label={speaking ? 'Stop reading' : 'Read aloud'}
      title={why ?? (speaking ? 'Stop reading' : 'Read aloud')}
      // (Focusable all the same, with its reason: a disabled button says nothing of why.)
      aria-disabled={why !== null}
      aria-describedby={why ? reason : undefined}
      onClick={() => (speaking ? stopReading() : why === null && readAnswer(id, content))}
    >
      {speaking ? <Stop size={14} weight="fill" /> : <SpeakerHigh size={14} />}
      {why && (
        <span id={reason} className="visually-hidden">
          {why}
        </span>
      )}
    </button>
  )
}

/** Under an answer: what was said aloud of it - the Lead's own line, or its first sentences, said so. */
export function SaidAloud({ message }: { message: Message }) {
  const fromStart = useVoice(s => s.fromStart[message.id])
  const said = message.spoken ?? fromStart
  if (!said) return null
  return (
    <div className="msg-said">
      <span className="muted">{message.spoken ? 'Said aloud: ' : 'Said aloud, read from the start of the answer: '}</span>
      {said}
    </div>
  )
}

/** Beside the message box: the Lead's answers read aloud as they come, or not. */
export function AutoRead() {
  const on = useVoice(s => s.autoRead)
  const mode = useVoice(s => s.mode)
  const about = useId()
  useVoices()
  useVoice(geminiOn)
  if (!reader().canSpeak) return null
  const what = mode === 'whole' ? 'the whole answer, as it is written' : 'a short summary, when the work ends'
  const says = cannotRead() ?? (on ? `Auto-read is on: ${what}.` : 'Auto-read is off: answers are read from their 🔊 button.')
  return (
    <button
      type="button"
      className="icon-btn composer-auto-read"
      aria-label="Auto-read"
      aria-pressed={on}
      aria-describedby={about}
      title={says}
      onClick={() => {
        if (on) stopReading()
        useVoice.getState().set({ autoRead: !on })
      }}
    >
      <SpeakerHigh size={15} weight={on ? 'fill' : 'regular'} />
      <span id={about} className="visually-hidden">
        {says}
      </span>
    </button>
  )
}

/** Beside the message box: why Gemini could not read (the browser reads on, for now), and the browser's voice for good. */
export function ReadFailed() {
  const failed = useVoice(s => s.failed)
  // (Offered only where it can read: never in another language's voice.)
  const browser = useVoice(s => engine.voices(s.language).length > 0)
  if (!failed) return null
  const dismiss = () => useVoice.setState({ failed: null })
  return (
    <div role="alert" className="alert voice-failed">
      {failed.why}
      {browser && (
        <button
          type="button"
          className="btn btn-small"
          onClick={() => {
            useVoice.getState().set({ gemini: false })
            read(failed.id, failed.text)
          }}
        >
          Use the browser’s voice
        </button>
      )}
      <button type="button" className="icon-btn" aria-label="Dismiss" title="Dismiss" onClick={dismiss}>
        <X size={12} />
      </button>
    </div>
  )
}

/**
 * The microphone: what is said is written into the message box where the cursor is, as it is
 * heard. Nothing is sent by itself. Pressed again, once the browser stops, or once the user
 * types, it stops.
 */
export function Dictate({ onStart, onText, onError }: { onStart: () => { before: string; after: string }; onText: (text: string) => void; onError: (why: string | null) => void }) {
  const [listening, setListening] = useState(false)
  useEffect(() => () => engine.stop(), [])
  if (!engine.canListen) return null
  function start() {
    stopReading()
    onError(null)
    const { before, after } = onStart()
    const gap = before && !/\s$/.test(before) ? ' ' : ''
    setListening(true)
    engine.listen(
      useVoice.getState().language,
      heard => onText(before + gap + heard.trim() + (after && !/^\s/.test(after) ? ' ' : '') + after),
      why => {
        setListening(false)
        onError(why)
      },
    )
  }
  return (
    <button
      type="button"
      className="icon-btn composer-mic"
      aria-label="Dictate"
      aria-pressed={listening}
      title={listening ? 'Listening: press to stop' : 'Dictate: what you say is written into the box, and nothing is sent'}
      onClick={() => (listening ? engine.stop() : start())}
    >
      <Microphone size={15} weight={listening ? 'fill' : 'regular'} />
    </button>
  )
}

/** Settings › The app › Voice (this browser's, for every chat): how answers are read aloud and in what voice, and where speech goes. */
export function VoiceSettings() {
  // (Its settings only: what is being read changes at every key, and is none of its business.)
  const settings = useVoice(useShallow(s => ({ mode: s.mode, language: s.language, voice: s.voice, rate: s.rate, pitch: s.pitch, style: s.style, set: s.set })))
  const { set } = settings
  const gemini = useVoice(geminiOn)
  // Gemini's tab first while it reads.
  const [tab, setTab] = useState<'Browser' | 'Gemini' | null>(null)
  const shown = tab ?? (gemini ? 'Gemini' : 'Browser')
  // The browser's own languages too: dictation and the Lead's line need no voice to read them.
  const languages = [...new Set([settings.language, 'en-US', ...navigator.languages, ...useVoices().map(voice => voice.lang)])].sort()
  const voices = useVoices(settings.language)
  // With no voice of this computer's for the language, the browser's own is a service's.
  const online = voices.length > 0 && !voices.some(voice => voice.local)
  return (
    <section aria-label="Voice" className="voice-settings">
      <h2>Voice</h2>
      <p className="choice-note">This browser’s, for every chat: kept here, not on the server. Dictate and Read aloud stay beside the message box.</p>
      <div className="voice-panel">
          <fieldset className="voice-modes">
            <legend className="kicker">Auto-read reads</legend>
            {(
              [
                ['whole', 'Whole answer', 'Sentence by sentence, as it is written'],
                ['summary', 'Short summary', 'A sentence or two the Orchestrator adds to be said, read when the work ends'],
              ] as const
            ).map(([value, label, note]) => (
              <label key={value} className="choice" htmlFor={`voice-${value}`}>
                <input id={`voice-${value}`} type="radio" name="voice-mode" checked={settings.mode === value} onChange={() => set({ mode: value })} />
                <span>
                  {label}
                  <span className="choice-note">{note}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className="voice-fields">
            <label htmlFor="voice-language">Dictation language</label>
            <select id="voice-language" className="input" value={settings.language} onChange={e => set({ language: e.target.value, voice: null })}>
              {languages.map(lang => (
                <option key={lang}>{lang}</option>
              ))}
            </select>
          </div>
          <div className="tabs voice-tabs" role="tablist" aria-label="Read aloud with">
            {(['Browser', 'Gemini'] as const).map(name => (
              <button key={name} id={`voice-tab-${name}`} type="button" role="tab" aria-selected={shown === name} aria-controls="voice-tab" className="tab" onClick={() => setTab(name)}>
                {name}
              </button>
            ))}
          </div>
          <div id="voice-tab" role="tabpanel" aria-labelledby={`voice-tab-${shown}`} className="voice-tab">
            {shown === 'Gemini' ? <GeminiTab /> : <BrowserTab settings={settings} voices={voices} online={online} gemini={gemini} />}
          </div>
          <label className="voice-style" htmlFor="voice-style">
            How the Orchestrator speaks
            <textarea id="voice-style" className="input" rows={2} maxLength={300} value={settings.style} placeholder="short and friendly" onChange={e => set({ style: e.target.value })} />
            <span className="choice-note">Sent with your message when Auto-read reads a short summary.</span>
          </label>
          {!engine.canListen && <div className="muted cmd-approval-note">This browser cannot write down what you say, so there is no microphone.</div>}
          {!engine.canSpeak && !gemini && <div className="muted cmd-approval-note">This browser cannot read aloud.</div>}
          <div className="muted cmd-approval-note">{gemini ? `${HEARD} Reading aloud is Gemini’s. ${GEMINI_PRIVACY} KOLONİ keeps no sound.` : PRIVACY}</div>
      </div>
    </section>
  )
}

/** The browser's own reading: its voice, rate and pitch, what it lacks for the language, and a preview. */
function BrowserTab({ settings, voices, online, gemini }: { settings: Pick<ReturnType<typeof useVoice.getState>, 'voice' | 'rate' | 'pitch' | 'language' | 'set'>; voices: ReturnType<typeof useVoices>; online: boolean; gemini: boolean }) {
  return (
    <>
      <div className="voice-fields">
        <label htmlFor="voice-voice">Voice</label>
        <select id="voice-voice" className="input" value={settings.voice ?? ''} disabled={voices.length === 0} onChange={e => settings.set({ voice: e.target.value || null })}>
          <option value="">{online ? 'The browser’s own (online)' : 'The browser’s own'}</option>
          {voices.map(voice => (
            <option key={voice.uri} value={voice.uri}>
              {voice.local ? voice.name : `${voice.name} (online)`}
            </option>
          ))}
        </select>
        <label htmlFor="voice-rate">Rate</label>
        <input id="voice-rate" type="range" min={0.5} max={2} step={0.1} value={settings.rate} onChange={e => settings.set({ rate: Number(e.target.value) })} />
        <label htmlFor="voice-pitch">Pitch</label>
        <input id="voice-pitch" type="range" min={0} max={2} step={0.1} value={settings.pitch} onChange={e => settings.set({ pitch: Number(e.target.value) })} />
      </div>
      {engine.canSpeak && voices.length === 0 && (
        <div role="note" className="composer-warning">
          No voice on this computer reads {settings.language}: nothing is read aloud in it.
        </div>
      )}
      {online && (
        <div role="note" className="composer-warning">
          No voice of this computer’s reads {settings.language}: every one here is online.
        </div>
      )}
      {gemini && <div className="muted cmd-approval-note">Gemini reads while it is on: turn it off in its tab to hear these voices.</div>}
      <button type="button" className="btn btn-small" disabled={gemini || cannotRead() !== null} onClick={() => read('preview', SAMPLE)}>
        <SpeakerHigh size={13} />
        Preview
      </button>
    </>
  )
}

/** The Gemini tab: the key (given once, never shown again), the model and voice, and where the text goes. */
function GeminiTab() {
  const saved = useVoice(s => s.saved)
  const on = useVoice(s => s.gemini)
  const fallback = useVoice(s => s.fallback)
  const rate = useVoice(s => s.rate)
  const setVoice = useVoice(s => s.set)
  const [key, setKey] = useState('')
  const [manner, setManner] = useState(saved?.style ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const has = saved?.has_key === true
  async function put(change: { api_key?: string; model?: string; voice?: string; style?: string }) {
    setBusy(true)
    setError(null)
    try {
      // (A key saved is tried again, whatever went wrong before.)
      useVoice.setState({ saved: await api.put<GeminiVoice>('/voice/gemini', change), ...(change.api_key && { fallback: false }) })
      return true
    } catch (err) {
      setError(errorText(err))
      return false
    } finally {
      setBusy(false)
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (await put({ api_key: key.trim() })) setKey('')
  }
  return (
    <>
      {has ? (
        <div className="voice-key">
          A key is saved.
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            onClick={() => {
              stopReading()
              void put({ api_key: '' })
            }}
          >
            Remove key
          </button>
        </div>
      ) : (
        <form className="voice-key" onSubmit={save}>
          <label htmlFor="gemini-key">Gemini API key</label>
          {/* Write-only: once saved it stays on the server, and the page never sees it again. */}
          <input id="gemini-key" className="input" type="password" autoComplete="off" spellCheck={false} placeholder="From Google AI Studio" value={key} onChange={e => setKey(e.target.value)} />
          <button type="submit" className="btn btn-small" disabled={busy || !key.trim()}>
            Save key
          </button>
        </form>
      )}
      {saved?.note && (
        <div role="status" className="composer-warning">
          {saved.note}
        </div>
      )}
      <label className="choice" htmlFor="gemini-on">
        <input
          id="gemini-on"
          type="checkbox"
          checked={on && has}
          disabled={!has}
          aria-describedby="gemini-on-note"
          onChange={e => {
            stopReading()
            useVoice.setState({ fallback: false })
            useVoice.getState().set({ gemini: e.target.checked })
          }}
        />
        <span>Read aloud with Gemini</span>
      </label>
      <span id="gemini-on-note" className="choice-note">
        {has ? 'When off, this computer’s voices read.' : 'With no key saved, this computer’s voices read.'}
      </span>
      {has && on && fallback && <div className="muted cmd-approval-note">Gemini could not read the last time: this computer’s voices read until you preview it again.</div>}
      <div className="voice-fields">
        <label htmlFor="gemini-model">Model</label>
        <select id="gemini-model" className="input" value={saved?.model ?? GEMINI_MODELS[0][0]} disabled={!has || busy} onChange={e => void put({ model: e.target.value })}>
          {GEMINI_MODELS.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <label htmlFor="gemini-voice">Voice</label>
        <select id="gemini-voice" className="input" value={saved?.voice ?? 'Kore'} disabled={!has || busy} onChange={e => void put({ voice: e.target.value })}>
          {GEMINI_VOICES.map(name => (
            <option key={name}>{name}</option>
          ))}
        </select>
        {/* The same rate as the browser's voices: played faster or slower here, nothing more is sent. */}
        <label htmlFor="gemini-rate">Rate</label>
        <input id="gemini-rate" type="range" min={0.5} max={2} step={0.1} value={rate} aria-valuetext={`${rate}×`} onChange={e => setVoice({ rate: Number(e.target.value) })} />
      </div>
      <label className="voice-style" htmlFor="gemini-style">
        How Gemini says it
        <textarea
          id="gemini-style"
          className="input"
          rows={2}
          maxLength={200}
          value={manner}
          disabled={!has || busy}
          placeholder="calm, like a radio host"
          aria-describedby="gemini-style-note"
          onChange={e => setManner(e.target.value)}
          onBlur={() => manner.trim() !== (saved?.style ?? '') && void put({ style: manner.trim() })}
        />
      </label>
      <span id="gemini-style-note" className="choice-note">
        Gemini’s voice reads in this manner; it is not sent to the Orchestrator.
      </span>
      <button
        type="button"
        className="btn btn-small"
        disabled={!(on && has)}
        onClick={() => {
          // Tried again: Gemini reads once more.
          useVoice.setState({ fallback: false })
          read('preview', SAMPLE)
        }}
      >
        <SpeakerHigh size={13} />
        Preview
      </button>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="muted cmd-approval-note">{GEMINI_PRIVACY}</div>
    </>
  )
}
