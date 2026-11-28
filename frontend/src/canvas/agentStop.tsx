import { ChatCircleText, Stop } from '@phosphor-icons/react'
import { api } from '../api/client'
import type { Agent } from '../api/types'
import { useAsk } from '../memory/useAsk'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { PROOF_CALL } from './checksNode'

const STOPPABLE: ReadonlySet<Agent['status']> = new Set(['queued', 'running', 'waiting', 'blocked'])

/**
 * D3 (0.1.11): whether the user may stop this agent alone - one at work below the Orchestrator that an agent opened with
 * spawn_agent. Not KOLONİ's own look (Stop this check stops it), nor a step of a team's recipe (its team's Stop); the
 * server holds the same rule (`stop_agent`).
 */
export function canStop(state: ConvState | null, agent: Agent | undefined): boolean {
  if (!state || !agent?.parent_agent_id || !STOPPABLE.has(agent.status)) return false
  const call = state.toolCalls.find(one => one.id === agent.tool_call_id)
  if (call?.name !== 'spawn_agent' || call.provider_call_id.startsWith(PROOF_CALL)) return false
  return !state.conversation.teams.some(row => row.state?.recipe && row.state.agents.includes(agent.id))
}

/** Its window opened at its Tell box (or the Orchestrator's, for a CLI that hears nothing while it works). */
export function messageAgent(agentId: string) {
  useApp.getState().openAgentWindow(agentId)
  setTimeout(() => document.querySelector<HTMLInputElement>(`.agent-tell[data-agent="${agentId}"] input`)?.focus())
}

/** An agent's own Stop and Message (D3), on its node and in its window's head, while it may be stopped alone. */
export function StopAndMessage({ agentId, name }: { agentId: string; name: string }) {
  const may = useApp(s =>
    canStop(
      s.conv,
      s.conv?.agents.find(one => one.id === agentId),
    ),
  )
  const { busy, error, ask } = useAsk()
  if (!may) return null
  return (
    <>
      <button
        type="button"
        className="node-open nodrag"
        aria-label={`Stop ${name}`}
        title={`Stop ${name}: its work so far is kept for your Take in`}
        disabled={busy}
        onClick={event => {
          event.stopPropagation()
          void ask(async () => {
            await api.post(`/agents/${agentId}/stop`)
          })
        }}
        onDoubleClick={event => event.stopPropagation()}
      >
        <Stop size={12} weight="fill" />
      </button>
      <button
        type="button"
        className="node-open nodrag"
        aria-label={`Message ${name}`}
        title={`Message ${name} while it works`}
        onClick={event => {
          event.stopPropagation()
          messageAgent(agentId)
        }}
        onDoubleClick={event => event.stopPropagation()}
      >
        <ChatCircleText size={12} />
      </button>
      {error && (
        <span role="alert" className="node-stop-why">
          {error}
        </span>
      )}
    </>
  )
}
