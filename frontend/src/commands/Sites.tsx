import { X } from '@phosphor-icons/react'
import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { AllowedWeb } from '../api/types'

/**
 * K-tarayici-disari A3: adds a site the project's agents' browsers open - its name, and whether
 * it is asked every time. No <form>: it also sits in Project settings' own form, so Enter and the
 * button add the site and never send the settings.
 */
export function SiteForm({ onAdd }: { onAdd: (host: string, askFirst: boolean) => Promise<unknown> }) {
  const [host, setHost] = useState('')
  const [askFirst, setAskFirst] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function add() {
    if (!host.trim()) return
    setError(null)
    try {
      await onAdd(host.trim(), askFirst)
      setHost('')
      setAskFirst(false)
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <>
      <div className="allow-list-rule">
        <input
          className="input mono"
          aria-label="Allow a site"
          placeholder="Allow a site…"
          value={host}
          maxLength={500}
          onChange={e => setHost(e.target.value)}
          onKeyDown={e => {
            if (e.key !== 'Enter') return
            e.preventDefault()
            void add()
          }}
        />
        <label className="muted" title="Asked about every time an agent opens it, Full auto too">
          <input type="checkbox" aria-label="Ask first for the new site" checked={askFirst} onChange={e => setAskFirst(e.target.checked)} /> Ask first
        </label>
        <button type="button" className="btn btn-small" disabled={!host.trim()} onClick={() => void add()}>
          Allow site
        </button>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </>
  )
}

/** Project settings' list of the sites the project's agents open: each marked Ask first or not, removed, or added. */
export function ProjectSites({ projectId, onCount }: { projectId: string; onCount?: (sites: number) => void }) {
  const [sites, setSites] = useState<AllowedWeb[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const read = useCallback(
    () =>
      api.get<AllowedWeb[]>(`/projects/${projectId}/sites`).then(
        listed => {
          setSites(listed)
          onCount?.(listed.length)
        },
        err => setError(errorText(err)),
      ),
    [projectId, onCount],
  )
  useEffect(() => void read(), [read])

  async function act(work: Promise<unknown>) {
    setError(null)
    try {
      await work
    } catch (err) {
      setError(errorText(err))
    }
    await read()
  }

  return (
    <section aria-label="Sites agents open" className="field">
      <h2>Sites agents open</h2>
      <span className="choice-note">The agents’ own browsers open these in every chat of this project without asking, unless marked Ask first.</span>
      {sites?.length === 0 && <p className="muted">None yet.</p>}
      {sites?.map(site => (
        <div key={site.id} className="allow-list-rule">
          <span className="mono">{site.host}</span>
          <label className="muted">
            <input type="checkbox" aria-label={`Ask first for ${site.host}`} checked={site.ask_first} onChange={e => void act(api.patch(`/allowed-web/${site.id}`, { ask_first: e.target.checked }))} /> Ask first
          </label>
          <button type="button" className="icon-btn" aria-label={`Remove site ${site.host}`} onClick={() => void act(api.delete(`/allowed-web/${site.id}`))}>
            <X size={12} />
          </button>
        </div>
      ))}
      <SiteForm onAdd={(host, askFirst) => api.post(`/projects/${projectId}/sites`, { host, ask_first: askFirst }).then(read)} />
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
