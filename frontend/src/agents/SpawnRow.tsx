import { Robot } from '@phosphor-icons/react'
import type { Agent } from '../api/types'
import { StatusLabel } from '../shell/StatusLabel'
import { useApp } from '../state/store'
import { AGENT_STATUS, titleOf } from './agentStatus'

interface Props {
  agent: Agent
  /** Asked to show this agent (the canvas selects its node). */
  onSelect: (agentId: string) => void
  /** What it changed in its working copy waits for the user's decision: it is not done yet. */
  asks?: boolean
}

/** One sub-agent in a list: its role, what it was asked to do and how it is going. */
export function SpawnRow({ agent, onSelect, asks = false }: Props) {
  const [label, color] = asks ? ['changes wait for your decision', 'var(--warn)'] : AGENT_STATUS[agent.status]
  const teams = useApp(s => s.teams)
  // B-363: the task's own words - not the folder line a Lead opens its brief with ("Project folder: ./ (git repo…)"),
  // nor KOLONİ's "KOLONİ opened you at the same time as…" (then role and status say it).
  // shortcut: those two openings only; widen it if other boilerplate is seen to lead a task.
  const words = (one: string) => (/^\s*Project folder\b/i.test(one) ? (/[.)]\s+(\S.*)$/.exec(one)?.[1] ?? '') : one)
  const line = (agent.task ?? '').split('\n').map(words).find(one => one.trim()) ?? ''
  const firstLine = line.startsWith('KOLONİ opened you') ? '' : line
  return (
    <div className="tool-row">
      <button
        type="button"
        className="tool-row-head"
        title="Show this agent on the canvas"
        onClick={() => onSelect(agent.id)}
      >
        <span style={{ color, display: 'grid' }}>
          <Robot size={13} className={agent.status === 'running' ? 'pulse' : undefined} />
        </span>
        <span className="tool-row-summary">
          <strong>{titleOf(agent.name || agent.role_name, teams)}</strong> <span className="muted">{firstLine}</span>
        </span>
        <StatusLabel color={color}>{label}</StatusLabel>
      </button>
    </div>
  )
}
