import { CaretRight } from '@phosphor-icons/react'
import { type ReactNode, useLayoutEffect, useRef } from 'react'
import type { Command, FileChange, Run, ToolCall } from '../api/types'
import { TOOL_STATUS } from './ToolRow'
import { runHead } from './toolRuns'

interface Props {
  /** The focus was on one of its steps as the turn ended: those are drawn anew in it, so its line takes the focus. */
  refocus: boolean
  /** How the turn ended: completed, or failed, stopped or interrupted. */
  ended: Run['status']
  /** How many steps are in it: the Lead's words, a line of calls, a row each. */
  count: number
  /** How long the turn took, where it is known. */
  took: string | null
  /** Every call folded in it: what of them did not end well is counted on its line. */
  calls: ToolCall[]
  state: { commands: Command[]; fileChanges: FileChange[] }
  children: ReactNode
}

/** What a turn that did not complete says on its fold's line. */
const ENDED: Partial<Record<Run['status'], string>> = { failed: 'Failed', cancelled: 'Stopped', interrupted: 'Interrupted' }

/**
 * A finished turn's steps before its answer, as VS Code folds them: one closed line, "Completed 5 steps in 32s · 1 failed";
 * with a step that failed, its reason under the line, outside the fold - why something did not happen, without opening it.
 */
export function TurnSteps({ refocus, ended, count, took, calls, state, children }: Props) {
  const line = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    const at = document.activeElement
    if (refocus && (!at || at === document.body)) line.current?.focus()
  }, [refocus])
  // (A command that exited with an error is counted failed by runHead, as on the line inside.)
  const { marks } = runHead(calls, state)
  const why = firstWhy(calls)
  return (
    <>
      <details className="turn-steps">
        <summary ref={line}>
          <span>{ENDED[ended] ? `${ENDED[ended]} after ${count} steps` : `Completed ${count} steps${took ? ` in ${took}` : ''}`}</span>
          {marks.map(([end, n]) => (
            <span key={end} className={`tag ${end === 'failed' ? 'tag-del' : 'tag-warn'}`}>
              {`${n} ${TOOL_STATUS[end][0]}`}
            </span>
          ))}
          <CaretRight size={12} className="turn-steps-caret" aria-hidden />
        </summary>
        <div className="turn-steps-body">{children}</div>
      </details>
      {why && (
        <div className="turn-steps-why muted" title={why}>
          <span aria-hidden>↳ </span>
          <span>{why}</span>
        </div>
      )}
    </>
  )
}

/** The first failed step's reason in one line, as KOLONİ wrote it: its result's first line, "error: " off (app/agent does the same); null with none. */
function firstWhy(calls: ToolCall[]): string | null {
  const line = calls.find(call => call.status === 'failed' && call.result)?.result?.split('\n', 1)[0].replace(/^error: /, '').trim()
  return line || null
}
