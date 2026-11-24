import { useState } from 'react'
import { api, errorText } from '../api/client'
import type { Storage } from '../api/types'
import { useConfirm } from './Confirm'

/**
 * Over this many MB of kept copies, a warning: none goes by itself, and a trigger over its budget keeps one a firing -
 * 1 GB is some 20 copies of a mid-size project's files.
 */
export const KEPT_WARN_MB = 1024

/**
 * Settings › Your data: the working copies kept for your word - how many, what they take, and each one's Discard (its
 * card's own: the copy's folder is deleted). KOLONİ deletes none unasked.
 */
export function KeptCopies({ storage, onChanged }: { storage: Storage; onChanged: () => void }) {
  const confirm = useConfirm()
  const [error, setError] = useState<string | null>(null)
  const kept = storage.kept ?? []
  if (kept.length === 0) return null
  const size = storage.kept_mb ?? null
  const discard = (mergeId: string, title: string) =>
    confirm.ask(
      `Delete the copy kept from “${title}”? What it holds is not in the project, and goes with it.`,
      'Discard',
      () => {
        setError(null)
        api.post(`/merges/${mergeId}/reject`).then(onChanged, err => setError(errorText(err)))
      },
      'Keep it',
    )
  return (
    <section className="choice-note" aria-label="Kept copies">
      <p>
        {kept.length === 1 ? '1 copy is' : `${kept.length} copies are`} kept for your word (
        {size === null ? 'size not counted' : `${size} MB`}): take one in on its card in its chat, or discard it here.
      </p>
      {size !== null && size > KEPT_WARN_MB && (
        <p role="alert" className="alert">
          Kept copies take over {KEPT_WARN_MB / 1024} GB: discard the ones you no longer need.
        </p>
      )}
      <ul>
        {kept.map(one => (
          <li key={one.merge_id}>
            {one.title}{' '}
            <button type="button" className="btn" onClick={() => discard(one.merge_id, one.title)}>
              Discard
            </button>
          </li>
        ))}
      </ul>
      {confirm.shown()}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
