/**
 * The speech engine (slice 32a, design §2.3): one small interface the chat talks to. Its one
 * implementation here is the browser's own `SpeechRecognition` and `speechSynthesis`; a
 * speech server (32b) or another reader (32e, Gemini's voices, below) is another object with the same shape.
 * Nothing is recorded or kept: the browser hands over words, not sound.
 */

import { keyHeader } from '../api/client'

export interface Voice {
  /** The browser's id for it: kept as the choice, looked up again when speaking. */
  uri: string
  name: string
  lang: string
  /** False for a voice of a service (Chrome's "Google …", Edge's "… Online"): what it reads goes there. */
  local: boolean
}

export interface SpeakHow {
  language: string
  /** A voice's `uri`; null: the browser's own for the language. */
  voice: string | null
  rate: number
  pitch: number
}

export interface VoiceEngine {
  /** Whether it can write down what is said (no: Firefox), and read aloud, in this browser. */
  readonly canListen: boolean
  readonly canSpeak: boolean
  /** Listens until `stop()` or its own end; `onText` gets all that was heard so far. */
  listen(language: string, onText: (text: string) => void, onEnd: (error: string | null) => void): void
  stop(): void
  /** The voices that speak `language` (all of them without one). */
  voices(language?: string): Voice[]
  /** Called when the list of voices changes (Chrome fills it after the page loads). */
  onVoices(listener: () => void): () => void
  speak(text: string, how: SpeakHow, onEnd?: () => void): void
  /** Stops reading and drops whatever was waiting to be read. */
  cancel(): void
}

// (Not in TypeScript's DOM types: the parts used here.)
interface Recognition {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
}
type RecognitionClass = new () => Recognition

const sameLanguage = (lang: string, language: string) => lang.replace('_', '-').toLowerCase() === language.toLowerCase()

/** Why listening ended, in words; null when it simply ended. */
function why(error: string): string | null {
  switch (error) {
    case 'aborted':
      return null
    case 'not-allowed':
    case 'service-not-allowed':
      return 'The microphone was not allowed. Allow it for this page in the browser.'
    case 'no-speech':
      return 'Nothing was heard.'
    case 'audio-capture':
      return 'No microphone was found.'
    case 'network':
      return 'The browser’s speech service could not be reached.'
    case 'language-not-supported':
      return 'The browser cannot write down this language.'
    default:
      return `Speech recognition failed: ${error}.`
  }
}

/** The browser's engine. It reads the window's objects when used, so a test can put its own in. */
function browserEngine(): VoiceEngine {
  // Held until they end: Chrome lets go of an utterance nothing holds, and its onend never comes.
  const reading = new Set<SpeechSynthesisUtterance>()
  const recognitionClass = () => {
    const found = window as unknown as { SpeechRecognition?: RecognitionClass; webkitSpeechRecognition?: RecognitionClass }
    return found.SpeechRecognition ?? found.webkitSpeechRecognition
  }
  let listening: Recognition | null = null
  return {
    get canListen() {
      return recognitionClass() !== undefined
    },
    get canSpeak() {
      return 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window
    },
    listen(language, onText, onEnd) {
      const Made = recognitionClass()
      if (!Made) return onEnd('This browser cannot write down what you say.')
      listening?.stop()
      const recognition = new Made()
      recognition.lang = language
      recognition.continuous = true
      recognition.interimResults = true
      let error: string | null = null
      // (A result that comes after stop() is dropped: the user may be typing by then.)
      recognition.onresult = event =>
        listening === recognition &&
        onText(
          Array.from(event.results)
            .map(result => result[0].transcript)
            .join(''),
        )
      recognition.onerror = event => {
        error = why(event.error)
      }
      recognition.onend = () => {
        if (listening === recognition) listening = null
        onEnd(error)
      }
      listening = recognition
      try {
        recognition.start()
      } catch (err) {
        listening = null
        onEnd(`Speech recognition failed: ${err instanceof Error ? err.message : String(err)}.`)
      }
    },
    stop() {
      listening?.stop()
    },
    voices(language) {
      if (!this.canSpeak) return []
      return window.speechSynthesis
        .getVoices()
        .filter(voice => !language || sameLanguage(voice.lang, language))
        .map(voice => ({ uri: voice.voiceURI, name: voice.name, lang: voice.lang.replace('_', '-'), local: voice.localService }))
    },
    onVoices(listener) {
      if (!this.canSpeak) return () => {}
      const synth = window.speechSynthesis
      synth.addEventListener('voiceschanged', listener)
      return () => synth.removeEventListener('voiceschanged', listener)
    },
    speak(text, how, onEnd) {
      if (!this.canSpeak) return onEnd?.()
      const utterance = new window.SpeechSynthesisUtterance(text)
      const all = window.speechSynthesis.getVoices()
      // None chosen: the first of this computer's own for the language, so that nothing goes out unasked.
      const voice = all.find(each => each.voiceURI === how.voice) ?? all.find(each => each.localService && sameLanguage(each.lang, how.language))
      if (voice) utterance.voice = voice
      utterance.lang = voice?.lang ?? how.language
      utterance.rate = how.rate
      utterance.pitch = how.pitch
      // Ended, or cut off by cancel(): either way it is no longer being read.
      const done = () => {
        reading.delete(utterance)
        onEnd?.()
      }
      utterance.onend = done
      utterance.onerror = done
      reading.add(utterance)
      window.speechSynthesis.speak(utterance)
    },
    cancel() {
      if (this.canSpeak) window.speechSynthesis.cancel()
    },
  }
}

export const engine = browserEngine()

/** What only reads aloud: Gemini's voices write nothing down. */
export type Reader = Pick<VoiceEngine, 'canSpeak' | 'speak' | 'cancel'>

/** The most the app takes in one text (schemas.GeminiSayIn). */
export const MOST = 4000

/** The sound of `text`, from the app, which asks Google for it in the manner kept there (app/api/voice.py). */
async function sound(text: string, signal: AbortSignal): Promise<Blob> {
  let res: Response
  try {
    res = await fetch('/api/voice/gemini/say', { method: 'POST', headers: { 'Content-Type': 'application/json', ...keyHeader() }, body: JSON.stringify({ text }), signal })
  } catch (err) {
    if (signal.aborted) throw err
    throw new Error('Gemini could not read it: the app could not be reached.')
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    if (typeof data?.detail === 'string') throw new Error(data.detail)
    throw new Error(res.status === 422 ? 'Gemini could not read it: the app did not take the text.' : `Gemini could not read it: the app answered ${res.status}.`)
  }
  return res.blob()
}

/** Plays `blob` to its end, or until `signal` stops it; `onStart` once it sounds. Its address is let go either way. */
function play(blob: Blob, signal: AbortSignal, onStart: () => void, rate: number): Promise<void> {
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  // Faster or slower in the browser; its pitch is kept (the element's own `preservesPitch`).
  audio.playbackRate = rate
  return new Promise<void>((resolve, reject) => {
    const end = (error?: Error) => {
      audio.pause()
      URL.revokeObjectURL(url)
      signal.removeEventListener('abort', stop)
      if (error) reject(error)
      else resolve()
    }
    const stop = () => end()
    signal.addEventListener('abort', stop)
    audio.onended = stop
    audio.onerror = () => end(new Error('Gemini could not read it: the browser could not play its sound.'))
    audio.play().then(onStart, (err: unknown) =>
      end(
        err instanceof Error && err.name === 'NotAllowedError'
          ? new Error('The browser plays sound only after you click on the page.')
          : err instanceof Error
            ? err
            : new Error(String(err)),
      ),
    )
  })
}

/**
 * Gemini's voices (slice 32e): each text goes to the app, which asks Google and hands back WAV;
 * they are played in the order given. A text is asked for once the one before it starts to
 * sound - one ahead, so a stop spends no more. On a failure the rest is given up, and `onFail`
 * hears why with the texts that were not read, the failed one first.
 */
export function geminiEngine(onFail: (why: string, rest: string[]) => void): Reader {
  // The last sound queued (the next plays after it), and the start of the last one (the next is asked for then).
  let played: Promise<unknown> = Promise.resolve()
  let started: Promise<unknown> = Promise.resolve()
  let round = new AbortController()
  // What this round has still to read to its end, in order.
  let waiting: string[] = []
  const self: Reader = {
    get canSpeak() {
      return typeof Audio !== 'undefined'
    },
    speak(text, how, onEnd) {
      const { signal } = round
      const queue = waiting
      queue.push(text)
      const before = started
      let begun = () => {}
      started = new Promise<void>(resolve => (begun = resolve))
      // shortcut: a sentence a request while an answer is still written; the free tier's few requests a
      // minute can run out on a long one (Google's 429 is said, and the browser reads on).
      const coming = before.then(() => (signal.aborted ? null : sound(text, signal)))
      coming.catch(() => {}) // (heard below, in its turn)
      played = played.then(async () => {
        try {
          const blob = await coming
          if (blob && !signal.aborted) await play(blob, signal, begun, how.rate)
          if (!signal.aborted) queue.shift()
        } catch (err) {
          if (!signal.aborted) {
            const rest = [...queue]
            self.cancel()
            onFail(err instanceof Error ? err.message : String(err), rest)
          }
        } finally {
          begun()
          onEnd?.()
        }
      })
    },
    cancel() {
      round.abort()
      round = new AbortController()
      started = Promise.resolve()
      waiting = []
    },
  }
  return self
}
