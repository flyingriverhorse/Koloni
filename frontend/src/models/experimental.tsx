import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ExperimentalClis } from '../api/types'
import type { ProviderKind } from './ModelsPage'

/** 0.1.8: what is offered only under Experimental - agy (0.1.10: Codex run one step at a time is cut). Still run where in use. */
export const isExperimental = (kind: ProviderKind) => kind === 'agy_cli'

/** The kinds offered, apart: the usual ones and those under Experimental - shown with experimental CLIs on, or the
 *  kind already chosen (a saved provider's: never hidden). */
export function kindsShown<T extends [ProviderKind, string]>(kinds: T[], kind: ProviderKind, show: boolean) {
  const usual = kinds.filter(([one]) => !isExperimental(one))
  return [usual, kinds.filter(([one]) => isExperimental(one) && (show || one === kind))] as const
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

// Every page that reads it, told when Settings changes it: Settings keeps its levels mounted, and This project ›
// Memory and web shows Let agy search too by it.
const told = new Set<(show: boolean) => void>()

/** Settings' Show experimental CLIs, as it was read or saved: whatever reads it now follows. */
export function experimentalChanged(show: boolean) {
  told.forEach(listener => listener(show))
}

/** Whether experimental CLIs are shown; off until read, and where it could not be. */
export function useExperimentalClis(): boolean {
  const [show, setShow] = useState(false)
  useEffect(() => {
    let current = true
    told.add(setShow)
    api.get<ExperimentalClis>('/experimental-clis').then(
      read => current && setShow(read.show),
      () => {},
    )
    return () => {
      current = false
      told.delete(setShow)
    }
  }, [])
  return show
}
