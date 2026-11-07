import { Robot } from '@phosphor-icons/react'
import { useState } from 'react'
import { Markdown } from '../chat/Markdown'
import type { ToolCall } from '../api/types'
import { TOOL_STATUS, ToolRow } from '../chat/ToolRow'
import { CommandRow } from '../commands/CommandRow'
import { StatusLabel } from '../shell/StatusLabel'
import type { ConvState } from '../state/applyEvent'
import { innerCalls, isOwnSubAgent, ownSubAgentBrief, ownSubAgentEnding, ownSubAgentModel, ownSubAgentTask } from './ownWork'

interface Props {
  state: ConvState
  /** The call the sub-agent is on record as. */
  call: ToolCall
  onOpenChange?: (changeId: string) => void
}

/** What a sub-agent of a CLI's own was asked, what it did, and what it said last. */
export function OwnSubAgentWork({ state, call, onOpenChange }: Props) {
  const { prompt, role } = ownSubAgentBrief(call)
  const calls = innerCalls(state, call.id)
  const working = call.status === 'running' || call.status === 'pending'
  const ending = ownSubAgentEnding(call)
  return (
    <>
      {/* It is no agent of KOLONİ's: neither the role's model nor a pick from the team guide applies to it. */}
      <div className="choice-note">{ownSubAgentModel(call)}</div>
      {/* 89g: a role KOLONİ offered the CLI (its node said it before nodes were three lines: the user's, 5 Nov). */}
      {role && <div className="choice-note">{role} (inside Claude Code)</div>}
      {prompt && <div className="agent-feed-task">{prompt}</div>}
      {calls.length === 0 && <p className="muted">{working ? 'Nothing on record yet.' : 'Nothing on record.'}</p>}
      {calls.map(inner => {
        // A sub-agent it opened itself: a block of its own, inside this one.
        if (isOwnSubAgent(inner)) {
          return <OwnSubAgentBlock key={inner.id} state={state} call={inner} onOpenChange={onOpenChange} />
        }
        const ran = state.commands.find(c => c.tool_call_id === inner.id)
        if (ran) return <CommandRow key={inner.id} command={ran} failed={inner.status === 'failed'} />
        const change = state.fileChanges.find(f => f.tool_call_id === inner.id)
        if (change) {
          return (
            <div key={inner.id} className="chat-change">
              <span className="mono chat-change-path">{change.path}</span>
              <span className="mono" style={{ color: 'var(--ok)' }}>+{change.additions}</span>
              <span className="mono" style={{ color: 'var(--del)' }}>−{change.deletions}</span>
              {onOpenChange && (
                <button type="button" className="btn btn-small" onClick={() => onOpenChange(change.id)}>
                  View diff
                </button>
              )}
            </div>
          )
        }
        return <ToolRow key={inner.id} call={inner} />
      })}
      {ending && (
        <>
          <div className="kicker">{ending.label}</div>
          <div className="markdown">
            <Markdown>{ending.text}</Markdown>
          </div>
        </>
      )}
    </>
  )
}

/**
 * A CLI's own sub-agent in its agent's window: one row that opens onto its work. Open
 * while it works, closed once it is done, until the user chooses otherwise.
 */
export function OwnSubAgentBlock({ state, call, onOpenChange }: Props) {
  const [chosen, setChosen] = useState<boolean | null>(null)
  const open = chosen ?? (call.status === 'running' || call.status === 'pending')
  const [label, color] = TOOL_STATUS[call.status]
  const task = ownSubAgentTask(call) || 'Sub-agent'
  return (
    <div className="own-sub" role="group" aria-label={`Own sub-agent: ${task}`}>
      <button type="button" className="tool-row-head" aria-expanded={open} onClick={() => setChosen(!open)}>
        <Robot size={13} color="var(--accent)" />
        <span className="tool-row-summary">{task}</span>
        <span className="tool-row-status mono muted">own sub-agent</span>
        <StatusLabel color={color}>{label}</StatusLabel>
      </button>
      {open && (
        <div className="own-sub-work">
          <OwnSubAgentWork state={state} call={call} onOpenChange={onOpenChange} />
        </div>
      )}
    </div>
  )
}
