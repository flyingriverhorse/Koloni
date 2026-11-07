import { useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Limits, Provider } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { asOf, limitsLine, NO_PLAN, nearOf, nearWords, readAgo, windowName } from './limitsText'

interface Props {
  providers: Provider[]
  /** What is known of what is left of one provider's plan; `afresh` has it read now (never Claude Code's here: that runs a turn). Throws ApiError. */
  onLimits: (providerId: string, afresh: boolean) => Promise<Limits>
  /** Opens a provider on the Models page, where its own limit is set. */
  onModels?: (providerId: string) => void
}

/**
 * What is left of each CLI's plan, as the CLI itself says: Codex, agy and Copilot when they are asked (no model is
 * called), Claude Code in its own runs and the user's own sessions. And an API's rate limits, as its last answer said
 * them, and DeepSeek's balance (slice 73). Opening the page shows the last readings; only "Check now" has Codex, agy,
 * Copilot and DeepSeek asked afresh. Without a CLI or an API that says anything there is nothing to say: no section.
 */
export function PlanLimits({ providers, onLimits, onModels }: Props) {
  const all = providers.filter(p => p.kind.endsWith('_cli') || p.kind === 'anthropic' || p.kind === 'openai_compat')
  const ids = all.map(p => p.id).join(' ')
  // Asked afresh on "Check now": all but Claude Code (the server asks only those it can ask without a model turn).
  const afresh = all.filter(p => p.kind !== 'claude_cli').map(p => p.id).join(' ')
  // Which reading is wanted, and the last one that came: provider id -> what it said, or why it could not be read.
  const [round, setRound] = useState(0)
  const [read, setRead] = useState<{ round: number; told: Record<string, Limits | string> }>({ round: -1, told: {} })

  useEffect(() => {
    let latest = true
    const asked = ids.split(' ').filter(Boolean)
    // The first round is the page opening: what is known. Each later one is "Check now", which asks only Codex:
    // reading Claude Code's runs a turn, which only its own Read now on the Models page does.
    void Promise.all(asked.map(async id => [id, await onLimits(id, round > 0 && afresh.split(' ').includes(id)).catch(errorText)] as const)).then(told => {
      if (latest) setRead({ round, told: Object.fromEntries(told) })
    })
    return () => {
      latest = false
    }
  }, [ids, afresh, onLimits, round])

  // An OpenAI-compatible server is shown once it has said something: a model server on this machine says nothing.
  const clis = all.filter(p => p.kind !== 'openai_compat' || (typeof read.told[p.id] === 'object' && (read.told[p.id] as Limits).unknown !== NO_PLAN))
  if (clis.length === 0) return null
  const checking = read.round !== round
  return (
    <section className="memory-section" aria-label="Plan limits">
      <div className="memory-head">
        <h3>Plan limits</h3>
        <button type="button" className="btn btn-small" disabled={checking} onClick={() => setRound(round + 1)}>
          {checking ? 'Checking…' : 'Check now'}
        </button>
      </div>
      <table className="usage-table usage-limits" aria-label="Plan limits by provider">
        <tbody>
          {clis.map(provider => {
            const limits = read.told[provider.id]
            return (
              <tr key={provider.id}>
                <th scope="row">
                  {provider.name}
                  {onModels && (
                    <span className="choice-note">
                      <button type="button" className="usage-open" aria-label={`Limit ${provider.name} in Models`} onClick={() => onModels(provider.id)}>
                        Limit in Models →
                      </button>
                    </span>
                  )}
                </th>
                <td>
                  {/* A bar for each window whose used share is known now: a stale or unsaid one has none. */}
                  {typeof limits === 'object' &&
                    limits.windows
                      .filter(w => w.used_percent !== null && !w.stale)
                      .map((w, at) => (
                        <meter key={at} className="budget-meter" aria-label={`${provider.name}: ${windowName(w)} used`} min={0} max={100} low={80} high={100} optimum={0} value={w.used_percent!} />
                      ))}
                  {limits === undefined ? 'reading…' : typeof limits === 'string' ? `could not be read: ${limits}` : limitsLine(limits)}
                  {provider.kind === 'claude_cli' && <span className="choice-note">Check now does not read it: that takes a Claude Code turn. Read now on its Models card does.</span>}
                  {typeof limits === 'object' &&
                    nearOf(limits).map((w, at) => (
                      <span key={`near ${at}`} className="choice-note">
                        <span className="tag tag-warn">{nearWords(provider.name, w)}</span>
                      </span>
                    ))}
                  {typeof limits === 'object' && limits.read_at && (
                    // A reading that failed leaves the last good one, with its time, and says so beside it.
                    <span className="choice-note">
                      {`${limits.failed ? `could not be read just now: ${limits.failed}; last ` : ''}${readAgo(limits.read_at)} (${asOf(limits.read_at)})${limits.source ? `, from ${limits.source}` : ''}`}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="muted memory-hint">
        These are the limits of the account the CLI on this machine is signed in to.{' '}
        <Hint doc={GUIDE.planMeters}>
          This page shows the last reading; agy and Copilot are read again in the background once it is over 10 minutes
          old. Codex and Copilot also say it in their own native runs, with no model turn of its own. “Check now” asks Codex,
          agy and Copilot again, without calling a model. Claude Code is not asked here: its limits are read from its own runs
          and your own Claude Code sessions, or in one short request by Read now on its Models card. Each last reading is kept
          with its time, also after KOLONİ restarts. No other CLI says what is left of its plan. An API says its rate
          limits in each answer, read as its agents run (kept until KOLONİ restarts); “Check now” asks DeepSeek its
          balance.
        </Hint>
      </div>
    </section>
  )
}
