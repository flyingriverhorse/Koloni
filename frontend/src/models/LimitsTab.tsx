import { type FormEvent, useState } from 'react'
import { errorText } from '../api/client'
import type { Provider } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { paidOf } from './cards'

/** What the Limits tab changes (slice 81c): only what was changed is sent. */
export type LimitsChange = Partial<Pick<Provider, 'plan' | 'step_down_at' | 'day_limit' | 'month_limit'>>

// Empty: none. Undefined: as written it is no limit, and nothing is sent.
const share = (typed: string) => (typed.trim() === '' ? null : /^\d{2,3}$/.test(typed.trim()) && +typed >= 50 && +typed <= 100 ? +typed : undefined)
// Plain decimals only: "1e3", "0x10" or "Infinity" are no amount anyone writes.
const money = (typed: string) => (typed.trim() === '' ? null : /^\d+(\.\d+)?$/.test(typed.trim()) && +typed > 0 ? +typed : undefined)
const shown = (value: number | null) => (value === null ? '' : String(value))
const PLAN_NOTE = 'Its runs then show no cost on Usage and count nothing in a project’s budget.'
const PLAN_HINT = 'For a key paid in credits or a plan. Its runs are counted apart, as runs with no price are.'

/**
 * A provider's limits: a key that is a plan counts no money; an API key's most a day and a month, past which a new
 * turn on it asks first; a subscription's share of its plan from which picks go a tier lower. Each can be empty.
 */
export function LimitsTab({
  provider,
  unkept = null,
  onSave,
}: {
  provider: Provider
  /** Why no limit of spend can be kept now (`limitUnkept`); null: it can. */
  unkept?: string | null
  onSave: (values: LimitsChange) => Promise<void>
}) {
  const paid = paidOf(provider)
  const [plan, setPlan] = useState(provider.plan)
  const [step, setStep] = useState(shown(provider.step_down_at))
  const [day, setDay] = useState(shown(provider.day_limit))
  const [month, setMonth] = useState(shown(provider.month_limit))
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const values = { step_down_at: share(step), day_limit: money(day), month_limit: money(month) }
  const changed: LimitsChange = {
    ...(plan !== provider.plan ? { plan } : {}),
    ...Object.fromEntries(Object.entries(values).filter(([name, value]) => value !== undefined && value !== provider[name as keyof typeof values])),
  }
  const wrong = Object.values(values).some(value => value === undefined)
  // A new edit is not what was saved.
  const editing =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      setSaid(null)
      set(value)
    }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setSaid(null)
    try {
      await onSave(changed)
      setSaid('Saved.')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  if (paid === 'this machine')
    return <p className="muted provider-note">A model server on this machine spends no money and has no plan: there is nothing to limit.</p>
  // "Step down a tier at [ ] % of the plan", "At most $[ ] a day": the words around the box are its label.
  const field = (id: string, [before, after]: [string, string], value: string, set: (typed: string) => void, note: string, hint: string) => {
    const bad = value.trim() !== '' && (id === 'limit-step' ? share(value) : money(value)) === undefined
    return (
      <div className="field">
        <span className="limit-line">
          <label htmlFor={id}>{before}</label>
          <input
            id={id}
            className="input mono"
            inputMode="decimal"
            value={value}
            placeholder="none"
            aria-label={`${before} … ${after}`}
            aria-invalid={bad || undefined}
            aria-describedby={`${id}-note`}
            onChange={e => editing(set)(e.target.value)}
          />
          <span>{after}</span>
        </span>
        <span id={`${id}-note`} className="muted provider-note">
          {bad ? 'As written it is no limit, and it is not saved. ' : ''}
          {note} <Hint doc={GUIDE.limits}>{hint}</Hint>
        </span>
      </div>
    )
  }
  return (
    <form className="provider-limits" onSubmit={e => void submit(e)}>
      {paid === 'subscription' ? (
        field(
          'limit-step',
          ['Step down a tier at', '% of the plan'],
          step,
          setStep,
          'A whole number from 50 to 100, or empty for never. A role that always runs on one tier, or on one model, is never stepped down: your own rule wins.',
          'When the window with the least left has used this much, a model picked by tier on this subscription is one of the next tier down, and the agent’s card says why.',
        )
      ) : (
        <>
          <label className="choice" htmlFor="limit-plan">
            {/* Named by all of its note, as the page shows it, and not by the hint's button. */}
            <input id="limit-plan" type="checkbox" aria-label={`This key is a plan: count no money ${PLAN_NOTE} ${PLAN_HINT}`} checked={plan} onChange={e => editing(setPlan)(e.target.checked)} />
            <span>
              This key is a plan: count no money
              <span className="choice-note">
                {PLAN_NOTE} <Hint doc={GUIDE.limits}>{PLAN_HINT}</Hint>
              </span>
            </span>
          </label>
          {!plan && (
            <>
              {unkept && (
                <p role="note" className="composer-warning provider-note">
                  {unkept}. A limit here is in dollars, and what is spent is counted at your prices.
                </p>
              )}
              {field('limit-day', ['At most $', 'a day'], day, setDay, 'Spent at your prices, in every project; empty for no limit. Past it, a new message whose Orchestrator runs here asks you first, a model picked by tier is the next one of its tier, and no sub-agent or room member is opened here.', 'It asks you as a project’s budget does.')}
              {field('limit-month', ['At most $', 'a month'], month, setMonth, 'This calendar month, the same way.', 'As a day’s limit, counted from the first of the month.')}
            </>
          )}
        </>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {said && !error && <div role="status">{said}</div>}
      <div className="role-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || wrong || Object.keys(changed).length === 0}>
          Save limits
        </button>
      </div>
    </form>
  )
}
