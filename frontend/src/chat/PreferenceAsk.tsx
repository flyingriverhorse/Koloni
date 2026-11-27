import { useId } from 'react'
import type { MemoryRecord } from '../api/types'
import { useAsk } from '../memory/useAsk'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'

/** The Orchestrator's suggestions for your preferences made in this chat (suggest_preference), waiting for your word. */
const preferenceAsks = (conv: ConvState | null, suggestions: MemoryRecord[] | undefined) =>
  conv ? (suggestions ?? []).filter(one => one.origin === 'agent' && one.conversation_id === conv.conversation.id) : []

/**
 * suggest_preference (the user, 28 Nov): "Add this to your preferences: “…”?" over the message box, for each line the
 * Orchestrator suggested from your own words in this chat - Add puts it in Your preferences, Not now leaves them as they
 * are. The same suggestion as on the Memory page and Ready for you: answered in one place, gone from all.
 */
export function PreferenceAsk({ conv, open }: { conv: ConvState | null; open: boolean }) {
  const asks = preferenceAsks(
    open ? conv : null,
    useApp(s => s.memory?.suggestions),
  )
  if (asks.length === 0) return null
  return (
    <>
      {asks.map(one => (
        <Ask key={one.id} record={one} />
      ))}
    </>
  )
}

function Ask({ record }: { record: MemoryRecord }) {
  const id = useId()
  const { busy, error, ask } = useAsk()
  const s = useApp.getState()
  return (
    <section aria-labelledby={id} className="cmd-approval card-tell">
      <h3 id={id} className="kicker cmd-approval-kicker">
        Your preferences
      </h3>
      <p>
        Add this to your preferences: <q>{record.text}</q>?
      </p>
      <div className="decided-btns">
        <button
          type="button"
          className="btn btn-small btn-primary"
          disabled={busy}
          onClick={() => void ask(() => s.addPreference(record.id))}
        >
          Add
        </button>
        <button
          type="button"
          className="btn btn-small"
          disabled={busy}
          onClick={() => void ask(() => s.rejectMemory(record.id))}
        >
          Not now
        </button>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
