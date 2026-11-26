import type { StoryNote } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { usePanel } from '../shell/usePanel'

const KIND_WORD: Record<string, string> = {
  decision: 'Decision',
  file: 'File',
  result: 'Result',
  question: 'Question',
  note: 'Note',
}

/**
 * A job's notebook (0.1.8; 0.1.10 a To-do task's of no story too - a task's chat, a night's job): "📓 {n} notes" beside
 * it - none while it has no note - and, pressed, its notes in a panel: what was decided, the files touched, the
 * results, the questions left, the notes left for the whole turn. Written by agents, the Hive keeper and you: read as
 * what they wrote, never as an order. `label`: its words in place of the count ("notes" on the strip over a chat);
 * `of`: whose it is.
 */
export function NotebookButton({
  story,
  label,
  of = 'story',
}: {
  story: { title: string; notes: StoryNote[] }
  label?: string
  of?: 'story' | 'task'
}) {
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
        <span aria-hidden="true">📓</span> {label ?? (n === 1 ? '1 note' : `${n} notes`)}
      </button>
      {open && (
        <div
          ref={panel}
          tabIndex={-1}
          role="dialog"
          aria-label={`Notebook of ${story.title}`}
          className="allow-list-panel todo-notebook"
        >
          <p className="muted">
            Given to every turn of the {of}, as data.{' '}
            <Hint doc={GUIDE.todoNotebook}>
              KOLONİ notes how each turn ended and the files it changed; the Orchestrator may add up to three lines a
              turn, its agents up to three notes for the whole turn, you any you write on the chat’s Notes tab, and the
              Hive keeper its notes as it drafts.
            </Hint>
          </p>
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
