import type { KeyboardEvent } from 'react'
import { partId } from './memoryText'

/**
 * 0.1.10: the Memory page's two parts - what the project knows (your words, its facts and notes) and the sources to look
 * things up in (what was the Knowledge page) - as two tabs, each with what waits in it: notes put forward for your
 * word, sources that may be old. Ctrl+K's Knowledge opens the second. `waiting` / `old`: null while not read yet.
 */
export function MemoryParts({
  sources,
  onPart,
  waiting,
  old,
}: {
  sources: boolean
  onPart: (sources: boolean) => void
  waiting: number | null
  old: number | null
}) {
  const part = (on: boolean, words: string, badge: string | null) => (
    <button
      id={partId(on)}
      type="button"
      role="tab"
      className="tab"
      aria-selected={on === sources}
      aria-controls={`${partId(on)}-panel`}
      tabIndex={on === sources ? 0 : -1}
      onClick={() => onPart(on)}
    >
      {words}
      {badge && (
        <>
          {' '}
          <span className="memory-badge">{badge}</span>
        </>
      )}
    </button>
  )
  // Two tabs: either arrow goes to the other, Home to the first, End to the last.
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const to = ({ ArrowRight: !sources, ArrowLeft: !sources, Home: false, End: true } as Record<string, boolean>)[
      event.key
    ]
    if (to === undefined) return
    event.preventDefault()
    onPart(to)
    event.currentTarget.querySelector<HTMLElement>(`#${partId(to)}`)?.focus()
  }
  return (
    <div role="tablist" aria-label="Memory’s parts" className="tabs memory-tabs" onKeyDown={onKey}>
      {part(
        false,
        'What the project knows',
        waiting ? `${waiting} ${waiting === 1 ? 'waits' : 'wait'} for your word` : null,
      )}
      {part(true, 'Sources to look things up in', old ? `${old} may be old` : null)}
    </div>
  )
}

/** 0.1.10: how what the project remembers reaches an agent - three ways, read left to right, above its two parts. */
export function Ways() {
  return (
    <ul aria-label="How memory reaches an agent" className="memory-ways">
      <li>
        <b>Given at the start</b>
        <span className="muted">
          your preferences and rules, to every agent; the Project notes, to the Orchestrator; a fact, when the work
          names its subject
        </span>
      </li>
      <li>
        <b>Found when asked</b>
        <span className="muted">an agent’s Recall: notes and facts, earlier messages, linked projects</span>
      </li>
      <li>
        <b>Sources given to a role</b>
        <span className="muted">only a role you give one looks in it: docs, repositories, folders</span>
      </li>
    </ul>
  )
}
