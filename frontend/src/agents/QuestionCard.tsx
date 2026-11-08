import { PaperPlaneRight, Question as QuestionIcon } from '@phosphor-icons/react'
import { type FormEvent, useState } from 'react'
import { errorText } from '../api/client'
import type { Question } from '../api/types'
import { READY_FOR_YOU, TEAMS_READY, shownOption, shownQuestion } from './teamRun'

interface Props {
  question: Question
  onAnswer: (answer: string) => Promise<void>
  /** K-hazir-satir: said in this one line instead, with its choices and a way to the card in full. */
  line?: { text: string; onDetails: () => void }
}

/** A recipe's card's option (Ask me, Ready for you) that takes the user's words with it (B-114). */
const CHANGES = 'Ask for changes'

/**
 * KOLONİ's own cards' titles, by the first of their options - words KOLONİ sets, never an agent or a tool (app/agent).
 * Their text, which may quote an agent's or a tool's words, is never made a title: it stands whole under it.
 */
const TITLES: [(option: string) => boolean, string][] = [
  [option => option === 'Allow', 'Allow this?'],
  [option => option.startsWith('Continue (+'), 'Go on past its step limit?'],
  [option => option === 'Go on', 'Go on with the recipe?'],
  [option => option === 'Try again' || option === 'Skip', 'A recipe step did not finish'],
  [option => option === 'Take it in and go on', 'Go on from the kept work?'],
  [option => option === 'Start it', 'Start this MCP server?'],
]

/**
 * A question card's title and the text under it (sample A). An agent's question is its own title, the card saying the
 * agent asks. KOLONİ's own (`leave`) has a fixed title, its text whole under it; its Ready for you card is "Teams' work
 * is ready", its fixed "Ready for you: " prefix left out.
 */
function questionTitle(question: Pick<Question, 'question' | 'leave' | 'options'>): { who: string; title: string; said: string | null } {
  const text = question.question
  if (!question.leave) return { who: 'The agent asks', title: text, said: null }
  const who = 'KOLONİ asks'
  if (text.startsWith(READY_FOR_YOU)) return { who, title: TEAMS_READY, said: text.slice(READY_FOR_YOU.length).replace(/^:\s*/, '') }
  const first = question.options[0] ?? ''
  return { who, title: TITLES.find(([is]) => is(first))?.[1] ?? 'KOLONİ needs your word', said: text }
}

/**
 * A question an agent is waiting on: pick an option or answer in your own words. One that
 * asks leave for a tool (`leave`) is KOLONİ's own, not the agent's, and its options are all
 * there is to say: any other answer would be a no, so none is offered. Ask for changes first
 * asks what to change - optional - and sends it with it.
 */
export function QuestionCard({ question, onAnswer, line }: Props) {
  const [draft, setDraft] = useState('')
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function answer(text: string) {
    setBusy(true)
    setError(null)
    try {
      await onAnswer(text)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (asking) void answer(draft.trim() ? `${CHANGES}: ${draft.trim()}` : CHANGES)
    else if (draft.trim()) void answer(draft.trim())
  }

  const { who, title, said } = questionTitle(question)
  return (
    <form className={`cmd-approval${line ? ' question-line' : ''}`} onSubmit={submit}>
      {line ? (
        <div className="question-text">{line.text}</div>
      ) : (
        <>
          {/* (Who asks, on every card: an agent's words read as the agent's, KOLONİ's as its own.) */}
          <div className="card-who">{who}</div>
          <div className="kicker cmd-approval-kicker">{title}</div>
          {said && <p className="card-said question-text">{said}</p>}
        </>
      )}
      {question.options.length > 0 && (
        <div className="question-options">
          {question.options.map(option => (
            <button key={option} type="button" className="btn btn-small" disabled={busy} onClick={() => (option === CHANGES ? setAsking(true) : answer(option))}>
              {shownOption(option, question.leave)}
            </button>
          ))}
          {line && (
            <button type="button" className="link-btn" onClick={line.onDetails}>
              details →
            </button>
          )}
        </div>
      )}
      {asking && (
        <div className="question-free">
          <input
            className="input"
            aria-label="What to change"
            placeholder="What to change (optional)…"
            value={draft}
            disabled={busy}
            onChange={e => setDraft(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn btn-small btn-primary" disabled={busy}>
            Send
          </button>
        </div>
      )}
      {!question.leave && !asking && !line && (
        <div className="question-free">
          <input
            className="input"
            aria-label="Your answer"
            placeholder={question.options.length > 0 ? 'Or answer in your own words…' : 'Your answer…'}
            value={draft}
            disabled={busy}
            onChange={e => setDraft(e.target.value)}
          />
          <button
            type="submit"
            className="btn btn-small btn-primary"
            aria-label="Send answer"
            disabled={busy || !draft.trim()}
          >
            <PaperPlaneRight size={13} />
          </button>
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </form>
  )
}

const ENDED: Record<Exclude<Question['status'], 'pending' | 'answered'>, string> = {
  cancelled: 'not answered',
  interrupted: 'not answered',
  // (G5.4: its files changed after your answer - the card was asked again.)
  superseded: 'asked again: its files changed since',
}

/**
 * A question that is over: what was asked and what you said. `ended`: said in place of how it ended (Ready for you);
 * `text`: in place of what was asked (K-hazir-satir: the chat's one line).
 */
export function QuestionRow({ question, ended, text }: { question: Question; ended?: string; text?: string }) {
  return (
    <div className="question-row">
      <span className="question-icon">
        <QuestionIcon size={13} />
      </span>
      <div className="question-body">
        <div className="question-text">{text ?? shownQuestion(question)}</div>
        {question.answer !== null && question.status !== 'pending' && <div className="question-answer">{shownOption(question.answer, question.leave)}</div>}
        {question.status !== 'pending' && question.status !== 'answered' && <div className="mono muted question-ended">{ended ?? ENDED[question.status]}</div>}
      </div>
    </div>
  )
}
