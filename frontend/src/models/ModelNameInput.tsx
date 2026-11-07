import { useEffect, useId, useState } from 'react'
import type { Provider } from '../api/types'

/** Model names worth offering for a provider, and why there are none when there are none. */
export interface OfferedModels {
  models: string[]
  note: string | null
}

export type LoadModels = (providerId: string) => Promise<OfferedModels>

interface Props {
  id?: string
  label?: string
  value: string
  placeholder?: string
  /** The saved provider whose models are offered; none for one not saved yet. */
  providerId: string | null
  loadModels?: LoadModels
  /** The id its list of names goes by, for other fields to offer the same names. */
  listId?: string
  /** More names to offer: the catalogue's, for a provider not saved yet. */
  more?: string[]
  /** Its note is left out: the form says why there is no list in a line of its own. */
  quiet?: boolean
  onChange: (value: string) => void
}

/**
 * A model name: free text, with the names the provider can list offered as you type.
 * Where a provider has no list, the note says what to type instead; nothing is made up.
 */
export function ModelNameInput({ id, label, value, placeholder, providerId, loadModels, listId: shared, more = [], quiet, onChange }: Props) {
  const ownId = useId()
  const listId = shared ?? ownId
  const [offered, setOffered] = useState<OfferedModels | null>(null)
  useEffect(() => {
    setOffered(null)
    if (!providerId || !loadModels) return
    let current = true
    loadModels(providerId)
      .then(result => {
        if (current) setOffered(result)
      })
      .catch(() => {})  // no suggestions is not an error worth a message
    return () => {
      current = false
    }
  }, [providerId, loadModels])
  return (
    <>
      <input
        id={id}
        aria-label={label}
        className="input mono"
        list={listId}
        value={value}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
      />
      <datalist id={listId}>
        {[...new Set([...(offered?.models ?? []), ...more])].map(name => (
          <option key={name} value={name} />
        ))}
      </datalist>
      {offered?.note && !quiet && <span className="muted provider-note">{offered.note}</span>}
    </>
  )
}

/** A picker's providers by name. One switched off on the Models page is shown and cannot be picked: a choice saved
 *  on it before still reads as it is, and a turn on it is refused with what to do. */
export function ProviderOptions({ providers }: { providers: Pick<Provider, 'id' | 'name' | 'enabled'>[] }) {
  return (
    <>
      {providers.map(p => (
        <option key={p.id} value={p.id} disabled={p.enabled === false}>
          {p.name}
          {p.enabled === false && ' — off'}
        </option>
      ))}
    </>
  )
}
