import { CaretRight } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import type { Command, FileChange, ToolCall } from '../api/types'
import { commandStatus } from '../commands/commandStatus'
import { TOOL_STATUS } from './ToolRow'
import { runHead } from './toolRuns'

interface Props {
  /** How many steps are in it: the Lead's words, a line of calls, a row each. */
  count: number
  /** How long the turn took, where it is known. */
  took: string | null
  /** Every call folded in it: what of them did not end well is counted on its line. */
  calls: ToolCall[]
  state: { commands: Command[]; fileChanges: FileChange[] }
  children: ReactNode
}

/** A finished turn's steps before its answer, as VS Code folds them: one closed line, "Completed 5 steps in 32s · 1 failed". */
export function TurnSteps({ count, took, calls, state, children }: Props) {
  // A command that exited with an error ended its call well (app/agent): its own record says it failed.
  const ran = new Set(calls.filter(call => call.status === 'succeeded').map(call => call.id))
  const exited = state.commands.filter(c => ran.has(c.tool_call_id ?? '') && commandStatus(c).tone === 'del').length
  const { marks } = runHead(calls, state)
  const failed = (marks.find(([end]) => end === 'failed')?.[1] ?? 0) + exited
  const counted = [...(failed ? [['failed', failed] as const] : []), ...marks.filter(([end]) => end !== 'failed')]
  return (
    <details className="turn-steps">
      <summary>
        <span>
          Completed {count} steps{took && ` in ${took}`}
        </span>
        {counted.map(([end, n]) => (
          <span key={end} className={`tag ${end === 'failed' ? 'tag-del' : 'tag-warn'}`}>
            {`${n} ${TOOL_STATUS[end][0]}`}
          </span>
        ))}
        <CaretRight size={12} className="turn-steps-caret" aria-hidden />
      </summary>
      <div className="turn-steps-body">{children}</div>
    </details>
  )
}
