import type { Agent, ProjectMemory } from '../api/types'
import { TOOL_STATUS } from '../chat/ToolRow'
import type { ConvState } from '../state/applyEvent'
import { findRecord, queryOf, restsOn, sourceOf } from './memoryText'

/**
 * One fact an agent was given, by its id, as it is on record now. How its source stood
 * when it was given is not on record, so what is said is how it stands at the last reading
 * of the memory - and says "now", so that it is not taken for how it stood then.
 */
export function GivenFact({ memory, id }: { memory: ProjectMemory; id: string }) {
  const record = findRecord(memory, id)
  if (!record) return <span className="muted">a fact that is no longer on record</span>
  const inCore = record.tier === 'fact' && record.status === 'active'
  return (
    <>
      <span>{record.text}</span>
      <span className="mono muted">
        {restsOn(record)}
        {!inCore ? ' · now: no longer in the core' : record.source && ` · now: ${sourceOf(record)}`}
      </span>
    </>
  )
}

interface Props {
  state: ConvState
  agent: Agent
  /** The project's memory; null or left out while it has not been read. */
  memory?: ProjectMemory | null
}

/**
 * Which memory an agent worked with: the facts of the core it was given when it started,
 * and what it looked up itself, with what came back. An agent that was given nothing and
 * looked nothing up shows nothing.
 */
export function AgentMemory({ state, agent, memory }: Props) {
  const given = agent.facts_given ?? []
  const looked = state.toolCalls
    .filter(t => t.agent_id === agent.id && t.name === 'recall')
    .sort((a, b) => a.seq - b.seq)
  if (given.length === 0 && looked.length === 0) return null
  return (
    <>
      {given.length > 0 && (
        <div role="group" aria-label="Given from memory" className="memory-given">
          <div className="kicker">Given from memory</div>
          {memory ? (
            <ul className="memory-list">
              {given.map(id => (
                <li key={id} className="memory-given-item">
                  <GivenFact memory={memory} id={id} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              {given.length} {given.length === 1 ? 'fact' : 'facts'}; reading the project’s memory…
            </p>
          )}
        </div>
      )}
      {looked.length > 0 && (
        <div role="group" aria-label="Looked up in memory" className="memory-given">
          <div className="kicker">Looked up in memory</div>
          <ul className="memory-list">
            {looked.map(call => (
              <li key={call.id} className="memory-given-item">
                <span>
                  <span className="mono muted">asked: </span>
                  {queryOf(call) || '(nothing)'}
                  {call.status !== 'succeeded' && (
                    <span className="mono" style={{ color: TOOL_STATUS[call.status][1] }}>
                      {' '}
                      · {TOOL_STATUS[call.status][0]}
                    </span>
                  )}
                </span>
                <pre className="mono memory-found">{call.result ?? '(no result yet)'}</pre>
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}
