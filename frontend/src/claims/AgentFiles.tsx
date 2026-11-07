import type { Agent } from '../api/types'
import { pendingMerge } from '../changes/copies'
import type { ConvState } from '../state/applyEvent'
import { heldBy } from './claims'

/**
 * The files an agent holds now, and the one it waits for when another agent holds that:
 * shown with the agent's details and in its window. Nothing when it holds none and waits
 * for none.
 */
export function AgentFiles({ state, agent }: { state: Pick<ConvState, 'claims' | 'merges'>; agent: Agent }) {
  const held = heldBy(state, agent.id)
  const wait = agent.status === 'blocked' ? agent.waiting_for : null
  if (!wait && held.length === 0) return null
  // The agent it waits for may hold the file because its changes wait for the user's
  // decision: known for an agent of this conversation, and said then. Of an agent of another
  // conversation it is not known, so nothing is said of what the wait asks of them.
  const asked = wait ? pendingMerge(state, wait.agent_id) !== null : false
  return (
    <div className="agent-files">
      {wait && (
        <p role="note" className="agent-files-wait">
          Waits for {wait.agent_name || 'an agent of another conversation'} to finish with{' '}
          <span className="mono">{wait.path}</span>.{' '}
          {asked
            ? `${wait.agent_name}'s changes wait for you: it goes on when you have decided.`
            : `It goes on when ${wait.agent_name || 'that agent'} is done with the file.`}
        </p>
      )}
      {held.length > 0 && (
        <>
          <div className="kicker">Holds</div>
          <ul className="agent-files-list mono" aria-label="Files it holds">
            {held.map(path => (
              <li key={path}>{path}</li>
            ))}
          </ul>
          <p className="muted provider-note">
            Until its work is done and the project has its changes: another agent that wants one of these waits.
          </p>
        </>
      )}
    </div>
  )
}
