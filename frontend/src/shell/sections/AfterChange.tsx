import { useState } from 'react'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { Row } from './part'

/** Kanıtlı bitiş: what KOLONİ checks after a turn that changed code, in this project. */
export const AFTER_CHANGE: [value: Project['after_change'], label: string][] = [
  ['check', 'Check it'],
  ['tests', 'Tests only'],
  ['nothing', 'Nothing'],
]
/** What it runs and how long a turn waits for it, in sight under the control. */
export const AFTER_CHANGE_NOTE =
  'After a turn that changed code KOLONİ runs this project’s tests once on the work as it now stands and says under the answer what was checked and what was not; failing tests go back to the Orchestrator at most twice. In a turn you watch it waits at most 2 minutes for them. Nothing runs nothing; the Checked lines still say so.'
/** 0162: a project that had turned 89m's switch off is Nothing - said, never silently. */
export const FROM_OFF = 'You had turned off “Finish only when the tests pass”, so this is Nothing: KOLONİ runs no tests after a change here.'

/** Settings › This project › Checks and git: After a change - its part of the section's Save, and its row. */
export function useAfterChange(project: Project) {
  // (A server older than the page has no such field yet: the default.)
  const saved = project.after_change ?? 'check'
  const [after, setAfter] = useState(saved)
  const patch = after !== saved ? { after_change: after } : {}
  const view = (
    <Row
      label="After a change"
      htmlFor="after-change"
      doc={GUIDE.checked}
      warn={
        <span id="after-change-note" className="choice-note">
          {AFTER_CHANGE_NOTE}
          {project.after_change_from_off && after === 'nothing' && <span data-testid="after-change-from-off"> {FROM_OFF}</span>}
        </span>
      }
    >
      <select id="after-change" className="input" value={after} aria-describedby="after-change-note" onChange={e => setAfter(e.target.value as Project['after_change'])}>
        {AFTER_CHANGE.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </Row>
  )
  return { patch, view }
}
