import { CaretDown, CaretRight } from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import type { Command, FileChange, ToolCall } from '../api/types'
import { StatusLabel } from '../shell/StatusLabel'
import { RUN_MARKS } from './ToolRow'
import { runHead } from './toolRuns'

// Calls whose line was left open, kept while the page is open (a reload closes them): by every
// call of the line, so a line a card splits stays open on both sides, and one joined to an open one opens.
const opened = new Set<string>()
// Live lines you closed, by their first call: they stay closed as more calls join them.
const shut = new Set<string>()

interface Props {
  calls: ToolCall[]
  state: { commands: Command[]; fileChanges: FileChange[] }
  /** The calls' rows, as the chat shows each of them anywhere else. */
  children: ReactNode
  /** The newest line of a turn at work (0.1.5): open while it runs, unless you closed it. */
  live?: boolean
}

/** An agent's calls in a row, one line that counts them (K-ozet-satiri); opened, their rows. */
export function ToolRun({ calls, state, children, live = false }: Props) {
  const [, redraw] = useState(0)
  const open = calls.some(call => opened.has(call.id)) || (live && !shut.has(calls[0].id))
  const { what, marks, status } = runHead(calls, state)
  const [label, color] = RUN_MARKS[status]
  // "1 failed", "2 rejected", "3 refused by the judge", "4 parked": what did not end well is never folded away.
  const marked = marks.map(([end, count]) => `${count} ${RUN_MARKS[end][0]}`)
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
          if (open) shut.add(calls[0].id)
          else shut.delete(calls[0].id)
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
