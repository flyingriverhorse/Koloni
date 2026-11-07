import type { ReactNode } from 'react'
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
  /** After its Save: what is not kept in its fields. */
  saved?: () => void
  /** The project as "Use them" saved it: its fields show that. */
  take?: (now: Project) => void
}

/** A section whose Save sends `patch`: changed when there is anything in it, or when it cannot be sent. */
export const part = (patch: ProjectSettingsValues, valid: boolean, view: ReactNode, more: Partial<Part> = {}): Part => ({
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
export const sent = <K extends string, T>(key: K, value: T | undefined, kept: T) => (value !== undefined && value !== kept ? ({ [key]: value } as Record<K, T>) : {})

/**
 * One setting on one line (tek-ev): its name, the why behind ⓘ, its control - and what it runs or spends in sight
 * under the control, never behind ⓘ.
 */
export function Row({ label, htmlFor, why, whyId, doc, warn, children }: { label: string; htmlFor?: string; why?: ReactNode; whyId?: string; doc?: GuidePlace; warn?: ReactNode; children: ReactNode }) {
  return (
    <div className="set-row">
      <span className="set-name">
        {htmlFor ? <label htmlFor={htmlFor}>{label}</label> : label}
        {why && <Hint id={whyId} doc={doc}>{why}</Hint>}
      </span>
      <span className="set-value">
        {children}
        {warn}
      </span>
    </div>
  )
}
