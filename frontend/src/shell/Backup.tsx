import { useEffect, useRef, useState } from 'react'
import { api, download, errorText } from '../api/client'
import type { Restored, Staged } from '../api/types'

export const RESTORED_NOTE =
  'Ready to restore. It replaces your data the next time KOLONİ starts: close KOLONİ and start it again. Until then nothing changes, and anything you do meanwhile is set aside with your current data in runtime/before-restore/.'
export const HELD_NOTE = 'Triggers and backlogs wait until you press Resume.'
export const SECRETS_NOTE =
  "Without this, the keys KOLONİ stores in its settings are left out. A key that was ever written in a chat, an agent's output or a command stays in the file: keep it private either way."
export const TRUST_NOTE = 'Restore only a file you exported yourself: it decides which programs KOLONİ may start.'

const when = (made: string | null) => (made ? new Date(made).toLocaleString() : 'an export')

/**
 * Your data, in Settings › The app (K-disa-aktar; tek-ev: no longer in the top bar): everything of KOLONİ's exported to one .zip, and a .zip restored at the next
 * start. The export is a POST (it says its origin) saved by `download`: the key never in an address the browser keeps, and a refusal
 * said here.
 */
export function Backup() {
  const [secrets, setSecrets] = useState(false)
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [staged, setStaged] = useState<Restored | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pick = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.get<Staged>('/backup/staged').then(
      told => {
        setStaged(told.staged)
        setFailed(told.failed)
      },
      err => setError(errorText(err)),
    )
  }, [])

  const restore = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      setStaged(await api.upload<Restored>('/backup/restore', file))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
      if (pick.current) pick.current.value = '' // (the same file may be chosen again)
    }
  }

  const exportAll = async () => {
    setExporting(true)
    setError(null)
    try {
      await download('POST', `/backup/export?secrets=${secrets}`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setExporting(false)
    }
  }

  const cancel = async () => {
    setError(null)
    try {
      await api.delete('/backup/staged')
      setStaged(null)
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <section className="backup" aria-label="Your data">
      <div className="kicker">Export</div>
      <p className="muted">
        Your KOLONİ data in one .zip: chats, agents, providers, memory, triggers, skills and attachments. Not in it: your project folders
        (their .koloni/ knowledge too), working copies, logs, previews, the CLIs’ own folders and the database’s upgrade backups.
      </p>
      <form
        onSubmit={e => {
          e.preventDefault()
          void exportAll()
        }}
      >
        <label className="choice">
          <input type="checkbox" checked={secrets} aria-describedby="backup-secrets-note" onChange={e => setSecrets(e.target.checked)} />
          <span>Include API keys and secrets (keep this file safe)</span>
        </label>
        <p id="backup-secrets-note" className="muted">
          {SECRETS_NOTE}
        </p>
        <button type="submit" className="btn btn-small btn-primary" disabled={exporting}>
          {exporting ? 'Exporting…' : 'Export everything'}
        </button>
      </form>
      <div className="kicker">Restore</div>
      <p className="muted">{TRUST_NOTE}</p>
      <div className="change-actions">
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => pick.current?.click()}>
          {busy ? 'Reading the file…' : 'Restore from a file…'}
        </button>
        <input ref={pick} type="file" hidden accept=".zip,application/zip" aria-label="An export to restore" onChange={e => void restore(e.target.files?.[0])} />
      </div>
      {staged && (
        <div role="status">
          <p>
            A restore of {when(staged.made_at)} waits for the next start.{' '}
            <button type="button" className="link-btn" onClick={() => void cancel()}>
              Cancel
            </button>
          </p>
          <p>{RESTORED_NOTE}</p>
          <p className="muted">{HELD_NOTE}</p>
          {!staged.secrets && staged.need_keys.length > 0 && (
            <p className="muted">The file has no keys. These need theirs again: {staged.need_keys.join(', ')}.</p>
          )}
        </div>
      )}
      {failed && <p className="muted">A restore could not be applied at the last start: it is kept in {failed}, and KOLONİ’s log says why.</p>}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
