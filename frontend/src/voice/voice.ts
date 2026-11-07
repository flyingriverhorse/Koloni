/**
 * How answers are read aloud, as this browser keeps it, and what is being read right now
 * (slice 32a). The settings stay in this browser: its voices are this machine's. Gemini's
 * (slice 32e) are the server's: its key never comes to the page.
 */
import { create } from 'zustand'
import { api } from '../api/client'
import type { GeminiVoice } from '../api/types'
import { engine, geminiEngine, MOST, type Reader } from './engine'
import { sentences, speakable } from './speakable'

export interface VoiceSettings {
  /** The Lead's answers are read as they come. */
  autoRead: boolean
  /** Read all of it as it is written, or the short line the Lead adds to be said. */
  mode: 'whole' | 'summary'
  language: string
  /** A voice's uri; null: the browser's own for the language. */
  voice: string | null
  rate: number
  pitch: number
  /** How the Lead speaks, in the user's words: sent with the message (at most 300 characters). */
  style: string
  /** Gemini's voices read whenever a key is saved; false: the browser's do all the same. */
  gemini: boolean
}

export const VOICE_KEY = 'koloni-voice'
/** A language tag the server takes (schemas.SpokenIn): with another, no line to say is asked for. */
export const LANGUAGE_TAG = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,4}$/
export const DEFAULTS: VoiceSettings = { autoRead: false, mode: 'whole', language: 'en-US', voice: null, rate: 1, pitch: 1, style: '', gemini: true }

function stored(): VoiceSettings {
  try {
    const kept = JSON.parse(localStorage.getItem(VOICE_KEY) ?? '{}') as Partial<VoiceSettings>
    return { ...DEFAULTS, ...kept }
  } catch {
    return DEFAULTS
  }
}

interface VoiceState extends VoiceSettings {
  /** The message being read aloud, while it is. */
  speaking: string | null
  /** Grows at every stop: a reading that was going on does not pick up again after it. */
  stops: number
  /**
   * What was said of an answer the Lead wrote no line to say for: its first sentences.
   * shortcut: kept in memory only, so its "Said aloud" line is gone on reload; upgrade to a server field if the user misses it.
   */
  fromStart: Record<string, string>
  /** Gemini's settings on the server; null until they are known. */
  saved: GeminiVoice | null
  /** Why Gemini could not read, and what of which message it could not, until the user moves on. */
  failed: { why: string; id: string; text: string } | null
  /** Gemini failed: the browser's voices read until Gemini is tried again or the page is reloaded (never kept). */
  fallback: boolean
  set(change: Partial<VoiceSettings>): void
}

export const useVoice = create<VoiceState>()(set => ({
  ...stored(),
  speaking: null,
  stops: 0,
  fromStart: {},
  saved: null,
  failed: null,
  fallback: false,
  set(change) {
    set(change)
    const { autoRead, mode, language, voice, rate, pitch, style, gemini } = useVoice.getState()
    try {
      localStorage.setItem(VOICE_KEY, JSON.stringify({ autoRead, mode, language, voice, rate, pitch, style, gemini }))
    } catch {
      // the choice just does not persist
    }
  },
}))

/** Gemini reads: a key is saved, the user has not turned it off, and it has not just failed. */
export const geminiOn = (s: VoiceState) => s.gemini && s.saved?.has_key === true && !s.fallback

/** Asks the server once for Gemini's settings; with no answer, the browser's voices read. */
export function loadGemini() {
  api
    .get<GeminiVoice>('/voice/gemini')
    .then(saved => useVoice.setState({ saved }))
    .catch(() => {})
}

// A failure says why, and the browser reads on from what Gemini could not - in this language's voice only (cannotRead).
const geminiReader = geminiEngine((why, rest) => {
  const id = useVoice.getState().speaking ?? 'preview'
  const text = rest.join(' ')
  useVoice.setState({ failed: { why, id, text }, fallback: true })
  read(id, text, true)
})

/** What reads aloud now. */
export const reader = (): Reader => (geminiOn(useVoice.getState()) ? geminiReader : engine)

/** Why nothing can be read aloud as things stand; null when it can. */
export function cannotRead(): string | null {
  // (Gemini's voices speak every language: it hears which from the text.)
  if (geminiOn(useVoice.getState())) return geminiReader.canSpeak ? null : 'This browser cannot play sound.'
  if (!engine.canSpeak) return 'This browser cannot read aloud.'
  const { language } = useVoice.getState()
  // Never read in another language's voice.
  if (engine.voices(language).length === 0) return `No voice on this computer reads ${language}.`
  return null
}

// Utterances still to be read for the message being read; a stop makes the old ones' ends count for nothing.
let left = 0
let round = 0

/** A text cut where the app would refuse it. */
const cut = (part: string) => Array.from({ length: Math.ceil(part.length / MOST) }, (_, i) => part.slice(i * MOST, (i + 1) * MOST))

/** Sentences joined into as few texts as the app takes: one request for most answers. */
const joined = (parts: string[]) =>
  parts.reduce<string[]>((out, part) => {
    const last = out.at(-1)
    if (last !== undefined && last.length + 1 + part.length <= MOST) out[out.length - 1] = `${last} ${part}`
    else out.push(part)
    return out
  }, [])

/**
 * Reads `text` aloud for message `id`, sentence by sentence (a long utterance is cut short
 * by some browsers) - by Gemini, all of it at once when it is not queued. `after`: queued
 * behind what is being read, not instead of it.
 */
export function read(id: string, text: string, after = false) {
  if (cannotRead()) return
  if (!after) {
    stopReading()
    useVoice.setState({ failed: null })
  }
  const { done, rest } = sentences(`${text} `)
  const each = [...done, rest].filter(Boolean).flatMap(cut)
  const speaker = reader()
  const parts = speaker !== engine && !after ? joined(each) : each
  if (parts.length === 0) return
  const { language, voice, rate, pitch } = useVoice.getState()
  const mine = round
  left += parts.length
  // shortcut: one count for all that is queued, so ■ moves to the newer answer while an older one's
  // sentences are still read; upgrade to a count per answer if that confuses anyone.
  useVoice.setState({ speaking: id })
  for (const part of parts) {
    speaker.speak(part, { language, voice, rate, pitch }, () => {
      if (mine !== round) return
      left -= 1
      if (left === 0) useVoice.setState({ speaking: null })
    })
  }
}

/** Reads a whole answer: its words, with code passed over. */
export function readAnswer(id: string, markdown: string) {
  read(id, speakable(markdown))
}

/** Stops reading, and whatever was going to be read of it: typing, the mic, sending, Stop. */
export function stopReading() {
  round += 1
  left = 0
  // Both: the reader may have been changed while one read.
  engine.cancel()
  geminiReader.cancel()
  useVoice.setState(s => ({ speaking: null, stops: s.stops + 1 }))
}
