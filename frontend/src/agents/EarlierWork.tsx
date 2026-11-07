import { inScratch } from '../changes/copies'
import { Markdown } from '../chat/Markdown'
import type { ConvState } from '../state/applyEvent'
import { earlierLinks, messageTime, wentOnIn } from '../topics/topics'
import { AgentSteps } from './AgentSteps'

/** "the 10:40 message", "the 10:40 and 10:42 messages", "the 10:40, 10:41 and 10:42 messages". */
function messagesInWords(times: string[]): string {
  if (times.length === 1) return `the ${times[0]} message`
  return `the ${times.slice(0, -1).join(', ')} and ${times[times.length - 1]} messages`
}

interface Props {
  state: ConvState
  agentId: string
  /** Open: what it did then is drawn only while it is (AgentView's folds). */
  open: boolean
  onToggle: (open: boolean) => void
  onOpenChange: (changeId: string) => void
  onSelectAgent: (agentId: string) => void
}

/**
 * What an agent that goes on from earlier turns did in them: for each turn its task, what it
 * did, and its report. Folded until asked for - this turn's work is what it is opened for.
 */
export function EarlierWork({ state, agentId, open, onToggle, onOpenChange, onSelectAgent }: Props) {
  const links = earlierLinks(state, agentId)
  if (links.length === 0) return null
  const files = new Set(state.fileChanges.filter(f => links.some(link => link.agent.id === f.agent_id) && !inScratch(f.path)).map(f => f.path)).size
  return (
    <details className="agent-fold" open={open} onToggle={e => onToggle(e.currentTarget.open)}>
      <summary>
        Earlier work{' '}
        <span className="agent-fold-count">
          {messagesInWords(links.map(link => messageTime(state, link.agent.run_id)))} · {files} file{files === 1 ? '' : 's'}
        </span>
      </summary>
      {open && links.map(({ agent }) => (
        <div key={agent.id} role="group" aria-label={`The ${messageTime(state, agent.run_id)} message`} className="earlier-work-link">
          <div className="kicker">{messageTime(state, agent.run_id)} · its task</div>
          <div className="agent-feed-task">{agent.task || 'No task on record.'}</div>
          <div className="kicker">What it did</div>
          <AgentSteps
            state={state}
            agent={agent}
            onOpenChange={onOpenChange}
            onSelectAgent={onSelectAgent}
            without={agent.report}
            empty="Nothing on record."
          />
          <div className="kicker">Its report</div>
          {agent.report ? (
            <div className="markdown">
              <Markdown>{agent.report}</Markdown>
            </div>
          ) : (
            <p className="muted">It ended without a report.</p>
          )}
        </div>
      ))}
    </details>
  )
}

/** For an agent a later one went on from: where it went on, and the way there. */
export function WentOn({ state, agentId, onSelectAgent }: Pick<Props, 'state' | 'agentId' | 'onSelectAgent'>) {
  const later = wentOnIn(state, agentId)
  if (!later) return null
  return (
    <button
      type="button"
      className="btn btn-small went-on"
      title="Show that message’s work, and the agent that went on from this one"
      onClick={() => onSelectAgent(later.agent.id)}
    >
      went on in the {messageTime(state, later.agent.run_id)} message
    </button>
  )
}
