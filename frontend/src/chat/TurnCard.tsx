import { Check, Copy } from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import { WAITS, titleOf } from '../agents/agentStatus'
import type { Agent, Message, Run } from '../api/types'
import { when } from '../canvas/turns'
import { autoPicked, modelName, pickedWhy } from '../shell/modelName'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { ReadAloud } from '../voice/VoiceControls'
import { useVoice } from '../voice/voice'
import { CheckedSection } from './CheckedSection'

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
  /** The chat's newest turn: its Copy and Read aloud are always in sight. */
  latest?: boolean
  /** It ends with its answer's words: hidden, its foot of only those stands over their end, taking no room. */
  wordsEnd?: boolean
  /** What KOLONİ checked at its end (its "checked" message): under the answer once the turn is over. */
  checked?: Message
}

/**
 * When the turn last said something: its last message of the Lead's or of KOLONİ's (a sub-agent's are not in the chat) -
 * not a night's closing line, which KOLONİ puts on the last turn there was, hours later.
 */
function lastAt(state: ConvState, run: Run, lead: Agent | undefined) {
  return (
    state.messages
      .filter(
        m =>
          m.run_id === run.id && m.role !== 'away' && m.role !== 'checked' && (!m.agent_id || m.agent_id === lead?.id),
      )
      .at(-1)?.created_at ?? run.created_at
  )
}

/** Its Lead's model as the head says it ("fusion → gpt-6-luna" where Copilot's routing picked it), and Copilot's reason for that pick. */
function modelOf(lead: Agent | undefined) {
  if (!lead?.model_id) return { model: null, why: null }
  const routed = autoPicked(lead.model_from)
  return { model: routed + modelName(lead.model_id), why: pickedWhy(lead.effort_note, lead.model_from, lead.model_id) }
}

/** Who answered: the Lead's name opens its window - where Tell reaches it at work, since none opens by itself (21 Nov). */
function TurnName({ lead, name }: { lead: Agent | undefined; name: string }) {
  if (!lead) return <span className="turn-name">{name}</span>
  return (
    <button
      type="button"
      className="turn-name"
      title="Open its window"
      onClick={() => useApp.getState().openAgentWindow(lead.id)}
    >
      {name}
    </button>
  )
}

/** The turn's message read aloud now, if one is. */
const saidOf = (state: ConvState, run: Run, speaking: string | null) =>
  state.messages.find(m => m.id === speaking && m.run_id === run.id)

/**
 * One Lead turn in the chat (0.1.5: no frame): who answered, with what model and when; the turn's groups as the chat draws
 * them; and once it is over a quiet foot - Copy and Read aloud, what it did at their right. A turn at work has none - only
 * the ■ of what of it Auto-read reads.
 */
export function TurnCard({
  state,
  run,
  lead,
  answer,
  children,
  summary,
  waits,
  latest = false,
  wordsEnd = false,
  checked,
}: Props) {
  const teams = useApp(s => s.teams)
  // (Whole answer reads a step's words while the next step is written: the ■ stays with the step still heard.)
  const said = useVoice(s => saidOf(state, run, s.speaking))
  const name = titleOf(lead?.name || 'Agent', teams)
  const { model, why } = modelOf(lead)
  const at = lastAt(state, run, lead)
  const over = summary !== null
  return (
    <article
      className={['turn', latest && 'turn-latest', wordsEnd && !checked && 'turn-words-end'].filter(Boolean).join(' ')}
      data-run={run.id}
      aria-label={`${name}, ${waits ? WAITS : when(at)}`}
    >
      <div className="turn-head">
        <span className="turn-avatar" aria-hidden>
          {name.charAt(0)}
        </span>
        <TurnName lead={lead} name={name} />
        {model && <span className="turn-model">{model}</span>}
        {waits ? <span className="tag tag-warn">{WAITS}</span> : <time dateTime={at}>{when(at)}</time>}
      </div>
      {why && (
        <div className="turn-why" title={why}>
          {why}
        </div>
      )}
      {children}
      <CheckedSection message={checked} over={over} latest={latest} />
      {(over || said) && (
        // Its parts in fixed places: at the turn's end the ■ the keyboard is on stays the same button.
        <footer className="turn-foot">
          {answer && <AnswerActions message={answer} said={said} over={over} />}
          {summary}
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
        <>
          {/* (As a message's ⋯ copies: no clipboard here, or the browser refused, and it stays "Copy".) */}
          <button
            type="button"
            className="icon-btn"
            aria-label={copied ? 'Copied' : 'Copy'}
            title={copied ? 'Copied' : 'Copy'}
            onClick={() =>
              void navigator.clipboard?.writeText(message.content).then(
                () => setCopied(true),
                () => {},
              )
            }
            onBlur={() => setCopied(false)}
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
          {/* "Copied" said once, by a region of its own: emptied as the focus leaves, which a screen reader does not say. */}
          <span className="visually-hidden" aria-live="polite">
            {copied ? 'Copied' : ''}
          </span>
        </>
      )}
      <ReadAloud id={said.id} content={said.content} written={said.status === 'complete'} />
    </span>
  )
}
