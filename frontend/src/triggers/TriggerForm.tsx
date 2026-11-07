import { type FormEvent, type ReactNode, useState } from 'react'
import { errorText } from '../api/client'
import type { AllowedCommand, Conversation } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { CommandLeave } from './CommandLeave'
import { WebLeave } from './WebLeave'
import { type Allow, type Field, type FormValues, LIMITS, OWN_TOPIC, WEEK, allowIn, costNote, fieldOf, validate, withConversation } from './triggerText'

const ENDS: [FormValues['ends'], string][] = [
  ['none', 'No end'],
  ['runs', 'After so many runs'],
  ['until', 'After a day'],
]

/** A day by this machine's clock, `days` from today, as a date field takes it: an end is from today to a year ahead. */
const day = (days = 0) => {
  const at = new Date()
  at.setDate(at.getDate() + days)
  return `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}-${String(at.getDate()).padStart(2, '0')}`
}
const today = () => day()

interface Props {
  /** What the form starts from. */
  initial: FormValues
  /** Editing a trigger that is there: its kind cannot change. */
  editing: boolean
  /** The project's conversations: a trigger's turns go into one of them. */
  conversations: Conversation[]
  /** Something the chat asked to allow, filled in here and not saved. */
  allow?: Allow | null
  /** Throws ApiError with the server's reason. */
  onSubmit: (values: FormValues) => Promise<void>
  onCancel: () => void
  onRules: (conversationId: string) => Promise<AllowedCommand[]>
  onAddRule: (conversationId: string, prefix: string) => Promise<AllowedCommand>
  /** The hosts a conversation makes GET requests to without asking: the ones a trigger can be given. */
  onHosts?: (conversationId: string) => Promise<string[]>
}

const NO_HOSTS = async (): Promise<string[]> => []

interface RowProps {
  id: string
  label: string
  error?: string
  note?: string
  /** Something more to know about it, behind ⓘ beside its label - never what it runs or spends. */
  more?: string
  children: (described: string | undefined) => ReactNode
}

/** A field with its label, what is wrong with it, and what it takes. */
function Row({ id, label, error, note, more, children }: RowProps) {
  const described = [error ? `${id}-error` : note ? `${id}-note` : '', more ? `${id}-more` : ''].filter(Boolean).join(' ') || undefined
  return (
    <div className="field">
      <span>
        <label htmlFor={id}>{label}</label>
        {more && (
          <>
            {' '}
            <Hint doc={GUIDE.triggerMaking} id={`${id}-more`}>{more}</Hint>
          </>
        )}
      </span>
      {children(described)}
      {error ? (
        <span id={`${id}-error`} className="alert">
          {error}
        </span>
      ) : (
        note && (
          <span id={`${id}-note`} className="choice-note">
            {note}
          </span>
        )
      )}
    </div>
  )
}

const KINDS: [FormValues['kind'], string][] = [
  ['schedule', 'By the clock'],
  ['files', 'When files change'],
  ['webhook', 'On a request from outside'],
]

/**
 * A trigger, to make or to change. What its turns may do without asking starts at nothing,
 * and each permission says what it means: nobody is there to be asked when it runs.
 */
export function TriggerForm({ initial, editing, conversations, allow = null, onSubmit, onCancel, onRules, onAddRule, onHosts = NO_HOSTS }: Props) {
  // What the chat asked to allow: at once when it needs no list, and a command once the list is read.
  const [values, setValues] = useState<FormValues>(() => (allow && !('command' in allow) ? allowIn(initial, allow, []) : initial))
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({})
  const [refused, setRefused] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // A command from the chat: ticked (its rule was found), or still to be added to the list.
  const [fromChat, setFromChat] = useState<'ticked' | 'to add' | null>(null)
  const command = allow && 'command' in allow ? allow.command : null
  const set = (change: Partial<FormValues>) => setValues(prev => ({ ...prev, ...change }))

  function rulesRead(rules: AllowedCommand[]) {
    if (!command || fromChat !== null || values.conversationId !== initial.conversationId) return
    const found = rules.some(rule => rule.prefix === command)
    setFromChat(found ? 'ticked' : 'to add')
    if (found) setValues(prev => allowIn(prev, { command }, rules))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    const wrong = validate(values)
    setErrors(wrong)
    setRefused(null)
    if (Object.keys(wrong).length > 0) return
    setBusy(true)
    try {
      await onSubmit(values)
    } catch (err) {
      const detail = errorText(err)
      const field = fieldOf(detail)
      if (field) setErrors({ [field]: detail })
      else setRefused(detail)
    } finally {
      setBusy(false)
    }
  }

  const note =
    allow === null
      ? null
      : 'write' in allow
        ? '“May change files” was switched on from the chat.'
        : 'agents' in allow
          ? '“May open sub-agents” was raised by one from the chat.'
          : fromChat === 'ticked'
            ? `“${allow.command}” was ticked from the chat.`
            : fromChat === 'to add'
              ? `“${allow.command}” is not on this conversation’s list yet: add it below, then tick it.`
              : null

  return (
    <form className="trigger-form" aria-label={editing ? 'Edit trigger' : 'New trigger'} noValidate onSubmit={event => void submit(event)}>
      {note && (
        <div role="status" className="composer-warning">
          Not saved yet: {note} Look it over and save.
        </div>
      )}
      <Row id="trigger-name" label="Name" error={errors.name}>
        {described => (
          <input id="trigger-name" className="input" autoFocus value={values.name} maxLength={LIMITS.name} aria-describedby={described} aria-invalid={errors.name ? true : undefined} onChange={e => set({ name: e.target.value })} />
        )}
      </Row>
      <Row id="trigger-kind" label="Starts" note={editing ? 'How a trigger starts cannot be changed: make another one.' : undefined}>
        {described => (
          <select id="trigger-kind" className="input" value={values.kind} disabled={editing} aria-describedby={described} onChange={e => set({ kind: e.target.value as FormValues['kind'] })}>
            {KINDS.map(([kind, label]) => (
              <option key={kind} value={kind}>
                {label}
              </option>
            ))}
          </select>
        )}
      </Row>
      {values.kind === 'schedule' && (
        <fieldset className="trigger-leave">
          <legend>When</legend>
          <label className="choice">
            <input type="radio" name="trigger-schedule" checked={values.schedule === 'every'} onChange={() => set({ schedule: 'every' })} />
            <span>At an interval</span>
          </label>
          <label className="choice">
            <input type="radio" name="trigger-schedule" checked={values.schedule === 'at'} onChange={() => set({ schedule: 'at' })} />
            <span>At a time of day</span>
          </label>
          {values.schedule === 'every' ? (
            <Row id="trigger-every" label="Every so many minutes" error={errors.when} note={`At least ${LIMITS.every[0]}. The first run starts at once.`}>
              {described => (
                <input id="trigger-every" className="input mono trigger-number" type="number" min={LIMITS.every[0]} max={LIMITS.every[1]} value={values.every} aria-describedby={described} aria-invalid={errors.when ? true : undefined} onChange={e => set({ every: e.target.value })} />
              )}
            </Row>
          ) : (
            <div className="trigger-pair">
              <Row id="trigger-at" label="Time" error={errors.when} note="By this machine's clock.">
                {described => (
                  <input id="trigger-at" className="input mono" type="time" value={values.at} aria-describedby={described} aria-invalid={errors.when ? true : undefined} onChange={e => set({ at: e.target.value })} />
                )}
              </Row>
              <Row id="trigger-days" label="Days" error={errors.days}>
                {described => (
                  <select id="trigger-days" className="input" value={values.days} aria-describedby={described} aria-invalid={errors.days ? true : undefined} onChange={e => set({ days: e.target.value as FormValues['days'] })}>
                    <option value="daily">Every day</option>
                    <option value="weekdays">Weekdays</option>
                    <option value="chosen">Chosen days</option>
                  </select>
                )}
              </Row>
            </div>
          )}
          {values.schedule === 'at' && values.days === 'chosen' && (
            <fieldset className="trigger-week" aria-describedby={errors.days ? 'trigger-days-error' : undefined}>
              <legend>On these days</legend>
              {WEEK.map(([day, name]) => (
                <label key={day} className="choice">
                  <input
                    type="checkbox"
                    aria-label={name}
                    checked={values.week.includes(day)}
                    onChange={e => set({ week: e.target.checked ? [...values.week, day] : values.week.filter(one => one !== day) })}
                  />
                  <span aria-hidden="true">{name.slice(0, 3)}</span>
                </label>
              ))}
            </fieldset>
          )}
        </fieldset>
      )}
      {values.kind === 'files' && (
        <Row
          id="trigger-glob"
          label="Path pattern"
          error={errors.glob}
          note="Paths inside the project folder, e.g. src/**/*.py. Two triggers that change each other’s files can keep starting each other; only “Runs a day” stops that."
          more="It runs ten seconds after the last change."
        >
          {described => (
            <input id="trigger-glob" className="input mono" value={values.glob} maxLength={LIMITS.glob} placeholder="src/**/*.py" aria-describedby={described} aria-invalid={errors.glob ? true : undefined} onChange={e => set({ glob: e.target.value })} />
          )}
        </Row>
      )}
      {values.kind === 'webhook' && (
        <p className="muted trigger-note">
          It runs when a program on this machine sends a request to its address. <Hint doc={GUIDE.triggerWebhooks}>The address holds a key and is shown once, when the trigger is made.</Hint>
        </p>
      )}
      <Row
        id="trigger-conversation"
        label="Conversation"
        error={errors.conversation}
        note={conversations.length === 0 ? 'This project has no conversation yet: start one first.' : `Its messages are added to this conversation. While that conversation is at work, a run that falls due is skipped${values.kind === 'files' ? '; a change to its files waits until the conversation is free' : ''}.`}
        more={OWN_TOPIC}
      >
        {described => (
          <select id="trigger-conversation" className="input" value={values.conversationId} aria-describedby={described} onChange={e => setValues(prev => withConversation(prev, e.target.value))}>
            {values.conversationId === '' && <option value="">Choose a conversation</option>}
            {conversations.map(conversation => (
              <option key={conversation.id} value={conversation.id}>
                {conversation.title}
              </option>
            ))}
          </select>
        )}
      </Row>
      <Row id="trigger-message" label="Message" error={errors.message} note="What the agent is told each time, as if you had written it.">
        {described => (
          <textarea id="trigger-message" className="input role-instructions" rows={4} value={values.message} maxLength={LIMITS.message} aria-describedby={described} aria-invalid={errors.message ? true : undefined} onChange={e => set({ message: e.target.value })} />
        )}
      </Row>

      <fieldset className="trigger-leave">
        <legend>What its work may do without asking</legend>
        <p className="muted trigger-note">
          There is nobody to ask when it runs. Anything not allowed here is refused, except the project’s own test command, which runs unticked; its work says afterwards what it would have asked for. The conversation’s own permission level does not apply.
        </p>
        <label className="choice" htmlFor="trigger-write">
          <input id="trigger-write" type="checkbox" aria-label="May change files" checked={values.write} aria-describedby="trigger-write-note" onChange={e => set({ write: e.target.checked })} />
          <span>
            May change files
            <span id="trigger-write-note" className="choice-note">
              Its work writes and edits files in the project without asking you.
            </span>
            <span className="choice-note">Without it, nothing a sub-agent or its commands write in its own working copy reaches the project.</span>
          </span>
        </label>
        {values.conversationId && (
          <CommandLeave
            // Another conversation: another list, and nothing typed for the one before.
            key={values.conversationId}
            conversationId={values.conversationId}
            ticked={values.commands}
            onTicked={commands => set({ commands })}
            onRules={onRules}
            onAddRule={onAddRule}
            suggest={command && values.conversationId === initial.conversationId ? command : ''}
            onRead={rulesRead}
            error={errors.commands}
          />
        )}
        <Row id="trigger-agents" label="May open sub-agents" error={errors.agents} note="How many sub-agents a run may open in all: 0 to 4." more="Each may do only what this trigger allows.">
          {described => (
            <input id="trigger-agents" className="input mono trigger-number" type="number" min={LIMITS.agents[0]} max={LIMITS.agents[1]} value={values.agents} aria-describedby={described} aria-invalid={errors.agents ? true : undefined} onChange={e => set({ agents: e.target.value })} />
          )}
        </Row>
        <WebLeave conversationId={values.conversationId} web={values.web} hosts={values.hosts} notify={values.notify} onChange={set} onHosts={onHosts} />
      </fieldset>

      <fieldset className="trigger-leave">
        <legend>Budget</legend>
        <p className="muted trigger-note">A run that goes over is stopped. Three runs in a row that fail or go over switch the trigger off.</p>
        <div className="trigger-budget">
          <Row id="trigger-steps" label="Model steps a run" error={errors.steps} note="1 to 200, all its agents together.">
            {described => (
              <input id="trigger-steps" className="input mono" type="number" min={1} max={200} value={values.steps} aria-describedby={described} aria-invalid={errors.steps ? true : undefined} onChange={e => set({ steps: e.target.value })} />
            )}
          </Row>
          <Row id="trigger-minutes" label="Minutes a run" error={errors.minutes} note="1 to 240.">
            {described => (
              <input id="trigger-minutes" className="input mono" type="number" min={1} max={240} value={values.minutes} aria-describedby={described} aria-invalid={errors.minutes ? true : undefined} onChange={e => set({ minutes: e.target.value })} />
            )}
          </Row>
          <Row id="trigger-per-day" label="Runs a day" error={errors.perDay} note="1 to 500.">
            {described => (
              <input id="trigger-per-day" className="input mono" type="number" min={1} max={500} value={values.perDay} aria-describedby={described} aria-invalid={errors.perDay ? true : undefined} onChange={e => set({ perDay: e.target.value })} />
            )}
          </Row>
        </div>
      </fieldset>

      <fieldset className="trigger-leave" aria-describedby={errors.ends ? 'trigger-ends-error' : undefined}>
        <legend>Ends</legend>
        {ENDS.map(([end, label]) => (
          <label key={end} className="choice">
            <input type="radio" name="trigger-ends" checked={values.ends === end} onChange={() => set({ ends: end, endUntil: end === 'until' && !values.endUntil ? today() : values.endUntil })} />
            <span>{label}</span>
          </label>
        ))}
        {values.ends === 'runs' && (
          <Row id="trigger-end-runs" label="Runs, then it switches itself off" error={errors.ends} note={`${LIMITS.runs[0]} to ${LIMITS.runs[1]}, counted from when you save.`}>
            {described => (
              <input id="trigger-end-runs" className="input mono trigger-number" type="number" min={LIMITS.runs[0]} max={LIMITS.runs[1]} value={values.endRuns} aria-describedby={described} aria-invalid={errors.ends ? true : undefined} onChange={e => set({ endRuns: e.target.value })} />
            )}
          </Row>
        )}
        {values.ends === 'until' && (
          <Row id="trigger-end-until" label="Its last day" error={errors.ends} note="It runs on this day, by this machine's clock, and switches itself off after it. At most a year ahead.">
            {described => (
              <input id="trigger-end-until" className="input mono" type="date" min={today()} max={day(365)} value={values.endUntil} aria-describedby={described} aria-invalid={errors.ends ? true : undefined} onChange={e => set({ endUntil: e.target.value })} />
            )}
          </Row>
        )}
        {values.ends === 'none' && (
          <div role="note" className="composer-warning" aria-label="No end">
            <strong>No end:</strong> it runs until you switch it off. {costNote(values)}
          </div>
        )}
      </fieldset>

      <label className="choice" htmlFor="trigger-catch-up">
        <input id="trigger-catch-up" type="checkbox" aria-label="Run once when KOLONİ starts if a run was missed" checked={values.catchUp} onChange={e => set({ catchUp: e.target.checked })} />
        <span>
          Run once when KOLONİ starts if a run was missed
          <span className="choice-note">Just one run, however many were missed while KOLONİ was closed.</span>
        </span>
      </label>
      {values.kind === 'schedule' && (
        <label className="choice" htmlFor="trigger-run-unchanged">
          <input id="trigger-run-unchanged" type="checkbox" aria-label="Run even if nothing changed" checked={values.runUnchanged} onChange={e => set({ runUnchanged: e.target.checked })} />
          <span>
            Run even if nothing changed{' '}
            <Hint doc={GUIDE.triggerMaking}>Otherwise, in a git project, a run is skipped when the commit, the files and the settings are the same as at its last finished run. A run that may use the web always runs.</Hint>
          </span>
        </label>
      )}

      {refused && (
        <div role="alert" className="alert">
          {refused}
        </div>
      )}
      <div className="role-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {editing ? 'Save' : 'Add trigger'}
        </button>
        <button type="button" className="btn" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}
