import type { Merge, MergeFile } from '../api/types'
import { isKept } from './copies'

/** Why a file an agent changed in its working copy is not in the project. */
function whyNot(merge: Merge, file: MergeFile): string {
  // Whatever stood on the card: what keeps it out of the project is your no.
  if (merge.status === 'rejected') return 'you discarded it'
  if (file.note) return file.note
  return file.state === 'conflict' ? 'changed in the project meanwhile' : 'not taken'
}

/**
 * What of an agent's changes did not reach the project, once that is settled: a line for
 * each such file, with why. Nothing while its card still asks (a kept copy's too), or when
 * all of it is in.
 */
export function NotApplied({ merge, name }: { merge: Merge; name: string }) {
  // (A file that was never offered - `left_out` - is not a change of the agent's that was not applied.)
  const settled = merge.files.filter(f => f.state !== 'applied' && f.state !== 'left_out')
  const left = merge.status === 'pending' || isKept(merge) ? [] : settled
  if (left.length === 0) return null
  return (
    // (A card that only tells: nothing waits on it.)
    <div className="cmd-approval card-tell" role="group" aria-label={`Not all of ${name}'s work reached the project`}>
      <div className="kicker cmd-approval-kicker">Not all of {name}'s work reached the project</div>
      {left.map(f => (
        <div key={f.path} className="card-said">
          <span className="mono">{f.path}</span> — {whyNot(merge, f)}
        </div>
      ))}
    </div>
  )
}
