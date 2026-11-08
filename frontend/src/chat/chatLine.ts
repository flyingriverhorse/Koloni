/**
 * What the chat's closed line says, and how tall it is open: kept apart from the panel so
 * that each can be checked on its own.
 */
import { titleOf } from '../agents/agentStatus'
import type { Message } from '../api/types'
import { activeRun, type ConvState } from '../state/applyEvent'
import { waitingOf } from './waiting'

export const HEIGHT_KEY = 'koloni-chat-height'
/** How tall the open box is, as a share of the canvas: at first, at most, at least. (At most: the canvas less TOP px - ChatPanel.) */
export const HEIGHT = 0.45
export const MOST = 1
export const LEAST = 0.2
/** What the open chat leaves of the canvas above it, at its tallest (slice 38e: the user's wish; 50% before). */
export const TOP = 16

/** The height this browser kept for the chat; the default where there is none it can have. */
export function storedHeight(): number {
  try {
    const kept = Number(localStorage.getItem(HEIGHT_KEY) ?? NaN)
    return kept >= LEAST && kept <= MOST ? kept : HEIGHT
  } catch {
    return HEIGHT
  }
}

/** What waits for the user's word in the conversation and can be answered now: Ready for you's count (K-bekleyenler). */
export const waitingCards = (conv: ConvState): number => waitingOf(conv).filter(row => row.current).length

/** What the Lead and the agents said in the chat that was not there when it was last open: the closed line's number (spec 38 §2). */
export const unreadOf = (inChat: Message[], seen: ReadonlySet<string>): number =>
  inChat.filter(m => (m.role === 'assistant' || m.role === 'agent') && !seen.has(m.id)).length

/** What the closed chat says happened last: who is at work, else the first line of the newest message in it. */
export function latestOf(conv: ConvState, inChat: Message[]): string {
  const run = activeRun(conv)
  const worker = run && conv.agents.findLast(a => a.run_id === run.id && a.status === 'running')
  if (worker) return `${titleOf(worker.name || worker.role_name)} is working`
  // (B-205: KOLONİ's line on where the work is stands under the answer in the chat; here the answer is the line, R178.)
  return answerLast(inChat.filter(m => m.role !== 'landed')).at(-1)?.content.split('\n').map(part => part.trim()).find(Boolean) ?? ''
}

/** R178: KOLONİ's lines that came right after a Lead's answer ("Tester was not opened this turn.") stand just above it, so
 * the answer stays the turn's last word - read with it, not under it (or on the closed chat's line) in its place. */
export function answerLast(messages: Message[]): Message[] {
  const out = [...messages]
  // (Each swap carries the answer one line on: past every KOLONİ line after it, theirs in their order.)
  for (let i = 1; i < out.length; i++) {
    const [answer, note] = [out[i - 1], out[i]]
    if (note.role === 'koloni' && answer.role === 'assistant' && answer.content && answer.run_id === note.run_id) {
      ;[out[i - 1], out[i]] = [note, answer]
    }
  }
  return out
}
