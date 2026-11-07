import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Attachment } from '../api/types'
import { useApp } from '../state/store'

interface Issue {
  number: number
  title: string
  url: string
  updated_at: string | null
}

/** What the server kept: the issue as a file of the next message, framed as data (`add_github_issue`). */
interface Kept {
  attachment: Attachment
  number: number
  url: string
}

/**
 * Item 57: a new chat in the project started from a GitHub issue - pasted, or picked from its repository's open ones.
 * Read with the user's own gh; the issue goes as a file of the first message, and the message waits for Send.
 * (Its title is not put in the message: anyone can write an issue, and the message is the user's word.)
 */
export function GitHubIssue({ onStarted }: { onStarted: (conversationId: string) => void }) {
  const projectId = useApp(s => s.projectId)
  const [open, setOpen] = useState(false)
  if (!projectId) return null
  return (
    <>
      <button type="button" className="btn" title="A new chat in this chat’s folder, on a GitHub issue" onClick={() => setOpen(true)}>
        From a GitHub issue…
      </button>
      {open && (
        <IssueDialog
          projectId={projectId}
          onClose={() => setOpen(false)}
          onStarted={id => {
            setOpen(false)
            onStarted(id)
          }}
        />
      )}
    </>
  )
}

function IssueDialog({ projectId, onClose, onStarted }: { projectId: string; onClose: () => void; onStarted: (conversationId: string) => void }) {
  const [listed, setListed] = useState<{ why_not: string | null; issues: Issue[] } | null>(null)
  const [ref, setRef] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The chat made for a try the server refused: the next try goes into it, not into one more empty chat.
  // shortcut: Cancel after a refused try leaves that chat, empty (deleting the open chat opens another
  // new one); delete it when the store can close a chat without opening one.
  const made = useRef<string | null>(null)
  useEffect(() => {
    api.post<{ why_not: string | null; issues: Issue[] }>(`/projects/${projectId}/github-issues`).then(setListed, err => setListed({ why_not: errorText(err), issues: [] }))
  }, [projectId])

  async function start(issue: string) {
    setBusy(true)
    setError(null)
    try {
      if (!made.current) {
        await useApp.getState().newConversation(projectId)
        made.current = useApp.getState().conv?.conversation.id ?? null
      }
      const id = made.current
      if (!id) return
      const kept = await api.post<Kept>(`/conversations/${id}/attachments/github-issue?${new URLSearchParams({ ref: issue })}`)
      useApp.getState().attached(kept.attachment)
      // (The address is gh's word: put in the message only as a github.com address, on one line.)
      const url = /^https:\/\/github\.com\/\S+$/.test(kept.url) ? ` — ${kept.url}` : ''
      useApp.getState().setDraft(id, `Work on GitHub issue #${kept.number}${url} (its text is attached).`)
      onStarted(id)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-back" onKeyDown={e => e.key === 'Escape' && onClose()}>
      <div className="provider-dialog" role="dialog" aria-modal="true" aria-labelledby="gh-issue-heading">
        <div className="provider-dialog-head">
          <h3 id="gh-issue-heading">Start from a GitHub issue</h3>
          <span className="muted">Its text, with its comments, goes with your first message as a file. Nothing runs before you press Send.</span>
        </div>
        <form
          className="field"
          onSubmit={e => {
            e.preventDefault()
            void start(ref)
          }}
        >
          <label htmlFor="gh-issue-ref">Issue address or #number</label>
          <input id="gh-issue-ref" className="input" autoFocus value={ref} placeholder="https://github.com/owner/repo/issues/12" onChange={e => setRef(e.target.value)} />
          <button type="submit" className="btn btn-primary" disabled={busy || !ref.trim()}>
            Start the chat
          </button>
        </form>
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
        <Listed listed={listed} busy={busy} onPick={number => void start(String(number))} />
        <button type="button" className="btn btn-small" onClick={onClose}>
          Cancel
        </button>
      </div>
    </div>
  )
}

/** The repository's open issues, or why there are none: gh is not installed or signed in, or no remote is GitHub's. */
function Listed({ listed, busy, onPick }: { listed: { why_not: string | null; issues: Issue[] } | null; busy: boolean; onPick: (number: number) => void }) {
  if (!listed) return <p className="muted">Reading the open issues…</p>
  if (listed.why_not)
    return (
      <p className="muted">
        No issues listed: {listed.why_not}.
        {/not installed/.test(listed.why_not) && (
          <>
            {' '}
            KOLONİ reads GitHub with your own gh: install it from https://cli.github.com, then sign in with <code>gh auth login</code>.
          </>
        )}
      </p>
    )
  if (!listed.issues.length) return <p className="muted">The repository has no open issues.</p>
  return (
    <ul className="folder-path" aria-label="Open issues">
      {listed.issues.map(issue => (
        <li key={issue.number}>
          <button type="button" className="folder-row" disabled={busy} onClick={() => onPick(issue.number)}>
            #{issue.number} {issue.title}
            {issue.updated_at && <span className="muted"> · updated {new Date(issue.updated_at).toLocaleDateString()}</span>}
          </button>
        </li>
      ))}
    </ul>
  )
}
