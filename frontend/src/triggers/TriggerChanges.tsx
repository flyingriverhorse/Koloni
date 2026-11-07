import type { TriggerLogEntry } from '../api/types'
import { when } from '../canvas/turns'

interface Props {
  /** What was done, newest first. */
  changes: TriggerLogEntry[]
  /** What the list is called. */
  label: string
  /** Say which trigger each row is about: the project's list, where they are of several. */
  named?: boolean
}

/**
 * What was made and changed on triggers, as plain rows: when, which trigger, what, and how
 * it stood afterwards. A trigger is a standing leave to act with nobody watching, so this
 * stays - also for a trigger that has since been deleted.
 */
export function TriggerChanges({ changes, label, named = false }: Props) {
  return (
    <ul className="trigger-changes" aria-label={label}>
      {changes.map(change => (
        <li key={change.id}>
          <span className="mono muted">{when(change.at)}</span> · {named && <>{change.name} · </>}
          {change.what}
          {change.detail && <>: {change.detail}</>}
        </li>
      ))}
    </ul>
  )
}
