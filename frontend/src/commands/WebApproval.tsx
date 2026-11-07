import { Check, Checks, X } from '@phosphor-icons/react'
import { useState } from 'react'
import { errorText } from '../api/client'
import type { ToolCall, WebRequest } from '../api/types'
import { CardMore } from '../shell/CardMore'
import type { CommandDecision } from './CommandApproval'

interface Props {
  request: WebRequest
  /** The call that asks for it: its recorded arguments hold the body that would leave. */
  call?: ToolCall
  /** Asked for an expert, whose every search is asked (K-uzman): no "always" is offered. */
  expert?: boolean
  onDecide: (decision: CommandDecision) => Promise<void>
}

/** K-tarayici-disari A2: what each action on a site's page asks. */
const ACTS: Partial<Record<WebRequest['kind'], string>> = { form: 'Send this form?', password: 'Type into a password field?', sign: 'Click this?', field: 'Type into this field?' }

/** The body a request would send, as its call's record has it; null without one. */
function bodyOf(call?: ToolCall): string | null {
  try {
    const body = (JSON.parse(call?.arguments ?? '{}') as { body?: unknown }).body
    return typeof body === 'string' && body ? body : null
  } catch {
    return null
  }
}

/**
 * Asks before a web search or an HTTP request leaves this machine: what goes out and where,
 * and whether to remember the answer. The address and the body are shown as they will be
 * sent; header values are never shown - they are kept nowhere.
 */
export function WebApproval({ request, call, expert = false, onDecide }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const search = request.kind === 'search'
  const body = search ? null : bodyOf(call)
  // Only searching, and GET from one place, can be allowed for the conversation. A host
  // alone is that host over https on its usual port; anything else is written in full.
  // A GET with a body or headers of the agent's own is covered by no rule: none is offered.
  const bare = request.headers.length === 0 && request.body_chars === null
  const always = search ? (expert ? null : 'Always allow searching in this conversation') : request.method === 'GET' && bare && request.host ? `Always allow GET to ${request.host}` : null
  const place = request.host?.includes('://') ? request.host : `https://${request.host}`

  async function decide(decision: CommandDecision) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(decision)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  // K-tarayici-disari A2: what the agent's browser would do on a site's page - asked every time.
  const act = ACTS[request.kind]
  if (act)
    return (
      <div className="cmd-approval">
        <div className="kicker cmd-approval-kicker">{act}</div>
        {/* (The site apart: the page's own words, which it chooses, are only in what is quoted.) */}
        <div className="cmd-approval-where">{request.host && <span className="tag">{request.host}</span>}</div>
        <pre className="mono cmd-approval-command">{request.target}</pre>
        <div className="muted cmd-approval-note">Sending a form, a password, a sign-in or a payment on a site is asked every time, at every level.</div>
        <div className="change-actions">
          <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => decide('once')}>
            <Check size={13} />
            Yes, this once
          </button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
            <X size={13} />
            Reject
          </button>
        </div>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
      </div>
    )

  // K-tarayici-disari: a site the agent's own browser would open.
  if (request.kind === 'page')
    return (
      <div className="cmd-approval">
        <div className="kicker cmd-approval-kicker">Open this site?</div>
        <pre className="mono cmd-approval-command">{request.target}</pre>
        <div className="cmd-approval-where">
          <span className="tag">{request.host}</span>
        </div>
        <div className="muted cmd-approval-note">The agent’s own browser opens it, with an empty profile: none of your sign-ins. “Allow this site” lets every chat of this project open it without asking, unless you mark it Ask first.</div>
        <div className="change-actions">
          <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => decide('once')}>
            <Check size={13} />
            This time
          </button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('always')}>
            <Checks size={13} />
            Allow this site
          </button>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
            <X size={13} />
            Reject
          </button>
        </div>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
      </div>
    )

  return (
    <div className="cmd-approval">
      <div className="kicker cmd-approval-kicker">{search ? 'Search the web?' : 'Make this request?'}</div>
      <pre className="mono cmd-approval-command">{search ? request.target : `${request.method} ${request.target}`}</pre>
      <div className="cmd-approval-where">
        {search ? (
          <span className="mono muted">The query leaves this machine.</span>
        ) : (
          <>
            <span className="tag">{request.host}</span>
            {request.headers.map(name => (
              <span key={name} className="mono muted">
                {name}: ***
              </span>
            ))}
            {request.body_chars !== null && <span className="mono muted">with a body of {request.body_chars} characters</span>}
          </>
        )}
      </div>
      {body !== null && (
        <pre className="mono cmd-approval-command" aria-label="The body it sends">
          {body}
        </pre>
      )}
      {!search && <div className="muted cmd-approval-note">Anything written in the address or the body is sent as it is, and kept in the record, except values of fields named like a secret.</div>}
      <div className="change-actions">
        <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => decide('once')}>
          <Check size={13} />
          {search ? 'Search once' : 'Send once'}
        </button>
        {always && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('always')}>
            <Checks size={13} />
            {always}
          </button>
        )}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => decide('reject')}>
          <X size={13} />
          Reject
        </button>
      </div>
      {!always && (
        <CardMore>
          {search ? 'An expert’s search is asked every time.' : `A ${request.method}${request.method === 'GET' ? ' with a body or headers of its own' : ''} is asked every time.`}
        </CardMore>
      )}
      {always && !search && <div className="muted cmd-approval-note">“Always” is for GET to {place} only: this scheme, host and port.</div>}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
