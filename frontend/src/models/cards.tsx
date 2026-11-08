import { TIERS, type Availability, type Limits, type Provider, type Usage } from '../api/types'
import { dayAndTime } from '../agents/failure'
import { Hint } from '../shell/Hint'
import { totalCost } from '../usage/cost'
import { balance, readAgo, windowWords } from '../usage/limitsText'
import { isCli, stateOf } from './ModelsPage'

/** What switching a provider off does, on its switch (its card's and its window's). */
export const OFF_MEANS =
  'Off: nothing new starts on it - no chat, no agent, no learning; its key and settings stay. A turn already running goes on until it ends; Stop ends it now.'

/** How a provider is paid for, under its name on its card. */
export type Paid = 'subscription' | 'API key' | 'this machine'

// A server on this machine: its own address, whichever way it is written.
const LOCAL = /^https?:\/\/(localhost|127\.|\[::1\]|0\.0\.0\.0)/i

export function paidOf(provider: Provider): Paid {
  // shortcut: Copilot on a model server of your own counts as a subscription here; give it its own kind if such
  // setups become common.
  if (isCli(provider.kind)) return 'subscription'
  return provider.base_url && LOCAL.test(provider.base_url) ? 'this machine' : 'API key'
}

/** What a card's gauge shows: the share filled (null: none known), the value and the words after it. */
export interface Reading {
  share: number | null
  value: string
  label: string
  /** No bar at all: an API key with no daily limit says what it spent, with nothing to fill (79). */
  plain?: boolean
  /** A plan's other windows, its credits and when it was read, behind the card's ⓘ; an API key's daily limit that
   *  cannot be kept, in sight (81c). */
  more?: string
  /** Why the plan could not be read just now, the last reading kept: in sight. */
  failed?: string
}

const LOOKING: Reading = { share: null, value: '…', label: 'looking…' }

/** An amount in the user's price currency: "$1.85", "$5", "1.85 EUR". */
function cash(amount: number, currency: string): string {
  const cents = Number.isInteger(amount) ? 0 : 2
  const written = amount.toLocaleString('en-US', { minimumFractionDigits: cents, maximumFractionDigits: 2 })
  return currency === 'USD' ? `$${written}` : `${written} ${currency}`
}

/** What an API key spent today by the record, against its daily limit where it has one and can keep it (81c):
 *  "$1.85 / $5 today". */
function spentToday(provider: Provider, today: Usage['by_model'], unkept: string | null): Reading {
  const rows = today.filter(row => row.provider_id === provider.id)
  const costs = rows.flatMap(row => (row.cost ? [row.cost] : []))
  const currencies = new Set(costs.map(cost => cost.currency))
  // Amounts in two currencies are never added; nothing priced of what ran is not known.
  const unkeptHere = provider.day_limit !== null && unkept ? { more: unkept } : {}
  if (currencies.size > 1 || (rows.length && !costs.length)) return { share: null, value: totalCost(rows, []), label: 'today', plain: true, ...unkeptHere }
  const currency = [...currencies][0] ?? 'USD'
  const spent = costs.reduce((sum, cost) => sum + cost.amount, 0)
  const least = costs.length < rows.length || costs.some(cost => cost.at_least || cost.cache_unpriced) ? '≥ ' : ''
  const value = `${least}${cash(spent, currency)}`
  if (provider.day_limit === null) return { share: null, value, label: 'today', plain: true }
  // Never "$6 / $5" while turns run unasked: a limit that cannot be kept says so instead (as `over_limit` holds back nothing).
  if (unkept) return { share: null, value, label: 'today', plain: true, ...unkeptHere }
  return { share: spent / provider.day_limit, value: `${value} / ${cash(provider.day_limit, currency)}`, label: 'today' }
}

/** A reading's `source`, as the card says it after how long ago it was read. */
const SOURCE_WORDS: Record<string, string> = {
  'its last run': 'in its last run here',
  'a short run to read it': 'in a short run to read it',
  'your Claude Code session': 'from your Claude Code session',
}

/**
 * What is known now, and nothing more: what is left of a CLI's plan as it last said it, what an API key
 * spent today by the record, whether a server on this machine answers. Undefined: still read; null:
 * reading it failed.
 */
export function readingOf(
  provider: Provider,
  {
    limits,
    today,
    avail,
    unkept = null,
  }: { limits?: Limits | null; today?: Usage['by_model'] | null; avail?: Availability | null; unkept?: string | null },
): Reading {
  const paid = paidOf(provider)
  if (paid === 'this machine') {
    if (avail === undefined) return LOOKING
    const [look, said] = stateOf(provider, avail)
    return look === 'ok' ? { share: 1, value: 'on', label: 'running' } : { share: 0, value: 'off', label: said }
  }
  if (paid === 'API key') {
    // shortcut: no balance here - that is slice 73's, said only where the service says it.
    if (provider.plan) {
      // Its quota last seen used up (its 429): when - the time today, else the date too (a monthly quota: a weekday
      // alone could be any week). What is left no API says.
      const seen = limits?.used_up && limits.read_at
      const today = seen && new Date(seen).toDateString() === new Date().toDateString()
      const at = seen && new Date(seen).toLocaleString(undefined, { ...(today ? {} : { month: 'short', day: 'numeric' }), hour: '2-digit', minute: '2-digit' })
      return { share: null, value: 'plan', label: at ? `quota used up, seen ${at}` : 'no money counted', plain: true }
    }
    if (today === undefined) return { ...LOOKING, plain: true }
    if (today === null) return { share: null, value: '–', label: 'spent today: not known', plain: true }
    return spentToday(provider, today, unkept)
  }
  if (limits === undefined) return LOOKING
  const windows = limits?.windows ?? []
  const known = windows.filter(w => w.used_percent !== null && !w.stale)
  // The narrowest window: the one with the least left, whatever its length - what a step down reads too (81c).
  const narrowest = known.reduce<(typeof known)[number] | null>((least, w) => (least && least.used_percent! >= w.used_percent! ? least : w), null)
  if (!narrowest) return { share: null, value: '–', label: limits?.failed ? `Could not be read: ${limits.failed}` : unknownOf(limits) }
  const left = (w: (typeof windows)[number]) => 100 - Math.round(w.used_percent!)
  const others = windows
    .filter(w => w !== narrowest)
    .map(w => {
      const name = windowWords(w)[1]
      if (w.used_percent === null || w.stale) return `${name} –`
      // (One the last reading did not name says when it was read itself: B-74.)
      return `${name} ${left(w)}% left${w.resets_at ? ` · resets ${dayAndTime(w.resets_at)}` : ''}${w.read_at ? ` · ${readAgo(w.read_at)}` : ''}`
    })
  const credits = limits?.credits?.unlimited ? 'credits unlimited' : limits?.credits?.balance ? `${balance(limits.credits.balance)} credits` : null
  // Where Claude Code said it: a reading from a run here leaves out what was used elsewhere since.
  const from = SOURCE_WORDS[limits?.source ?? '']
  const read = limits?.read_at ? `${readAgo(limits.read_at)}${from ? `, ${from}` : ''}` : null
  return {
    share: left(narrowest) / 100,
    value: `${left(narrowest)}%`,
    label: `left ${windowWords(narrowest)[0]}`,
    more: [...others, credits, read].filter(Boolean).join(' · ') || undefined,
    // A reading that failed just now leaves the last one, and says why under it.
    ...(limits?.failed && { failed: `not read now: ${limits.failed}` }),
  }
}

/** Why a CLI's plan use is not known, in short: Claude Code says it in its own runs, Codex when it is read. */
function unknownOf(limits: Limits | null): string {
  const why = limits?.unknown
  if (!why) return 'plan use not known'
  if (why.startsWith('not run yet')) return 'Known after its first run here'
  const short = why.split(':')[0]
  return short[0].toUpperCase() + short.slice(1)
}

/** The value and its words in one line (and how old it is), and a bar filled as far as the share where one is known. */
export function Gauge({ share, value, label, ago }: Reading & { ago?: string }) {
  return (
    <span className="gauge">
      <span>
        <span className="gauge-value">{value}</span> <span className="gauge-label">
          {label}
          {ago && ` · ${ago}`}
        </span>
      </span>
      {share !== null && (
        <span className="plan-use-bar" aria-hidden="true">
          <span style={{ width: `${Math.min(share, 1) * 100}%` }} />
        </span>
      )}
    </span>
  )
}

/** How many of a provider's models have each tier, strongest first; a number with its tier's colour and name. */
export function TierCounts({ provider }: { provider: Provider }) {
  return (
    <span className="tier-counts">
      {[...TIERS].reverse().map(tier => {
        const count = provider.models.filter(m => m.tier === tier).length
        return (
          count > 0 && (
            <span key={tier} className={`tier-count tier-${tier}`} title={tier}>
              {count}
              <span className="visually-hidden"> {tier}</span>
            </span>
          )
        )
      })}
      <span className="muted">of {provider.models.length} models</span>
    </span>
  )
}

/** One provider: its name, how it is paid for, its state, its gauge and its tiers; a click opens it. Beside it, its
 *  switch and one action: a plan read afresh (`onRead`: Codex's app-server is started, no model is run; Claude Code
 *  runs one short turn), else a Check (`onCheck`: no model is run). */
export function ProviderCard({
  provider,
  isDefault,
  state: [look, said],
  reading,
  open,
  onOpen,
  onSwitch,
  onRead,
  onCheck,
  busy = false,
  readAt,
}: {
  provider: Provider
  isDefault: boolean
  /** Its state, as `stateOf` says it. */
  state: [look: 'ok' | 'bad' | 'off', said: string]
  reading: Reading
  open: boolean
  onOpen: () => void
  onSwitch: (on: boolean) => void
  onRead?: () => void
  onCheck?: () => void
  busy?: boolean
  /** When its plan was last read: said beside the bar, so an old reading does not pass for now's. */
  readAt?: string | null
}) {
  const paid = paidOf(provider)
  // Switched off: greyed and said; its window still opens.
  const off = provider.enabled === false
  // K-cli-surface: a CLI version not measured - behind ⓘ, unless it runs the old way for it.
  // shortcut: told apart by the backend's words (`cli_surface.checked`); send a flag if they change.
  const oldWay = provider.version_note?.endsWith('the old way')
  const quiet = oldWay ? null : provider.version_note
  // Behind ⓘ: a plan's other windows, credits and when it was read. An API key's `more` is a limit it cannot keep: in sight.
  const aside = paid === 'subscription' ? reading.more : undefined
  const action = onRead ?? onCheck
  // What reading Claude Code's costs is said beside it: one turn of its plan.
  const cost = onRead && provider.kind === 'claude_cli' ? `provider-card-cost-${provider.id}` : undefined
  // Beside the card's button, not in it: a control in a button is neither, and its click would open the window.
  return (
    <div className="provider-card-box">
      <button id={`provider-card-${provider.id}`} type="button" className={`provider-card${off ? ' provider-off' : ''}`} aria-current={open || undefined} onClick={onOpen}>
        <span className="provider-card-head">
          <span className={`state-dot state-${look}`} aria-hidden="true" />
          <span className="provider-card-name">{provider.name}</span>
        </span>
        <span className="provider-card-kind">
          {paid}
          {isDefault && ' · default'}
        </span>
        <span className={look === 'bad' && !off ? 'provider-card-state' : 'provider-card-status'}>{off ? 'switched off' : said}</span>
        {/* A server's state is its status already. */}
        {paid !== 'this machine' && <Gauge {...reading} ago={readAt && reading.share !== null ? readAgo(readAt) : undefined} />}
        {reading.failed && <span className="provider-card-state">{reading.failed}</span>}
        {paid !== 'subscription' && reading.more && <span className="provider-card-state">{reading.more}</span>}
        {provider.key_warning && <span className="provider-card-state">{provider.key_warning}</span>}
        {/* Antigravity's terms, section 6: said on or off, so switching it on is an informed choice. */}
        {provider.kind === 'agy_cli' && (
          <span className="provider-card-state">Google’s terms forbid using Antigravity through another app; your Google account may be suspended.</span>
        )}
        {oldWay && <span className="provider-card-state">{provider.version_note}</span>}
        <TierCounts provider={provider} />
      </button>
      <input
        type="checkbox"
        role="switch"
        className="switch provider-card-switch"
        aria-label={`${provider.name} on`}
        title={OFF_MEANS}
        checked={!off}
        onChange={e => onSwitch(e.target.checked)}
      />
      {(action || aside || quiet) && (
        <span className="provider-card-foot">
          {action && (
            <button
              type="button"
              className="btn btn-small"
              aria-label={onRead ? `Read ${provider.name}’s plan now` : `Check ${provider.name}`}
              aria-describedby={cost}
              title={onRead ? undefined : 'Looks again whether it can be used now; no model is run'}
              disabled={busy}
              onClick={action}
            >
              {onRead ? (busy ? 'Reading…' : 'Read now') : busy ? 'Checking…' : 'Check'}
            </button>
          )}
          {cost && (
            <span id={cost} className="muted">
              one short request
            </span>
          )}
          {(aside || quiet) && (
            <Hint>
              {aside && <span className="hint-para">{aside}</span>}
              {quiet && <span className="hint-para provider-card-version">{quiet}</span>}
            </Hint>
          )}
        </span>
      )}
    </div>
  )
}
