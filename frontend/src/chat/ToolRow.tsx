import { Check, CircleNotch, Clock, MinusCircle, X } from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import type { ToolCall } from '../api/types'
import { commandSeconds } from '../commands/commandStatus'
import { StatusLabel } from '../shell/StatusLabel'
import { useApp } from '../state/store'
import { keyOf } from '../views/views'
import { shotOf, toolName, toolSummary, webNote } from './toolSummary'

export const TOOL_STATUS: Record<ToolCall['status'], [label: string, color: string]> = {
  pending: ['waiting', 'var(--muted)'],
  running: ['running', 'var(--accent)'],
  succeeded: ['done', 'var(--ok)'],
  failed: ['failed', 'var(--del)'],
  denied: ['rejected', 'var(--warn)'],
  interrupted: ['interrupted', 'var(--warn)'],
}

function StatusIcon({ status }: { status: ToolCall['status'] }) {
  switch (status) {
    case 'pending':
      return <Clock size={13} />
    case 'running':
      return <CircleNotch size={13} className="spin" />
    case 'succeeded':
      return <Check size={13} />
    case 'failed':
      return <X size={13} />
    default:
      return <MinusCircle size={13} />
  }
}

interface Props {
  call: ToolCall
  /**
   * The call has not returned because its agent waits - for a file another agent holds, or
   * for the user's leave to call a tool of an MCP server: what the row reads then ("waiting
   * for Coder to finish with cart.py"), where it otherwise names the call - and it is
   * "waiting", not "running".
   */
  waits?: string | null
  /** K-inspector: under it, how big its result is and how long it took (an agent's steps); the result stays folded. */
  sized?: boolean
  /** In the chat (0.1.5): its kind's icon, in place of a done step's tick; its file as a pill. */
  icon?: ReactNode
}

/** Under a step: how big its result is, and how long it took where that is known. */
const sizeNote = (result: string, seconds: ReturnType<typeof commandSeconds>) => (
  <div className="tool-row-note mono muted">
    result {result.length.toLocaleString('en-US')} chars{seconds !== null && ` · ${seconds}s`}
  </div>
)

/** The picture of a step, small under it: a click puts it beside the chat. */
const shotButton = (call: ToolCall, shot: string, cid: string) => (
  <button type="button" className="tool-row-shot" title="Open beside the chat" onClick={() => useApp.getState().openFiles(keyOf(shot))}>
    <img src={`/api/conversations/${cid}/views/${call.id}/${encodeURIComponent(shot.split('/').at(-1) ?? '')}`} alt={`${call.name === 'browser_screenshot' ? 'Screenshot' : 'Image'} ${shot.split('/').at(-1)}`} />
  </button>
)

/** An opened row: the call's arguments and its result, as recorded. */
const detailOf = (call: ToolCall) => (
  <div className="tool-row-detail">
    <div className="kicker">Arguments</div>
    <pre className="mono">{call.arguments || '{}'}</pre>
    <div className="kicker">Result</div>
    <pre className="mono">{call.result ?? '(no result yet)'}</pre>
  </div>
)

/** A step's words, what follows its tool's name - its file, its search - as a pill: the words stay as they are. */
function Said({ summary, name }: { summary: string; name: string }) {
  if (!summary.startsWith(`${name} `)) return summary
  return (
    <>
      {name} <span className="step-file">{summary.slice(name.length + 1)}</span>
    </>
  )
}

/** How a row reads: its state's word and colour, its mark and its words - in the chat (`icon`) a done step's kind's icon and its file a pill. */
function lookOf(call: ToolCall, waits: string | null, icon: ReactNode) {
  if (waits) return { label: 'waiting', color: 'var(--muted)', mark: <Clock size={13} />, summary: `${toolName(call)}: ${waits}`, pill: false }
  const [label, color] = TOOL_STATUS[call.status]
  return { label, color, mark: icon && call.status === 'succeeded' ? icon : <StatusIcon status={call.status} />, summary: toolSummary(call), pill: Boolean(icon) }
}

export function ToolRow({ call, waits = null, sized = false, icon }: Props) {
  const [open, setOpen] = useState(false)
  const { label, color, mark, summary, pill } = lookOf(call, waits, icon)
  const answered = webNote(call)
  const cid = useApp(s => s.conv?.conversation.id)
  const shot = shotOf(call)
  const seconds = commandSeconds(call)
  return (
    <div className="tool-row">
      <button
        type="button"
        className="tool-row-head"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span style={{ color, display: 'grid' }}>{mark}</span>
        <span className="tool-row-summary mono" title={waits ? summary : undefined}>
          {pill ? <Said summary={summary} name={toolName(call)} /> : summary}
        </span>
        {call.origin === 'cli' && <span className="tool-row-status mono muted">own tool</span>}
        <StatusLabel color={color}>{label}</StatusLabel>
      </button>
      {/* A search or a request: which way answered, without opening the row. */}
      {answered && <div className="tool-row-note mono muted">{answered}</div>}
      {sized && call.result !== null && sizeNote(call.result, seconds)}
      {/* The agent's screenshot (slice 51), or the image it looked at (28e): small under the step; a click puts it beside the chat, as `show` does. */}
      {shot && cid && shotButton(call, shot, cid)}
      {open && detailOf(call)}
    </div>
  )
}
