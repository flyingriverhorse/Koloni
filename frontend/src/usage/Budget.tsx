import { Wallet } from '@phosphor-icons/react'
import type { Budget } from '../api/types'
import { budgetWarning, UNENFORCED, unenforced, usedPercent } from './budgetText'
import { money } from './cost'

/**
 * In the top bar (tek-ev §3): a pill from 80% of the month's budget on, until the month or the budget changes, and
 * while the budget is not enforced; it opens Usage, where the budget is read.
 */
export function BudgetPill({ budget, onOpen }: { budget: Budget | null; onOpen: () => void }) {
  if (!budget || !(budget.warn || unenforced(budget))) return null
  const said = unenforced(budget) ? 'not enforced' : `${budget.over ? 'over · ' : ''}${usedPercent(budget)}%`
  // shortcut: near the budget the bar takes two lines just over 1250 and 1100 px with a turn that waits and a trigger
  // on (measured: 1283, 1171), as theme/base.css's B-174 steps already allow for longer states; the strip it replaced
  // was a line of its own. Step the bar by its own width there if that is met.
  // (Short, so that the bar keeps to one line - B-174; its whole warning in its title, its description: a name with
  // "message" in it would be the message box's label too.)
  return (
    <button type="button" className="budget-pill" aria-label={`Budget ${said}`} title={`${budgetWarning(budget)}. Opens Usage.`} onClick={onOpen}>
      <Wallet size={14} weight="bold" aria-hidden /> {said}
    </button>
  )
}

/** On the Usage page: this calendar month's spend against the budget, a bar and its numbers; unpriced turns said apart. */
export function BudgetSection({ budget, onSettings }: { budget: Budget; onSettings?: () => void }) {
  if (budget.budget === null) return null
  const unpriced = budget.unpriced_runs
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
          <meter className="budget-meter" aria-label="Monthly budget used" min={0} max={budget.budget} low={budget.budget * 0.8} high={budget.budget} optimum={0} value={budget.spent} />
          <p className="usage-summary">
            <span className="mono">
              {money({ amount: budget.spent, currency: budget.currency ?? '', at_least: budget.at_least })} of {budget.budget.toLocaleString('en-US')} {budget.currency ?? ''}
            </span>{' '}
            <span className="muted">· {usedPercent(budget)}% used</span>
          </p>
          {budget.over && <p className="alert">{budgetWarning(budget)}</p>}
        </>
      )}
      {unpriced > 0 && (
        <p className="muted memory-hint">
          {unpriced === 1 ? '1 message' : `${unpriced} messages`} this month ran on a model with no price (or a CLI, or one that reported nothing):
          not counted in the spend.
        </p>
      )}
    </section>
  )
}
