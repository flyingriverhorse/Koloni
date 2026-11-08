import type { Agent } from '../api/types'
import { modelName } from '../shell/modelName'

/** What the Observer's model said of a sub-agent's report - a model's opinion, signed - or why it said nothing. */
export function Observation({ agent }: { agent: Agent }) {
  if (agent.observation === null && agent.observation_note === null) return null
  const by = agent.observed_by && ` (${agent.observed_by.provider_name} · ${modelName(agent.observed_by.model_id)})`
  return (
    <p className="muted provider-note">
      {agent.observation !== null && <span className="tag tag-warn">opinion</span>} Observer{by}:{' '}
      {agent.observation !== null ? `“${agent.observation}”` : `no observation - ${agent.observation_note}`}
    </p>
  )
}
