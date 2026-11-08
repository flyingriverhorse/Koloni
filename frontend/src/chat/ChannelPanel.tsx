import { titleOf } from '../agents/agentStatus'
import type { ConvState } from '../state/applyEvent'

/** What agents said to one another: tasks, reports, messages and their replies. Read-only. */
export function ChannelPanel({ state }: { state: ConvState }) {
  if (state.channelMessages.length === 0) {
    return <div className="msg-list msg-empty muted">What agents say to each other shows here.</div>
  }
  const role = (agentId: string) => titleOf(state.agents.find(a => a.id === agentId)?.name || 'Agent')
  // A note is left for an agent at work; it is delivered when that agent next reads.
  const delivery = (message: (typeof state.channelMessages)[number]) => {
    if (message.kind !== 'note') return ''
    const left = state.messages.find(
      m =>
        m.role === 'agent' &&
        // not the same words handed over from the shared notebook
        !m.board_post_id &&
        m.agent_id === message.to_agent_id &&
        m.from_agent_id === message.from_agent_id &&
        m.content === message.content,
    )
    return left?.delivered_at ? ' · delivered' : ' · not delivered'
  }
  return (
    <div className="msg-list channel">
      {state.channelMessages.map(message => (
        <div key={message.id} className="channel-message">
          <div className="channel-head">
            <span className="mono">
              {role(message.from_agent_id)} → {role(message.to_agent_id)} · {message.kind}
              {delivery(message)}
            </span>
            <span className="mono muted">
              {new Date(message.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
          <div className="channel-body">{message.content}</div>
        </div>
      ))}
    </div>
  )
}
