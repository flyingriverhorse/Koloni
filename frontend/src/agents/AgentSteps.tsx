import { Markdown } from '../chat/Markdown'
import type { Agent } from '../api/types'
import { titleOf } from './agentStatus'
import { pendingMerge } from '../changes/copies'
import { TalkRow } from '../chat/TalkRow'
import { ToolRow } from '../chat/ToolRow'
import { callWaits } from '../claims/claims'
import { CommandRow } from '../commands/CommandRow'
import { MemoryTold } from '../memory/MemoryTold'
import { foldRepeats } from '../shell/repeats'
import type { ConvState } from '../state/applyEvent'
import { OwnSubAgentBlock } from './OwnSubAgent'
import { homeOf, subAgentIds } from './ownWork'
import { SpawnRow } from './SpawnRow'

interface Props {
  state: ConvState
  agent: Agent
  onOpenChange: (changeId: string) => void
  onSelectAgent: (agentId: string) => void
  /** Words of its last message that are shown elsewhere (its report): not said twice. */
  without?: string | null
  /** What stands there while it has said and done nothing. */
  empty?: string
  /** Its steps, where they are counted already (`stepsOf`): not worked out twice. */
  of?: ReturnType<typeof stepsOf>
}

/**
 * An agent's steps as they are shown: each message of its own conversation (not what it said in
 * a discussion) with words or calls, and its calls in order - what a sub-agent of the CLI's own
 * did is inside that sub-agent's block, not in the agent's own flow. Words of its last message
 * that are shown elsewhere (`without`, its report) are not said twice.
 */
export function stepsOf(state: ConvState, agentId: string, without: string | null = null) {
  const messages = state.messages.filter(m => m.agent_id === agentId && !m.discussion_id)
  const subAgents = subAgentIds(state.toolCalls)
  const callsOf = (messageId: string) =>
    state.toolCalls
      .filter(t => t.message_id === messageId && homeOf(t, subAgents) === null)
      .sort((a, b) => a.seq - b.seq)
  const last = messages[messages.length - 1]
  const said = (message: (typeof messages)[number]) =>
    without !== null && message === last && message.role === 'assistant' && message.content.trim() === without.trim() ? '' : message.content
  const shown = messages.filter(m => said(m) || callsOf(m.id).length > 0)
  // What KOLONİ told it the same, several times in a row, is one step (×N); never its own or anybody's words.
  return { steps: foldRepeats(shown, m => (m.role === 'memory' ? m.content : null)), said, callsOf, subAgents }
}

const at = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

/** What one agent said and did, step by step, in order, each step with its time. */
export function AgentSteps({ state, agent, onOpenChange, onSelectAgent, without = null, empty, of }: Props) {
  const { steps, said, callsOf, subAgents } = of ?? stepsOf(state, agent.id, without)
  if (steps.length === 0) return empty ? <p className="muted">{empty}</p> : null

  return (
    <>
      {steps.map(([message, count]) => (
        <div key={message.id} className="agent-feed-step">
          <time className="mono muted agent-step-time" dateTime={message.created_at}>
            {at(message.created_at)}
          </time>
          {message.board_post_id ? (
            // Handed to it from the turn's shared notebook: written for everyone, not sent to it.
            <div className="msg-from">
              <div className="asked-by mono">
                note from the notebook, written by{' '}
                {message.from_agent_id ? titleOf(state.agents.find(a => a.id === message.from_agent_id)?.name || 'an agent') : 'you'}
              </div>
              <div className="msg-quote">{message.content}</div>
            </div>
          ) : message.room_post_id ? (
            // Handed to it from its room: said there for every member, as KOLONİ gave it over.
            <div className="msg-from">
              <div className="asked-by mono">handed to it from the room</div>
              <div className="msg-quote">{message.content}</div>
            </div>
          ) : message.role === 'memory' ? (
            <MemoryTold content={message.content} count={count} />
          ) : message.role === 'agent' ? (
            <div className="msg-from">
              {/* (From nobody: KOLONİ's own word - the user's said to it while it works, 89d C, among them.) */}
              <div className="asked-by mono">
                from {message.from_agent_id ? titleOf(state.agents.find(a => a.id === message.from_agent_id)?.name || 'Agent') : 'KOLONİ'}
              </div>
              <div className="msg-quote">{message.content}</div>
            </div>
          ) : (
            said(message) && (
              <div className="markdown">
                <Markdown written={message.status === 'complete'}>{message.content}</Markdown>
              </div>
            )
          )}
          {callsOf(message.id).map(call => {
            const child = state.agents.find(a => a.tool_call_id === call.id)
            if (child) {
              return <SpawnRow key={call.id} agent={child} onSelect={onSelectAgent} asks={pendingMerge(state, child.id) !== null} />
            }
            if (subAgents.has(call.id)) {
              return <OwnSubAgentBlock key={call.id} state={state} call={call} onOpenChange={onOpenChange} />
            }
            const ran = state.commands.find(c => c.tool_call_id === call.id)
            if (ran) return <CommandRow key={call.id} command={ran} failed={call.status === 'failed'} />
            const change = state.fileChanges.find(f => f.tool_call_id === call.id)
            if (change) {
              return (
                <div key={call.id} className="chat-change">
                  <span className="mono chat-change-path">{change.path}</span>
                  <span className="mono" style={{ color: 'var(--ok)' }}>+{change.additions}</span>
                  <span className="mono" style={{ color: 'var(--del)' }}>−{change.deletions}</span>
                  <button type="button" className="btn btn-small" aria-label={`View diff of ${change.path}`} onClick={() => onOpenChange(change.id)}>
                    View diff
                  </button>
                </div>
              )
            }
            if (call.name === 'message_agent') {
              return <TalkRow key={call.id} call={call} from={agent.name || agent.role_name} />
            }
            return <ToolRow key={call.id} call={call} waits={callWaits(state, call)} sized />
          })}
        </div>
      ))}
    </>
  )
}
