import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ExperimentalClis } from '../api/types'
import type { Mode, ProviderKind } from './ModelsPage'

/** 0.1.8: what is offered only under Experimental - agy, and Codex run one step at a time. Still run where in use. */
export const isExperimental = (kind: ProviderKind, mode?: Mode | null) =>
  kind === 'agy_cli' || (kind === 'codex_cli' && mode === 'step')

/** The kinds offered, apart: the usual ones and those under Experimental - shown with experimental CLIs on, or the
 *  kind already chosen (a saved provider's: never hidden). */
export function kindsShown<T extends [ProviderKind, string]>(kinds: T[], kind: ProviderKind, show: boolean) {
  const usual = kinds.filter(([one]) => !isExperimental(one))
  return [usual, kinds.filter(([one]) => isExperimental(one) && (show || one === kind))] as const
}

/** A kind's ways to run, apart in the same way: an experimental one shown with experimental CLIs on, or where it is
 *  the way the provider runs now. (A kind under Experimental, agy, has its ways as usual ones: its kind says it.) */
export function modesShown(kind: ProviderKind, modes: Mode[], runs: Mode | null, show: boolean) {
  const apart = (mode: Mode) => !isExperimental(kind) && isExperimental(kind, mode)
  return [modes.filter(mode => !apart(mode)), modes.filter(mode => apart(mode) && (show || mode === runs))] as const
}

/** A select's options, those under Experimental in a group of their own. */
export function Choices<T extends string>({
  usual,
  experimental,
}: {
  usual: [T, string][]
  experimental: [T, string][]
}) {
  const option = ([value, label]: [T, string]) => (
    <option key={value} value={value}>
      {label}
    </option>
  )
  return (
    <>
      {usual.map(option)}
      {experimental.length > 0 && <optgroup label="Experimental">{experimental.map(option)}</optgroup>}
    </>
  )
}

/** Whether experimental CLIs are shown; off until read, and where it could not be. */
export function useExperimentalClis(): boolean {
  const [show, setShow] = useState(false)
  useEffect(() => {
    let current = true
    api.get<ExperimentalClis>('/experimental-clis').then(
      told => current && setShow(told.show),
      () => {},
    )
    return () => {
      current = false
    }
  }, [])
  return show
}
