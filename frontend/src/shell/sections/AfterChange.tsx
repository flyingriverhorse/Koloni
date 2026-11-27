import { useState } from 'react'
import type { Project } from '../../api/types'
import { GUIDE } from '../guide'
import { afterChangeSaid } from './afterChangeWords'
import { FoundTests } from './FoundTests'
import { fromOf, Marked, Row } from './part'
import { USUAL } from './usual'

/** Kanıtlı bitiş: what KOLONİ checks after a turn that changed code, in this project. */
export const AFTER_CHANGE: [value: Project['after_change'], label: string][] = [
  ['check', 'Test and review'],
  ['tests', 'Tests only'],
  ['nothing', 'Nothing'],
]
/** Behind ⓘ: what a turn's answer then says, and where the guide says the rest. */
export const AFTER_CHANGE_WHY =
  'After a turn that changed code KOLONİ tests the work as it now stands - and, under Test and review, a Reviewer reads a big or security-touching change - then says under the answer what was checked and what was not.'
/** S3 (decisions 14a, 19): how often work goes back - failing tests and the Reviewer's findings, one count a turn. */
/** The Fix rounds one may choose (k-canli-016: up to 10, the user's). */
export const FIX_ROUNDS = Array.from({ length: 10 }, (_, n) => n + 1)
export const FIX_ROUNDS_NOTE =
  'How often a turn’s failing tests or the Reviewer’s blocking findings go back to the Orchestrator: until it passes (the default) - while each round makes progress, at most 20 times and within the turn’s token limit -, or 1 to 10 times; then you decide (Fix it).'
/** k-canli-016 (the user's): the choice that goes on while each round makes progress - the project's null. */
export const UNTIL = 'Until it passes'
/** S11 (decisions 18, 19): the rounds spent and a test still failing, the next stronger tier tries; off, the work waits. */
export const STRONGER_NOTE =
  'The rounds spent with a test still failing, the next stronger tier on the Models page tries (it says what is wrong first; its model’s use is said). Failing work is never taken in: you decide. A Reviewer’s hold after the rounds waits for you (Fix it).'
/** 0162: a project that had turned 89m's switch off is Nothing - said, never silently. */
export const FROM_OFF =
  'You had turned off “Finish only when the tests pass”, so this is Nothing: KOLONİ runs no tests after a change here.'

/** The Fix rounds row: until it passes (null) or 1 to 10. */
function fixRoundsRow(fix: number | null, setFix: (fix: number | null) => void, rounds: number | null) {
  return (
    <Row
      label="Fix rounds"
      htmlFor="fix-rounds"
      doc={GUIDE.checked}
      from={fromOf(fix, rounds, USUAL.fix_rounds)}
      warn={
        <span id="fix-rounds-note" className="choice-note">
          {FIX_ROUNDS_NOTE}
        </span>
      }
    >
      <select
        id="fix-rounds"
        className="input"
        value={fix ?? 'until'}
        aria-describedby="fix-rounds-note"
        onChange={e => setFix(e.target.value === 'until' ? null : Number(e.target.value))}
      >
        <option value="until">{UNTIL}</option>
        {FIX_ROUNDS.map(n => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    </Row>
  )
}

/** Settings › This project › When the work is done (Checks and git before 0.1.10): After a change - its part of the
 *  section's Save, its rows, and under More what KOLONİ found. */
export function useAfterChange(project: Project) {
  // (A server older than the page has no such field yet: the default.)
  const saved = project.after_change ?? 'check'
  const [after, setAfter] = useState(saved)
  const [forget, setForget] = useState(false)
  // (null: until it passes - the default, and what a server older than the page says by leaving it out)
  const rounds = project.fix_rounds ?? null
  const [fix, setFix] = useState<number | null>(rounds)
  const strongerSaved = project.stronger_model ?? true
  const [stronger, setStronger] = useState(strongerSaved)
  const patch = {
    ...(after !== saved && { after_change: after }),
    ...(fix !== rounds && { fix_rounds: fix ?? ('until' as const) }),
    ...(stronger !== strongerSaved && { stronger_model: stronger }),
    ...(forget && { forget_tests_found: true }),
  }
  const view = (
    <>
      <Row
        label="After a change"
        htmlFor="after-change"
        why={AFTER_CHANGE_WHY}
        doc={GUIDE.checked}
        from={fromOf(after, saved, USUAL.after_change)}
        warn={
          <span id="after-change-note" className="choice-note">
            {afterChangeSaid(project, after, fix, stronger)}
            {project.after_change_from_off && after === 'nothing' && (
              <span data-testid="after-change-from-off"> {FROM_OFF}</span>
            )}
          </span>
        }
      >
        <select
          id="after-change"
          className="input"
          value={after}
          aria-describedby="after-change-note"
          onChange={e => setAfter(e.target.value as Project['after_change'])}
        >
          {AFTER_CHANGE.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Row>
      {fixRoundsRow(fix, setFix, rounds)}
      <Marked from={fromOf(stronger, strongerSaved, USUAL.stronger_model)}>
        <label className="choice">
          <input type="checkbox" checked={stronger} onChange={e => setStronger(e.target.checked)} />
          <span>
            Then a stronger model
            <span className="choice-note">{STRONGER_NOTE}</span>
          </span>
        </label>
      </Marked>
    </>
  )
  return {
    patch,
    view,
    found: <FoundTests found={project.tests_found ?? {}} forget={forget} setForget={setForget} />,
    now: { after_change: after, fix_rounds: fix, stronger_model: stronger },
    saved: () => setForget(false),
  }
}
