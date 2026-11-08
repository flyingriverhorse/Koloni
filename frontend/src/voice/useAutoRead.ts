import { useEffect, useRef } from 'react'
import type { Message } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { firstTwo, sentences, speakable } from './speakable'
import { loadGemini, read, useVoice } from './voice'

/** Read to its end, or stopped: nothing more of it is read by itself. */
const DONE = -1

/** The Lead's own answers in the chat: not a sub-agent's, not a discussion's, not a note handed to it. */
export function leadAnswers(conv: ConvState): Message[] {
  const lead = new Set(conv.agents.filter(a => a.depth === 0).map(a => a.id))
  return conv.messages.filter(m => m.role === 'assistant' && m.agent_id !== null && lead.has(m.agent_id) && !m.discussion_id && !m.board_post_id)
}

/**
 * Auto-read (slice 32a): while it is on, the Lead's answer is read as it comes - the whole of
 * it, a sentence as soon as the sentence is written, or the short line to be said once the
 * turn is over. What was there when the conversation was opened is not read, and a stop
 * (typing, the mic, sending, Stop) ends the reading of what was being written.
 */
export function AutoReader() {
  // A leaf of its own: a stop at every key draws it again, not the chat.
  const conv = useApp(s => s.conv)
  const autoRead = useVoice(s => s.autoRead)
  const mode = useVoice(s => s.mode)
  const stops = useVoice(s => s.stops)
  // By the conversation: what it held when opened, and how many sentences of each answer were queued.
  const known = useRef<{ cid: string; past: Set<string>; queued: Map<string, number>; stops: number } | null>(null)
  // Whether Gemini's voices read: known once the page is open.
  useEffect(loadGemini, [])

  useEffect(() => {
    if (!conv) return
    const answers = leadAnswers(conv)
    const k = known.current
    if (!k || k.cid !== conv.conversation.id) {
      known.current = { cid: conv.conversation.id, past: new Set([...conv.messages, ...conv.runs].map(each => each.id)), queued: new Map(), stops }
      return
    }
    const stopped = k.stops !== stops
    k.stops = stops
    for (const message of answers) {
      if (k.past.has(message.id) || k.queued.get(message.id) === DONE) continue
      if (!autoRead || mode !== 'whole' || stopped) {
        k.queued.set(message.id, DONE)
        continue
      }
      const writing = message.status === 'streaming'
      const { done, rest } = sentences(speakable(message.content, writing))
      const parts = writing ? done : [...done, rest].filter(Boolean)
      for (const part of parts.slice(k.queued.get(message.id) ?? 0)) read(message.id, part, true)
      k.queued.set(message.id, writing ? parts.length : DONE)
    }
    for (const run of conv.runs) {
      if (k.past.has(run.id) || run.status !== 'completed') continue
      k.past.add(run.id)
      if (!autoRead || mode !== 'summary') continue
      const last = answers.findLast(m => m.run_id === run.id && m.content)
      if (!last) continue
      // shortcut: the Lead's "Say:" line shows in the answer while it streams and is taken off at the
      // turn's end; upgrade to hiding a trailing "Say:" line in the chat if it distracts.
      const said = last.spoken ?? firstTwo(last.content)
      if (!last.spoken) useVoice.setState(s => ({ fromStart: { ...s.fromStart, [last.id]: said } }))
      read(last.id, said)
    }
  }, [conv, autoRead, mode, stops])
  return null
}
