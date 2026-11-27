import { type ReactNode, useState } from 'react'
import type { Usage } from '../api/types'
import { cached } from '../shell/tokens'
import { day, money } from './cost'
import { count } from './usageText'

export type Numbers = Pick<
  Usage['by_start'][number],
  'runs' | 'agents' | 'input_tokens' | 'output_tokens' | 'cache_read_tokens' | 'cache_write_tokens' | 'unknown_agents'
>
type Cost = Usage['by_model'][number]['cost']
/** One line of a table: what it is of (and its words, to sort by), its numbers and - in the table that has one - its cost. */
export interface Row {
  key: string
  name: ReactNode
  text: string
  numbers: Numbers
  cost?: Cost
  /** What its Cost cell says, where not its cost: "plan" for a subscription's, Copilot's AI credits beside it. */
  costText?: string
  /** Its cost leaves out cache tokens that have no price. */
  unpriced?: boolean
  /** KOLONİ's own requests, in no message: its "agents" are requests, said under its name, not in the Agents column. */
  requests?: boolean
}

/** What a row's Cost cell says: its own words where it has them, else its cost. */
const costCell = (row: Pick<Row, 'cost' | 'costText'>) => row.costText ?? money(row.cost ?? null)

type Column = 'name' | 'runs' | 'agents' | 'input_tokens' | 'output_tokens' | 'cost'
// A cost is sorted by its currency, then its amount: amounts in two currencies are not compared.
type Key = string | number | null | [string, number]
const valueOf = (row: Row, by: Column): Key =>
  by === 'name' ? row.text : by === 'cost' ? (row.cost ? [row.cost.currency, row.cost.amount] : null) : row.numbers[by]
/** Two rows in a column's order; what is not known is last, whichever way. */
function compare(a: Key, b: Key, down: boolean) {
  if (a === null || b === null) return Number(a === null) - Number(b === null)
  const order = Array.isArray(a)
    ? a[0].localeCompare((b as [string, number])[0]) || a[1] - (b as [string, number])[1]
    : typeof a === 'string'
      ? a.localeCompare(b as string)
      : (a as number) - (b as number)
  return down ? -order : order
}

export function UsageTable({
  label,
  first,
  rows,
  cost,
}: {
  label: string
  first: string
  rows: Row[]
  cost?: boolean
}) {
  // Null: as read. A number is first looked at from the biggest, a name from A.
  const [sort, setSort] = useState<{ by: Column; down: boolean } | null>(null)
  const shown = sort ? [...rows].sort((a, b) => compare(valueOf(a, sort.by), valueOf(b, sort.by), sort.down)) : rows
  const head = (by: Column, text: string) => (
    <th scope="col" aria-sort={sort?.by === by ? (sort.down ? 'descending' : 'ascending') : undefined}>
      <button
        type="button"
        className="sort-head"
        onClick={() => setSort({ by, down: sort?.by === by ? !sort.down : by !== 'name' })}
      >
        {text}
      </button>
    </th>
  )
  return (
    <div className="tools-table">
      <table className="usage-table" aria-label={label}>
        <thead>
          <tr>
            {head('name', first)}
            {head('runs', 'Messages')}
            {head('agents', 'Agents')}
            {head('input_tokens', 'Tokens sent')}
            {head('output_tokens', 'Tokens written')}
            {cost && head('cost', 'Cost')}
          </tr>
        </thead>
        <tbody>
          {shown.map(({ key, name, numbers: n, cost: paid, unpriced, requests, ...row }) => (
            <tr key={key}>
              <th scope="row">
                {name}
                {n.unknown_agents > 0 && (
                  <span className="choice-note">
                    {n.unknown_agents === 1 ? '1 agent' : `${n.unknown_agents} agents`} reported nothing or only part
                  </span>
                )}
                {requests && (
                  <span className="choice-note">
                    {n.agents === 1 ? '1 request' : `${count(n.agents)} requests`} of its own, in no message
                  </span>
                )}
                {cached(n) && <span className="choice-note">{cached(n)}</span>}
                {unpriced && (
                  <span className="choice-note">Cache tokens without a price are left out of the cost.</span>
                )}
                {paid?.price_from && (
                  <span className="choice-note">
                    Priced at {paid.price_from}’s price{paid.price_read_on ? ` (${day(paid.price_read_on)})` : ''}: you
                    gave it none.
                  </span>
                )}
              </th>
              <td className="mono">{n.runs}</td>
              <td className="mono">{requests ? '—' : n.agents}</td>
              <td className="mono">{count(n.input_tokens)}</td>
              <td className="mono">{count(n.output_tokens)}</td>
              {cost && <td className="mono">{costCell({ ...row, cost: paid })}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
