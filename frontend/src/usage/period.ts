export type Period = 'today' | '7' | '30' | 'all'

export const PERIODS: [Period, string][] = [
  ['today', 'Today'],
  ['7', '7 days'],
  ['30', '30 days'],
  ['all', 'All'],
]
const DAY = 24 * 60 * 60 * 1000

/** The moment a period starts, as the server is asked for it; null for all of it. */
export function since(period: Period, now = new Date()): string | null {
  if (period === 'all') return null
  if (period === 'today') return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
  return new Date(now.getTime() - Number(period) * DAY).toISOString()
}
