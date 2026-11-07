import type { Budget } from '../api/types'

/** How much of the budget is used, in whole percents rounded down: never "100%" while still under it. */
// (+1e-9: 0.29 * 100 is 28.999999999999996, and 29% is what was used.)
export const usedPercent = (budget: Budget) => Math.floor((budget.share ?? 0) * 100 + 1e-9)

/** With this month's costs in more than one currency nothing is added up (`spent` is null): the budget holds nothing back. */
export const unenforced = (budget: Budget) => budget.budget !== null && budget.spent === null
export const UNENFORCED = 'This budget is not enforced: prices are in more than one currency'

/** What the top bar's pill (its title) and the toast say at 80%: and, over it, what that means for the next message. */
export function budgetWarning(budget: Budget) {
  if (unenforced(budget)) return UNENFORCED
  const used = `This project has used ${budget.at_least ? 'at least ' : ''}${usedPercent(budget)}% of its monthly budget`
  return budget.over ? `${used}: a new message asks before its work starts, and triggers start none` : used
}
