import { useState } from 'react'
import { Warning } from '@phosphor-icons/react'
import { errorText } from '../api/client'
import type { InjectionWarning as Found } from '../api/types'
import { useApp } from '../state/store'

/** A rule's name as words: "ignore_previous" is "ignore previous". */
const ruleWords = (rule: string) => rule.replaceAll('_', ' ')

/**
 * Text from outside that read like orders to an agent (93-A4): which rule, from where - never the text. Only a warning:
 * nothing was kept from the agent, which was told to take it as data. "False alarm" is counted by rule.
 */
export function InjectionWarning({ warning, agent }: { warning: Found; agent?: string }) {
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const said = warning.false_alarm
  // (B-141: read as one name - a screen reader said "(rule: )", the tag apart.)
  const told = `${agent ? `${agent} · ` : ''}Text from ${warning.where} looks like it tries to give the agent orders (rule: ${ruleWords(warning.rule)}).`
  return (
    // (A card that only tells: nothing waits on it.)
    <div role="note" aria-label={told} className="cmd-approval card-tell injection-warning">
      <div className="kicker cmd-approval-kicker">
        {/* (A webhook's is the one anybody on the internet could have sent: app.injection.SEVERITY.) */}
        <Warning size={13} style={{ color: warning.source === 'webhook' ? 'var(--del)' : 'var(--warn)', flex: 'none' }} />
        Text tried to give orders
      </div>
      <p className="card-said">
        {agent && `${agent} · `}Text from {warning.where} looks like it tries to give the agent orders (rule:{' '}
        <span className="tag tag-warn">{ruleWords(warning.rule)}</span>).
      </p>
      <div className="change-actions">
        <button
          type="button"
          className="btn btn-small"
          disabled={busy || said}
          title="Counted for this rule; nothing else changes"
          onClick={() => {
            setBusy(true)
            setFailed(null)
            void useApp
              .getState()
              .falseAlarm(warning.id)
              .catch((error: unknown) => setFailed(errorText(error)))
              .finally(() => setBusy(false))
          }}
        >
          {said ? 'Marked false alarm' : 'False alarm'}
        </button>
        {warning.false_alarms > 0 && (
          <span className="muted">
            {warning.false_alarms} false {warning.false_alarms === 1 ? 'alarm' : 'alarms'} for this rule
          </span>
        )}
      </div>
      {failed && (
        <span role="alert" className="alert">
          Not counted: {failed}
        </span>
      )}
    </div>
  )
}
