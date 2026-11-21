import { CaretDown, CaretRight, Check, Question as QuestionIcon } from '@phosphor-icons/react'
import { type FormEvent, type KeyboardEvent, type ReactNode, useId, useState } from 'react'
import { titleOf } from '../agents/agentStatus'
import { shownOption } from '../agents/teamRun'
import { errorText } from '../api/client'
import type { Question } from '../api/types'
import { when } from '../canvas/turns'
import type { ConvState } from '../state/applyEvent'
import { type ChatTab, useApp } from '../state/store'
import { ASK_CARD_ID, firstLine, leadQuestions } from './chatLine'

interface Props {
  conv: ConvState | null
  /** The chat is open: closed, its line says what the Orchestrator asks (the card is hidden, not gone). */
  open: boolean
  tab: ChatTab
  onAnswer: (questionId: string, answer: string) => Promise<void>
}

/** Your own answer's choice: the row after the options. */
const OWN = '\u0000own'

/**
 * The Orchestrator's question, just over the message box (0.1.5, as VS Code has it): who asks and in which turn, its
 * options numbered, your own answer as the last row, and Submit. Keys 1-9 pick an option, Enter sends; ‹ 1/2 › while it
 * asks two; ⌄ folds it to its head. There is no ✕: it is answered, or a message is queued behind it. Answered, the
 * focus goes back to the message box.
 */
export function AskCard({ conv, open, tab, onAnswer }: Props) {
  const [at, setAt] = useState(0)
  const [folded, setFolded] = useState(false)
  const asks = conv ? leadQuestions(conv) : []
  if (!conv || asks.length === 0) return null
  const index = Math.min(at, asks.length - 1)
  const question = asks[index]
  const pager = asks.length > 1 && (
    <span className="ask-pager">
      <button type="button" className="icon-btn" aria-label="Previous question" disabled={index === 0} onClick={() => setAt(index - 1)}>
        ‹
      </button>
      <span className="mono">
        {index + 1}/{asks.length}
      </span>
      <button type="button" className="icon-btn" aria-label="Next question" disabled={index === asks.length - 1} onClick={() => setAt(index + 1)}>
        ›
      </button>
    </span>
  )
  const head = (
    <div className="ask-head">
      <AskedBy conv={conv} question={question} />
      {pager}
      <button type="button" className="icon-btn ask-fold" aria-label="Fold the question" aria-expanded={!folded} onClick={() => setFolded(!folded)}>
        {folded ? <CaretRight size={13} /> : <CaretDown size={13} />}
      </button>
    </div>
  )
  // (Each question its own choice and words: going between two keeps both.)
  // (Closed, or on Talk or Notes, hidden, not gone: an answer half written in it stays.)
  return <AskForm key={question.id} question={question} head={head} folded={folded} hidden={!open || tab !== 'Chat'} onAnswer={answer => onAnswer(question.id, answer)} />
}

/** "Orchestrator asks · 10:42": who asks, and when its turn began. */
function AskedBy({ conv, question }: { conv: ConvState; question: Question }) {
  const teams = useApp(s => s.teams)
  const asker = conv.agents.find(a => a.id === question.agent_id)
  const turn = conv.runs.find(r => r.id === question.run_id)
  return (
    <span className="ask-who">
      {titleOf(asker?.name || 'Lead', teams)} asks{turn && ` · ${when(turn.created_at)}`}
    </span>
  )
}

/** The card's form: the question, its options and your own answer, and Submit. */
function AskForm({ question, head, folded, hidden, onAnswer }: { question: Question; head: ReactNode; folded: boolean; hidden: boolean; onAnswer: (answer: string) => Promise<void> }) {
  const name = useId()
  const [choice, setChoice] = useState<string | null>(null)
  const [own, setOwn] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const answer = choice === OWN ? own.trim() : choice
  const title = firstLine(question.question)
  const more = question.question.trim().slice(title.length).trim()

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    if (!answer || busy) return
    setBusy(true)
    setError(null)
    try {
      await onAnswer(answer)
      document.querySelector<HTMLElement>('.composer-input')?.focus()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  // 1-9 pick an option (not while your own answer is written, nor mid-composition); Enter sends.
  function onKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.nativeEvent.isComposing) return
    if (event.key === 'Enter') {
      event.preventDefault()
      void submit()
      return
    }
    const n = Number(event.key)
    const typing = (event.target as HTMLElement).matches('input[type=text], input:not([type])')
    if (typing || !Number.isInteger(n) || n < 1 || n > question.options.length + 1) return
    event.preventDefault()
    // (The number after the options is your own answer's: its words are written then.)
    if (n > question.options.length) return event.currentTarget.querySelector<HTMLInputElement>('input[type=text]')?.focus()
    setChoice(question.options[n - 1])
    event.currentTarget.querySelectorAll<HTMLInputElement>('input[type=radio]')[n - 1]?.focus()
  }

  return (
    <form id={ASK_CARD_ID} className="ask-card" aria-label="Orchestrator asks" hidden={hidden} onSubmit={submit} onKeyDown={onKeyDown}>
      {head}
      {!folded && (
        <div className="ask-body">
          <div className="ask-title">{title}</div>
          {more && <p className="ask-more">{more}</p>}
          <div role="radiogroup" aria-label={title} className="ask-options">
            {question.options.map((option, i) => (
              <label key={option} className="ask-option">
                <input type="radio" name={name} checked={choice === option} disabled={busy} onChange={() => setChoice(option)} />
                <span className="ask-n" aria-hidden>
                  {i + 1}
                </span>
                <span className="ask-label">{shownOption(option, false)}</span>
                {choice === option && <Check size={14} className="ask-check" aria-hidden />}
              </label>
            ))}
            <div className="ask-option ask-own">
              <input type="radio" name={name} aria-label="Answer in your own words" checked={choice === OWN} disabled={busy} onChange={() => setChoice(OWN)} />
              <span className="ask-n" aria-hidden>
                {question.options.length + 1}
              </span>
              <input
                type="text"
                className="input"
                aria-label="Your answer"
                placeholder={question.options.length > 0 ? 'Or answer in your own words…' : 'Your answer…'}
                value={own}
                disabled={busy}
                onChange={e => {
                  setOwn(e.target.value)
                  setChoice(OWN)
                }}
              />
            </div>
          </div>
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
          <div className="ask-foot">
            <button type="submit" className="btn btn-small btn-primary" disabled={!answer || busy}>
              Submit
            </button>
          </div>
        </div>
      )}
    </form>
  )
}

/** The card's checked option, else its first, else - folded - its fold: where the line in the turn takes the focus. */
function focusCard() {
  const card = document.getElementById(ASK_CARD_ID)
  const at = (selector: string) => card?.querySelector<HTMLElement>(selector)
  ;(at('input[type=radio]:checked') ?? at('input[type=radio]') ?? at('.ask-fold'))?.focus()
}

/** In its turn, the Orchestrator's open question as one line: a click goes to the card over the message box. */
export function AskLine({ question, who }: { question: Question; who: string }) {
  return (
    <button type="button" className="ask-line" onClick={focusCard}>
      <QuestionIcon size={13} aria-hidden />
      <span className="ask-line-words">
        {who} asks: {firstLine(question.question)} · <span className="ask-line-waits">waits for you</span>
      </span>
    </button>
  )
}

const ENDED: Partial<Record<Question['status'], string>> = { cancelled: 'not answered', interrupted: 'not answered', superseded: 'asked again: its files changed since' }

/** In its turn, the Orchestrator's question once it is over: "Question: … / Answered: …"; opened, its options, the one given ticked. */
export function AskedRow({ question }: { question: Question }) {
  const given = question.status === 'answered' ? question.answer : null
  return (
    <details className="asked-row">
      <summary>
        <span className="asked-q">
          <b>Question:</b> <span>{firstLine(question.question)}</span>
        </span>
        <span className="asked-a">
          {given === null ? (
            <span>{ENDED[question.status] ?? 'not answered'}</span>
          ) : (
            <>
              Answered: <span>{given}</span>
            </>
          )}
        </span>
      </summary>
      <ul className="asked-options">
        {question.options.map(option => (
          <li key={option} aria-label={option === given ? `${option}, your answer` : option}>
            {option === given ? <Check size={12} aria-hidden /> : <span className="asked-none" aria-hidden />}
            {option}
          </li>
        ))}
        {given !== null && !question.options.includes(given) && (
          <li aria-label={`${given}, your answer`}>
            <Check size={12} aria-hidden />
            {given}
          </li>
        )}
      </ul>
    </details>
  )
}
