import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Agent, Command, FileChange, Handed, Merge, PendingRole, Provider, Question } from '../api/types'
import { findingsLine } from '../canvas/deriveGraph'
import { when as clock } from '../canvas/turns'
import { Markdown } from '../chat/Markdown'
import { CHANGE_LABEL } from '../changes/changeLabel'
import { atGivenSteps, cardMerges, copyLine, inScratch, isKept } from '../changes/copies'
import { NotApplied } from '../changes/NotApplied'
import { CopyCounts, counted, useWorkingCopy } from '../changes/WorkingCopy'
import { AgentFiles } from '../claims/AgentFiles'
import { spent } from '../shell/tokens'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { continuesFrom } from '../topics/topics'
import { AT_WORK, titleOf } from './agentStatus'
import { stepsOf } from './AgentSteps'
import { WentOn } from './EarlierWork'
import { failureText, nextStep, planConsole } from './failure'
import { queueLine } from './livePlan'
import { homeOf, LET_THROUGH, letThrough, NOT_WATCHED, notWatched } from './ownWork'
import { phaseLine, phasesOf } from './phases'

export const many = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** What an agent waits on you for, shown with it wherever it is shown: the same cards as the chat's. */
export interface AgentAsks {
  renderSpawnApproval?: (agent: Agent) => ReactNode
  renderMerge?: (merge: Merge, agent: Agent) => ReactNode
  renderRoleApproval?: (role: PendingRole) => ReactNode
  renderQuestion?: (question: Question) => ReactNode
  renderCommandApproval?: (command: Command) => ReactNode
}

/**
 * A report without its Findings section, where its findings are listed apart (K-inspector), as the server reads that
 * section (`_findings`): its last line named "Findings" (a heading or "Findings:") outside a fenced block, to the next
 * heading, fence or "Checked:" line.
 */
export function withoutFindings(report: string): string {
  const lines = report.split('\n')
  const fence = (line: string) => /^(```|~~~)/.test(line.trim())
  let [fenced, at] = [false, -1]
  lines.forEach((line, i) => {
    if (fence(line)) fenced = !fenced
    else if (!fenced && /^#*\s*\**\s*findings\s*\**\s*(:|$)/i.test(line.trim())) at = i
  })
  if (at < 0) return report
  const end = lines.findIndex((line, i) => i > at && (fence(line) || /^(#|[-*•\s]*checked\s*\**\s*:)/i.test(line.trim())))
  return [...lines.slice(0, at), ...(end < 0 ? [] : lines.slice(end))].join('\n').trimEnd()
}

/** One fold of an agent: its body is drawn only while it is open - a hidden one would be drawn again at every streamed word. */
export function Fold({ title, count, open, onToggle, className = '', children }: {
  title: string
  count: ReactNode
  open: boolean
  onToggle: (open: boolean) => void
  className?: string
  children: ReactNode
}) {
  return (
    <details className={`agent-fold ${className}`} open={open} onToggle={e => onToggle(e.currentTarget.open)}>
      <summary>
        {title} <span className="agent-fold-count">{count}</span>
      </summary>
      {open && children}
    </details>
  )
}

/** One changed file: its lines, where it stands (`labelled`) and its diff a click away. */
export function ChangeRow({ change, labelled = false, onOpenChange }: { change: FileChange; labelled?: boolean; onOpenChange: (changeId: string) => void }) {
  return (
    <div className="chat-change">
      <span className="mono chat-change-path" title={change.path}>
        {change.path}
      </span>
      <span className="mono" style={{ color: 'var(--ok)' }}>+{change.additions}</span>
      <span className="mono" style={{ color: 'var(--del)' }}>−{change.deletions}</span>
      {labelled && <span className={CHANGE_LABEL[change.status][1]}>{CHANGE_LABEL[change.status][0]}</span>}
      <button type="button" className="btn btn-small" aria-label={`View diff of ${change.path}`} onClick={() => onOpenChange(change.id)}>
        View diff
      </button>
    </div>
  )
}

/** Its failure, on top in red, with the one thing to do about it on a line of its own. */
export function ErrorAlert({ state, agent, providers }: { state: ConvState; agent: Agent; providers: Provider[] }) {
  const run = state.runs.find(r => r.id === agent.run_id)
  const error = agent.error ?? (agent.depth === 0 ? (run?.error ?? null) : null)
  if (!error || error === 'step_limit' || atGivenSteps(error)) return null
  // shortcut: matched by the provider's name, as a card's spend is; a renamed provider's agents are not found.
  const provider = providers.find(p => p.name === agent.provider_name)
  const step = nextStep({ ...agent, error }, provider)
  const planLink = planConsole({ ...agent, error }, provider)
  return (
    <div role="alert" className="alert">
      {failureText(agent) && <strong>{failureText(agent)}. </strong>}
      {error}
      {step && (
        <>
          <br />
          {step}
        </>
      )}
      {planLink && (
        <>
          {' '}
          <a href={planLink} target="_blank" rel="noreferrer">
            See what is left in Alibaba's console
          </a>
        </>
      )}
    </div>
  )
}

/** The commands of its that wait for the user's yes. */
export const waitingCommands = (state: ConvState, agentId: string) => state.commands.filter(c => c.agent_id === agentId && c.status === 'proposed')

/** Whether anything of it waits for the user now. */
export function asksNow(state: ConvState, agent: Agent): boolean {
  return (
    agent.status === 'proposed' ||
    cardMerges(state, agent.id).length > 0 ||
    state.pendingRoles.some(r => r.agent_id === agent.id) ||
    state.questions.some(q => q.agent_id === agent.id && q.status === 'pending') ||
    waitingCommands(state, agent.id).length > 0
  )
}

/**
 * What it waits on you for, each as the chat's own card (answered in one place, it is answered in all): its start, its
 * changes, a role, a question, a command. (No key here: each renderer keys its card - B-98.)
 */
export function AsksNow({ state, agent, asks }: { state: ConvState; agent: Agent; asks: AgentAsks }) {
  return (
    <>
      {agent.status === 'proposed' && asks.renderSpawnApproval?.(agent)}
      {cardMerges(state, agent.id).map(m => asks.renderMerge?.(m, agent))}
      {state.pendingRoles.filter(r => r.agent_id === agent.id).map(r => asks.renderRoleApproval?.(r))}
      {state.questions.filter(q => q.agent_id === agent.id && q.status === 'pending').map(q => asks.renderQuestion?.(q))}
      {waitingCommands(state, agent.id).map(c => asks.renderCommandApproval?.(c))}
    </>
  )
}

/** Its CLI's model is queued (K-qoder-kuyruk): one line, as it stands now. */
export function QueueLine({ state, agent }: { state: ConvState; agent: Agent }) {
  const queue = state.live[agent.id]?.queue
  if (!queue) return null
  return (
    <dl className="facts agent-sum">
      <dt>Queue</dt>
      <dd>{queueLine(queue)}</dd>
    </dl>
  )
}

/** A task longer than this, on one line, is folded too. */
const TASK_LINE = 120

/** Who asked it, and what: its task's first line, the rest a click away - and where its work came from or went on. */
export function Asked({ state, agent, onSelectAgent }: { state: ConvState; agent: Agent; onSelectAgent: (agentId: string) => void }) {
  // (A sub-agent that waits to be let start has its task in the card that asks.)
  const task = agent.status === 'proposed' ? null : agent.task
  const continuesTurn = continuesFrom(state, agent.id)
  const parent = state.agents.find(a => a.id === agent.parent_agent_id)
  return (
    <div className="agent-asked">
      {task && (
        <p className="insp-request">
          <span className="muted">Asked by {parent ? titleOf(parent.name || parent.role_name) : 'you'}: </span>
          <TaskText task={task} />
          {continuesTurn !== null && <span className="muted"> (continues from the {continuesTurn} message)</span>}
        </p>
      )}
      <HandedFrom state={state} agent={agent} onSelectAgent={onSelectAgent} />
      <WentOn state={state} agentId={agent.id} onSelectAgent={onSelectAgent} />
    </div>
  )
}

/** Its task: a long one (a lead's brief) its first line, the rest a click away. */
function TaskText({ task }: { task: string }) {
  const [open, setOpen] = useState(false)
  const lines = task.split('\n').length
  if (lines === 1 && task.length <= TASK_LINE) return task
  return (
    <>
      <span className={open ? undefined : 'agent-task-line'}>{open ? task : task.split('\n').find(line => line.trim())}</span>
      <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? '▾ fold' : `▸ ${lines > 1 ? many(lines, 'line') : 'all of it'}`}
      </button>
    </>
  )
}

/**
 * K-devir-1: the ended agents whose work its briefing carried. B-366: one of another chat is not in this state - its
 * name and chat are asked of the server, and which chat it is is the server's to say.
 */
function HandedFrom({ state, agent, onSelectAgent }: { state: ConvState; agent: Agent; onSelectAgent: (agentId: string) => void }) {
  const handed = (agent.handed_from ?? []).map(id => ({ id, from: state.agents.find(a => a.id === id) }))
  const elsewhere = handed.some(one => !one.from)
  const [told, setTold] = useState<Handed[]>([])
  useEffect(() => {
    if (!elsewhere) return
    let gone = false
    api.get<Handed[]>(`/agents/${agent.id}/handed`).then(
      found => !gone && setTold(found),
      () => {}, // (unnamed then, as before: "an earlier agent")
    )
    return () => {
      gone = true
    }
  }, [agent.id, elsewhere])
  if (handed.length === 0) return null
  return (
    <dl className="facts agent-sum">
      <dt>Handed on from</dt>
      <dd>
        {/* R167: a list, each one's words and comma in its own item - read loose, a screen reader had ", , in chat"
            before the names. */}
        <ul className="inline-list">
          {handed.map(({ id, from }, i) => (
            <li key={id}>
              <HandedOne state={state} id={id} from={from} far={told.find(one => one.agent_id === id)} onSelectAgent={onSelectAgent} />
              {i < handed.length - 1 && ', '}
            </li>
          ))}
        </ul>
      </dd>
    </dl>
  )
}

function HandedOne({ state, id, from, far, onSelectAgent }: { state: ConvState; id: string; from?: Agent; far?: Handed; onSelectAgent: (agentId: string) => void }) {
  if (from) {
    return (
      <button type="button" className="link-btn" onClick={() => onSelectAgent(id)}>
        {titleOf(from.name || from.role_name)} ({clock(from.ended_at ?? from.started_at ?? from.created_at)})
      </button>
    )
  }
  if (!far) return 'an earlier agent'
  const here = far.conversation_id === state.conversation.id
  // Of another chat: a click opens that chat, as the Workspace's "Last on this file" does.
  return (
    <>
      <button type="button" className="link-btn" onClick={() => (here ? onSelectAgent(id) : void useApp.getState().openConversation(far.conversation_id))}>
        {titleOf(far.agent_name || far.agent_role)} ({clock(far.at)})
      </button>
      {!here && ` in chat «${far.conversation_title}»`}
    </>
  )
}

/**
 * How its CLI works, where it is seen without a click - what runs unasked is never folded away: its CLI was started
 * without leave to write or run (the user's own settings for that CLI can allow more: said once a command or a change of
 * its is on record), or it works with its own tools; and K-native-not: what of KOLONİ's rules nobody watches the way its
 * CLI runs, said from its start.
 */
export function HowItRuns({ state, agent }: { state: ConvState; agent: Agent }) {
  const ownTools = state.toolCalls.some(t => t.agent_id === agent.id && t.origin === 'cli')
  const unwatched = useApp(s => notWatched(s, agent))
  return (
    <>
      {(agent.provider_mode === 'reads' || ownTools || unwatched) && (
        <p>
          <span className="tag tag-warn">{agent.provider_mode === 'reads' ? <>reads only{letThrough(state, agent.id) && LET_THROUGH}</> : 'works with its own tools'}</span>
        </p>
      )}
      {unwatched && (
        <details className="muted provider-note">
          <summary>{NOT_WATCHED}</summary>
          <ul>
            {unwatched.map(rule => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

/**
 * Its report: its findings each with the role it went to, as its node counts them, then its words - in the panel cut to
 * a few lines (`short`), whole in its window. While it works, what it is on now.
 */
export function Report({ state, agent, short = false }: { state: ConvState; agent: Agent; short?: boolean }) {
  if (agent.report === null) return <NoReport state={state} agent={agent} />
  const found = findingsLine(agent.findings)
  return (
    <div className="agent-report">
      {found && <p className="mono agent-found">{found.line}</p>}
      {agent.findings && agent.findings.length > 0 && (
        <ul className="agent-findings">
          {agent.findings.map((finding, i) => (
            <li key={i}>
              {finding.what}{' '}
              <span className="muted">
                ({finding.kind}
                {finding.blocking === false && ', suggestion'})
              </span>{' '}
              <span className="mono">→ {finding.role ?? 'no role named'}</span>
            </li>
          ))}
        </ul>
      )}
      <Clamped short={short} text={agent.findings?.length ? withoutFindings(agent.report) : agent.report} />
    </div>
  )
}

/**
 * Its report's words: in the panel cut to a few lines, with Show all where they are cut, which opens them in place. A
 * link in the cut part is out of the Tab order while it is hidden (its words are read out all the same).
 */
function Clamped({ text, short }: { text: string; short: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const [whole, setWhole] = useState(!short)
  const [cut, setCut] = useState(false)
  useLayoutEffect(() => {
    const el = box.current!
    const over = !whole && el.scrollHeight > el.clientHeight + 1
    setCut(over)
    const bottom = el.getBoundingClientRect().bottom
    for (const link of Array.from(el.querySelectorAll('a'))) {
      if (over && link.getBoundingClientRect().top >= bottom) link.setAttribute('tabindex', '-1')
      else link.removeAttribute('tabindex')
    }
  }, [text, whole])
  return (
    <>
      <div ref={box} className={`markdown${whole ? '' : ' agent-report-clamp'}`}>
        <Markdown>{text}</Markdown>
      </div>
      {cut && (
        <button type="button" className="link-btn agent-report-more" onClick={() => setWhole(true)}>
          Show all
        </button>
      )}
    </>
  )
}

function NoReport({ state, agent }: { state: ConvState; agent: Agent }) {
  if (agent.status === 'proposed') return null
  if (!AT_WORK.has(agent.status)) return <p className="muted">It wrote no report.</p>
  const last = phasesOf(state, agent).at(-1)
  const line = last && phaseLine(state, last)
  return (
    <>
      <p className="muted">No report yet — it writes one when its work is over.</p>
      {line && (
        <p className="agent-now">
          Now: {last.kind === 'said' ? `“${last.said}”` : line.title}
          {line.result && ` — ${line.result}`}
        </p>
      )}
    </>
  )
}

/**
 * The key numbers: what it did, counted from its record - its own steps, not a CLI sub-agent's inside them; a command is
 * not counted among its tools as well, nor one that never ran; a change thrown away with its working copy is not one it
 * made - and its tokens as its provider said them, "–" where it said none.
 */
// shortcut: no cost per agent is on record (the Usage page prices the turn); add it here if the agent gets one.
export function KeyNumbers({ state, agent }: { state: ConvState; agent: Agent }) {
  const stepped = stepsOf(state, agent.id, agent.report)
  const own = (callId: string | null) => homeOf(state.toolCalls.find(t => t.id === callId), stepped.subAgents) === null
  const commands = state.commands.filter(c => c.agent_id === agent.id && c.status !== 'proposed' && c.status !== 'rejected' && own(c.tool_call_id))
  const tools = state.toolCalls.filter(
    t => t.agent_id === agent.id && t.name !== 'run_command' && homeOf(t, stepped.subAgents) === null && !state.commands.some(c => c.tool_call_id === t.id),
  )
  const made = new Set(state.fileChanges.filter(f => f.agent_id === agent.id && !inScratch(f.path) && f.status !== 'discarded').map(f => f.path)).size
  const show = (n: number | null) => (n === null ? '–' : n.toLocaleString('en-US'))
  const units = spent(agent)
  if (!agent.started_at) return null
  return (
    <dl className="facts agent-sum agent-numbers">
      <dt>Did</dt>
      <dd>
        {many(made, 'file')} changed · {many(tools.length, 'tool')} · {many(commands.length, 'command')} · {many(stepped.steps.length, 'step')}
      </dd>
      <dt>Tokens</dt>
      <dd>
        {`${show(agent.input_tokens)} in / ${show(agent.output_tokens)} out`}
        {units && ` · ${units}`}
      </dd>
    </dl>
  )
}

/**
 * What it changed: where its work is kept (its own copy, or why not), what of it did not reach the project and why, and
 * each file with its diff a click away - in the Workspace's Files view.
 */
export function AgentChanges({ state, agent, open, onToggle, onOpenChange }: {
  state: ConvState
  agent: Agent
  open: boolean
  onToggle: (open: boolean) => void
  onOpenChange: (changeId: string) => void
}) {
  // (Its scratch writes are on their calls' cards in its steps, with their undo.)
  const changes = state.fileChanges.filter(f => f.agent_id === agent.id && !inScratch(f.path))
  // What of its changes did not reach the project, with why: also a file no change record shows.
  const unapplied = state.merges.filter(m => m.agent_id === agent.id && m.status !== 'pending' && !isKept(m) && m.files.some(f => f.state !== 'applied'))
  const files = new Set(changes.map(f => f.path)).size
  return (
    <Fold title="Changes" count={files ? many(files, 'file') : 'none'} open={open} onToggle={onToggle}>
      <CopyNote state={state} agent={agent} />
      <AgentFiles state={state} agent={agent} />
      {unapplied.map(m => (
        <NotApplied key={m.id} merge={m} name={titleOf(agent.name || agent.role_name)} />
      ))}
      {changes.length === 0 && unapplied.length === 0 && <p className="muted">No changes by this agent.</p>}
      {/* shortcut: a file changed twice has two lines, each with its own diff; make it one line per file if that reads as noise. */}
      {changes.map(change => (
        <ChangeRow key={change.id} change={change} labelled onOpenChange={onOpenChange} />
      ))}
    </Fold>
  )
}

/** Where it works: its own copy (counted as its work goes on, slice 70), or the project itself and why. */
function CopyNote({ state, agent }: { state: ConvState; agent: Agent }) {
  const copy = copyLine(state, agent)
  const live = agent.copy?.state === 'own' && AT_WORK.has(agent.status)
  const working = useWorkingCopy(live ? agent.id : null, `${state.fileChanges.filter(f => f.status === 'in_copy').length}`)
  const why: Record<string, string> = {
    too_big: 'This project is too big to copy: it works in the project itself, beside the other agents.',
    failed: 'This project could not be copied: it works in the project itself, beside the other agents.',
  }
  return (
    <>
      {copy && <p className="muted provider-note">{why[agent.copy?.state ?? ''] ?? `It ${copy}: the project gets its changes when its work is over.`}</p>}
      {working && <CopyCounts agentId={agent.id} counts={counted(working)} onSee={() => useApp.getState().openFiles(`copy:${agent.id}`)} />}
    </>
  )
}
