import type { Waiting } from '../api/types'
import { type Decide, PushRow, type PushWords, WaitingRow } from '../backlog/WaitingForYou'
import { useAsk } from '../memory/useAsk'
import { useApp } from '../state/store'

/** The push's words here: what its buttons do - its Run opens a pull request only where the project's way says so. */
const PUSH: PushWords = ['Push', 'Push anyway', 'Not now']
const PUSH_PR: PushWords = ['Push and open PR', 'Push anyway', 'Not now']

/**
 * A row the night parked for you (§10), on Ready for you: Waiting for you's own row and its words - a command's Run or
 * Reject, a question's answer; the push's Push (and open PR) or Not now, its notes and Push anyway - each only once you
 * are back and its job is not at work, as the row says.
 */
export function ParkedRow({ row, awayId }: { row: Waiting; awayId: string }) {
  const { busy, error, ask } = useAsk()
  const decide: Decide = (one, word, answer) =>
    void ask(() => useApp.getState().awayDo(awayId, `waiting/${one.id}`, { word, answer }))
  return (
    <>
      <ol className="waiting-rows">
        {row.kind === 'push' ? (
          <PushRow row={row} awayId={awayId} words={row.opens_pr ? PUSH_PR : PUSH} />
        ) : (
          <WaitingRow row={row} busy={busy} decide={decide} />
        )}
      </ol>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </>
  )
}
