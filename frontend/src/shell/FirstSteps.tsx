import { Check, Circle } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Health, Provider } from '../api/types'
import { isCli } from '../models/ModelsPage'

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
  /** The providers, the default first: while it does not answer, another that does is offered in its place. */
  providers: Provider[]
  onProvider: () => void
  /** A provider made the default. Throws ApiError with why not. */
  onUse: (providerId: string) => Promise<void>
  onHidden: () => void
  /** The provider they now say isn't answering (null: none): the top bar does not say it too. */
  onSaysProvider: (providerId: string | null) => void
}

const answers = (health: Health | null) => health !== null && health.model_reachable && !health.not_listed

/**
 * The first switched-on provider after the default that /health says can be reached (null: none, or not looked for) - asked one
 * after another, again at each reading of the default.
 * shortcut: a CLI counts once it is installed and could be started (/health never runs one), signed in or not; upgrade when
 * /health can tell a CLI that is signed in.
 */
function useOther(health: Health | null, providers: Provider[], down: boolean): Provider | null {
  const [other, setOther] = useState<Provider | null>(null)
  // (Only where the reading is the default's: for a chat on a provider of its own, another default changes nothing.)
  const look = down && health?.provider_id === providers[0]?.id
  useEffect(() => {
    let latest = true
    const read = async () => {
      for (const one of look ? providers.slice(1).filter(one => one.enabled !== false) : []) {
        const reading = await api.get<Health>(`/health?provider_id=${encodeURIComponent(one.id)}`).catch(() => null)
        if (!latest) return
        if (answers(reading)) return setOther(one)
      }
      setOther(null)
    }
    void read()
    return () => {
      latest = false
    }
  }, [health, providers, look])
  return look ? other : null
}

/** The provider whose reading says it does not answer, by name (null: it does, or the user wrote - then the banner says it). */
const downOf = (health: Health | null, wrote: boolean) => (!wrote && health && !health.model_reachable && health.provider_name) || null

/** Under a provider step whose provider does not answer: what to do - or, where another answers, that one offered as the default. */
function ProviderNote({ name, other, onUse }: { name: string; other: Provider | null; onUse: Props['onUse'] }) {
  if (!other) return `${name} isn't answering - add another provider, or start its model server.`
  return (
    <>
      {name} isn't answering, and new chats run on it. {other.name} is {isCli(other.kind) ? 'installed' : 'answering'}.{' '}
      <UseOther other={other} onUse={onUse} />
    </>
  )
}

/** The done provider step's one button: the default is changed by the user's press only, never by itself. */
function UseOther({ other, onUse }: { other: Provider; onUse: Props['onUse'] }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const use = (main: HTMLElement | null) => {
    setBusy(true)
    setError(null)
    onUse(other.id)
      // The button goes with its offer: the focus goes to the page, not to nowhere.
      .then(() => main?.focus())
      .catch(err => setError(errorText(err)))
      .finally(() => setBusy(false))
  }
  return (
    <>
      <button type="button" className="btn btn-small" disabled={busy} onClick={event => use(event.currentTarget.closest<HTMLElement>('.main'))}>
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

/**
 * The first run's one path (0.1.0-ilk-calistirma), in the middle of the canvas: a provider, a folder, a message -
 * each read from what is so, never ticked by itself, so all three done they are gone without a flag. The first not
 * done is the current one and the only one with a button - but for a provider step done by another provider than the
 * default, which offers that one as the default. Hidden by hand, they come back only from Help.
 */
export function FirstSteps({ health, project, folder, wrote, turn, again, providers, onProvider, onUse, onHidden, onSaysProvider }: Props) {
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
  // Any provider that answers will do - where it is not the default, the step says so and offers it: a new chat runs on the default.
  const other = useOther(health, providers, down !== null)
  const provider = wrote || answers(health) || other !== null
  // (The top bar leaves it to them while they say it; here it says what to do about it.)
  const note = down && <ProviderNote name={down} other={other} onUse={onUse} />
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
            className={`first-step${step.done ? ' first-step-done' : ''}${step.note ? ' first-step-noted' : ''}`}
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
