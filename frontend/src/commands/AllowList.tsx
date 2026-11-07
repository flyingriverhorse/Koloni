import { X } from '@phosphor-icons/react'
import { type FormEvent, useState } from 'react'
import { errorText } from '../api/client'
import type { AllowedCommand, AllowedWeb } from '../api/types'
import { usePanel } from '../shell/usePanel'
import { SiteForm } from './Sites'

interface Props {
  rules: AllowedCommand[]
  /** What goes out on the web without asking: searching, or GET from a host. */
  web?: AllowedWeb[]
  onRemove: (ruleId: string) => void
  onRemoveWeb?: (ruleId: string) => void
  /** Allow GET to a host the user writes; with it the list is there even while it is empty. */
  onAllowHost?: (host: string) => Promise<unknown>
  /** K-tarayici-disari: mark a site the agents' browsers open Ask first, or take the mark off. */
  onAskFirst?: (ruleId: string, askFirst: boolean) => void
  /** K-tarayici-disari A3: add a site the user writes, for every chat of the project. */
  onAllowSite?: (host: string, askFirst: boolean) => Promise<unknown>
}

/** A web rule in words, as the list shows it. */
export const webRule = (rule: AllowedWeb) => (rule.kind === 'search' ? 'search the web' : rule.kind === 'page' ? `open ${rule.host}` : `GET ${rule.host}`)

/**
 * What this conversation does without asking - the commands it runs, and what it sends out
 * on the web; nothing is drawn when there is none and none can be added.
 */
export function AllowList({ rules, web = [], onRemove, onRemoveWeb, onAllowHost, onAskFirst, onAllowSite }: Props) {
  const { open, setOpen, close, button, panel } = usePanel()
  const [host, setHost] = useState('')
  const [error, setError] = useState<string | null>(null)
  const count = rules.length + web.length
  if (count === 0 && !onAllowHost) return null
  const all = [
    ...rules.map(rule => ({ id: rule.id, text: rule.prefix, danger: rule.danger, site: null, remove: () => onRemove(rule.id) })),
    ...web.map(rule => ({ id: rule.id, text: webRule(rule), danger: '', site: rule.kind === 'page' ? rule : null, remove: () => onRemoveWeb?.(rule.id) })),
  ]

  async function allow(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await onAllowHost?.(host.trim())
      setHost('')
    } catch (err) {
      setError(errorText(err))
    }
  }

  return (
    <div className="allow-list">
      <button
        ref={button}
        type="button"
        className="btn btn-small"
        aria-expanded={open}
        title="Commands, searches and requests that go without asking in this conversation, and the sites agents open in the project"
        onClick={() => (open ? close() : setOpen(true))}
      >
        {count} {count === 1 ? 'rule' : 'rules'}
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel" role="dialog" aria-label="Runs without asking">
          <div className="kicker">Runs without asking</div>
          {/* However many there are, the panel stays as tall: the rules scroll. */}
          <div className="allow-list-rules">
            {all.map(rule => (
              <div key={rule.id} className="allow-list-rule">
                <span className="mono">{rule.text}</span>
                {/* (A rule kept from before slice 90 for a command that is asked every time now.) */}
                {rule.danger && <span className="muted" title={rule.danger}>covers nothing now - it deletes or names a secret</span>}
                {/* (A site holds in every chat of the project; marked, it is asked every time, at every level.) */}
                {rule.site && (
                  <label className="muted" title="Every chat of this project opens it; marked, it is asked about every time, Full auto too">
                    <input type="checkbox" checked={rule.site.ask_first} disabled={!onAskFirst} onChange={e => onAskFirst?.(rule.id, e.target.checked)} /> Ask first
                  </label>
                )}
                <button type="button" className="icon-btn" aria-label={`Remove rule ${rule.text}`} onClick={rule.remove}>
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
          {onAllowHost && (
            <form className="allow-list-rule" onSubmit={allow}>
              <input className="input mono" aria-label="Allow GET to a host" placeholder="Allow GET to a host…" value={host} maxLength={500} onChange={e => setHost(e.target.value)} />
              <button type="submit" className="btn btn-small" disabled={!host.trim()}>
                Allow
              </button>
            </form>
          )}
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
          {onAllowSite && <SiteForm onAdd={onAllowSite} />}
        </div>
      )}
    </div>
  )
}
