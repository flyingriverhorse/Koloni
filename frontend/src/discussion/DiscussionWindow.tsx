import { ChatsCircle, X } from '@phosphor-icons/react'
import { type FormEvent, Fragment, useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import { placed } from '../shell/move'
import type { ConvState } from '../state/applyEvent'
import { discussionLine, nameIn, speakerOf } from './discussionText'

interface Props {
  state: ConvState
  discussionId: string
  onClose: () => void
  onSay: (discussionId: string, content: string) => Promise<void>
  onEnd: (discussionId: string) => Promise<void>
}

/**
 * The shared place of a discussion: everything said in it, by whom, round by round.
 * While it runs you can speak in it yourself, or end it.
 */
export function DiscussionWindow({ state, discussionId, onClose, onSay, onEnd }: Props) {
  const feed = useRef<HTMLDivElement>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const el = feed.current
    if (el) el.scrollTop = el.scrollHeight
  })

  const discussion = state.discussions.find(d => d.id === discussionId)
  if (!discussion) return null
  const posts = state.discussionPosts.filter(p => p.discussion_id === discussion.id)
  const running = discussion.status === 'running'
  const speaker = speakerOf(state, discussion)

  async function act(work: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function say(event: FormEvent) {
    event.preventDefault()
    const content = draft.trim()
    if (!content) return
    void act(async () => {
      await onSay(discussion!.id, content)
      setDraft('')
    })
  }

  return (
    <section ref={placed} className="changes agent-window discussion-window" aria-label="Discussion">
      <div className="changes-bar">
        <ChatsCircle size={15} color="var(--accent)" />
        <span className="changes-title">Discussion</span>
        <span className="mono muted changes-summary">{discussionLine(discussion)}</span>
        <span className="changes-spacer" />
        <button type="button" className="icon-btn" aria-label="Close discussion" onClick={onClose}>
          <X size={14} />
        </button>
      </div>
      <div className="agent-feed" ref={feed}>
        <div className="agent-feed-task">{discussion.topic}</div>
        <div className="mono muted discussion-members">
          {discussion.members
            .map(m => nameIn(state, m.agent_id) + (m.status === 'left' ? ' (left)' : ''))
            .join(' · ')}
        </div>
        {posts.length === 0 && !speaker && <p className="muted">Nothing said yet.</p>}
        {posts.map((post, index) => {
          const who = nameIn(state, post.agent_id)
          return (
            <Fragment key={post.id}>
              {(index === 0 || posts[index - 1].round !== post.round) && (
                <div className="discussion-round mono muted">Round {post.round}</div>
              )}
              {post.kind === 'left' ? (
                <div className="muted">
                  {who} left the discussion: {post.content}
                </div>
              ) : post.passed ? (
                <div className="muted">{who} has nothing to add</div>
              ) : (
                <div className="discussion-post">
                  <div className={`asked-by mono${post.agent_id === null ? ' discussion-you' : ''}`}>{who}</div>
                  <div className="discussion-said">{post.content}</div>
                </div>
              )}
            </Fragment>
          )
        })}
        {speaker && <div className="msg-status mono">{speaker.name} is speaking…</div>}
      </div>
      {running && (
        <form className="discussion-say" onSubmit={say}>
          <input
            className="input"
            aria-label="Say something to everyone"
            placeholder="Say something to everyone"
            value={draft}
            onChange={e => setDraft(e.target.value)}
          />
          <button type="submit" className="btn btn-small btn-primary" disabled={busy || !draft.trim()}>
            Say
          </button>
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            onClick={() => void act(() => onEnd(discussion.id))}
          >
            End discussion
          </button>
        </form>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
