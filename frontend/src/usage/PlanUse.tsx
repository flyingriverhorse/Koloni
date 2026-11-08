import { useEffect, useState } from 'react'
import type { Limits, Provider } from '../api/types'
import { paidOf } from '../models/cards'
import { type Near, nearOf, nearWords, readAgo, windowName } from './limitsText'

type Window = Limits['windows'][number]

interface Props {
  providers: Provider[]
  /** What a CLI last said of its plan; never read afresh from here (Claude Code's Read now runs a turn). */
  onLimits: (providerId: string) => Promise<Limits>
  /** How often it is asked again. */
  every: number
  onOpen: () => void
  /** The windows near their limit in what was read (the toasts say each once): told after every reading. */
  onNear?: (near: Near[]) => void
}

/** The window the bar shows: the one most used of those known now - a week filling up is not hidden behind a quiet 5 hours
 *  (B-48, the user's decision of 25 Oct); on a tie the first the plan names. */
function shownWindow(limits: Limits): Window | null {
  const known = limits.windows.filter(w => w.used_percent !== null && !w.stale)
  return known.reduce<Window | null>((most, w) => (most && most.used_percent! >= w.used_percent! ? most : w), null)
}

/**
 * In the top bar: how much of each subscription's window is used, as its CLI last said it. A plan with no
 * reading shows nothing; with none at all, nothing is there. One button, to the Usage page.
 */
export function PlanUse({ providers, onLimits, every, onOpen, onNear }: Props) {
  const clis = providers.filter(p => paidOf(p) === 'subscription')
  const ids = clis.map(p => p.id).join(' ')
  const [read, setRead] = useState<Record<string, Limits | null>>({})
  useEffect(() => {
    let live = true
    const ask = () => {
      for (const id of ids.split(' ').filter(Boolean))
        onLimits(id).then(
          told => live && setRead(was => ({ ...was, [id]: told })),
          () => live && setRead(was => ({ ...was, [id]: null })),
        )
    }
    ask()
    // Asked as often as the Board: the last reading is looked up. Only agy and Copilot, which need no turn for it,
    // are read afresh by the server meanwhile, at most once in 10 minutes.
    const timer = setInterval(() => document.hidden || ask(), every)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [ids, onLimits, every])

  useEffect(() => {
    onNear?.(
      providers.flatMap(provider => {
        const limits = read[provider.id]
        return limits && !limits.unknown
          ? nearOf(limits).map(w => ({ key: `${provider.id} ${w.name ?? w.minutes}`, resets_at: w.resets_at, text: nearWords(provider.name, w) }))
          : []
      }),
    )
  }, [read, providers, onNear])

  const plans = clis.flatMap(provider => {
    const limits = read[provider.id]
    const w = limits && !limits.unknown ? shownWindow(limits) : null
    return w ? [{ provider, limits: limits!, w, used: Math.round(w.used_percent!) }] : []
  })
  if (plans.length === 0) return null
  const label = `Plan use: ${plans.map(({ provider, w, used }) => `${provider.name} ${used}% of ${windowName(w)}`).join(', ')}; open Usage`
  // How old each reading is, and why the last read failed, as its Models card says it.
  const title = plans
    .map(({ provider, limits, w, used }) =>
      [`${provider.name}: ${used}% of ${windowName(w)} used`, limits.read_at && readAgo(limits.read_at), limits.failed && `not read now: ${limits.failed}`]
        .filter(Boolean)
        .join(', '),
    )
    .join('\n')
  return (
    <button type="button" className="btn plan-use" aria-label={label} title={title} onClick={onOpen}>
      {plans.map(({ provider, used }) => (
        <span key={provider.id} className={used >= 80 ? 'plan-use-meter plan-use-hot' : 'plan-use-meter'}>
          {/* Its own name (K-claude-hesap: two Claude Code accounts side by side), cut short where long. */}
          <span className="plan-use-name" title={provider.name}>
            {provider.name}
          </span>
          <span className="plan-use-bar" aria-hidden="true">
            <span style={{ width: `${Math.min(used, 100)}%` }} />
          </span>
          {used}%
        </span>
      ))}
    </button>
  )
}
