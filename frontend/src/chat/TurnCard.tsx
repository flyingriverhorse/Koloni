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
  /** The turn's last message of the Lead's with words: its ■ stays in sight while it is read, the turn still at work. */
  answer: Message | undefined
  children: ReactNode
  /** Once the turn is over: what it did, and its answer's Copy and Read aloud. Null while it runs. */
  foot: ReactNode | null
  /** Something in it waits for your word: said where its time would be. */
  waits: boolean
}

/** When the turn last said something: its last message of the Lead's or of KOLONİ's (a sub-agent's are not in the chat). */
function lastAt(state: ConvState, run: Run, lead: Agent | undefined) {
  return state.messages.filter(m => m.run_id === run.id && (!m.agent_id || m.agent_id === lead?.id)).at(-1)?.created_at ?? run.created_at
}

/**
 * One Lead turn in the chat (0.1.4): who answered, with what model and when; the turn's groups as the chat draws them;
 * and once it is over a quiet foot. A turn at work has none - only the ■ of an answer Auto-read reads as it is written.
 */
export function TurnCard({ state, run, lead, answer, children, foot, waits }: Props) {
  const teams = useApp(s => s.teams)
  const reading = useVoice(s => s.speaking !== null && s.speaking === answer?.id)
  const name = titleOf(lead?.name || 'Agent', teams)
  const model = lead?.model_id && modelName(lead.model_id)
  const at = lastAt(state, run, lead)
  const end = foot ?? (reading && answer ? <AnswerActions message={answer} /> : null)
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
      {end && <footer className="turn-foot">{end}</footer>}
    </article>
  )
}

/**
 * Under a turn's answer: Copy its words as written (markdown), once it is whole, and Read aloud - its ■ while it is
 * read. Icons only: no words of theirs join the answer's.
 */
export function AnswerActions({ message }: { message: Message }) {
  const [copied, setCopied] = useState(false)
  const written = message.status === 'complete'
  return (
    <span className="turn-actions">
      {written && (
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
      <ReadAloud id={message.id} content={message.content} written={written} />
    </span>
  )
}
