import { useState } from 'react'
import type { Agent, Provider } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { type AgentAsks, AgentChanges, Asked, AsksNow, ErrorAlert, HowItRuns, KeyNumbers, Report } from './agentParts'

interface Props extends AgentAsks {
  state: ConvState
  agent: Agent
  providers?: Provider[]
  onOpenChange: (changeId: string) => void
  onSelectAgent: (agentId: string) => void
}

/**
 * One agent in the side panel (design A, "Report first"): a short report card - what waits for you on top, who asked
 * what, its report (or what it is on now), what it changed, its key numbers. The whole story
 * and everything raw are in its window.
 * (No key inside: the panel keys the card by its agent, and an approval card of a renderer has its own - B-98.)
 */
export function AgentCard({ state, agent, providers = [], onOpenChange, onSelectAgent, ...asks }: Props) {
  const [changes, setChanges] = useState(true)
  return (
    <>
      <ErrorAlert state={state} agent={agent} providers={providers} />
      <AsksNow state={state} agent={agent} asks={asks} />
      <Asked state={state} agent={agent} onSelectAgent={onSelectAgent} />
      <HowItRuns state={state} agent={agent} />
      <section className="agent-sec" aria-label="Report">
        <div className="kicker">Report</div>
        <Report state={state} agent={agent} short />
      </section>
      <AgentChanges state={state} agent={agent} open={changes} onToggle={setChanges} onOpenChange={onOpenChange} />
      <KeyNumbers state={state} agent={agent} />
    </>
  )
}
