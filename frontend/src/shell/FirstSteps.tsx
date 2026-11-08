import { Check, Circle } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import type { Health } from '../api/types'

const KEY = 'koloni-first-steps'

interface Props {
  /** What /health says of the open chat's provider; null while it is not read yet. */
  health: Health | null
  /** A folder (a project) is known. */
  project: boolean
  /** The open chat's main folder, said once the step is done; null for a plain chat. */
  folder: string | null
  /** The user wrote in a chat - any of them. */
  wrote: boolean
  /** Whether the open conversation has a turn; undefined while that is not read yet. */
  turn: boolean | undefined
  /** Asked for again from Help: shown even when done or hidden before, until it is hidden again. */
  again: boolean
  onProvider: () => void
  onHidden: () => void
  /** The provider they now say isn't answering (null: none): the top bar does not say it too. */
  onSaysProvider: (providerId: string | null) => void
}

/**
 * The first run's one path (0.1.0-ilk-calistirma), in the middle of the canvas: a provider, a folder, a message -
 * each read from what is so, never ticked by itself, so all three done they are gone without a flag. The first not
 * done is the current one and the only one with a button. Hidden by hand, they come back only from Help.
 */
export function FirstSteps({ health, project, folder, wrote, turn, again, onProvider, onHidden, onSaysProvider }: Props) {
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(KEY) === 'hidden'
    } catch {
      return false // storage is closed to the page: shown until hidden in this session
    }
  })
  // A provider that does not answer is not done (a seeded "Local" with no server behind it); once the user wrote, it is -
  // so a model that stops later brings no steps back: the banner says that.
  const provider = wrote || (health !== null && health.model_reachable && !health.not_listed)
  // (The top bar leaves it to them while they say it; here it says what to do about it.)
  const note = !provider && health?.provider_name && !health.model_reachable ? `${health.provider_name} isn't answering - add another provider, or start its model server.` : null
  const steps = [
    {
      done: provider,
      text: provider ? 'A provider is set up.' : 'A provider: the model your agents run on.',
      note,
      button: 'Add a provider',
      go: onProvider,
    },
    {
      done: project,
      text: !project ? 'A folder: the project your agents work in.' : folder ? <>Project folder: <span className="mono" title={folder}>{folder}</span></> : 'A project folder is added.',
      button: 'Choose a folder',
      // (The top bar's folder button opens its panel, where "Open a folder…" is.)
      go: () => document.querySelector<HTMLElement>('.folder-button')?.click(),
    },
    {
      done: wrote,
      text: wrote ? 'Your first message is written.' : 'Your first message: what you want done.',
      button: 'Write your first message',
      go: () => document.querySelector<HTMLElement>('.composer-input')?.focus(),
    },
  ]
  const current = steps.findIndex(step => !step.done)
  // shortcut: before the conversations are read, `turn` is false for a moment and the steps can show for that moment;
  // upgrade when the store says its list was read.
  // Over a turn they would be in its way: they stand only on a conversation with none yet, unless asked for.
  const shown = again || !(hidden || health === null || current === -1 || turn !== false)
  useEffect(() => {
    onSaysProvider(shown && note !== null ? (health?.provider_id ?? null) : null)
    return () => onSaysProvider(null)
  }, [shown, note, health?.provider_id, onSaysProvider])
  if (!shown) return null
  const hide = () => {
    try {
      localStorage.setItem(KEY, 'hidden')
    } catch {
      // storage is closed to the page: hidden for this session only
    }
    setHidden(true)
  }
  return (
    <section className="first-steps" aria-label="First steps">
      <h2>First steps</h2>
      <ol>
        {steps.map((step, at) => (
          <li
            key={step.button}
            className={step.done ? 'first-step first-step-done' : 'first-step'}
            aria-current={at === current ? 'step' : undefined}
          >
            {step.done ? <Check size={14} aria-hidden /> : <Circle size={14} aria-hidden />}
            <span className="visually-hidden">{step.done ? 'Done: ' : 'To do: '}</span>
            <span className={step.done || at === current ? undefined : 'muted'}>{step.text}</span>
            {at === current && (
              <button type="button" className="btn btn-small btn-primary" onClick={step.go}>
                {step.button}
              </button>
            )}
            {at === current && step.note && <span className="muted first-step-note">{step.note}</span>}
          </li>
        ))}
      </ol>
      <button
        type="button"
        className="btn btn-small"
        onClick={event => {
          // The button goes with the steps: the focus goes to the page, not to nowhere.
          event.currentTarget.closest<HTMLElement>('.main')?.focus()
          hide()
          onHidden()
        }}
      >
        Hide the first steps
      </button>
    </section>
  )
}
