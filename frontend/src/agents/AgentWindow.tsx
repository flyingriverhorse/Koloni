import { Robot, X } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Agent, ProjectMemory, Provider } from '../api/types'
import { pendingMerge } from '../changes/copies'
import { useAsk } from '../memory/useAsk'
import { ranOn } from '../shell/modelName'
import { placed } from '../shell/move'
import { StatusLabel } from '../shell/StatusLabel'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { AGENT_STATUS, AT_WORK, hearsNothing, titleOf } from './agentStatus'
import { AgentDetails } from './AgentDetails'
import { type AgentAsks, AgentChanges, Asked, AsksNow, ErrorAlert, Fold, HowItRuns, KeyNumbers, QueueLine, Report } from './agentParts'
import { stepsOf } from './AgentSteps'
import { EarlierWork } from './EarlierWork'
import { STEP_MARK } from './livePlan'
import { Observation } from './Observation'
import { SpawnRow } from './SpawnRow'
import { Story } from './Story'

export type { AgentAsks } from './agentParts'
export { withoutFindings } from './agentParts'
export { CompactNow, when } from './AgentDetails'

/** How it stands, as its header says it: a lead as its turn does, and not "done" while its changes wait for your decision. */
export function agentState(state: ConvState, agent: Agent): [label: string, color: string] {
  if (pendingMerge(state, agent.id)) return ['changes wait for your decision', 'var(--warn)']
  const run = state.runs.find(r => r.id === agent.run_id)
  // The lead carries its turn: how the turn ended is how it ended.
  return AGENT_STATUS[run && agent.depth === 0 && agent.status !== 'waiting' && agent.status !== 'blocked' ? run.status : agent.status]
}

/** What it runs on, as its header says it: a lead with no model of its own on record has its turn's. */
export function agentWhere(state: ConvState, agent: Agent): string {
  const model = agent.model_id ?? (agent.depth === 0 ? (state.runs.find(r => r.id === agent.run_id)?.model_id ?? null) : null)
  return ranOn(agent.provider_name, model, agent.model_from, agent.effort, agent.tier)
}

interface StoryProps extends AgentAsks {
  state: ConvState
  agent: Agent
  /** The project's memory, to name the facts the agent was given; null while not read. */
  memory?: ProjectMemory | null
  /** The providers as they stand now: what a failed agent's plan key says to do. */
  providers?: Provider[]
  onOpenChange: (changeId: string) => void
  onSelectAgent: (agentId: string) => void
  /** Details open on its raw stream: the "Raw" button of its node opens its window so. */
  raw?: boolean
  /** Details opened or folded by the user: the window keeps the store's flag with it, so the node's "Raw" opens it again. */
  onMore?: (open: boolean) => void
}

/**
 * One agent's whole story, in its window (design A, "Report first"), read top to bottom: who asked what, its report,
 * its key numbers, what it did as plain phases (what waits for you its last - on top once its work is over), what it
 * changed, its earlier work and
 * sub-agents - and Details, folded, with everything raw.
 * (No key inside: the window keys it by its agent, and an approval card of a renderer has its own - B-98.)
 */
export function AgentStory({ state, agent, memory, providers = [], onOpenChange, onSelectAgent, raw = false, onMore, ...asks }: StoryProps) {
  const [details, setDetails] = useState(raw)
  const [open, setOpen] = useState({ changes: true, earlier: false, kids: false })
  const fold = (name: keyof typeof open) => (on: boolean) => setOpen(was => (was[name] === on ? was : { ...was, [name]: on }))
  // The "Raw" button of its node, pressed while its window lay open: Details opens on it.
  const [rawBefore, setRawBefore] = useState(raw)
  if (raw !== rawBefore) {
    setRawBefore(raw)
    if (raw) setDetails(true)
  }
  const children = state.agents.filter(a => a.parent_agent_id === agent.id)
  // Its work over, what waits for you (its changes, say) is on top, as in the panel; while it works, its story's last step.
  const over = !AT_WORK.has(agent.status)
  return (
    <>
      <ErrorAlert state={state} agent={agent} providers={providers} />
      {over && <AsksNow state={state} agent={agent} asks={asks} />}
      <Asked state={state} agent={agent} onSelectAgent={onSelectAgent} />
      <QueueLine state={state} agent={agent} />
      <HowItRuns state={state} agent={agent} />
      <h3 className="agent-h">Report</h3>
      <Report state={state} agent={agent} />
      <Observation agent={agent} />
      <KeyNumbers state={state} agent={agent} />
      <h3 className="agent-h">What it did</h3>
      <LivePlan state={state} agent={agent} />
      <Story state={state} agent={agent} asks={asks} onOpenChange={onOpenChange} onSelectAgent={onSelectAgent} asksAbove={over} />
      <AgentChanges state={state} agent={agent} open={open.changes} onToggle={fold('changes')} onOpenChange={onOpenChange} />
      <EarlierWork state={state} agentId={agent.id} open={open.earlier} onToggle={fold('earlier')} onOpenChange={onOpenChange} onSelectAgent={onSelectAgent} />
      <Fold title="Sub-agents" count={children.length || 'none'} open={open.kids} onToggle={fold('kids')}>
        {children.length === 0 && <p className="muted">No sub-agents.</p>}
        {children.map(child => (
          <SpawnRow key={child.id} agent={child} onSelect={onSelectAgent} asks={pendingMerge(state, child.id) !== null} />
        ))}
      </Fold>
      <AgentDetails
        state={state}
        agent={agent}
        memory={memory}
        providers={providers}
        open={details}
        onToggle={on => {
          setDetails(on)
          if (on !== raw) onMore?.(on)
        }}
        onOpenChange={onOpenChange}
        onSelectAgent={onSelectAgent}
      />
    </>
  )
}

/** Its CLI's plan as it says it while it works (89j, Codex's), a step a line, over the story it goes with. */
function LivePlan({ state, agent }: { state: ConvState; agent: Agent }) {
  const plan = state.live[agent.id]?.plan
  if (!plan?.length) return null
  return (
    <dl className="facts agent-sum">
      <dt>Plan</dt>
      <dd>
        <ol className="agent-plan">
          {plan.map((step, index) => (
            <li key={index} className={`agent-plan-${step.status}`}>
              {STEP_MARK[step.status]} {step.step}
            </li>
          ))}
        </ol>
      </dd>
    </dl>
  )
}

interface Props extends AgentAsks {
  state: ConvState
  /** The project's memory, to name the facts the agent was given; null while not read. */
  memory?: ProjectMemory | null
  providers?: Provider[]
  agentId: string
  onClose: () => void
  onOpenChange: (changeId: string) => void
  onSelectAgent: (agentId: string) => void
}

/**
 * One agent's own window, beside the canvas: its whole story (`AgentStory`). For an
 * agent that works with its own tools (a CLI in native mode) this is where its work shows.
 */
export function AgentWindow({ state, agentId, onClose, ...rest }: Props) {
  // The agent's node on the canvas opens this window straight on what its CLI wrote: the store's to say.
  const raw = useApp(s => s.agentWindowRaw)
  const agent = state.agents.find(a => a.id === agentId)
  const atWork = agent ? AT_WORK.has(agent.status) : false
  // While it works its newest step stays in sight, as long as the reader is at it (not scrolled up to read).
  const feed = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const below = () => {
    const el = feed.current
    const newest = el?.querySelectorAll('.agent-story > li')
    const step = newest?.[newest.length - 1]
    return el && step ? step.getBoundingClientRect().bottom - el.getBoundingClientRect().bottom : null
  }
  useEffect(() => {
    const by = below()
    if (atWork && pinned.current && by !== null && by > 0) feed.current!.scrollTop += by
  })
  // K-38b-sinirlar: how many steps it had when the user last looked - as it opened, pressed or focused, or in
  // front of the stage's other windows as a step came; its header counts the ones since.
  // shortcut: kept in the window, so closed it forgets them, and the agent's node shows none; upgrade to the store
  // and a badge on the node if the user wants what came while it was closed counted.
  const steps = agent ? stepsOf(state, agent.id).steps.length : 0
  const [seen, setSeen] = useState<Record<string, number>>({})
  const look = () => setSeen(was => (was[agentId] === steps ? was : { ...was, [agentId]: steps }))
  useEffect(() => {
    if (seen[agentId] === undefined || feed.current?.parentElement?.hasAttribute('data-front')) look()
  })
  if (!agent) return null
  const [label, color] = agentState(state, agent)
  const where = agentWhere(state, agent)
  const fresh = steps - (seen[agentId] ?? steps)
  return (
    <section ref={placed} tabIndex={-1} className="changes agent-window" aria-label="Agent window" onPointerDownCapture={look} onFocusCapture={look}>
      <div className="changes-bar">
        <Robot size={15} color="var(--accent)" />
        <span className="changes-title">{titleOf(agent.name || agent.role_name)}</span>
        {where && <span className="mono muted changes-summary">{where}</span>}
        <span className="changes-spacer" />
        {fresh > 0 && (
          <span className="chat-waits" title="Steps since you last looked at this window">
            {fresh} new
          </span>
        )}
        <StatusLabel color={color}>{label}</StatusLabel>
        <button type="button" className="icon-btn" aria-label="Close agent window" onClick={onClose}>
          <X size={14} />
        </button>
      </div>
      <div
        className="agent-feed"
        ref={feed}
        onScroll={() => {
          const by = below()
          pinned.current = by === null || by < 40
        }}
      >
        <AgentStory key={agent.id} state={state} agent={agent} raw={raw} onMore={useApp.getState().showAgentRaw} {...rest} />
      </div>
      <TellAtWork key={agent.id} agent={agent} />
    </section>
  )
}

/**
 * 89d C: under its window, the user's own word to the agent while it works - into Claude Code's or Codex's turn, a CLI
 * session's next KOLONİ tool result, or KOLONİ's own agent's next step. Not where its CLI hears nothing (Copilot's and
 * agy's own), nor once its work is over; what the server says where it could not hear it.
 */
export function TellAtWork({ agent }: { agent: Agent }) {
  const kind = useApp(s => s.providers.find(p => p.name === agent.provider_name)?.kind)
  const { busy, error, ask } = useAsk()
  const [words, setWords] = useState('')
  const [said, setSaid] = useState<string | null>(null)
  if (!AT_WORK.has(agent.status) || agent.status === 'proposed' || hearsNothing(agent.provider_mode, kind)) return null
  const name = titleOf(agent.name || agent.role_name)
  return (
    <form
      className="agent-tell"
      onSubmit={e => {
        e.preventDefault()
        if (words.trim() && !busy)
          void ask(async () => {
            setSaid(null)
            await api.post(`/agents/${agent.id}/tell`, { words })
            setWords('')
            setSaid(`Sent to ${name} while it works`)
          })
      }}
    >
      <input className="input" aria-label={`Tell ${name}`} placeholder={`Tell ${name}…`} maxLength={4000} value={words} onChange={e => setWords(e.target.value)} />
      {/* (Named for whom: never taken for the chat's own Send.) */}
      <button type="submit" className="btn btn-small" aria-label={`Send to ${name}`} disabled={busy || !words.trim()}>
        Send
      </button>
      <span role="status" className="muted changes-summary">
        {said}
      </span>
      {error && (
        <span role="alert" className="changes-summary" style={{ color: 'var(--del)' }}>
          {error}
        </span>
      )}
    </form>
  )
}
