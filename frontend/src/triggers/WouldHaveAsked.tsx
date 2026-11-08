import { CardMore } from '../shell/CardMore'
import type { Refused } from './refused'
import type { Allow } from './triggerText'

interface Props {
  /** What the turn was refused for want of somebody to ask. */
  refused: Refused[]
  /** Open the trigger's form with one of them allowed - not saved. Left out when the trigger is not on record. */
  onAllow?: (allow: Allow) => void
}

/**
 * At the end of a turn nobody was watching: what it would have asked the user for, had
 * somebody been there. Each was refused, and nothing waits; what a trigger can allow has a
 * way to its form.
 */
export function WouldHaveAsked({ refused, onAllow }: Props) {
  if (refused.length === 0) return null
  return (
    // (A card that only tells: nothing waits on it.)
    <div className="cmd-approval card-tell would-ask" role="group" aria-label="It would have asked you">
      <div className="kicker cmd-approval-kicker">Nobody was here to ask</div>
      <p className="card-said">It would have asked you for these. Each was refused, and nothing was done in its place.</p>
      <ul>
        {refused.map(request => (
          <li key={request.id}>
            <span className="mono">{request.what}</span>
            {request.allow && onAllow && (
              <button type="button" className="would-ask-allow" onClick={() => onAllow(request.allow as Allow)}>
                Allow this in the trigger
              </button>
            )}
          </li>
        ))}
      </ul>
      {onAllow && refused.some(request => request.allow) && <CardMore>Allowing one opens the trigger’s form; it is yours to save.</CardMore>}
    </div>
  )
}
