import { useEffect, useRef, useState } from 'react'
import { errorText, overWhat } from '../api/client'
import type { Day, DayWords } from '../api/types'
import { Hint } from '../shell/Hint'
import { ranOn } from '../shell/modelName'
import { since } from './period'

interface Props {
  /** The open conversation: its Lead's models are the ones "Say it in words" asks. */
  currentId: string | null
  /** "HH:MM" the day's summary is sent at; null: it is not. */
  noteAt: string | null
  /** Reads the project's day from a moment on. Throws ApiError. */
  onLoad: (since: string) => Promise<Day>
  /** Asks a conversation's model once to say the day's numbers in words; `overBudget`: the user's word to ask over the month's budget. Throws ApiError. */
  onWords: (since: string, conversationId: string, overBudget?: boolean) => Promise<DayWords>
  /** Opens a conversation at a turn; rejects with the reason when it cannot be opened. */
  onOpenTurn?: (conversationId: string, runId: string) => Promise<void>
}

/**
 * Usage's Today for this project (tek-ev §3), beside the boxes the usage adds up: what the record alone knows of the
 * day since this midnight here - the messages that failed and the files changed (each chat's Workspace lists them) -
 * and the day said in words by a model, once, on the user's word.
 */
export function TodayView({ currentId, noteAt, onLoad, onWords, onOpenTurn }: Props) {
  const [day, setDay] = useState<Day | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [words, setWords] = useState<DayWords | null>(null)
  const [wordsError, setWordsError] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  // The server's word that the project is over this month's budget: asked again only on the user's.
  const [over, setOver] = useState<string | null>(null)
  const sayButton = useRef<HTMLButtonElement>(null)
  const [notOpened, setNotOpened] = useState<string | null>(null)
  const from = since('today')!

  useEffect(() => {
    let live = true
    onLoad(from).then(
      read => live && (setDay(read), setError(null)),
      err => live && setError(errorText(err)),
    )
    return () => {
      live = false
    }
  }, [onLoad, from])

  const asked = currentId ?? day?.conversations[0]?.conversation_id ?? null
  async function say(overBudget = false) {
    if (!asked) return
    setAsking(true)
    setWordsError(null)
    setOver(null)
    try {
      setWords(await (overBudget ? onWords(from, asked, true) : onWords(from, asked)))
    } catch (err) {
      if (!overBudget && overWhat(err)) setOver((err as Error).message)
      else setWordsError(errorText(err))
    } finally {
      setAsking(false)
    }
  }

  if (error)
    return (
      <div role="alert" className="alert">
        The day could not be read: {error}
      </div>
    )
  if (!day) return <p className="muted">Reading the day…</p>
  const failed = day.conversations.flatMap(c => c.failed_runs.map(run => ({ ...run, conversation: c })))
  return (
    <section aria-label="Today" className="memory-section usage-day">
      <dl className="usage-stats">
        <div>
          <dt>Failed</dt>
          <dd className="usage-stat mono">{day.failed}</dd>
          <dd>{day.failed === 1 ? 'message' : 'messages'} today</dd>
        </div>
        <div>
          <dt>Files changed</dt>
          <dd className="usage-stat mono">{day.changed_files.length}</dd>
          <dd>in the project, each once</dd>
        </div>
      </dl>
      {failed.length > 0 && (
        <details className="more">
          <summary>Failed today ({failed.length})</summary>
          {notOpened && (
            <div role="alert" className="alert">
              Not opened: {notOpened}
            </div>
          )}
          <ul className="board-agents" aria-label="Work that failed">
            {failed.map(run => (
              <li key={run.run_id} className="board-agent">
                <span className="board-agent-name">{run.conversation.title}</span>
                {run.error && <span className="muted">{run.error}</span>}
                {onOpenTurn && (
                  <button
                    type="button"
                    className="usage-open"
                    aria-label={`Show the work that failed in ${run.conversation.title}`}
                    onClick={() => {
                      setNotOpened(null)
                      onOpenTurn(run.conversation.conversation_id, run.run_id).catch(err => setNotOpened(errorText(err)))
                    }}
                  >
                    Show its work
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="muted memory-hint">
        Since midnight, counted from the record: no model is asked.
        {noteAt ? ` Sent as text at ${noteAt} each day.` : ' It can be sent each evening: project settings, Notifications.'}
      </p>
      {asked && (
        <p>
          <button ref={sayButton} type="button" className="btn btn-small" disabled={asking} aria-describedby="day-words-note day-words-more" onClick={() => void say()}>
            Say it in words
          </button>{' '}
          <span className="muted">
            <span id="day-words-note">
              A model sums up the day, once: a request you pay for, on the Usage page as KOLONİ itself. It is sent the numbers
              above, the conversations’ titles, the changed files’ paths (the first 20) and the agents’ names. With no fast
              model, the Orchestrator’s own model writes it, in{' '}
              {currentId ? 'the open conversation' : `“${day.conversations[0]?.title}”, the latest of the day: no conversation is open`}.
            </span>{' '}
            <Hint id="day-words-more">
              A fast model writes this summary: the first one the Orchestrator may pick. To have one, give a model the fast tier on the
              Models page and tick “Agents may choose this” for its provider. The answer shows which model wrote it.
            </Hint>
          </span>
        </p>
      )}
      {wordsError && (
        <div role="alert" className="alert">
          Not said in words: {wordsError}
        </div>
      )}
      {over && (
        <div role="group" aria-label="Over this month’s budget" className="composer-warning composer-budget">
          <span role="alert">{over}</span>
          <button type="button" className="btn btn-small" autoFocus onClick={() => void say(true)}>
            Go on anyway
          </button>
          <button
            type="button"
            className="btn btn-small"
            onClick={() => {
              setOver(null)
              sayButton.current?.focus()
            }}
          >
            Cancel
          </button>
        </div>
      )}
      {words && (
        <figure aria-label="Model text" className="memory-hint">
          <figcaption className="kicker">Model text · {ranOn(words.provider_name, words.model_id)} · may be wrong: the numbers above are the record</figcaption>
          <p>{words.text}</p>
        </figure>
      )}
    </section>
  )
}
