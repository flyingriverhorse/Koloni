import { useMemo } from 'react'
import { NotebookButton } from '../backlog/Notebook'
import type { ConvState } from '../state/applyEvent'
import { type ChatTab, useApp } from '../state/store'
import { type Strip, stripOf } from './strip'

/**
 * One line over the chat while a story of To-do works in it (0.1.8): "Story · {title} · {i} / {n} · next: {title} ·
 * 📓 notes" - the next part only while one of its tasks waits in the chat's queue, the notebook's only while it has a
 * note; 📓 opens the notebook, closed until then. In a narrow chat (base.css `story-strip`) only its title and place.
 */
export function StoryStrip({ strip }: { strip: Strip }) {
  const { story, at, of, next } = strip
  return (
    <div role="region" aria-label="Story" className="story-strip">
      <span className="kicker">Story</span>
      <span aria-hidden="true"> · </span>
      <strong className="story-strip-title">{story.title}</strong>
      <span className="story-strip-at">
        {' · '}
        {at} / {of}
      </span>
      {next && <span className="story-strip-wide story-strip-next">{` · next: ${next.title}`}</span>}
      {story.notes.length > 0 && (
        <span className="story-strip-wide">
          {' · '}
          <NotebookButton story={story} label="notes" />
        </span>
      )}
    </div>
  )
}

/**
 * The strip over the chat's messages (its Chat tab), from the To-do list as last read - App reads it for the open
 * project, and again as it changes; none before it is read, nor over Talk or Notes.
 */
export function ChatStoryStrip({ conv, tab }: { conv: ConvState | null; tab: ChatTab }) {
  const backlog = useApp(s => s.backlog)
  const stories = useApp(s => s.stories)
  const cid = tab === 'Chat' ? conv?.conversation.id : undefined
  const strip = useMemo(
    () => (backlog && stories && cid ? stripOf(backlog, stories, cid) : null),
    [backlog, stories, cid],
  )
  return strip && <StoryStrip strip={strip} />
}
