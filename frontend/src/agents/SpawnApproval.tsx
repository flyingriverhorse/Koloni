import { Check, X } from '@phosphor-icons/react'
import { Fragment, type ReactNode, useState } from 'react'
import { errorText } from '../api/client'
import type { Agent, PendingRole } from '../api/types'
import { titleOf } from './agentStatus'
import { ranOn } from '../shell/modelName'
import type { Stays } from './staysOn'
import { CardMore } from '../shell/CardMore'

export type SpawnDecision = 'approve' | 'reject'

interface CardProps {
  kicker: string
  /** Left out where there is nothing to say yes to: only the other answer is offered. */
  approve?: string
  /** What saying no is called here, when it is not "Reject" (Discard: it deletes the copy - another act). */
  reject?: string
  /** Yes cannot be said yet: the card itself says what is missing. */
  approveOff?: boolean
  /** Neither answer can be given right now: the card itself says what it waits for. */
  off?: boolean
  onDecide: (decision: SpawnDecision) => Promise<void>
  /** A third way, beside the two (K-devam-butce: Continue on a stopped agent's card). */
  also?: { label: string; run: () => Promise<void> }
  children: ReactNode
  /** What only explains the buttons: folded under Details, after them. */
  more?: ReactNode
}

/** A question with two answers; locked while the answer travels, and says why it failed. */
export function DecisionCard({ kicker, approve, reject = 'Reject', approveOff = false, off = false, onDecide, also, children, more }: CardProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function decide(decision: SpawnDecision | (() => Promise<void>)) {
    setBusy(true)
    setError(null)
    try {
      await (typeof decision === 'function' ? decision() : onDecide(decision))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cmd-approval">
      <div className="kicker cmd-approval-kicker">{kicker}</div>
      {children}
      <div className="change-actions">
        {approve && (
          <button type="button" className="btn btn-small btn-primary" disabled={busy || off || approveOff} onClick={() => decide('approve')}>
            <Check size={13} />
            {approve}
          </button>
        )}
        {also && (
          <button type="button" className="btn btn-small" disabled={busy || off} onClick={() => decide(also.run)}>
            {also.label}
          </button>
        )}
        <button type="button" className="btn btn-small" disabled={busy || off} onClick={() => decide('reject')}>
          <X size={13} />
          {reject}
        </button>
      </div>
      {more && <CardMore>{more}</CardMore>}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

export function ToolChips({ tools }: { tools: string[] }) {
  return (
    <div className="chips">
      {tools.map(tool => (
        <span key={tool} className="tag mono">
          {tool}
        </span>
      ))}
    </div>
  )
}

interface Props {
  agent: Agent
  /** The name of the agent that asked for it. */
  openedBy?: string
  /** The turn of the topic whose agent it goes on from, when it does: it starts with what that one did. */
  continuesTurn?: string | null
  /** It stays on the provider · model it ran on before, though its role would run elsewhere today. */
  stays?: Stays | null
  onDecide: (decision: SpawnDecision) => Promise<void>
  /** A skill of its role it is not given, opened in its window (on the Tools page). */
  onOpenSkill?: (name: string) => void
}

/** Asks before a sub-agent starts: which role, on which model, the whole task, and what it may use. */
export function SpawnApproval({ agent, openedBy, continuesTurn, stays, onDecide, onOpenSkill }: Props) {
  const where = ranOn(agent.provider_name, agent.model_id, agent.model_from)
  const leftOut = Object.entries(agent.skills?.left_out ?? {})
  return (
    <DecisionCard kicker="Open this sub-agent?" approve="Open agent" onDecide={onDecide}>
      <div className="cmd-approval-where">
        <strong>{agent.role_name}</strong>
        <span className="mono muted">depth {agent.depth}</span>
      </div>
      {continuesTurn != null && (
        <div className="spawn-line">
          continues {agent.name || agent.role_name} from the {continuesTurn} message
        </div>
      )}
      {where && (
        <div className="spawn-line">
          <span className="mono">{where}</span>
          {agent.chosen && <span className="tag tag-warn">chosen by {openedBy ? titleOf(openedBy) : 'the agent that opened it'}</span>}
        </div>
      )}
      {stays && (
        <div className="muted cmd-approval-note">
          It stays on {stays.on}, where it ran before.{stays.role && ` Its role would now run on ${stays.role}.`}
        </div>
      )}
      {agent.chosen && (
        <div className="muted cmd-approval-note">This is not its role's own model: the agent picked it from your team guide.</div>
      )}
      {/* The agent's own words, shown as such: in quotes. */}
      {agent.chosen_why && (
        <div className="spawn-line">
          Its reason: <q>{agent.chosen_why}</q>
        </div>
      )}
      <pre className="cmd-approval-command spawn-task">{agent.task}</pre>
      <ToolChips tools={agent.tools} />
      {/* What it may use besides: the tools of these servers, each call asked about as its mark says. */}
      {agent.mcp.length > 0 && (
        <div className="muted cmd-approval-note">
          MCP servers: <span className="mono">{agent.mcp.join(', ')}</span>
        </div>
      )}
      {/* K-skill-uyum: what of its role's skills it does not get here, and why. */}
      {leftOut.length > 0 && (
        <div className="muted cmd-approval-note">
          Skills:{' '}
          {leftOut.map(([name, why], at) => (
            <Fragment key={name}>
              {at > 0 && ', '}
              {onOpenSkill ? (
                <button type="button" className="link-btn" onClick={() => onOpenSkill(name)}>
                  {name}
                </button>
              ) : (
                name
              )}{' '}
              ({why})
            </Fragment>
          ))}{' '}
          left out
        </div>
      )}
    </DecisionCard>
  )
}

/** Asks before an agent adds a role to your list. */
export function RoleCard({ role, onDecide }: { role: PendingRole; onDecide: Props['onDecide'] }) {
  return (
    <DecisionCard kicker="Create this role?" approve="Create role" onDecide={onDecide} more="The role is kept on the Agents page. A sub-agent never gets tools its parent lacks.">
      <div className="cmd-approval-where">
        <strong>{role.name}</strong>
      </div>
      {role.description && <div className="spawn-line">{role.description}</div>}
      {role.instructions && <pre className="cmd-approval-command spawn-task">{role.instructions}</pre>}
      <ToolChips tools={role.tools} />
      {role.knowledge && (
        // K-uzman: an expert - what it knows and where it reads it. No cost is shown: it is not known before it reads.
        <div className="spawn-line">
          <span className="chip-knows">knows: {role.knowledge.topic}</span> advises · reads only. Learns from: {role.knowledge.sources.join(', ')} (at most {role.knowledge.max_pages} pages, {role.knowledge.max_usd} USD)
        </div>
      )}
    </DecisionCard>
  )
}
