import { type ReactNode, useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Budget, CataloguePrice, Limits, Price, Project, Provider, Usage } from '../api/types'
import { paidOf } from '../models/cards'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { HowItWorks } from '../shell/HowItWorks'
import { modelName } from '../shell/modelName'
import { spent } from '../shell/tokens'
import { BudgetSection } from './Budget'
import { money, totalCost } from './cost'
import { Days } from './Days'
import { type Period, PERIODS, since, stripFrom } from './period'
import { PlanLimits } from './PlanLimits'
import { Prices } from './Prices'
import { TopChats, WhoStarted } from './Spenders'
import { count, fullestPlan, started, summarySentence } from './usageText'
import { type Numbers, UsageTable } from './UsageTable'

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
  /** The open project's decisions in the period, in a line (karar defteri): shown with "This project". */
  decisions?: (period: Period) => ReactNode
}

const THESE: ['this' | 'all', string][] = [
  ['this', 'This project'],
  ['all', 'All projects'],
]

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
  return short
    ? { value: `≥ ${sum}`, short: `${short} of ${rows.length} rows not fully known` }
    : { value: sum, short: null }
}

/** Opens the Prices fold and moves to it, which brings it into view. */
function openPrices() {
  const fold = document.getElementById('usage-prices') as HTMLDetailsElement | null
  if (!fold) return
  fold.open = true
  fold.querySelector('summary')?.focus()
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
  // (KOLONİ's own requests are no agents: said apart, as in their row of "Who started it".)
  const agents = usage.by_start.reduce((n, row) => n + (row.started_by === 'koloni' ? 0 : row.agents), 0)
  const itself = usage.by_start.find(row => row.started_by === 'koloni')
  const boxes: [string, string, ...ReactNode[]][] = [
    ['Messages', count(turns), agents === 1 ? '1 agent' : `${count(agents)} agents`, itself && started(itself)],
    [
      'Tokens sent',
      sent.value,
      cache
        .filter(([sum]) => sum.value !== '–')
        .map(([sum, what]) => `${sum.value} ${what}`)
        .join(' · '),
      sent.short,
    ],
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

/** What a model's row says in its Cost cell where it has no cost: "plan" for a subscription's, "–" else; Copilot's
 *  own unit beside either. */
function costWords(row: Usage['by_model'][number], providers: Provider[]): string | undefined {
  const provider = providers.find(p => p.id === row.provider_id)
  const plan = provider && (paidOf(provider) === 'subscription' || provider.plan)
  // shortcut: a sum some of whose agents said no unit is shown as is, not "≥"; say how many said none if Copilot's
  // units are compared on the page.
  const units = [
    spent({ nano_aiu: row.nano_aiu ?? null, premium_requests: null }),
    spent({ nano_aiu: null, premium_requests: row.premium_requests ?? null }),
  ]
    .filter(Boolean)
    .join(' · ')
  if (!units && (row.cost || !plan)) return undefined
  return [row.cost ? money(row.cost) : plan ? 'plan' : '–', units].filter(Boolean).join(' · ')
}

/** A choice of one, as pressed buttons: the period, the projects. */
function Choice<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: [T, string][]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="usage-seg">
      {options.map(([one, name]) => (
        <button key={one} type="button" aria-pressed={one === value} onClick={() => onChange(one)}>
          {name}
        </button>
      ))}
    </div>
  )
}

/** The page's head: its name, and the period and the projects it counts ("This project" only where one is open). */
function Head({
  period,
  onPeriod,
  everywhere,
  onEverywhere,
  here,
}: {
  period: Period
  onPeriod: (period: Period) => void
  everywhere: boolean
  onEverywhere: (all: boolean) => void
  here: boolean
}) {
  return (
    <div className="conv-head usage-head">
      <div>
        <h2>Usage</h2>
        <p className="muted memory-hint">What was spent, who spent it, and how full the plans are.</p>
      </div>
      <div className="usage-filters">
        <Choice<Period> label="Period" options={PERIODS} value={period} onChange={onPeriod} />
        <Choice
          label="Projects"
          options={here ? THESE : THESE.slice(1)}
          value={everywhere ? 'all' : 'this'}
          onChange={one => onEverywhere(one === 'all')}
        />
      </div>
    </div>
  )
}

/** The strip's 30 days of a project or of all, whatever the period, and the moment they were asked as of; read again
 *  when `again` changes (a price). Null until read, or where they cannot be: the period's reading says why. */
function useDays(onLoad: Props['onLoad'], scope: string | null, again: number) {
  const [days, setDays] = useState<{ rows: Usage['by_day']; at: Date } | null>(null)
  useEffect(() => {
    let latest = true
    const at = new Date()
    onLoad(scope, stripFrom(at)).then(
      read => latest && setDays({ rows: read.by_day, at }),
      () => latest && setDays(null),
    )
    return () => {
      latest = false
    }
  }, [onLoad, scope, again])
  return days
}

/**
 * What was spent and where: the tokens the agents' models reported, added up. Only what a
 * model reported is counted; what none reported is "unknown", and money is shown only from
 * prices the user wrote.
 */
export function UsagePage({
  project,
  projects,
  onLoad,
  onOpen,
  providers = [],
  onLimits,
  prices = [],
  cataloguePrices = [],
  onPrice,
  onRemovePrice,
  budget,
  onModels,
  onSettings,
  today,
  decisions,
}: Props) {
  const [all, setAll] = useState(false)
  // A plain chat has no folder of its own: every one's is shown.
  const everywhere = all || !project
  const [period, setPeriod] = useState<Period>('today')
  // Counted up when a price changes: the usage is then read again, with its cost.
  const [priced, setPriced] = useState(0)
  // A reading, and the period it is of: the sentence is worded by that until the next one comes.
  const [reading, setReading] = useState<{ usage: Usage; period: Period } | null>(null)
  const usage = reading?.usage
  const [error, setError] = useState<string | null>(null)
  // What the plans last said (Plan limits reads them): the summary's plan used most.
  const [plans, setPlans] = useState<Record<string, Limits | string>>({})
  const scope = everywhere ? null : project.id

  // (Read first: the period's own reading is the last asked.)
  const days = useDays(onLoad, scope, priced)

  useEffect(() => {
    // Only the latest reading counts: an earlier one that answers late is not shown.
    let latest = true
    onLoad(scope, since(period)).then(
      read => {
        if (!latest) return
        setReading({ usage: read, period })
        setError(null)
      },
      err => {
        if (!latest) return
        // What was read before is of another project or period: it is not left under this one.
        setReading(null)
        setError(errorText(err))
      },
    )
    return () => {
      latest = false
    }
  }, [onLoad, scope, period, priced])

  const nameOf = (projectId: string | null) =>
    projectId ? (projects.find(p => p.id === projectId)?.name ?? 'another project') : 'No folder'
  const ours = everywhere ? null : budget
  // The project's decisions in the period: beside the chats where the tables are, else under the summary.
  const decided = !everywhere && decisions?.(period)
  const ran = Boolean(usage?.by_model.length)

  /** The summary: a sentence, the boxes under it, then the month's budget and the plans side by side. */
  const lede = () => (
    <article className="usage-lede" aria-label="Summary">
      {!usage ? (
        !error && <p className="muted">Reading the usage…</p>
      ) : (
        <>
          <p className="usage-big">
            {summarySentence({
              period: reading!.period,
              usage,
              cost: totalCost(usage.by_model, prices),
              budget: ours,
              plan: fullestPlan(providers, plans),
            })}
          </p>
          {/* (Today's day may count a message that failed before any agent reported: not "none ran".) */}
          {usage.by_model.length > 0 && (
            <Totals usage={usage} prices={prices} onPrices={onPrice && onRemovePrice ? openPrices : undefined} />
          )}
        </>
      )}
      <div className="usage-two">
        {ours && <BudgetSection budget={ours} onSettings={onSettings} />}
        {onLimits && <PlanLimits providers={providers} onLimits={onLimits} onModels={onModels} onRead={setPlans} />}
      </div>
    </article>
  )

  /** By provider and model on the left; on the right the chats that spent most, who started it, the decisions. */
  const tables = () => {
    if (!usage || !ran) return null
    const costed = usage.by_model.some(row => row.cost)
    // shortcut: a model's row counts KOLONİ's own requests among its agents and `by_model` does not say how many; give
    // its rows their own count if two models' requests are to be told apart.
    const itself = usage.by_start.find(row => row.started_by === 'koloni')
    return (
      <div className="usage-grid">
        <section className="memory-section" aria-label="By provider and model">
          <h3>By provider and model</h3>
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
              costText: costWords(row, providers),
              unpriced: Boolean(row.cost?.cache_unpriced),
            }))}
          />
          <div className="muted memory-hint">
            {itself && `Agents here include ${started(itself)}, in no message. `}
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
        <div className="usage-side">
          <TopChats rows={usage.by_conversation} here={project} nameOf={nameOf} onOpen={onOpen} />
          <WhoStarted rows={usage.by_start} />
          {decided}
        </div>
      </div>
    )
  }

  return (
    <div className="memory-page">
      <Head period={period} onPeriod={setPeriod} everywhere={everywhere} onEverywhere={setAll} here={!!project} />
      <HowItWorks page="usage">
        <p className="muted memory-hint">
          Tokens as the agents’ models reported them, for work started in the period. What an agent sent is the sum of
          its steps, and every step sends the whole conversation again. Nothing is estimated: what was not reported
          shows as “–”, and an agent from before totals were kept has no total of what it sent. “≥” means part of a
          total was not reported. Where a conversation has “Orchestrator model: automatic”, the question asked for each
          message counts as one more agent, under the model that was asked. What KOLONİ asks a model outside any message
          (the day in words, a recipe’s draft, an expert’s guide, a Check that runs a CLI) shows as “KOLONİ itself”, in
          the totals and in its project’s budget.
        </p>
      </HowItWorks>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {lede()}
      {period === 'today' && !everywhere && today}
      {!ran && decided}
      <Days read={days} />
      {tables()}
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
      <p className="muted memory-hint usage-honest">
        Nothing is estimated: tokens are only what the models reported, and what was not reported is “–”. Work on a
        subscription says “plan”: it counts no money, and how full the plan is shows above. Copilot also counts in its
        own unit, AI credits.
      </p>
    </div>
  )
}
