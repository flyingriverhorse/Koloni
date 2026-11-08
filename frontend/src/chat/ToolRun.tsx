import { CaretDown, CaretRight } from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import type { Command, FileChange, ToolCall } from '../api/types'
import { StatusLabel } from '../shell/StatusLabel'
import { TOOL_STATUS } from './ToolRow'
import { runHead } from './toolRuns'

// Calls whose line was left open, kept while the page is open (a reload closes them): by every
// call of the line, so a line a card splits stays open on both sides, and one joined to an open one opens.
const opened = new Set<string>()

interface Props {
  calls: ToolCall[]
  state: { commands: Command[]; fileChanges: FileChange[] }
  /** The calls' rows, as the chat shows each of them anywhere else. */
  children: ReactNode
}

/** An agent's calls in a row, one line that counts them (K-ozet-satiri); opened, their rows. */
export function ToolRun({ calls, state, children }: Props) {
  const [, redraw] = useState(0)
  const open = calls.some(call => opened.has(call.id))
  const { what, marks, status } = runHead(calls, state)
  const [label, color] = TOOL_STATUS[status]
  // "1 failed", "2 rejected", "1 interrupted": what did not end well is never folded away.
  const marked = marks.map(([end, count]) => `${count} ${TOOL_STATUS[end][0]}`)
  return (
    <div className="tool-run">
      <button
        type="button"
        className="tool-run-head"
        aria-expanded={open}
        aria-label={[what, ...marked, `${calls.length} calls`, label].filter(Boolean).join(', ')}
        onClick={() => {
          for (const call of calls) {
            if (open) opened.delete(call.id)
            else opened.add(call.id)
          }
          redraw(n => n + 1)
        }}
      >
        <span className="muted" style={{ display: 'grid' }}>
          {open ? <CaretDown size={12} /> : <CaretRight size={12} />}
        </span>
        <span className="tool-run-what" title={what}>
          {what}
        </span>
        {marks.map(([end], n) => (
          <span key={end} className={`tag ${end === 'failed' ? 'tag-del' : 'tag-warn'}`}>
            {marked[n]}
          </span>
        ))}
        <span className="tool-run-count mono muted">{calls.length} calls</span>
        <StatusLabel color={color}>{label}</StatusLabel>
      </button>
      {open && <div className="tool-run-body">{children}</div>}
    </div>
  )
}
