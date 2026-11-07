import { type ReactNode, useState } from 'react'
import type { Agent } from '../api/types'
import { Markdown } from '../chat/Markdown'
import { TalkRow } from '../chat/TalkRow'
import { ToolRow } from '../chat/ToolRow'
import { pendingMerge } from '../changes/copies'
import { callWaits } from '../claims/claims'
import { CommandRow } from '../commands/CommandRow'
import { MemoryTold } from '../memory/MemoryTold'
import type { ConvState } from '../state/applyEvent'
import { type AgentAsks, AsksNow, asksNow, ChangeRow } from './agentParts'
import { OwnSubAgentBlock } from './OwnSubAgent'
import { type Phase, phaseLine, phasesOf, phaseTone, type Tone, targetOf } from './phases'
import { SpawnRow } from './SpawnRow'

interface Props {
  state: ConvState
  agent: Agent
  asks: AgentAsks
  onOpenChange: (changeId: string) => void
  onSelectAgent: (agentId: string) => void
  /** What waits for you is on top of the window (its work is over): here only said, not a second card. */
  asksAbove?: boolean
}

const MARK: Record<Tone, string> = { ok: '✓', now: '●', warn: '–', bad: '!' }
const hm = (iso: string) => (iso ? new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '')

/**
 * What it did, told plainly (design A): its phases in order (`phasesOf`), each with its result in words and what it
 * said before it, the rows to act on (Stop, View diff, a sub-agent) under it - and, while something waits for you, that
 * as its last step, with the chat's own card.
 */
export function Story({ state, agent, asks, onOpenChange, onSelectAgent, asksAbove = false }: Props) {
  const phases = phasesOf(state, agent)
  const waits = asksNow(state, agent)
  if (phases.length === 0 && !waits) return <p className="muted">Nothing yet.</p>
  return (
    <ol className="agent-story">
      {phases.map(phase => (
        <PhaseItem key={phase.calls[0]?.id ?? phase.message?.id ?? phase.kind} state={state} agent={agent} phase={phase} onOpenChange={onOpenChange} onSelectAgent={onSelectAgent} />
      ))}
      {waits && (
        <li className="agent-phase agent-phase-asks">
          <span className="agent-phase-mark" aria-hidden="true">
            ?
          </span>
          <div className="agent-phase-main">
            <div className="agent-phase-head">
              <h4>Waits for you</h4>
            </div>
            {asksAbove ? <p className="muted">Its decision is on top of this window.</p> : <AsksNow state={state} agent={agent} asks={asks} />}
          </div>
        </li>
      )}
    </ol>
  )
}

function PhaseItem({ state, agent, phase, onOpenChange, onSelectAgent }: Omit<Props, 'asks' | 'asksAbove'> & { phase: Phase }) {
  const { title, result } = phaseLine(state, phase)
  const tone = phaseTone(state, phase)
  return (
    <li className={`agent-phase agent-phase-${tone}`}>
      <span className="agent-phase-mark" aria-hidden="true">
        {MARK[tone]}
      </span>
      <div className="agent-phase-main">
        <div className="agent-phase-head">
          <h4>{title}</h4>
          {result && <span className="agent-phase-result">— {result}</span>}
          <time className="mono muted" dateTime={phase.at}>
            {hm(phase.at)}
          </time>
        </div>
        {phase.said && phase.kind !== 'said' && <p className="agent-phase-said">“{phase.said}”</p>}
        {BODY[phase.kind]({ state, agent, phase, onOpenChange, onSelectAgent, open: tone === 'now' })}
      </div>
    </li>
  )
}

type BodyProps = Omit<Props, 'asks' | 'asksAbove'> & { phase: Phase; open: boolean }

/**
 * Folded under a phase: its rows as the raw list has them, drawn only while open (as an agent's `Fold`). It opens by
 * itself while its phase runs (Stop in reach) and stays open after, until the reader folds it.
 */
function More({ title, open, children }: { title: string; open: boolean; children: ReactNode }) {
  const [shown, setShown] = useState(open)
  // (Opened again only as its phase starts to run: a reader who folded it while it runs keeps it folded.)
  const [was, setWas] = useState(open)
  if (open !== was) {
    setWas(open)
    if (open) setShown(true)
  }
  return (
    <details className="more agent-phase-more" open={shown} onToggle={e => setShown(e.currentTarget.open)}>
      <summary>{title}</summary>
      {shown && children}
    </details>
  )
}

const toolRows = ({ state, phase, open }: BodyProps) => (
  <More title="What it did" open={open}>
    {phase.calls.map(call => (
      <ToolRow key={call.id} call={call} waits={callWaits(state, call)} sized />
    ))}
  </More>
)

/** Each kind's rows under its line: a running command's open, with its Stop. */
const BODY: Record<Phase['kind'], (props: BodyProps) => ReactNode> = {
  read: ({ phase, open }) => (
    <More title="What it looked at" open={open}>
      <ul className="agent-phase-files mono">
        {phase.calls.map(call => (
          <li key={call.id}>{targetOf(call)}</li>
        ))}
      </ul>
    </More>
  ),
  // A write with no change on record (it failed, or waits for a file another agent holds) is its call's row.
  change: ({ state, phase, onOpenChange }) =>
    phase.calls.map(call => {
      const change = state.fileChanges.find(f => f.tool_call_id === call.id)
      return change ? <ChangeRow key={call.id} change={change} onOpenChange={onOpenChange} /> : <ToolRow key={call.id} call={call} waits={callWaits(state, call)} sized />
    }),
  command: ({ state, phase, open }) => (
    <More title="What happened" open={open}>
      {phase.calls.map(call => {
        const ran = state.commands.find(c => c.tool_call_id === call.id)
        return ran ? <CommandRow key={call.id} command={ran} failed={call.status === 'failed'} /> : <ToolRow key={call.id} call={call} sized />
      })}
    </More>
  ),
  opened: ({ state, phase, onSelectAgent }) =>
    state.agents
      .filter(a => a.tool_call_id === phase.calls[0].id)
      .map(child => <SpawnRow key={child.id} agent={child} onSelect={onSelectAgent} asks={pendingMerge(state, child.id) !== null} />),
  own: ({ state, phase, onOpenChange }) => <OwnSubAgentBlock state={state} call={phase.calls[0]} onOpenChange={onOpenChange} />,
  talked: ({ agent, phase, open }) => (
    <More title="What was said" open={open}>
      {phase.calls.map(call => (
        <TalkRow key={call.id} call={call} from={agent.name || agent.role_name} />
      ))}
    </More>
  ),
  asked: toolRows,
  tool: toolRows,
  heard: ({ phase }) => <div className="msg-quote">{phase.message?.content}</div>,
  reminded: ({ phase }) => <MemoryTold content={phase.message?.content ?? ''} count={phase.count} />,
  said: ({ phase }) => (
    <div className="markdown">
      <Markdown written={phase.message?.status === 'complete'}>{phase.message?.content ?? ''}</Markdown>
    </div>
  ),
  report: () => null,
}
