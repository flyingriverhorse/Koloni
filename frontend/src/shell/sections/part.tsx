import { type KeyboardEvent, type ReactNode, useId, useState } from 'react'
import { Cell, type CellFill, type CellTone } from '../Cell'
import { type GuidePlace } from '../guide'
import { Hint } from '../Hint'
import type { Project } from '../../api/types'
import type { ProjectSettingsValues } from '../ProjectSettings'

/**
 * One section of Settings › This project, as its hook keeps it: what its Save sends, whether that can be sent, whether
 * anything of it is not saved yet, and its fields. Every section's hook is called each time, so what is typed in one
 * stays while another is shown.
 */
export interface Part {
  patch: ProjectSettingsValues
  valid: boolean
  changed: boolean
  view: ReactNode
  /** Saved row by row in the section: no Save of its own. */
  own?: boolean
  /** The project as "Use them" saved it: its fields show that. */
  take?: (now: Project) => void
}

/** A section whose Save sends `patch`: changed when there is anything in it, or when it cannot be sent. */
export const part = (
  patch: ProjectSettingsValues,
  valid: boolean,
  view: ReactNode,
  more: Partial<Part> = {},
): Part => ({
  patch,
  valid,
  changed: !valid || Object.keys(patch).length > 0,
  view,
  ...more,
})

/** Enter in a field of what saves itself (a list inside a section's form): never the section's Save. A textarea keeps
 *  its new line. */
export const noSubmit = (event: KeyboardEvent) => {
  if (event.key === 'Enter' && event.target instanceof HTMLInputElement) event.preventDefault()
}

/** A section saved row by row. */
export const own = (view: ReactNode): Part => ({ patch: {}, valid: true, changed: false, view, own: true })

export type Setter<T> = (value: T) => void

/** A whole number from `min` to `max` as typed, else undefined: nothing else is sent. */
export function within(text: string, min: number, max: number): number | undefined {
  return /^\d+$/.test(text.trim()) && Number(text) >= min && Number(text) <= max ? Number(text) : undefined
}
/** The same, where empty is no limit (null). */
export const limitOf = (text: string, max: number) => (text.trim() === '' ? null : within(text, 1, max))
export const typed = (value: number | null | undefined) => (value == null ? '' : String(value))
/** Sent only where it can be and is not what is saved. */
export const sent = <K extends string, T>(key: K, value: T | undefined, kept: T) =>
  value !== undefined && value !== kept ? ({ [key]: value } as Record<K, T>) : {}

/**
 * Where a setting's value comes from (0.1.10's Settings), as its cell says it: set at this level (full honey), its
 * default (an empty rim), or changed and not saved yet (light honey).
 */
export type From = 'here' | 'usual' | 'dirty'
const FROM: Record<From, { tone: CellTone; fill: CellFill; label: string }> = {
  here: { tone: 'honey', fill: 'full', label: 'set here' },
  usual: { tone: 'plain', fill: 'none', label: 'the default' },
  dirty: { tone: 'honey', fill: 'soft', label: 'changed, not saved' },
}
export const Mark = ({ from, hidden }: { from: From; hidden?: boolean }) => <Cell {...FROM[from]} hidden={hidden} />

/** Changed (and not saved) where it differs from what is saved; else set here where that is not its default. */
export const fromOf = (now: unknown, kept: unknown, usual: unknown): From =>
  !same(now, kept) ? 'dirty' : same(kept, usual) ? 'usual' : 'here'
/** (An empty text is no value: a server keeps it as null.) */
const same = (a: unknown, b: unknown) => JSON.stringify(a === '' ? null : a) === JSON.stringify(b === '' ? null : b)

/**
 * One setting on one line (tek-ev): its cell (where its value comes from), its name, the why behind ⓘ, its control -
 * and what it runs or spends in sight under the control, never behind ⓘ. `from` null: a row with no value of its own
 * (a list saved row by row), in line with those that have a cell.
 */
export function Row({
  label,
  htmlFor,
  why,
  whyId,
  doc,
  warn,
  from,
  children,
}: {
  label: string
  htmlFor?: string
  why?: ReactNode
  whyId?: string
  doc?: GuidePlace
  warn?: ReactNode
  from?: From | null
  children: ReactNode
}) {
  return (
    <div className={`set-row${from === undefined ? '' : ' set-row-marked'}`}>
      {from === null ? <span aria-hidden="true" /> : from && <Mark from={from} />}
      <span className="set-name">
        {htmlFor ? <label htmlFor={htmlFor}>{label}</label> : label}
        {why && (
          <Hint id={whyId} doc={doc}>
            {why}
          </Hint>
        )}
      </span>
      <span className="set-value">
        {children}
        {warn}
      </span>
    </div>
  )
}

/** A setting that is its own label (a checkbox, a choice of radios): its cell beside it - never inside the label, whose
 *  words are the control's name. */
export const Marked = ({ from, children }: { from: From; children: ReactNode }) => (
  <div className="set-line">
    <Mark from={from} />
    {children}
  </div>
)

/**
 * A section's head (0.1.10): its name, then what it does now in one sentence - made from the values as they stand on
 * the page, so it changes as they are changed.
 */
export const Said = ({ title, children }: { title: string; children: ReactNode }) => (
  <>
    <h2>{title}</h2>
    <p className="set-said">{children}</p>
  </>
)

/** What the cells mean, once under a section. */
export const Legend = () => (
  <p className="set-legend muted">
    {(['here', 'usual', 'dirty'] as const).map(from => (
      <span key={from}>
        <Mark from={from} hidden /> {FROM[from].label}
      </span>
    ))}
  </p>
)

/**
 * The settings few change, folded under More (the user, 26 Nov: "under an expander, not deleted"): a button that says
 * how many there are and how many are set here. Closed unless asked open (a link, Ctrl+K - each time with a new
 * count). `bad`: a value in it cannot be saved - it opens and stays open, so the field that says why is in sight while
 * Save is off, and is not shut under the cursor once it is fixed.
 */
export function More({
  label = 'More',
  count,
  set,
  bad = false,
  asked,
  children,
}: {
  label?: string
  count: number
  set: number
  bad?: boolean
  asked?: number
  children: ReactNode
}) {
  const [open, setOpen] = useState(asked !== undefined)
  const [seen, setSeen] = useState(asked)
  if (asked !== seen) {
    setSeen(asked)
    if (asked !== undefined) setOpen(true)
  }
  if (bad && !open) setOpen(true)
  const id = useId()
  return (
    <div className="set-more">
      <button
        type="button"
        className="link-btn set-more-button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => !bad && setOpen(!open)}
      >
        {label}{' '}
        <span className="muted">
          · {count} setting{count === 1 ? '' : 's'}, {set ? `${set} set here` : 'all at their defaults'}
        </span>
      </button>
      <div id={id} className="set-more-rows" hidden={!open}>
        {children}
      </div>
    </div>
  )
}

/**
 * A section's Save (0.1.10): a bar at the foot of the section only while something in it is changed, saying what - or
 * that a value in it cannot be saved. What the last save said stays, the bar or not.
 */
export function SaveBar({
  changed,
  valid,
  busy,
  said,
  saved,
}: {
  changed: boolean
  valid: boolean
  busy: boolean
  said: string[]
  saved: string
}) {
  return (
    <div className={`role-actions save-bar${changed ? ' save-bar-on' : ''}`}>
      {changed && (
        <>
          <span className="save-bar-what">
            {!valid
              ? 'A value here cannot be saved yet: see the field that says why.'
              : `${said.length || 'A'} change${said.length > 1 ? 's' : ''} not saved${said.length ? `: ${said.join(', ')}` : ''}`}
          </span>
          <button type="submit" className="btn btn-primary" disabled={busy || !valid}>
            Save
          </button>
        </>
      )}
      <span role="status" className="muted">
        {saved}
      </span>
    </div>
  )
}
