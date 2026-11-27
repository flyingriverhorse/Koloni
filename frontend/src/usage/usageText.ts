import type { Budget, Limits, Provider, Usage } from '../api/types'
import { UNENFORCED, unenforced, usedPercent } from './budgetText'
import { money } from './cost'
import { windowName } from './limitsText'
import { type Period, WHEN } from './period'

type Cost = Usage['by_model'][number]['cost']
type Start = Usage['by_start'][number]

/** A number a model reported, or "–" (its row says why) - never a made-up zero. */
export const count = (n: number | null) => (n === null ? '–' : n.toLocaleString('en-US'))

/** Who started it, as its row says: KOLONİ's own requests with no message are "KOLONİ itself" (K-56). */
export const STARTERS: Record<Start['started_by'], string> = {
  user: 'You',
  trigger: 'A trigger, with nobody watching',
  koloni: 'KOLONİ itself',
}

/** A starter in a line: "3 messages by you", "2 requests by KOLONİ itself" (these are in no message). */
export const started = (row: Start) =>
  row.started_by === 'koloni'
    ? `${count(row.agents)} ${row.agents === 1 ? 'request' : 'requests'} by KOLONİ itself`
    : `${count(row.runs)} ${row.runs === 1 ? 'message' : 'messages'} by ${row.started_by === 'trigger' ? 'a trigger' : 'you'}`

/** A row's tokens, sent and written; null where neither was reported. */
export const tokensOf = (row: { input_tokens: number | null; output_tokens: number | null }) =>
  row.input_tokens === null && row.output_tokens === null ? null : (row.input_tokens ?? 0) + (row.output_tokens ?? 0)

type Measured = { cost?: Cost; input_tokens: number | null; output_tokens: number | null }

/**
 * What rows are compared by - a day's bar, a chat's place, a starter's: their money where any has a cost, all in one
 * currency; else the tokens their models reported. What is not known is null, and says so - never a zero.
 */
export function measureOf<T extends Measured>(rows: T[]) {
  const priced = rows.filter(row => typeof row.cost?.amount === 'number')
  const inMoney = priced.length > 0 && new Set(priced.map(row => row.cost!.currency.toUpperCase())).size === 1
  const value = (row: T) => (inMoney ? (row.cost?.amount ?? null) : tokensOf(row))
  const said = (row: T) => {
    if (inMoney) return row.cost ? money(row.cost) : 'no money counted'
    const tokens = tokensOf(row)
    return tokens === null ? 'nothing reported' : `${count(tokens)} tokens`
  }
  return { inMoney, value, said }
}

/** The plan window used most, of what the subscriptions last said, as the page's summary says it; null: none known. */
export function fullestPlan(providers: Provider[], told: Record<string, Limits | string>): string | null {
  const found = providers.flatMap(provider => {
    const limits = told[provider.id]
    return typeof limits === 'object' && !limits.unknown
      ? limits.windows.filter(w => w.used_percent !== null && !w.stale).map(w => ({ provider, w }))
      : []
  })
  const top = found.reduce<(typeof found)[number] | null>(
    (most, one) => (most && most.w.used_percent! >= one.w.used_percent! ? most : one),
    null,
  )
  return top && `${top.provider.name} has used ${Math.round(top.w.used_percent!)}% of ${windowName(top.w)}.`
}

/** This month's budget in the summary; null without one. Over it, what that means. */
function budgetSaid(budget: Budget): string | null {
  if (budget.budget === null) return null
  if (unenforced(budget)) return `${UNENFORCED}.`
  const used = `This month’s budget is ${budget.at_least ? 'at least ' : ''}${usedPercent(budget)}% used`
  return budget.over ? `${used}: a new message asks before its work starts.` : `${used}.`
}

/**
 * The page's summary, in a sentence or three: what the period cost (its signs said in words), this month's budget
 * where the project has one, and the plan used most. Only what is known: with nothing priced no money is said.
 */
export function summarySentence({
  period,
  usage,
  cost,
  budget,
  plan,
}: {
  period: Period
  usage: Usage
  /** The period's cost as the Cost box says it (`totalCost`): "–" where nothing is priced. */
  cost: string
  /** This project's month against its budget; none for every project. */
  budget?: Budget | null
  plan?: string | null
}): string {
  const when = WHEN[period][0].toUpperCase() + WHEN[period].slice(1)
  const spent =
    usage.by_model.length === 0
      ? period === 'today'
        ? 'No agent reported usage today.'
        : 'No agent ran in this period.'
      : cost === '–'
        ? `${when} no money was counted: what ran was on a plan, had no price or reported nothing.`
        : `${when} ${cost.replace(/≥ /g, 'at least ').replace(/≈ /g, 'about ')} was spent.`
  return [spent, budget && budgetSaid(budget), plan].filter(Boolean).join(' ')
}
