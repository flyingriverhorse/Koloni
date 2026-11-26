import { type ReactNode, useEffect, useRef } from 'react'
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
 * One setting on one line (tek-ev): its name, the why behind ⓘ, its control - and what it runs or spends in sight
 * under the control, never behind ⓘ.
 */
export function Row({
  label,
  htmlFor,
  why,
  whyId,
  doc,
  warn,
  children,
}: {
  label: string
  htmlFor?: string
  why?: ReactNode
  whyId?: string
  doc?: GuidePlace
  warn?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="set-row">
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

/**
 * The limits few change, folded under More limits (the user, 26 Nov: "under an expander, not deleted"); closed unless
 * `open` (a link to one of them), and " · set" on it where one is not its default, as a role's safety stops say it.
 * `bad`: a value in it cannot be saved - it stays open, so the field that says why is in sight while Save is off.
 */
export function MoreLimits({
  set,
  bad = false,
  open = false,
  children,
}: {
  set: boolean
  bad?: boolean
  open?: boolean
  children: ReactNode
}) {
  const box = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    if (bad && box.current) box.current.open = true
  }, [bad])
  return (
    <details
      ref={box}
      className="more more-limits"
      open={open}
      onToggle={e => {
        if (bad) e.currentTarget.open = true
      }}
    >
      <summary>More limits{set && <span className="muted"> · set</span>}</summary>
      {children}
    </details>
  )
}
