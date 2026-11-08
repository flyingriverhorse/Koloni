import { type ReactNode, useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Budget, CataloguePrice, Limits, Price, Project, Provider, Usage } from '../api/types'
import { modelName } from '../shell/modelName'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { cached } from '../shell/tokens'
import { BudgetSection } from './Budget'
import { day, money, totalCost } from './cost'
import { Fold } from './Fold'
import { type Period, PERIODS, since } from './period'
import { PlanLimits } from './PlanLimits'
import { Prices } from './Prices'
import { HowItWorks } from '../shell/HowItWorks'

type Numbers = Pick<Usage['by_start'][number], 'runs' | 'agents' | 'input_tokens' | 'output_tokens' | 'cache_read_tokens' | 'cache_write_tokens' | 'unknown_agents'>
type Cost = Usage['by_model'][number]['cost']
/** One line of a table: what it is of (and its words, to sort by), its numbers and - in the table that has one - its cost. */
interface Row {
  key: string
  name: ReactNode
  text: string
  numbers: Numbers
  cost?: Cost
  /** Its cost leaves out cache tokens that have no price. */
  unpriced?: boolean
  /** KOLONİ's own requests, in no message: its "agents" are requests, said under its name, not in the Agents column. */
  requests?: boolean
}

interface Props {
  /** The open chat's project; "This project" is this one. None for a plain chat: all are shown. */
  project: Project | null
  projects: Project[]
  /** Reads the usage of one project, or of all (null), from a moment on (null: all of it). Throws ApiError. */
  onLoad: (projectId: string | null, since: string | null) => Promise<Usage>
  /** Opens a conversation. */
  onOpen: (conversationId: string) => void
  /** The providers, and how the plan of one is read: with both, the page has its "Plan limits". */
  providers?: Provider[]
  onLimits?: (providerId: string, afresh: boolean) => Promise<Limits>
  /** What the user says models cost, and how one is written or taken away: with both, the page has its "Prices". Each throws ApiError. */
  prices?: Price[]
  /** models.dev's price of the models in use, where the user wrote none. */
  cataloguePrices?: CataloguePrice[]
  onPrice?: (price: Price) => Promise<void>
  onRemovePrice?: (modelId: string) => Promise<void>
  /** This month's spend of the open project against its budget: shown with "This project". */
  budget?: Budget | null
  /** Where they are set: a provider's own limit on Models, the project's budget in its settings. */
  onModels?: (providerId: string) => void
  onSettings?: () => void
  /** The open project's day (tek-ev §3): shown with "This project" in the Today period. */
  today?: ReactNode
}

/** A number a model reported, or "–" (its row says why) - never a made-up zero. */
const count = (n: number | null) => (n === null ? '–' : n.toLocaleString('en-US'))

type Start = Usage['by_start'][number]
/** Who started it, as its row says: KOLONİ's own requests with no message are "KOLONİ itself" (K-56). */
const STARTERS: Record<Start['started_by'], string> = { user: 'You', trigger: 'A trigger, with nobody watching', koloni: 'KOLONİ itself' }
/** A starter in the fold's line: "3 messages by you", "2 requests by KOLONİ itself" (these are in no message). */
const started = (row: Start) =>
  row.started_by === 'koloni'
    ? `${count(row.agents)} ${row.agents === 1 ? 'request' : 'requests'} by KOLONİ itself`
    : `${count(row.runs)} ${row.runs === 1 ? 'message' : 'messages'} by ${row.started_by === 'trigger' ? 'a trigger' : 'you'}`
/**
 * A column's total over the rows: "–" where no row knows it, "≥" where a row does not know it
 * or an agent of the row reported nothing or only part - with how many rows that is, said
 * apart. Never a made-up zero.
 */
function total(rows: Numbers[], of: (row: Numbers) => number | null): { value: string; short: string | null } {
  const known = rows.map(of).filter(n => n !== null)
  if (known.length === 0) return { value: '–', short: null }
  const short = rows.filter(row => of(row) === null || row.unknown_agents > 0).length
  const sum = count(known.reduce((a, b) => a + b, 0))
  return short ? { value: `≥ ${sum}`, short: `${short} of ${rows.length} rows not fully known` } : { value: sum, short: null }
}

/** Opens the Prices fold and moves to it, which brings it into view. */
function openPrices() {
  const fold = document.getElementById('usage-prices') as HTMLDetailsElement | null
  if (!fold) return
  fold.open = true
  fold.querySelector('summary')?.focus()
}

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

function UsageTable({ label, first, rows, cost }: { label: string; first: string; rows: Row[]; cost?: boolean }) {
  // Null: as read. A number is first looked at from the biggest, a name from A.
  const [sort, setSort] = useState<{ by: Column; down: boolean } | null>(null)
  const shown = sort ? [...rows].sort((a, b) => compare(valueOf(a, sort.by), valueOf(b, sort.by), sort.down)) : rows
  const head = (by: Column, text: string) => (
    <th scope="col" aria-sort={sort?.by === by ? (sort.down ? 'descending' : 'ascending') : undefined}>
      <button type="button" className="sort-head" onClick={() => setSort({ by, down: sort?.by === by ? !sort.down : by !== 'name' })}>
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
          {shown.map(({ key, name, numbers: n, cost: paid, unpriced, requests }) => (
            <tr key={key}>
              <th scope="row">
                {name}
                {n.unknown_agents > 0 && (
                  <span className="choice-note">
                    {n.unknown_agents === 1 ? '1 agent' : `${n.unknown_agents} agents`} reported nothing or only part
                  </span>
                )}
                {requests && <span className="choice-note">{n.agents === 1 ? '1 request' : `${count(n.agents)} requests`} of its own, in no message</span>}
                {cached(n) && <span className="choice-note">{cached(n)}</span>}
                {unpriced && <span className="choice-note">Cache tokens without a price are left out of the cost.</span>}
                {paid?.price_from && (
                  <span className="choice-note">
                    Priced at {paid.price_from}’s price{paid.price_read_on ? ` (${day(paid.price_read_on)})` : ''}: you gave it none.
                  </span>
                )}
              </th>
              <td className="mono">{n.runs}</td>
              <td className="mono">{requests ? '—' : n.agents}</td>
              <td className="mono">{count(n.input_tokens)}</td>
              <td className="mono">{count(n.output_tokens)}</td>
              {cost && <td className="mono">{money(paid ?? null)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * The boxes on top: a number each, and a line or two under it. Tokens and cost add up the rows
 * by model; turns and agents those by who started them, where each turn is counted once.
 */
function Totals({ usage, prices, onPrices }: { usage: Usage; prices: Price[]; onPrices?: () => void }) {
  const rows = usage.by_model
  const sent = total(rows, row => row.input_tokens)
  const written = total(rows, row => row.output_tokens)
  const cache = [
    [total(rows, row => row.cache_read_tokens), 'read from the cache'],
    [total(rows, row => row.cache_write_tokens), 'written to the cache'],
  ] as const
  const cost = totalCost(rows, prices)
  const turns = usage.by_start.reduce((n, row) => n + row.runs, 0)
  // (KOLONİ's own requests are no agents: said in their row of "Who started it".)
  const agents = usage.by_start.reduce((n, row) => n + (row.started_by === 'koloni' ? 0 : row.agents), 0)
  const boxes: [string, string, ...ReactNode[]][] = [
    ['Messages', count(turns), agents === 1 ? '1 agent' : `${count(agents)} agents`],
    ['Tokens sent', sent.value, cache.filter(([sum]) => sum.value !== '–').map(([sum, what]) => `${sum.value} ${what}`).join(' · '), sent.short],
    ['Tokens written', written.value, written.short],
    [
      'Cost',
      cost,
      // The page's one word on prices: what has none counts nothing, here and in the budget.
      <>
        {cost !== '–' ? 'of what is priced' : prices.length === 0 ? 'no price set' : 'nothing priced yet'}
        {onPrices && (
          <>
            {' · '}
            <button type="button" className="usage-open" onClick={onPrices}>
              set prices
            </button>
          </>
        )}
      </>,
    ],
  ]
  return (
    <dl className="usage-stats">
      {boxes.map(([label, value, ...notes]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className="usage-stat mono">{value}</dd>
          {notes.filter(Boolean).map((note, at) => (
            <dd key={at}>{note}</dd>
          ))}
        </div>
      ))}
    </dl>
  )
}

/**
 * What was spent and where: the tokens the agents' models reported, added up. Only what a
 * model reported is counted; what none reported is "unknown", and money is shown only from
 * prices the user wrote.
 */
export function UsagePage({ project, projects, onLoad, onOpen, providers = [], onLimits, prices = [], cataloguePrices = [], onPrice, onRemovePrice, budget, onModels, onSettings, today }: Props) {
  const [all, setAll] = useState(false)
  // A plain chat has no folder of its own: every one's is shown.
  const everywhere = all || !project
  const [period, setPeriod] = useState<Period>('today')
  // Counted up when a price changes: the usage is then read again, with its cost.
  const [priced, setPriced] = useState(0)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const scope = everywhere ? null : project.id

  useEffect(() => {
    // Only the latest reading counts: an earlier one that answers late is not shown.
    let latest = true
    onLoad(scope, since(period)).then(
      read => {
        if (!latest) return
        setUsage(read)
        setError(null)
      },
      err => {
        if (!latest) return
        // What was read before is of another project or period: it is not left under this one.
        setUsage(null)
        setError(errorText(err))
      },
    )
    return () => {
      latest = false
    }
  }, [onLoad, scope, period, priced])

  const nameOf = (projectId: string | null) => (projectId ? (projects.find(p => p.id === projectId)?.name ?? 'another project') : 'No folder')
  const costed = usage?.by_model.some(row => row.cost) ?? false
  return (
    <div className="memory-page">
      <div className="conv-head">
        <h2>Usage</h2>
        <div className="usage-filters">
          <select className="input" aria-label="Projects" value={everywhere ? 'all' : 'this'} onChange={e => setAll(e.target.value === 'all')}>
            {project && <option value="this">This project</option>}
            <option value="all">All projects</option>
          </select>
          <select className="input" aria-label="Period" value={period} onChange={e => setPeriod(e.target.value as Period)}>
            {PERIODS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <HowItWorks page="usage">
        <p className="muted memory-hint">
          Tokens as the agents’ models reported them, for work started in the period. What an agent sent is the sum of
          its steps, and every step sends the whole conversation again. Nothing is estimated: what was not reported shows
          as “–”, and an agent from before totals were kept has no total of what it sent. “≥” means part of a total was
          not reported. Where a conversation has “Orchestrator model: automatic”, the question asked for each message counts as
          one more agent, under the model that was asked. What KOLONİ asks a model outside any message (the day in words,
          a recipe’s draft, an expert’s guide, a Check that runs a CLI) shows as “KOLONİ itself”, in the totals and in its
          project’s budget.
        </p>
      </HowItWorks>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {!usage ? (
        !error && <p className="muted">Reading the usage…</p>
      ) : usage.by_model.length === 0 ? (
        // (Today's day may count a message that failed before any agent reported: not "none ran".)
        <p className="muted">{period === 'today' ? 'No agent reported usage today.' : 'No agent ran in this period.'}</p>
      ) : (
        <Totals usage={usage} prices={prices} onPrices={onPrice && onRemovePrice ? openPrices : undefined} />
      )}
      {period === 'today' && !everywhere && today}
      {/* Plans and budget, read here and set where they belong; each only where it has something to say, side by side where there is room. */}
      <div className="usage-two">
        {onLimits && <PlanLimits providers={providers} onLimits={onLimits} onModels={onModels} />}
        {!everywhere && budget && <BudgetSection budget={budget} onSettings={onSettings} />}
      </div>
      {usage && usage.by_model.length > 0 && (
        <>
          <section className="memory-section" aria-label="By provider and model">
            <div className="memory-head">
              <h3>By provider and model</h3>
            </div>
            <UsageTable
              label="Usage by provider and model"
              first="Provider and model"
              cost
              rows={usage.by_model.map(row => ({
                key: `${row.provider_name}/${row.model_id}`,
                text: `${row.provider_name ?? 'unknown provider'} · ${modelName(row.model_id)}`,
                name: (
                  <>
                    {row.provider_name ?? 'unknown provider'} · <span className="mono">{modelName(row.model_id)}</span>
                  </>
                ),
                numbers: row,
                cost: row.cost,
                unpriced: Boolean(row.cost?.cache_unpriced),
              }))}
            />
            <div className="muted memory-hint">
              {costed
                ? 'Cost: from the prices you entered. Cache reads and writes are counted at the cache prices you gave, and not at all without them. Where you entered no price, models.dev’s is used, and the model’s row says so.'
                : 'Cost shows for a model with a price: yours, or else models.dev’s, where it has one.'}{' '}
              <Hint doc={GUIDE.prices}>
                {costed
                  ? 'Where a provider said nothing about a cache, all that was sent is counted at the input price. “≥” means an agent in the row reported nothing or only part, or cache tokens have no price: the amount covers only what was reported and priced.'
                  : 'Prices come from what you write under Prices, or else from models.dev, in USD.'}{' '}
                A CLI on a plan has no price for a token, so it never has a cost here.
              </Hint>
            </div>
          </section>
          <Fold title="By conversation" count={usage.by_conversation.length === 1 ? '1 conversation' : `${usage.by_conversation.length} conversations`}>
            <UsageTable
              label="Usage by conversation"
              first="Conversation"
              rows={usage.by_conversation.map(row => ({
                key: row.conversation_id,
                text: row.title,
                name: (
                  <>
                    <button type="button" className="usage-open" onClick={() => onOpen(row.conversation_id)}>
                      {row.title}
                    </button>
                    {(!project || row.project_id !== project.id) && <span className="muted"> · {nameOf(row.project_id)}</span>}
                  </>
                ),
                numbers: row,
              }))}
            />
          </Fold>
          <Fold title="Who started it" count={usage.by_start.map(started).join(' · ')}>
            <UsageTable
              label="Usage by who sent the message"
              first="Started by"
              cost
              rows={usage.by_start.map(row => {
                const name = STARTERS[row.started_by]
                return { key: row.started_by, name, text: name, numbers: row, cost: row.cost, requests: row.started_by === 'koloni' }
              })}
            />
          </Fold>
        </>
      )}
      {onPrice && onRemovePrice && (
        <Prices
          providers={providers}
          rows={usage?.by_model ?? []}
          prices={prices}
          catalogue={cataloguePrices}
          onPrice={async price => {
            await onPrice(price)
            setPriced(n => n + 1)
          }}
          onRemovePrice={async modelId => {
            await onRemovePrice(modelId)
            setPriced(n => n + 1)
          }}
        />
      )}
    </div>
  )
}
