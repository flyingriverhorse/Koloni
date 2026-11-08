import { useEffect, useId, useRef, useState } from 'react'
import type { Sign } from '../api/types'
import { took } from '../canvas/timeline'

/** The user's answers to signs, by agent id: kept in this browser only; the sign itself stays on the agent's record. */
const KEY = 'koloni-signs'
const MINUTE = 60_000
type Answer = { until: number } | { never: true }

function answers(): Record<string, Answer> {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(KEY) ?? '{}')
    return stored && typeof stored === 'object' ? (stored as Record<string, Answer>) : {}
  } catch {
    return {}
  }
}

function keep(agentId: string, answer: Answer) {
  localStorage.setItem(KEY, JSON.stringify({ ...answers(), [agentId]: answer }))
}

/** The time now, read again every `ms`: for what is shown only after a while. */
function useNow(ms: number): number {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(timer)
  }, [ms])
  return now
}

// What a click on the sign does to the node or row it sits on: nothing.
const stop = (event: { stopPropagation: () => void }) => event.stopPropagation()

/**
 * What was counted of an agent's own tool calls, as a chip: the count in a word, the sentence under
 * the pointer and in the panel it opens, with three answers kept in this browser. A fact, not a judgement.
 * `stopped`: its work was ended for it (a turn nobody watched); otherwise nothing was.
 */
export function SignChip({ agentId, sign, stopped = false }: { agentId: string; sign: Sign; stopped?: boolean }) {
  const now = useNow(MINUTE)
  const [, answered] = useState(0)
  const panel = useId()
  const chip = useRef<HTMLButtonElement>(null)
  const answer = answers()[agentId]
  if (answer && ('never' in answer || answer.until > now)) return null
  const pick = (given: Answer) => {
    keep(agentId, given)
    // The chip goes: focus goes to the node or row it was on, not to the page.
    chip.current?.parentElement?.closest<HTMLElement>('[tabindex]')?.focus()
    answered(n => n + 1)
  }
  return (
    <>
      <button
        ref={chip}
        type="button"
        className="tag tag-warn sign-chip nodrag"
        popoverTarget={panel}
        title={sign.text}
        onClick={stop}
        onDoubleClick={stop}
      >
        {sign.count}× {sign.kind === 'same_failure' ? 'same error' : 'same result'}
      </button>
      <div id={panel} popover="auto" className="sign-panel nodrag nopan" role="dialog" aria-label="What was counted" onClick={stop} onDoubleClick={stop}>
        <p>{sign.text}</p>
        <p className="muted">Counted from its own tool calls.{' '}
          {stopped ? 'Its work was stopped for it: nobody watched this turn.' : 'Nothing was stopped for it.'} Your answer is kept
          in this browser.</p>
        <div className="sign-answers">
          <button type="button" className="btn btn-small" onClick={() => pick({ until: Date.now() + 10 * MINUTE })}>
            Snooze 10 min
          </button>
          <button type="button" className="btn btn-small" onClick={() => pick({ until: Date.now() + 30 * MINUTE })}>
            It’s fine
          </button>
          <button type="button" className="btn btn-small" onClick={() => pick({ never: true })}>
            Don’t show for this agent
          </button>
        </div>
      </div>
    </>
  )
}

/**
 * How long a running agent has taken no step and had no tool start or end, measured by this browser's clock (R53 G6):
 * "last step 12s ago"; past 5 minutes, "no tool or step for N min" - only that: a model writing a long answer takes no
 * step meanwhile, so it is not said to be stuck; past 20 inside a tool, slow. Nothing is stopped for it. `trail`: what
 * follows it where it says anything (on a canvas node, " · ").
 */
export function Quiet({ lastEventAt, inTool, trail = '' }: { lastEventAt: string | null; inTool: boolean; trail?: string }) {
  const now = useNow(1000)
  if (!lastEventAt) return null
  const quiet = now - Date.parse(lastEventAt)
  const minutes = Math.floor(quiet / MINUTE)
  // (In a tool: how long that has run is said with it, `Since`.)
  if (inTool && minutes < 20) return null
  const said = inTool ? `slow · no tool event for ${minutes} min` : minutes < 5 ? `last step ${took(quiet)} ago` : `no tool or step for ${minutes} min`
  return (
    <span className="muted">
      {said}
      {trail}
    </span>
  )
}

/** How long something of an agent's has run, by this browser's clock: its tool, "12s · " (slice 84d); its work, "at work 1m 12s". */
export function Since({ at, work = false }: { at: string; work?: boolean }) {
  const now = useNow(1000)
  const time = took(now - Date.parse(at))
  return work ? <>at work {time}</> : <>{time} · </>
}
