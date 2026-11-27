export type Period = 'today' | '7' | 'month' | '30' | 'all'

export const PERIODS: [Period, string][] = [
  ['today', 'Today'],
  ['7', '7 days'],
  ['month', 'This month'],
  ['30', '30 days'],
  ['all', 'All'],
]

/** A period in a sentence: "12 decisions were made for you this month". */
export const WHEN: Record<Period, string> = {
  today: 'today',
  '7': 'in the last 7 days',
  month: 'this month',
  '30': 'in the last 30 days',
  all: 'so far',
}

const DAY = 24 * 60 * 60 * 1000

/** The moment a period starts, as the server is asked for it; null for all of it. */
export function since(period: Period, now = new Date()): string | null {
  if (period === 'all') return null
  if (period === 'today') return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
  // (This calendar month here, as a project's budget counts it.)
  if (period === 'month') return new Date(now.getFullYear(), now.getMonth(), 1).toISOString()
  return new Date(now.getTime() - Number(period) * DAY).toISOString()
}

/** The days of Usage's strip, today the last. */
export const DAYS = 30

/** The strip's first moment: midnight here, 29 days before today. */
export const stripFrom = (now = new Date()) =>
  new Date(now.getFullYear(), now.getMonth(), now.getDate() - (DAYS - 1)).toISOString()
