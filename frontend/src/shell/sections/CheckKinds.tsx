import { useState } from 'react'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { Row } from './part'

/** S5a: the kinds of work KOLONİ checks after a turn wrote them, as Settings names them (S5b adds Pages). */
export const CHECK_KINDS: [kind: string, label: string][] = [
  ['docs', 'Documents'],
  ['slides', 'Slides'],
  ['diagram', 'Diagrams'],
  ['data', 'Data'],
]
/** What they check, in sight under the boxes. */
export const CHECK_KINDS_NOTE =
  'Under Test and review, after a turn that wrote such files, KOLONİ checks them without a model: links and headings, whether a diagram parses and is connected, CSV rows and notebook cells, empty slides. A sure problem goes back as a fix round.'

/** Settings › This project › Checks and git: Check by kind of work - all on unless switched off (a kind left out is on). */
export function useCheckKinds(project: Project) {
  // (A server older than the page, or a test's project, has no such field: all on.)
  const saved: Record<string, boolean> = project.check_kinds ?? {}
  const [kinds, setKinds] = useState(saved)
  const on = (kind: string, from: Record<string, boolean>) => from[kind] ?? true
  const changed = CHECK_KINDS.filter(([kind]) => on(kind, kinds) !== on(kind, saved)).map(([kind]) => [kind, on(kind, kinds)])
  const patch = changed.length ? { check_kinds: Object.fromEntries(changed) as Record<string, boolean> } : {}
  const view = (
    <Row label="Check by kind of work" doc={GUIDE.checked} warn={<span id="check-kinds-note" className="choice-note">{CHECK_KINDS_NOTE}</span>}>
      {/* (As the branch's way below: the boxes side by side, each label whole, wrapping where they do not fit.) */}
      <fieldset className="choice" aria-label="Check by kind of work" aria-describedby="check-kinds-note">
        {CHECK_KINDS.map(([kind, label]) => (
          <label key={kind}>
            <input type="checkbox" checked={on(kind, kinds)} onChange={e => setKinds(was => ({ ...was, [kind]: e.target.checked }))} /> <span>{label}</span>
          </label>
        ))}
      </fieldset>
    </Row>
  )
  return { patch, view }
}
