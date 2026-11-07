import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { WorkingCopy as Copy } from '../api/types'

export interface Counts {
  files: number
  additions: number
  deletions: number
}

/** What a working copy's files add up to. */
export const counted = (copy: Copy): Counts => ({
  files: copy.files.length,
  additions: copy.files.reduce((n, f) => n + f.additions, 0),
  deletions: copy.files.reduce((n, f) => n + f.deletions, 0),
})

/**
 * "Working copy: 3 files changed +40 −12 · See changes · Open folder" (slice 70): what an agent's own copy changed
 * so far, while its work goes on. See changes opens its diff in the Workspace; Open folder the copy's folder in the
 * system's file manager (the server opens its own copy's folder, never one named here).
 */
export function CopyCounts({ agentId, counts, onSee }: { agentId: string; counts: Counts; onSee(): void }) {
  const [refused, setRefused] = useState<string | null>(null)
  return (
    <div className="working-copy">
      <span className="muted">Working copy:</span>{' '}
      <span>{`${counts.files} ${counts.files === 1 ? 'file' : 'files'} changed`}</span>{' '}
      <span className="mono" style={{ color: 'var(--ok)' }}>
        +{counts.additions}
      </span>{' '}
      <span className="mono" style={{ color: 'var(--del)' }}>
        −{counts.deletions}
      </span>{' '}
      <button type="button" className="btn btn-small" onClick={onSee}>
        See changes
      </button>
      <button type="button" className="btn btn-small" onClick={() => api.post(`/agents/${agentId}/copy/open`).then(() => setRefused(null), err => setRefused(errorText(err)))}>
        Open folder
      </button>
      {refused && (
        <span role="alert" className="muted">
          {refused}
        </span>
      )}
    </div>
  )
}

/** An agent's working copy, read again whenever `stamp` changes: what it holds that the project does not; null where it has none, undefined till read. */
export function useWorkingCopy(agentId: string | null, stamp: string): Copy | null | undefined {
  const [copy, setCopy] = useState<Copy | null | undefined>(undefined)
  useEffect(() => {
    if (!agentId) return
    let gone = false
    api.get<Copy>(`/agents/${agentId}/copy`).then(
      read => !gone && setCopy(read),
      () => !gone && setCopy(null),
    )
    return () => {
      gone = true
    }
  }, [agentId, stamp])
  return agentId ? copy : null
}
