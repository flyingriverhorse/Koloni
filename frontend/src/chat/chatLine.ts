/**
 * What the chat's closed line says, and how wide it is open: kept apart from the panel so
 * that each can be checked on its own.
 */
import { titleOf } from '../agents/agentStatus'
import { isReadyCard } from '../agents/teamRun'
import type { Message, Question } from '../api/types'
import { activeRun, type ConvState } from '../state/applyEvent'
import { waitingOf } from './waiting'

export const WIDTH_KEY = 'koloni-chat-width'
/** How wide the open column is, in px: at first, at least, at most (base.css also holds it to 60% of the stage). */
export const WIDTH = 420
export const NARROWEST = 340
export const WIDEST = 760
/** How tall the Workspace window is while the chat is closed, as a share of the canvas (open, it stands full height beside it). */
export const HEIGHT = 0.45

/** The width this browser kept for the open chat; the default where there is none it can have. */
export function storedWidth(): number {
  try {
    const kept = Number(localStorage.getItem(WIDTH_KEY) ?? NaN)
    return kept >= NARROWEST && kept <= WIDEST ? kept : WIDTH
  } catch {
    return WIDTH
  }
}

/** What waits for the user's word in the conversation and can be answered now: Ready for you's count (K-bekleyenler). */
export const waitingCards = (conv: ConvState): number => waitingOf(conv).filter(row => row.current).length

/** What the Lead and the agents said in the chat that was not there when it was last open: the closed line's number (spec 38 §2). */
export const unreadOf = (inChat: Message[], seen: ReadonlySet<string>): number =>
  inChat.filter(m => (m.role === 'assistant' || m.role === 'agent') && !seen.has(m.id)).length

export const firstLine = (text: string) => text.split('\n').map(part => part.trim()).find(Boolean) ?? ''

/** The card over the message box that holds the Orchestrator's question (AskCard): its line in the turn takes the focus there. */
export const ASK_CARD_ID = 'ask-card'

/** The Orchestrator's own question, asked or over: not KOLONİ's card about one of its calls, nor its Ready for you card. */
export const isLeadAsk = (conv: ConvState, q: Question): boolean =>
  !q.leave && !isReadyCard(q) && conv.agents.some(a => a.id === q.agent_id && a.depth === 0)

/** The Orchestrator's questions that wait for your answer, in the order asked (0.1.5: on the card over the message box). */
export const leadQuestions = (conv: ConvState): Question[] => conv.questions.filter(q => q.status === 'pending' && isLeadAsk(conv, q))

/** The Orchestrator's question that waits for your answer: the first. */
export const leadQuestion = (conv: ConvState): Question | undefined => leadQuestions(conv)[0]

/** What the closed chat says happened last: what the Orchestrator asks, else who is at work, else the first line of the newest message in it. */
export function latestOf(conv: ConvState, inChat: Message[]): string {
  // (Its turn waits on the question, whoever else is at work: 0.1.4.)
  const asked = leadQuestion(conv)
  const asker = asked && conv.agents.find(a => a.id === asked.agent_id)
  if (asked && asker) return `${titleOf(asker.name || asker.role_name)} asks: ${firstLine(asked.question)}`
  const run = activeRun(conv)
  const worker = run && conv.agents.findLast(a => a.run_id === run.id && a.status === 'running')
  if (worker) return `${titleOf(worker.name || worker.role_name)} is working`
  // (B-205: KOLONİ's line on where the work is stands under the answer in the chat; here the answer is the line, R178.)
  // (So is what KOLONİ checked at a turn's end: in the turn's foot, never its line.)
  return firstLine(answerLast(inChat.filter(m => m.role !== 'landed' && m.role !== 'checked')).at(-1)?.content ?? '')
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
