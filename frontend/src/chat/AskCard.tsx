import { CaretDown, CaretRight, Check, Question as QuestionIcon } from '@phosphor-icons/react'
import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useId, useRef, useState } from 'react'
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

/** What is chosen of a question, and your own words for it. */
type Draft = { choice: string | null; own: string }
const NO_DRAFT: Draft = { choice: null, own: '' }

/**
 * The Orchestrator's question, just over the message box (0.1.5, as VS Code has it): who asks and in which turn, its
 * options numbered, your own answer as the last row, and Submit. Keys 1-9 pick an option, Enter sends; ‹ 1/2 › while it
 * asks two; ⌄ folds it to its head. There is no ✕: it is answered, or a message is queued behind it. Answered, the
 * focus goes back to the message box.
 */
export function AskCard({ conv, open, tab, onAnswer }: Props) {
  // The question shown, by its id: another answered or come, it stays on the one shown. (None chosen: the first.)
  const [shown, setShown] = useState<string | null>(null)
  // Folded in a chat, by its id: another chat's card is open.
  const [folds, setFolds] = useState<Record<string, boolean>>({})
  // Each question's choice and words, by its id: going between two keeps both.
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const asks = conv ? leadQuestions(conv) : []
  const chat = conv?.conversation.id ?? ''
  const unfold = useCallback(() => setFolds(was => ({ ...was, [chat]: false })), [chat])
  const focus = useAskedFor(asks, setShown, unfold)
  if (!conv || asks.length === 0) return null
  const question = asks.find(q => q.id === shown) ?? asks[0]
  const folded = folds[conv.conversation.id] ?? false
  const head = (
    <div className="ask-head">
      <AskedBy conv={conv} question={question} />
      <Pager asks={asks} question={question} onGo={setShown} />
      <button
        type="button"
        className="icon-btn ask-fold"
        aria-label="Fold the question"
        aria-expanded={!folded}
        onClick={() => setFolds(was => ({ ...was, [conv.conversation.id]: !folded }))}
      >
        {folded ? <CaretRight size={13} /> : <CaretDown size={13} />}
      </button>
    </div>
  )
  // (Closed, or on Talk or Notes, hidden, not gone: an answer half written in it stays. Its form is the question's own:
  // what one refused is not said on another.)
  return (
    <div id={ASK_CARD_ID} role="form" aria-label="Orchestrator asks" className="ask-card" hidden={!open || tab !== 'Chat'}>
      {head}
      {!folded && (
        <AskForm
          key={question.id}
          question={question}
          focus={focus}
          draft={drafts[question.id] ?? NO_DRAFT}
          onDraft={draft => setDrafts(was => ({ ...was, [question.id]: draft }))}
          onAnswer={answer => onAnswer(question.id, answer)}
        />
      )}
    </div>
  )
}

/** ‹ 1/2 › while it asks two or more: round, never off, so a button the focus is on stays where it is. */
function Pager({ asks, question, onGo }: { asks: Question[]; question: Question; onGo: (id: string) => void }) {
  if (asks.length < 2) return null
  const index = asks.indexOf(question)
  const go = (by: number) => onGo(asks[(index + by + asks.length) % asks.length].id)
  return (
    <span className="ask-pager">
      <button type="button" className="icon-btn" aria-label="Previous question" onClick={() => go(-1)}>
        ‹
      </button>
      <span className="mono">
        {index + 1}/{asks.length}
      </span>
      <button type="button" className="icon-btn" aria-label="Next question" onClick={() => go(1)}>
        ›
      </button>
    </span>
  )
}

/** A question's line in its turn asks for its question (`ASKED`): the card goes to it, open, and its first option takes the focus. */
const ASKED = 'koloni-ask-question'

/** Follows a line's ask; true while the shown question's first option is to take the focus once drawn. */
function useAskedFor(asks: Question[], show: (id: string) => void, unfold: () => void) {
  const [wanted, setWanted] = useState<string | null>(null)
  const ids = asks.map(q => q.id).join(' ')
  useEffect(() => {
    const onAsk = (event: Event) => {
      const id = (event as CustomEvent<string>).detail
      if (!ids.split(' ').includes(id)) return
      show(id)
      unfold()
      setWanted(id)
    }
    document.addEventListener(ASKED, onAsk)
    return () => document.removeEventListener(ASKED, onAsk)
  }, [ids, show, unfold])
  return { wanted, done: () => setWanted(null) }
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
function AskForm(p: {
  question: Question
  focus: { wanted: string | null; done: () => void }
  draft: Draft
  onDraft: (draft: Draft) => void
  onAnswer: (answer: string) => Promise<void>
}) {
  const { question, onAnswer } = p
  const first = useRef<HTMLInputElement>(null)
  const { wanted, done } = p.focus
  useEffect(() => {
    if (wanted !== question.id) return
    first.current?.focus()
    done()
  }, [wanted, question.id, done])
  const { choice, own } = p.draft
  const setChoice = (to: string) => p.onDraft({ ...p.draft, choice: to })
  const name = useId()
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
    // (A button of its own - Submit - keeps its own Enter; a digit with Ctrl, Alt or Meta is the browser's.)
    if (event.nativeEvent.isComposing || (event.target as HTMLElement).closest('button')) return
    if (event.ctrlKey || event.altKey || event.metaKey) return
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
    <form className="ask-form" onSubmit={submit} onKeyDown={onKeyDown}>
        <div className="ask-body">
          <div className="ask-title">{title}</div>
          {more && <p className="ask-more">{more}</p>}
          <div role="radiogroup" aria-label={title} className="ask-options">
            {question.options.map((option, i) => (
              <label key={option} className="ask-option">
                <input type="radio" ref={i === 0 ? first : undefined} name={name} checked={choice === option} disabled={busy} onChange={() => setChoice(option)} />
                <span className="ask-n" aria-hidden>
                  {i + 1}
                </span>
                <span className="ask-label">{shownOption(option, false)}</span>
                {choice === option && <Check size={14} className="ask-check" aria-hidden />}
              </label>
            ))}
            <div className="ask-option ask-own">
              <input
                type="radio"
                ref={question.options.length === 0 ? first : undefined}
                name={name}
                aria-label="Answer in your own words"
                checked={choice === OWN}
                disabled={busy}
                onChange={() => setChoice(OWN)}
              />
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
                  p.onDraft({ choice: OWN, own: e.target.value })
                  // (☾ Away: the Orchestrator does not decide it for you while you write it.)
                  useApp.getState().typing(question.id)
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
    </form>
  )
}

/** In its turn, the Orchestrator's open question as one line: a click goes to its question on the card over the message box. */
export function AskLine({ question, who }: { question: Question; who: string }) {
  return (
    <button type="button" className="ask-line" onClick={() => document.dispatchEvent(new CustomEvent(ASKED, { detail: question.id }))}>
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
