import { useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { AllowedCommand } from '../api/types'

interface Props {
  /** The conversation the trigger's turns go into: the rules are that conversation's. */
  conversationId: string
  /** The ticked rules, by their ids. */
  ticked: string[]
  onTicked: (ids: string[]) => void
  /** Read a conversation's allow list. */
  onRules: (conversationId: string) => Promise<AllowedCommand[]>
  /** Put a command on a conversation's allow list; answers with the rule made. */
  onAddRule: (conversationId: string, prefix: string) => Promise<AllowedCommand>
  /** A command to put in the add field to begin with: one the chat asked to allow that is on no rule. */
  suggest?: string
  /** Called with the rules each time they are read. */
  onRead?: (rules: AllowedCommand[]) => void
  error?: string
}

/**
 * The commands a trigger's turns may run with nobody watching: ticked from the allow list
 * of its conversation (the rules "Always run" made there), and kept by the rules' ids. A
 * command is added to that list here too - which is a change to the conversation, not to
 * the trigger, and says so.
 *
 * Everything about how this permission is chosen and sent is in this one file.
 */
export function CommandLeave({ conversationId, ticked, onTicked, onRules, onAddRule, suggest = '', onRead, error }: Props) {
  // The list as it was read, with whose it is: another conversation's is not shown for a moment as this one's.
  const [read, setRead] = useState<{ of: string; rules: AllowedCommand[] } | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [adding, setAdding] = useState(suggest)
  const [busy, setBusy] = useState(false)
  const [refused, setRefused] = useState<string | null>(null)

  useEffect(() => {
    if (!conversationId) return
    let current = true
    onRules(conversationId).then(
      rules => {
        if (!current) return
        setRead({ of: conversationId, rules })
        setFailed(null)
        onRead?.(rules)
      },
      err => {
        if (current) setFailed(errorText(err))
      },
    )
    return () => {
      current = false
    }
    // (`onRead` is the form's own callback, made anew on each of its renders.)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, onRules])

  const rules = read?.of === conversationId ? read.rules : null

  async function add() {
    const prefix = adding.trim()
    if (!prefix || busy) return
    setBusy(true)
    setRefused(null)
    try {
      const made = await onAddRule(conversationId, prefix)
      // On the list now; whether this trigger may run it is still the user's to tick.
      setRead(prev => (prev?.of === conversationId && !prev.rules.some(r => r.id === made.id) ? { of: conversationId, rules: [...prev.rules, made] } : prev))
      setAdding('')
    } catch (err) {
      setRefused(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <fieldset className="trigger-leave" aria-label="May run these commands">
      <legend>May run these commands</legend>
      <p className="choice-note">With nobody watching, a ticked command runs exactly as written - no extra arguments.</p>
      {failed && (
        <div role="alert" className="alert">
          {failed}
        </div>
      )}
      {rules === null && !failed && <p className="muted trigger-note">Reading this conversation’s list…</p>}
      {rules?.length === 0 && <p className="muted trigger-note">This conversation has no allowed commands yet.</p>}
      {rules?.map(rule => (
        <label key={rule.id} className="choice">
          <input
            type="checkbox"
            checked={ticked.includes(rule.id)}
            onChange={event => onTicked(event.target.checked ? [...ticked, rule.id] : ticked.filter(id => id !== rule.id))}
          />
          <span className="mono">{rule.prefix}</span>
        </label>
      ))}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="field">
        <label htmlFor="trigger-add-command">Add a command to this conversation's list</label>
        <div className="trigger-add">
          <input
            id="trigger-add-command"
            className="input mono"
            value={adding}
            maxLength={200}
            placeholder="e.g. python -m pytest -q"
            aria-describedby="trigger-add-note"
            onChange={event => setAdding(event.target.value)}
            onKeyDown={event => {
              if (event.key !== 'Enter') return
              event.preventDefault() // adding to the list is not saving the trigger
              void add()
            }}
          />
          <button type="button" className="btn" disabled={busy || !adding.trim() || !conversationId} onClick={() => void add()}>
            Add to the list
          </button>
        </div>
        <span id="trigger-add-note" className="choice-note">
          This also lets this conversation's own messages run it without asking.
        </span>
        {refused && <span className="alert">{refused}</span>}
      </div>
    </fieldset>
  )
}
