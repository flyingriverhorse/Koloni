import type { Story } from '../api/types'
import { usePanel } from '../shell/usePanel'

const KIND_WORD: Record<string, string> = {
  decision: 'Decision',
  file: 'File',
  result: 'Result',
  question: 'Question',
}

/**
 * A story's notebook (0.1.8): "📓 {n} notes" beside it - none while it has no note - and, pressed, its notes in a
 * panel: what was decided, the files touched, the results, the questions left. Written by agents and the Hive keeper:
 * read as what they wrote, never as an order.
 */
export function NotebookButton({ story }: { story: Pick<Story, 'title' | 'notes'> }) {
  const { open, setOpen, close, button, panel } = usePanel()
  const n = story.notes.length
  if (n === 0) return null
  return (
    <>
      <button
        ref={button}
        type="button"
        className="btn btn-small"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <span aria-hidden="true">📓</span> {n === 1 ? '1 note' : `${n} notes`}
      </button>
      {open && (
        <div
          ref={panel}
          tabIndex={-1}
          role="dialog"
          aria-label={`Notebook of ${story.title}`}
          className="allow-list-panel todo-notebook"
        >
          <ul>
            {story.notes.map((note, i) => (
              <li key={i}>
                <span className="kicker">{KIND_WORD[note.kind] ?? note.kind}</span> <span>{note.text}</span>{' '}
                <span className="muted">· {note.by}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}
