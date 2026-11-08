import type { Agent } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { type TeamRequest, askerOf, standsLine } from '../agents/teamRequests'

/**
 * A request between teams in the chat (K-takimlar-arasi), where the Lead's turn opened the asked team's lead for it:
 * who asked which team for what, and how it stands. A click shows that lead on the canvas.
 */
export function RequestRow({ request, lead, state, onSelect }: { request: TeamRequest; lead: Agent; state: ConvState; onSelect: (agentId: string) => void }) {
  return (
    <div className="request-card">
      <div className="kicker request-card-who">
        {askerOf(request)} → {request.to}
      </div>
      <div className="request-card-what">
        {request.what.split('\n')[0]}
        {request.contract && <span className="muted"> · its contract is in the shared folder</span>}
      </div>
      <button type="button" className="link-btn request-card-line" title="Show its lead on the canvas" onClick={() => onSelect(lead.id)}>
        {standsLine(request, state.agents.findLast(a => a.parent_agent_id === lead.id))}
      </button>
    </div>
  )
}
