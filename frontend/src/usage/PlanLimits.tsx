import { useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Limits, Provider } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { Bar } from './Bar'
import {
  asOf,
  limitsLine,
  NEAR_AT,
  NO_PLAN,
  nearOf,
  nearWords,
  readAgo,
  stepsDown,
  stepWords,
  windowName,
} from './limitsText'

interface Props {
  providers: Provider[]
  /** What is known of what is left of one provider's plan; `afresh` has it read now (never Claude Code's here: that runs a turn). Throws ApiError. */
  onLimits: (providerId: string, afresh: boolean) => Promise<Limits>
  /** Opens a provider on the Models page, where its own limit is set. */
  onModels?: (providerId: string) => void
  /** Told each reading that comes: provider id -> what it said, or why it could not be read (the page's summary). */
  onRead?: (told: Record<string, Limits | string>) => void
}

type Window = Limits['windows'][number]

/** Where a subscription's picks go a tier lower, in words: from its share, or past it now - of the windows a step down
 *  reads (`used`). */
function StepNote({ step, used }: { step: number | null; used: number[] }) {
  if (step == null || used.length === 0) return null
  const most = Math.max(...used)
  return (
    <span className="choice-note">
      <span className={most >= step ? 'tag tag-warn' : undefined}>{stepWords(most, step)}</span>
    </span>
  )
}

/**
 * A plan's row: a bar for each window whose used share is known now (a stale or unsaid one has none), what is known of
 * it in a line, and its notes. The line on a bar of a window its step down reads is where its picks go a tier lower
 * (`step_down_at`); a bar is orange past it or near its limit, and its row says which in words.
 */
function PlanCell({ provider, limits }: { provider: Provider; limits: Limits | string | undefined }) {
  const read = typeof limits === 'object' ? limits : null
  const known = read?.windows.filter(w => w.used_percent !== null && !w.stale) ?? []
  const step = provider.step_down_at
  const mark = (w: Window) => (step != null && stepsDown(w) ? step : null)
  return (
    <td>
      {known.map((w, at) => (
        <Bar
          key={at}
          label={`${provider.name}: ${windowName(w)} used`}
          value={w.used_percent!}
          mark={mark(w)}
          hot={w.used_percent! >= NEAR_AT || (mark(w) !== null && w.used_percent! >= step!)}
        />
      ))}
      {limits === undefined ? 'reading…' : read ? limitsLine(read) : `could not be read: ${limits}`}
      {provider.kind === 'claude_cli' && (
        <span className="choice-note">
          Check now does not read it: that takes a Claude Code turn. Read now on its Models card does.
        </span>
      )}
      <StepNote step={step} used={known.filter(w => mark(w) !== null).map(w => w.used_percent!)} />
      {read &&
        nearOf(read).map((w, at) => (
          <span key={`near ${at}`} className="choice-note">
            <span className="tag tag-warn">{nearWords(provider.name, w)}</span>
          </span>
        ))}
      {read?.read_at && (
        // A reading that failed leaves the last good one, with its time, and says so beside it.
        <span className="choice-note">
          {`${read.failed ? `could not be read just now: ${read.failed}; last ` : ''}${readAgo(read.read_at)} (${asOf(read.read_at)})${read.source ? `, from ${read.source}` : ''}`}
        </span>
      )}
    </td>
  )
}

/**
 * What is left of each CLI's plan, as the CLI itself says: Codex, agy and Copilot when they are asked (no model is
 * called), Claude Code in its own runs and the user's own sessions. And an API's rate limits, as its last answer said
 * them, and DeepSeek's balance (slice 73). Opening the page shows the last readings; only "Check now" has Codex, agy,
 * Copilot and DeepSeek asked afresh. Without a CLI or an API that says anything there is nothing to say: no section.
 */
export function PlanLimits({ providers, onLimits, onModels, onRead }: Props) {
  const all = providers.filter(p => p.kind.endsWith('_cli') || p.kind === 'anthropic' || p.kind === 'openai_compat')
  const ids = all.map(p => p.id).join(' ')
  // Asked afresh on "Check now": all but Claude Code (the server asks only those it can ask without a model turn).
  const afresh = all
    .filter(p => p.kind !== 'claude_cli')
    .map(p => p.id)
    .join(' ')
  // Which reading is wanted, and the last one that came: provider id -> what it said, or why it could not be read.
  const [round, setRound] = useState(0)
  const [read, setRead] = useState<{ round: number; told: Record<string, Limits | string> }>({ round: -1, told: {} })

  useEffect(() => {
    let latest = true
    const asked = ids.split(' ').filter(Boolean)
    // The first round is the page opening: what is known. Each later one is "Check now", which asks only Codex:
    // reading Claude Code's runs a turn, which only its own Read now on the Models page does.
    void Promise.all(
      asked.map(
        async id => [id, await onLimits(id, round > 0 && afresh.split(' ').includes(id)).catch(errorText)] as const,
      ),
    ).then(told => {
      if (!latest) return
      const found = Object.fromEntries(told)
      setRead({ round, told: found })
      onRead?.(found)
    })
    return () => {
      latest = false
    }
  }, [ids, afresh, onLimits, round, onRead])

  // An OpenAI-compatible server is shown once it has said something: a model server on this machine says nothing.
  const clis = all.filter(
    p =>
      p.kind !== 'openai_compat' ||
      (typeof read.told[p.id] === 'object' && (read.told[p.id] as Limits).unknown !== NO_PLAN),
  )
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
          {clis.map(provider => (
            <tr key={provider.id}>
              <th scope="row">
                {provider.name}
                {onModels && (
                  <span className="choice-note">
                    <button
                      type="button"
                      className="usage-open"
                      aria-label={`Limit ${provider.name} in Models`}
                      onClick={() => onModels(provider.id)}
                    >
                      Limit in Models →
                    </button>
                  </span>
                )}
              </th>
              <PlanCell provider={provider} limits={read.told[provider.id]} />
            </tr>
          ))}
        </tbody>
      </table>
      <div className="muted memory-hint">
        These are the limits of the account the CLI on this machine is signed in to.{' '}
        <Hint doc={GUIDE.planMeters}>
          This page shows the last reading; agy and Copilot are read again in the background once it is over 10 minutes
          old. Copilot’s chat requests and its premium ones are shown apart, with what its account offers read in the
          same look. Codex and Copilot also say it in their own native runs, with no model turn of its own. “Check now”
          asks Codex, agy and Copilot again, without calling a model. Claude Code is not asked here: its limits are read
          from its own runs and your own Claude Code sessions, or in one short request by Read now on its Models card.
          Each last reading is kept with its time, also after KOLONİ restarts. No other CLI says what is left of its
          plan. An API says its rate limits in each answer, read as its agents run (kept until KOLONİ restarts); “Check
          now” asks DeepSeek its balance.
        </Hint>
      </div>
    </section>
  )
}
