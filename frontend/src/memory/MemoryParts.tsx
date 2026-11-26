/**
 * 0.1.10: the Memory page's two parts - what the project knows (its rules, facts and notes) and the sources to look
 * things up in (what was the Knowledge page). Two pages behind one rail button; Ctrl+K's Knowledge opens the second.
 */
export function MemoryParts({ sources, onPart }: { sources: boolean; onPart: (sources: boolean) => void }) {
  const part = (on: boolean, words: string) => (
    <button
      type="button"
      className={on === sources ? 'btn btn-small btn-primary' : 'btn btn-small'}
      aria-pressed={on === sources}
      onClick={() => onPart(on)}
    >
      {words}
    </button>
  )
  return (
    <div role="group" aria-label="Memory’s parts" className="memory-actions">
      {part(false, 'What the project knows')}
      {part(true, 'Sources to look things up in')}
    </div>
  )
}
