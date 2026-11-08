import { Clock, Pause, Play } from '@phosphor-icons/react'
import { useState } from 'react'
import type { Trigger } from '../api/types'

interface Props {
  /** The open project's triggers; null until they have been read. */
  triggers: Trigger[] | null
  /** Every trigger of every project is held back. */
  paused: boolean
  /** Stop everything holds: no trigger starts until its Resume (`HoldStatus`). */
  held?: boolean
  onPause: (paused: boolean) => Promise<void>
  /** Go to the Triggers page. */
  onOpen: () => void
}

/**
 * In the top bar, on every page: how many triggers are on - turns may start by themselves -
 * and one button that holds them all back. With no trigger it says nothing.
 */
export function TriggersStatus({ triggers, paused, held = false, onPause, onOpen }: Props) {
  const [busy, setBusy] = useState(false)
  if (!triggers || (triggers.length === 0 && !paused)) return null
  const on = triggers.filter(trigger => trigger.enabled).length

  async function pause(next: boolean) {
    setBusy(true)
    try {
      await onPause(next)
    } catch {
      // Nothing changed: the bar still says how things stand.
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`triggers-status${paused ? ' triggers-paused' : ''}`}>
      <button type="button" className="btn triggers-count" title="Open the Triggers page" onClick={onOpen}>
        <Clock size={14} />
        {paused ? 'Triggers paused' : `${on} ${on === 1 ? 'trigger' : 'triggers'} ${held ? '· held' : 'on'}`}
      </button>
      {paused ? (
        <button type="button" className="btn" disabled={busy} title="Let the triggers run again" onClick={() => void pause(false)}>
          <Play size={13} />
          Resume
        </button>
      ) : (
        on > 0 && (
          <button
            type="button"
            className="btn"
            disabled={busy}
            // (Named here: in a narrow window its words are not shown, theme/triggers.css.)
            aria-label="Pause all"
            title="Hold every trigger back, and stop the work they started that is still running"
            onClick={() => void pause(true)}
          >
            <Pause size={13} />
            <span className="hold-words">Pause all</span>
          </button>
        )
      )}
    </div>
  )
}
