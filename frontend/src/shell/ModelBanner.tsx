import { WarningCircle, X } from '@phosphor-icons/react'
import { useState } from 'react'
import type { Health } from '../api/types'

const KEY = 'koloni-model-banner'

/** A role of the chat that could not run where it would (`cannot_run`): who, and why. */
export interface Cannot {
  who: string
  why: string
}

interface Props {
  /** Of each provider the open chat would run on (store.inUse); null: not known yet - the chat is being read. */
  readings: Health[] | null
  /** Its roles that could not run where they would. */
  cannot?: Cannot[]
  /** The provider First steps say isn't answering, with what to do: the bar does not repeat it. */
  quietFor?: string | null
  /** Opens the Models page. */
  onModels: () => void
}

/** One thing wrong: `key` says what (not how it is worded: a reason's wording may change from one reading to the next). */
interface Wrong {
  key: string
  name: string
  line: string
  reason: string | null
  down: boolean
}

const nameOf = (health: Health) => health.provider_name ?? 'The model provider'

/** One reading's short line and its reason (null: none to tell). */
function said(health: Health): [string, string | null] {
  // The address without its scheme, path, query, fragment and user name or password - any of which can hold a
  // secret: "127.0.0.1:8080". (Not new URL(): a base URL typed wrong would throw.)
  const host = health.model_base_url.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '').split(/[/?#]/)[0].replace(/^.*@/, '')
  return health.not_listed
    ? // It was not asked anything: it may well be there, it just may not run as it is set.
      [`${nameOf(health)} has no model it may run with by default.`, health.error]
    : !health.model_reachable
      ? [`${nameOf(health)} isn't answering${host && ` at ${host}`}.`, health.error]
      : [`${health.model_id} does not support tool calls; chat works, file tools are off.`, null]
}

function wrongs(readings: Health[], cannot: Cannot[], quietFor: string | null): Wrong[] {
  const bad = readings.filter(h => (quietFor === null || h.provider_id !== quietFor) && (h.not_listed || !h.model_reachable || h.tools_supported === false))
  return [
    ...bad.map(h => {
      const [line, reason] = said(h)
      const key = [h.provider_name, h.model_base_url, h.not_listed, h.model_reachable, h.tools_supported].join(' ')
      return { key, name: nameOf(h), line, reason, down: !h.model_reachable && !h.not_listed }
    }),
    ...cannot.map(({ who, why }) => ({ key: `${who} can't run: ${why}`, name: who, line: `${who} can't run: ${why}`, reason: null, down: false })),
  ]
}

/** Each one's line in the list of several, named where its line does not name it, with its reason. */
const listed = ({ name, line, reason }: Wrong) => `${line.startsWith(name) ? '' : `${name}: `}${line}${reason ? ` ${reason}` : ''}`

const stored = () => {
  try {
    return sessionStorage.getItem(KEY)
  } catch {
    return null // storage is closed to the page: dismissed for this page only
  }
}

/**
 * The top bar's one line for what is wrong with what the open chat would run on (sample A): a provider /health found
 * wrong, or a role that cannot run. One: its line with its reason behind Details; several: how many and which, each
 * behind Details. Dismissed, it stays gone for the session until what is wrong changes - another state, or another one.
 */
export function ModelBanner({ readings, cannot = [], quietFor = null, onModels }: Props) {
  const [dismissed, setDismissed] = useState(stored)
  const [why, setWhy] = useState(false)
  const remember = (state: string | null) => {
    try {
      if (state === null) sessionStorage.removeItem(KEY)
      else sessionStorage.setItem(KEY, state)
    } catch {
      // storage is closed to the page: kept for this page only
    }
    setDismissed(state)
  }
  const wrong = readings ? wrongs(readings, cannot, quietFor) : []
  const state = wrong.length > 0 ? wrong.map(one => one.key).sort().join('\n') : null
  // Well again, it is shown again the next time it is not. (Not while the chat is read, nor while First steps say it.)
  if (readings && !quietFor && !state && dismissed !== null) remember(null)
  if (!state || state === dismissed) return null
  const several = wrong.length > 1
  const line = several
    ? `${wrong.length} ${wrong.every(one => one.down) ? "providers aren't answering" : 'need a look'}: ${wrong.map(one => one.name).join(', ')}.`
    : wrong[0].line
  const reason = several ? null : wrong[0].reason
  return (
    <div className="banner">
      <WarningCircle size={15} color="var(--warn)" aria-hidden="true" />
      {/* (Only the line is announced, not its buttons; cut short on a narrow window, the whole of it under the pointer.) */}
      <span role="status" className="banner-text" title={line}>
        {line}
      </span>
      {(several || reason) && (
        <button type="button" className="link-btn" aria-expanded={why} aria-controls="banner-why" onClick={() => setWhy(open => !open)}>
          Details
        </button>
      )}
      {/* shortcut: no "Start the server" button for a local address yet; add it here when slice 64 (local server management) lands. */}
      <button type="button" className="btn btn-small banner-pick" onClick={onModels}>
        Pick another model
      </button>
      <button
        type="button"
        className="icon-btn"
        aria-label="Dismiss model notice"
        onClick={event => {
          // The button goes with the banner: the focus goes to the page it is on (App's .main), not to nowhere.
          event.currentTarget.closest<HTMLElement>('.main')?.focus()
          remember(state)
          setWhy(false)
        }}
      >
        <X size={13} />
      </button>
      {reason && (
        <p id="banner-why" className="banner-why" hidden={!why}>
          {reason}
        </p>
      )}
      {several && (
        <ul id="banner-why" className="banner-why" hidden={!why}>
          {wrong.map(one => (
            <li key={one.key}>{listed(one)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
