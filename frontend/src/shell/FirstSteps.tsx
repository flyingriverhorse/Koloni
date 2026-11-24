import { Check, Circle } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Health, Provider } from '../api/types'
import { openFolderPanel } from './usePanel'

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
  /** The providers, the default first: while it does not answer, another switched-on one is offered in its place. */
  providers: Provider[]
  /** The open chat runs on a provider chosen for it: another default would change nothing for it, so none is offered. */
  pinned: boolean
  onProvider: () => void
  /** A provider made the default, and the reading on show read again. Throws ApiError with why not. */
  onUse: (providerId: string) => Promise<void>
  onHidden: () => void
  /** The provider they now say isn't answering (null: none): the top bar does not say it too. */
  onSaysProvider: (providerId: string | null) => void
}

const answers = (health: Health | null) => health !== null && health.model_reachable && !health.not_listed

/** The provider whose reading says it does not answer, by name (null: it does, or the user wrote - then the banner says it). */
const downOf = (health: Health | null, wrote: boolean) =>
  (!wrote && health && !health.model_reachable && health.provider_name) || null

type NoteProps = Pick<Props, 'health' | 'providers' | 'pinned' | 'onUse'> & { name: string }

/**
 * Under a provider step whose provider does not answer: what to do - or, where the list holds another switched-on provider (the
 * first that is not the one read), that one offered as the default. Nothing is asked of it (a reading may send its model a
 * request): it "is set up", no more is known - so the step is not ticked by it.
 */
function ProviderNote({ name, health, providers, pinned, onUse }: NoteProps) {
  const other = pinned ? undefined : providers.find(one => one.id !== health?.provider_id && one.enabled !== false)
  if (!other) return `${name} isn't answering - add another provider, or start its model server.`
  return (
    <>
      {name} isn't answering, and new chats run on it. {other.name} is set up too.{' '}
      <UseOther other={other} onUse={onUse} />
    </>
  )
}

/** The offer's one button: the default is changed by the user's press only, never by itself. */
function UseOther({ other, onUse }: { other: Provider; onUse: Props['onUse'] }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const use = (button: HTMLElement) => {
    const main = button.closest<HTMLElement>('.main')
    setBusy(true)
    setError(null)
    onUse(other.id)
      // Where the button went with its offer, the focus goes to the page, not to nowhere.
      .then(() => {
        if (!button.isConnected) main?.focus()
      })
      .catch(err => setError(errorText(err)))
      .finally(() => setBusy(false))
  }
  return (
    <>
      <button type="button" className="btn btn-small" disabled={busy} onClick={event => use(event.currentTarget)}>
        Use {other.name} for new chats
      </button>
      {error && (
        <span role="alert" className="alert">
          {error}
        </span>
      )}
    </>
  )
}

/** The folder step's words: what a folder is, or - done - the open chat's folder (a plain chat: only that one is added). */
const folderText = (project: boolean, folder: string | null) =>
  !project ? (
    'A folder: the project your agents work in.'
  ) : folder ? (
    <>
      Project folder:{' '}
      <span className="mono" title={folder}>
        {folder}
      </span>
    </>
  ) : (
    'A project folder is added.'
  )

/**
 * The first run's one path (0.1.0-ilk-calistirma), in the middle of the canvas: a provider, a folder, a message -
 * each read from what is so, never ticked by itself, so all three done they are gone without a flag. The first not
 * done is the current one and the only one with a button - and, where the default does not answer, one more that offers
 * another provider as the default. Hidden by hand, they come back only from Help.
 */
export function FirstSteps({
  health,
  project,
  folder,
  wrote,
  turn,
  again,
  providers,
  pinned,
  onProvider,
  onUse,
  onHidden,
  onSaysProvider,
}: Props) {
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(KEY) === 'hidden'
    } catch {
      return false // storage is closed to the page: shown until hidden in this session
    }
  })
  // A provider that does not answer is not done (a seeded "Local" with no server behind it); once the user wrote, it is -
  // so a model that stops later brings no steps back: the banner says that.
  const down = downOf(health, wrote)
  const provider = wrote || answers(health)
  // (The top bar leaves it to them while they say it; here it says what to do about it.)
  const note = down && <ProviderNote name={down} health={health} providers={providers} pinned={pinned} onUse={onUse} />
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
      text: folderText(project, folder),
      button: 'Choose a folder',
      go: openFolderPanel,
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
  const says = shown && down !== null
  useEffect(() => {
    onSaysProvider(says ? (health?.provider_id ?? null) : null)
    return () => onSaysProvider(null)
  }, [says, health?.provider_id, onSaysProvider])
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
            {/* (Only the current step has one: a provider that does not answer is not done.) */}
            {step.note && <span className="muted first-step-note">{step.note}</span>}
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
