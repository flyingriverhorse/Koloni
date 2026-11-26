import { useState } from 'react'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { Row } from './part'

/** S5a: the kinds of work KOLONİ checks after a turn wrote them, as Settings names them; S5b's Pages ("ui"); 0.1.7's Config, Scripts and Code style and types; and 0.1.10's box for A test for the change ("test"). */
export const CHECK_KINDS: [kind: string, label: string][] = [
  ['docs', 'Documents'],
  ['slides', 'Slides'],
  ['diagram', 'Diagrams'],
  ['data', 'Data'],
  ['ui', 'Pages'],
  ['config', 'Config'],
  ['scripts', 'Scripts'],
  ['style', 'Code style and types'],
  ['test', 'A test for the change'],
]
/** 0.1.10 (app/proof.py OFF_UNLESS_TICKED): off unless ticked - a project that never changed them has them off. */
const OFF_UNLESS_TICKED = ['ui', 'test']
/** What they check, in sight under the boxes. */
export const CHECK_KINDS_NOTE =
  'Under Test and review, after a turn that wrote such files, KOLONİ checks them without a model: links and headings, whether a diagram parses and is connected, CSV rows and notebook cells, empty slides, JSON, YAML and TOML files that parse (a package.json, pyproject.toml, GitHub workflow or Compose file in its expected shape), shell and PowerShell scripts that parse (read by their own shell, never run), the project’s own ruff, eslint, tsc and mypy where it has them (each asks before it runs unasked, a yes for that line); ticked, a changed page (or the running preview, for a component) in its own browser at 375, 768 and 1280 px for console errors, sideways scrolling and accessibility (alt text, names, contrast). A sure problem goes back as a fix round. Ticked, A test for the change asks the Orchestrator once for a test where code changed and no test did, under Tests only too. Pages and A test for the change are off unless ticked.'

/** Settings › This project › Checks and git: Check by kind of work - on unless switched off (a kind left out is on), but Pages and A test for the change, off unless ticked. */
export function useCheckKinds(project: Project) {
  // (A server older than the page, or a test's project, has no such field: all on.)
  const saved: Record<string, boolean> = project.check_kinds ?? {}
  const [kinds, setKinds] = useState(saved)
  const on = (kind: string, from: Record<string, boolean>) => from[kind] ?? !OFF_UNLESS_TICKED.includes(kind)
  const changed = CHECK_KINDS.filter(([kind]) => on(kind, kinds) !== on(kind, saved)).map(([kind]) => [
    kind,
    on(kind, kinds),
  ])
  const patch = changed.length ? { check_kinds: Object.fromEntries(changed) as Record<string, boolean> } : {}
  const view = (
    <Row
      label="Check by kind of work"
      doc={GUIDE.checked}
      warn={
        <span id="check-kinds-note" className="choice-note">
          {CHECK_KINDS_NOTE}
        </span>
      }
    >
      {/* (As the branch's way below: the boxes side by side, each label whole, wrapping where they do not fit.) */}
      <fieldset className="choice" aria-label="Check by kind of work" aria-describedby="check-kinds-note">
        {CHECK_KINDS.map(([kind, label]) => (
          <label key={kind}>
            <input
              type="checkbox"
              checked={on(kind, kinds)}
              onChange={e => setKinds(was => ({ ...was, [kind]: e.target.checked }))}
            />{' '}
            <span>{label}</span>
          </label>
        ))}
      </fieldset>
    </Row>
  )
  return { patch, view }
}
