import type { Price, Usage } from '../api/types'

type Cost = Usage['by_model'][number]['cost']

/**
 * What a row cost: "≥" where an agent of it is unknown - the amount is then only of
 * what was reported. No cost, or an amount that is no number, is a dash.
 */
export function money(cost: Cost) {
  if (typeof cost?.amount !== 'number') return '–'
  const amount = cost.amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
  return `${cost.at_least ? '≥' : '≈'} ${amount} ${cost.currency}`
}

/**
 * What the priced rows cost, a sum for each currency: an amount in one is never added to another.
 * A model with a price whose cost is not known (nothing it used was reported) makes its
 * currency's sum "≥".
 */
export function totalCost(rows: Usage['by_model'], prices: Price[]) {
  const sums = new Map<string, { amount: number | null; at_least: boolean }>()
  const add = (currency: string, amount: number | null, short: boolean) => {
    const sum = sums.get(currency) ?? { amount: null, at_least: false }
    sums.set(currency, { amount: amount === null ? sum.amount : (sum.amount ?? 0) + amount, at_least: sum.at_least || short })
  }
  for (const row of rows) {
    const price = prices.find(p => p.model_id === row.model_id)
    if (row.cost) add(row.cost.currency, row.cost.amount, Boolean(row.cost.at_least || row.cost.cache_unpriced))
    else if (price) add(price.currency, null, true)
  }
  // shortcut: a currency with no known amount at all is left out of the line, not said as "–"; say it if prices in several currencies become common.
  const known = [...sums].filter(([, sum]) => sum.amount !== null)
  return known.length === 0 ? '–' : known.map(([currency, sum]) => money({ ...sum, amount: sum.amount!, currency })).join(' + ')
}

/**
 * Why no provider's limit of spend can be kept (81c), as the server's `unkept` says it: a limit is in USD, as the
 * page writes it, and spend is at your prices - in another currency the two are never compared. Null: it can be.
 */
export function limitUnkept(prices: Price[]): string | null {
  const own = [...new Set(prices.map(price => price.currency.toUpperCase()))].sort()
  return own.some(currency => currency !== 'USD') ? `This limit can't be kept: your prices are in ${own.join(' and ')}` : null
}

/** The day a copy of the catalogue was read, as the pages say it: "21 Oct". */
export const day = (date: string) => new Date(date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
