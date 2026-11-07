import { ChatsCircle } from '@phosphor-icons/react'
import { useState } from 'react'
import type { ToolCall } from '../api/types'
import { titleOf } from '../agents/agentStatus'
import { StatusLabel } from '../shell/StatusLabel'
import { useApp } from '../state/store'
import { TOOL_STATUS } from './ToolRow'

/** What `message_agent` was asked to send, as far as its arguments can be read. */
export function talkOf(call: Pick<ToolCall, 'arguments'>): { to: string; message: string } {
  try {
    const args: unknown = JSON.parse(call.arguments || '{}')
    if (args && typeof args === 'object') {
      const { to, message } = args as Record<string, unknown>
      return { to: typeof to === 'string' ? to : '', message: typeof message === 'string' ? message : '' }
    }
  } catch {
    // not JSON: shown as an unnamed message
  }
  return { to: '', message: '' }
}

/** One message from an agent to another, with the reply it got. */
export function TalkRow({ call, from }: { call: ToolCall; from: string }) {
  const [open, setOpen] = useState(false)
  const teams = useApp(s => s.teams)
  const [label, color] = TOOL_STATUS[call.status]
  const { to, message } = talkOf(call)
  // A reply comes back as "<Name> replied:" and the text; anything else is shown as it is.
  const reply = call.result?.replace(/^[^\n]* replied:\n\n/, '')
  return (
    <div className="tool-row">
      <button type="button" className="tool-row-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span style={{ color, display: 'grid' }}>
          <ChatsCircle size={13} className={call.status === 'running' ? 'pulse' : undefined} />
        </span>
        <span className="tool-row-summary">
          <strong>
            {titleOf(from, teams)} → {titleOf(to, teams) || 'an agent'}
          </strong>{' '}
          <span className="muted">{message.split('\n')[0]}</span>
        </span>
        <StatusLabel color={color}>{label}</StatusLabel>
      </button>
      {open && (
        <div className="tool-row-detail">
          <div className="kicker">Message</div>
          <pre className="mono">{message || call.arguments}</pre>
          <div className="kicker">Reply</div>
          <pre className="mono">{reply ?? '(no reply yet)'}</pre>
        </div>
      )}
    </div>
  )
}
