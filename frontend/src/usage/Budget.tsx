import { Wallet } from '@phosphor-icons/react'
import type { Budget } from '../api/types'
import { Cell } from '../shell/Cell'
import { budgetWarning, daysLeft, UNENFORCED, unenforced, usedPercent } from './budgetText'
import { money } from './cost'

/**
 * In the top bar (tek-ev §3): a pill from 80% of the month's budget on, until the month or the budget changes, and
 * while the budget is not enforced; it opens Usage, where the budget is read.
 */
export function BudgetPill({ budget, onOpen }: { budget: Budget | null; onOpen: () => void }) {
  if (!budget || !(budget.warn || unenforced(budget))) return null
  const said = unenforced(budget) ? 'not enforced' : `${budget.over ? 'over · ' : ''}${usedPercent(budget)}%`
  // shortcut: near the budget the bar takes two lines just over 1250 and 1100 px with a turn that waits and a
  // on (measured: 1283, 1171), as theme/base.css's B-174 steps already allow for longer states; the strip it replaced
  // was a line of its own. Step the bar by its own width there if that is met.
  // (Short, so that the bar keeps to one line - B-174; its whole warning in its title, its description: a name with
  // "message" in it would be the message box's label too.)
  return (
    <button
      type="button"
      className="budget-pill"
      aria-label={`Budget ${said}`}
      title={`${budgetWarning(budget)}. Opens Usage.`}
      onClick={onOpen}
    >
      <Wallet size={14} weight="bold" aria-hidden /> {said}
    </button>
  )
}

const TENTHS = 10

/**
 * The month's spend as ten cells, each a tenth of the budget: full where it is spent, light where part of it is, and
 * red-orange all over once the budget is. One meter, named; its numbers are in words beside it, the cells hidden.
 */
function Comb({ budget, spent, of }: { budget: Budget; spent: number; of: number }) {
  const tenths = (spent / of) * TENTHS
  const tenth = `${(of / TENTHS).toLocaleString('en-US', { maximumFractionDigits: 2 })} ${budget.currency ?? ''}`
  return (
    <span
      role="meter"
      aria-label="Monthly budget used"
      aria-valuemin={0}
      aria-valuemax={of}
      aria-valuenow={spent}
      aria-valuetext={`${usedPercent(budget)}% used`}
      className="budget-comb"
    >
      {Array.from({ length: TENTHS }, (_, at) => {
        const part = Math.min(1, Math.max(0, tenths - at))
        return (
          <Cell
            key={at}
            big
            hidden
            tone={budget.over ? 'warn' : part > 0 ? 'honey' : 'plain'}
            fill={part >= 1 ? 'full' : part > 0 ? 'soft' : 'none'}
            label={`A tenth of the budget, ${tenth}: ${part >= 1 ? 'spent' : part > 0 ? 'partly spent' : 'not spent'}`}
          />
        )
      })}
    </span>
  )
}

/** On the Usage page: this calendar month's spend against the budget, its cells and numbers; unpriced turns said apart. */
export function BudgetSection({ budget, onSettings }: { budget: Budget; onSettings?: () => void }) {
  if (budget.budget === null) return null
  const unpriced = budget.unpriced_runs
  const left = daysLeft()
  return (
    <section className="memory-section" aria-label="This month’s budget">
      <div className="memory-head">
        <h3>This month’s budget</h3>
        {onSettings && (
          <button type="button" className="usage-open" onClick={onSettings}>
            Change in Settings →
          </button>
        )}
      </div>
      {budget.spent === null ? (
        <p className="muted">{UNENFORCED}: this month’s spend is not added up.</p>
      ) : (
        <>
          <Comb budget={budget} spent={budget.spent} of={budget.budget} />
          <p className="usage-summary">
            <span className="mono">
              {money({ amount: budget.spent, currency: budget.currency ?? '', at_least: budget.at_least })} of{' '}
              {budget.budget.toLocaleString('en-US')} {budget.currency ?? ''}
            </span>{' '}
            <span className="muted">
              · {usedPercent(budget)}% used ·{' '}
              {left === 0 ? 'the month’s last day' : left === 1 ? '1 day left' : `${left} days left`}
            </span>
          </p>
          {budget.over && <p className="alert">{budgetWarning(budget)}</p>}
          <p className="muted memory-hint">
            Each cell is a tenth of it. Once all are full, new work waits for your word.
          </p>
        </>
      )}
      {unpriced > 0 && (
        <p className="muted memory-hint">
          {unpriced === 1 ? '1 message' : `${unpriced} messages`} this month ran on a model with no price (or a CLI, or
          one that reported nothing): not counted in the spend.
        </p>
      )}
    </section>
  )
}
