import { CaretRight } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import type { Command, FileChange, ToolCall } from '../api/types'
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
  const { marks } = runHead(calls, state)
  return (
    <details className="turn-steps">
      <summary>
        <span>
          Completed {count} steps{took && ` in ${took}`}
        </span>
        {marks.map(([end, n]) => (
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
