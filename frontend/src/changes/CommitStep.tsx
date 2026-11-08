import { useState } from 'react'
import { errorText } from '../api/client'
import type { Merge } from '../api/types'

const files = (count: number) => `${count} file${count === 1 ? '' : 's'}`
/** A folder git may run programs from at a commit, where the project keeps its hooks in it - or a
 * hook tool's config, which names the commands it runs (`NOT_WRITTEN_UNATTENDED`). */
const HOOKS = /(^|\/)(\.(husky|githooks)\/|\.pre-commit-config\.yaml$|\.?lefthook(-local)?\.ya?ml$|\.lintstagedrc(\.[a-z]+)?$|lint-staged\.config\.[a-z]+$|\.?simple-git-hooks\.[a-z]+$)/i

interface Props {
  merge: Merge
  /** The agent whose changes were taken. */
  name: string
  /** `hooks`: where the commit asks (an agent changed git's hooks or config), with them or without. */
  onCommit: (message: string, hooks?: 'with' | 'without') => Promise<void>
}

/**
 * What was taken from an agent is in the project: the commit of those files, offered - and made
 * only by your own click, with the message as you leave it. "Not now" puts it aside; it stays
 * offered. Once made, it says which commit it is; one that cannot be offered says why.
 */
export function CommitStep({ merge, name, onCommit }: Props) {
  const offer = merge.commit
  const [message, setMessage] = useState(offer?.message ?? '')
  const [aside, setAside] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (!offer) return null
  if (offer.state === 'not_offered') {
    return (
      <div className="muted cmd-approval-note" role="group" aria-label={`Commit of ${name}'s changes`}>
        Not offered as a commit: {offer.message}.
      </div>
    )
  }
  if (offer.state === 'pull_request') {
    // K-dal-takim D2: the branch went to GitHub as a pull request - what was pushed, and where it is.
    return (
      <div className="muted cmd-approval-note" role="group" aria-label={`Pull request of ${name}'s changes`}>
        Pushed to <span className="mono">{offer.pushed}</span> as one commit (<span className="mono">{offer.sha?.slice(0, 10)}</span>)
        and opened a pull request:{' '}
        <a href={offer.url ?? undefined} target="_blank" rel="noreferrer">
          {offer.url}
        </a>
        . Nothing was merged here, and KOLONİ never merges it.
        {offer.notes?.map(note => (
          <div key={note}>{note}.</div>
        ))}
      </div>
    )
  }
  const taken = merge.files.filter(f => f.state === 'applied').map(f => f.path)
  if (offer.state === 'committed') {
    return (
      <div className="muted cmd-approval-note" role="group" aria-label={`Commit of ${name}'s changes`}>
        Committed {files(taken.length)} of {name}'s as <span className="mono">{offer.sha?.slice(0, 10)}</span>: {offer.message}
        {offer.notes?.map(note => (
          <div key={note}>{note}.</div>
        ))}
        {offer.holds && <pre className="cmd-approval-command mono">{offer.holds}</pre>}
      </div>
    )
  }
  if (aside) {
    return (
      <div className="change-actions" role="group" aria-label={`Commit of ${name}'s changes`}>
        <span className="muted cmd-approval-note">
          {name}'s {files(taken.length)} are in the project, not committed.
        </span>
        <button type="button" className="btn btn-small" onClick={() => setAside(false)}>
          Commit…
        </button>
      </div>
    )
  }
  const hooks = taken.filter(path => HOOKS.test(path))

  async function commit(hooks?: 'with' | 'without') {
    setBusy(true)
    setError(null)
    try {
      await onCommit(message, hooks)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cmd-approval" role="group" aria-label={`Commit of ${name}'s changes`}>
      <div className="kicker cmd-approval-kicker">
        Commit {taken.length === 1 ? 'this file' : `these ${taken.length} files`} of {name}'s?
      </div>
      <div className="mono cmd-approval-note">{taken.join(', ')}</div>
      <div className="muted cmd-approval-note">
        The commit holds {name}'s changes to these files and nothing else: edits of your own in them stay uncommitted,
        and what you have staged of other files stays staged (in these files it is unstaged, still in the file). A file
        where yours and {name}'s touch the same lines goes in whole; one git ignores, or one you staged something in
        that the file does not hold, is left out - each is said. It is your commit: the repository's own name and its
        own hooks - a hook may change what goes in, and touch your files itself.
      </div>
      {hooks.map(path => (
        <div key={path} className="alert">
          <span className="mono">{path}</span> — this changes a hook: it runs when you commit.
        </div>
      ))}
      <div className="field">
        <label htmlFor={`commit-message-${merge.id}`}>Message</label>
        <textarea
          id={`commit-message-${merge.id}`}
          className="input mono"
          rows={2}
          maxLength={5000}
          value={message}
          onChange={e => setMessage(e.target.value)}
        />
      </div>
      {offer.asks && (
        <div className="alert" role="alert">
          An agent changed this repository's commit hooks or git settings in this turn: commit with them, or without
          them?
          {offer.asks.includes('config') && (
            <>
              {' '}
              <span className="mono">.git/config</span> was changed: look at it first. Without them is refused, as git
              runs what it names when files are added.
            </>
          )}
        </div>
      )}
      <div className="change-actions">
        {offer.asks ? (
          <>
            <button type="button" className="btn btn-small" disabled={busy || message.trim() === ''} onClick={() => commit('with')}>
              Commit with them
            </button>
            <button type="button" className="btn btn-small" disabled={busy || message.trim() === ''} onClick={() => commit('without')}>
              Commit without them
            </button>
          </>
        ) : (
          <button type="button" className="btn btn-small btn-primary" disabled={busy || message.trim() === ''} onClick={() => commit()}>
            Commit
          </button>
        )}
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => setAside(true)}>
          Not now
        </button>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
