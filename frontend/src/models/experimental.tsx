import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ExperimentalClis } from '../api/types'
import type { Mode, ProviderKind } from './ModelsPage'

/** What is offered only under Experimental - agy (0.1.8) and a CLI run Native with its own tools (0.1.10). Still run
 *  where in use. */
export const isExperimental = (kind: ProviderKind, mode?: Mode | null) => kind === 'agy_cli' || mode === 'native'

/** The kinds offered, apart: the usual ones and those under Experimental - shown with experimental features on, or the
 *  kind already chosen (a saved provider's: never hidden). */
export function kindsShown<T extends [ProviderKind, string]>(kinds: T[], kind: ProviderKind, show: boolean) {
  const usual = kinds.filter(([one]) => !isExperimental(one))
  return [usual, kinds.filter(([one]) => isExperimental(one) && (show || one === kind))] as const
}

/** A kind's ways to run, apart in the same way: Native shown with experimental features on, or where it is the way the
 *  provider is saved with (`saved`: changed to another while editing, it is still offered back). (A kind under
 *  Experimental, agy, has its ways as usual ones: its kind says it.) */
export function modesShown(kind: ProviderKind, modes: Mode[], saved: Mode | null, show: boolean) {
  const apart = (mode: Mode) => !isExperimental(kind) && isExperimental(kind, mode)
  return [modes.filter(mode => !apart(mode)), modes.filter(mode => apart(mode) && (show || mode === saved))] as const
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

/** Settings' Show experimental features, as it was read or saved: whatever reads it now follows. */
export function experimentalChanged(show: boolean) {
  told.forEach(listener => listener(show))
}

/** Whether experimental features are shown; off until read, and where it could not be. */
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
