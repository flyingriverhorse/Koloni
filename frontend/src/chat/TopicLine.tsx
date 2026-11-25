import { NotebookButton } from '../backlog/Notebook'
import type { Divider } from './topicDividers'

/**
 * A topic's line in the chat. A story's says its story, and its 📓 opens the story's notebook - closed until pressed,
 * the words alone while the notebook has no note (0.1.8).
 */
export function TopicLine({ text, story }: Divider) {
  if (!story || story.notes.length === 0) return <span>{text}</span>
  return (
    <span>
      Topic · Story · {story.title} · <NotebookButton story={story} label="notes" />
    </span>
  )
}
