import { Check, Copy } from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import { WAITS, titleOf } from '../agents/agentStatus'
import type { Agent, Message, Run } from '../api/types'
import { when } from '../canvas/turns'
import { modelName } from '../shell/modelName'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { ReadAloud } from '../voice/VoiceControls'
import { useVoice } from '../voice/voice'

interface Props {
  state: ConvState
  run: Run
  lead: Agent | undefined
  /** The turn's answer, its last message of the Lead's with words: once the turn is over the foot copies it and reads it. */
  answer: Message | undefined
  children: ReactNode
  /** What the turn did (TurnSummary), once it is over; null while it runs. */
  summary: ReactNode | null
  /** Something in it waits for your word: said where its time would be. */
  waits: boolean
}

/** When the turn last said something: its last message of the Lead's or of KOLONİ's (a sub-agent's are not in the chat). */
function lastAt(state: ConvState, run: Run, lead: Agent | undefined) {
  return state.messages.filter(m => m.run_id === run.id && (!m.agent_id || m.agent_id === lead?.id)).at(-1)?.created_at ?? run.created_at
}

/** The turn's message read aloud now, if one is. */
const saidOf = (state: ConvState, run: Run, speaking: string | null) => state.messages.find(m => m.id === speaking && m.run_id === run.id)

/**
 * One Lead turn in the chat (0.1.4): who answered, with what model and when; the turn's groups as the chat draws them;
 * and once it is over a quiet foot. A turn at work has none - only the ■ of what of it Auto-read reads.
 */
export function TurnCard({ state, run, lead, answer, children, summary, waits }: Props) {
  const teams = useApp(s => s.teams)
  // (Whole answer reads a step's words while the next step is written: the ■ stays with the step still heard.)
  const said = useVoice(s => saidOf(state, run, s.speaking))
  const name = titleOf(lead?.name || 'Agent', teams)
  const model = lead?.model_id && modelName(lead.model_id)
  const at = lastAt(state, run, lead)
  const over = summary !== null
  return (
    <article className="turn-card" aria-label={`${name}, ${waits ? WAITS : when(at)}`}>
      <div className="turn-head">
        <span className="turn-avatar" aria-hidden>
          {name.charAt(0)}
        </span>
        <span className="turn-name">{name}</span>
        {model && <span className="turn-model">{model}</span>}
        {waits ? <span className="tag tag-warn">{WAITS}</span> : <time dateTime={at}>{when(at)}</time>}
      </div>
      {children}
      {(over || said) && (
        // Its parts in fixed places: at the turn's end the ■ the keyboard is on stays the same button.
        <footer className="turn-foot">
          {summary}
          {answer && <AnswerActions message={answer} said={said} over={over} />}
        </footer>
      )}
    </article>
  )
}

/**
 * Under a turn's answer: Copy its words as written (markdown), once the turn is over and it is whole, and Read aloud -
 * of it, or of the turn's message read now (`said`), with its ■. Icons only: no words of theirs join the answer's.
 */
export function AnswerActions({ message, said = message, over }: { message: Message; said?: Message; over: boolean }) {
  const [copied, setCopied] = useState(false)
  return (
    <span className="turn-actions">
      {over && message.status === 'complete' && (
        // (As a message's ⋯ copies: no clipboard here, or the browser refused, and it stays "Copy".)
        <button
          type="button"
          className="icon-btn"
          aria-label={copied ? 'Copied' : 'Copy'}
          title={copied ? 'Copied' : 'Copy'}
          aria-live="polite"
          onClick={() => void navigator.clipboard?.writeText(message.content).then(() => setCopied(true), () => {})}
          onBlur={() => setCopied(false)}
        >
          {copied ? <Check size={14} /> : <Copy size={14} />}
        </button>
      )}
      <ReadAloud id={said.id} content={said.content} written={said.status === 'complete'} />
    </span>
  )
}
