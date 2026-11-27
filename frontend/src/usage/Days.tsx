import type { Usage } from '../api/types'
import { DAYS } from './period'
import { measureOf } from './usageText'

type Day = Usage['by_day'][number]

/** A day as the server names it: YYYY-MM-DD by this machine's clock. */
const keyOf = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const named = (d: Date) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

/**
 * The last 30 days in one strip, a bar a day: the money spent where any of it is priced, else the tokens the models
 * reported. A day that ran with nothing known has a stub, not a zero; each bar's day and amount are in words, and the
 * first day, the most and today under the strip.
 */
export function Days({ read }: { read: { rows: Day[]; at: Date } | null }) {
  if (!read) return null
  // (As of the reading's moment: the days it was asked for, not a clock read as the page draws.)
  const { rows, at: now } = read
  const measure = measureOf(rows)
  const byDay = new Map(rows.map(row => [row.day, row]))
  const dates = Array.from(
    { length: DAYS },
    (_, at) => new Date(now.getFullYear(), now.getMonth(), now.getDate() - (DAYS - 1) + at),
  )
  const most = Math.max(0, ...rows.map(row => measure.value(row) ?? 0))
  const said = (date: Date) => {
    const row = byDay.get(keyOf(date))
    return `${named(date)}: ${row ? measure.said(row) : 'nothing ran'}`
  }
  const valueOn = (date: Date) => {
    const row = byDay.get(keyOf(date))
    return row ? measure.value(row) : 0
  }
  const top = most > 0 ? dates.find(date => valueOn(date) === most) : undefined
  return (
    <section className="memory-section usage-days" aria-label="Day by day">
      <h3>
        Day by day{' '}
        <span className="muted memory-hint">
          {measure.inMoney
            ? 'the money spent, the last 30 days'
            : measure.mixed
              ? 'the tokens reported, the last 30 days: costs are in more than one currency'
              : 'the tokens the models reported, the last 30 days: nothing in them has a cost'}
        </span>
      </h3>
      {rows.length === 0 ? (
        <p className="muted">Nothing ran in the last 30 days.</p>
      ) : (
        <div className="usage-strip-box">
          <ol className="usage-strip" aria-label="Each day">
            {dates.map((date, at) => {
              const value = valueOn(date)
              return (
                <li key={at} title={said(date)} className={at === DAYS - 1 ? 'usage-strip-today' : undefined}>
                  <span className="visually-hidden">{said(date)}</span>
                  {value === null ? (
                    <i className="usage-strip-unknown" />
                  ) : (
                    value > 0 && <i style={{ height: `${Math.max((value / most) * 100, 4)}%` }} />
                  )}
                </li>
              )
            })}
          </ol>
          <p className="usage-axis">
            <span>{named(dates[0])}</span>
            {top && <span>Most: {said(top)}</span>}
            <span>Today, {said(dates[DAYS - 1])}</span>
          </p>
        </div>
      )}
    </section>
  )
}
