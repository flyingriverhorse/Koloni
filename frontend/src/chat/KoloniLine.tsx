import { FolderOpen, GitBranch } from '@phosphor-icons/react'
import { api } from '../api/client'
import type { Message } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { useApp } from '../state/store'

// KOLONİ's own words for a line suggest_preference added (`app/preference_words.py`: ADDED, UNDONE).
const ADDED = 'Added to your preferences: '
const UNDONE = ' · undone'

/** A line of KOLONİ's own in the chat, which no agent wrote: on git, on where a turn's work is, or another. */
export function KoloniLine({ message, onShowGit }: { message: Message; onShowGit?: () => void }) {
  if (message.role === 'git') {
    // What a turn did to the project's git (slice 70): a branch switched, a worktree opened.
    return (
      <div className="msg msg-from git-said" role="note">
        <GitBranch size={13} aria-hidden />
        <span className="git-said-text">{message.content}</span>
        {onShowGit && (
          <button type="button" className="btn btn-small" onClick={onShowGit}>
            Show git
          </button>
        )}
      </div>
    )
  }
  if (message.role === 'landed') {
    // B-205: under the answer, where the turn's work is - from KOLONİ's records, not the model's words.
    return (
      <p className="msg msg-from landed-said" role="note" title="From KOLONİ's records, not the model's words">
        <FolderOpen size={13} aria-hidden />
        <span>
          <span className="landed-by">KOLONİ:</span> {message.content}
        </span>
      </p>
    )
  }
  if (message.content.startsWith(ADDED)) return <AddedLine message={message} />
  // A role a Lead's answer named but never opened this turn (K-lead-andigi-rol); at Take in, what stays in a copy (B-383).
  // Above the answer it follows (`answerLast`).
  return (
    <p className="msg msg-from muted" role="note">
      {message.content}
    </p>
  )
}

/** suggest_preference (Add them, tell me): "Added to your preferences: “…”" - your own sentence - with Undo, which takes
 *  exactly that line out of Your preferences; once undone, the line says so (` · undone`). */
function AddedLine({ message }: { message: Message }) {
  const { busy, error, ask } = useAsk()
  const undone = message.content.endsWith(UNDONE)
  return (
    <p className="msg msg-from muted" role="note">
      {message.content}
      {!undone && (
        <>
          {' · '}
          <button
            type="button"
            className="usage-open"
            disabled={busy}
            onClick={() =>
              void ask(async () => {
                await api.post(`/preference-lines/${message.id}/undo`)
                await useApp.getState().loadMemory()
              })
            }
          >
            Undo
          </button>
        </>
      )}
      {error && (
        <span role="alert" className="alert">
          {error}
        </span>
      )}
    </p>
  )
}
