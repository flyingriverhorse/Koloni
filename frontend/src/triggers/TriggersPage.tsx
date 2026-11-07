import { CaretDown, Copy, Plus } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import type { AllowedCommand, Conversation, NewTrigger, Trigger, TriggerChange, TriggerCreated, TriggerLogEntry, TriggerProposal } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { Menu } from './Menu'
import { TriggerCard } from './TriggerCard'
import { TriggerChanges } from './TriggerChanges'
import { TriggerForm } from './TriggerForm'
import { type Allow, type FormValues, OWN_TOPIC, PRESET, READY, blank, fromProposal, fromTrigger, toBody, toPatch } from './triggerText'

interface Props {
  /** The open project's triggers; null until they have been read. */
  triggers: Trigger[] | null
  /** Why they could not be read, if they could not. */
  error?: string | null
  /** The newest things done to the project's triggers - those of deleted ones too, shown only for those; null until read. */
  changes?: TriggerLogEntry[] | null
  /** The project's conversations: a trigger's turns go into one of them. */
  conversations: Conversation[]
  /** Something a turn was refused, to be allowed in its trigger: its form opens with that filled in. Or an agent's proposed trigger (slice 69): a new one's form opens with it. */
  draft: { triggerId: string; allow: Allow } | { proposal: TriggerProposal } | null
  /** The draft was taken up (or its trigger is gone): it is not to be opened again. */
  onDraftTaken: () => void
  /** Where this page is served from: a webhook's address begins with it. */
  origin: string
  /** Each of these throws ApiError with the server's reason. */
  onCreate: (values: NewTrigger) => Promise<TriggerCreated>
  onSave: (triggerId: string, change: TriggerChange) => Promise<void>
  onDelete: (triggerId: string) => Promise<void>
  onRun: (triggerId: string) => Promise<string>
  /** A webhook's key made anew; its answer carries the new key. */
  onNewKey?: (triggerId: string) => Promise<TriggerCreated>
  /** Draw a turn on the canvas: it may be in another conversation than the open one. */
  onShowTurn: (conversationId: string, runId: string) => void
  onRules: (conversationId: string) => Promise<AllowedCommand[]>
  onAddRule: (conversationId: string, prefix: string) => Promise<AllowedCommand>
  onHosts?: (conversationId: string) => Promise<string[]>
}

/** The form that is open: a new trigger from these values (an agent's proposal's, its id said), or one that is there. */
type Open = { id: null; initial: FormValues; allow: null; proposalId?: string } | { id: string; initial: FormValues; allow: Allow | null; proposalId?: undefined }

/**
 * Triggers start a turn by the clock, on changed files, or on a request from outside - in a
 * conversation you choose, with a message you wrote, and with nobody watching. Such a turn
 * asks nobody: it does only what its trigger allows. Only this page makes or changes one.
 */
export function TriggersPage({ triggers, error, changes = null, conversations, draft, onDraftTaken, origin, onCreate, onSave, onDelete, onRun, onNewKey, onShowTurn, onRules, onAddRule, onHosts }: Props) {
  const [open, setOpen] = useState<Open | null>(null)
  // A webhook's address, held only until it is put away: the server never says it again.
  const [made, setMade] = useState<{ name: string; address: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [gone, setGone] = useState(false)
  // Around "New trigger": the focus goes back to its button.
  const newRef = useRef<HTMLSpanElement>(null)

  // A request from the chat is taken up once the triggers are here.
  useEffect(() => {
    if (!draft || !triggers) return
    if ('proposal' in draft) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setOpen({ id: null, initial: fromProposal(draft.proposal), allow: null, proposalId: draft.proposal.id })
      onDraftTaken()
      return
    }
    const trigger = triggers.find(t => t.id === draft.triggerId)
    // (Taking up a request is something that happened outside this page: its state follows it.)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (trigger) setOpen({ id: trigger.id, initial: fromTrigger(trigger), allow: draft.allow })
    setGone(!trigger)
    onDraftTaken()
  }, [draft, triggers, onDraftTaken])

  const first = conversations[0]?.id ?? ''
  const titleOf = (id: string) => conversations.find(c => c.id === id)?.title ?? null

  async function submit(values: FormValues) {
    if (!open) return
    if (open.id) await onSave(open.id, toPatch(values))
    else {
      const created = await onCreate(toBody(values, open.proposalId ?? null))
      if (created.key) {
        setMade({ name: created.name, address: `${origin}/api/hooks/${created.key}` })
        setCopied(false)
      }
    }
    setOpen(null)
  }

  if (!triggers) {
    return (
      <div className="triggers-page">
        {error ? (
          <div role="alert" className="alert">
            {error}
          </div>
        ) : (
          <p className="muted">Reading the project’s triggers…</p>
        )}
      </div>
    )
  }

  // Each only fills the form; nothing is made until it is added.
  const start = (initial: FormValues) => setOpen({ id: null, initial, allow: null })
  // With none yet, it stands where the page says so; one button, not two of the same name.
  const newTrigger = (
    <span ref={newRef}>
      <Menu
        name="New trigger"
        className="btn btn-primary btn-small"
        wide
        face={
          <>
            <Plus size={13} aria-hidden />
            New trigger
            <CaretDown size={11} aria-hidden />
          </>
        }
      >
        <button type="button" role="menuitem" onClick={() => start(PRESET(first))}>
          <strong>Keep an agent on this project</strong>
          <span className="muted">Every hour it looks the project over. Reads only.</span>
        </button>
        {READY.map(card => (
          <button key={card.name} type="button" role="menuitem" onClick={() => start({ ...blank(first), name: card.name, ...card.values })}>
            <strong>{card.name}</strong>
            <span className="muted">{card.says}</span>
          </button>
        ))}
        <button type="button" role="menuitem" className="menu-last" onClick={() => start(blank(first))}>
          <strong>Start from blank</strong>
        </button>
      </Menu>
    </span>
  )
  // Decision 1: a deleted trigger's changes stay on the page, folded.
  // shortcut: only among the newest changes the server sends (`/triggers/changes`); older ones are not paged in.
  const orphaned = (changes ?? []).filter(change => !triggers.some(one => one.id === change.trigger_id))
  return (
    <div className="triggers-page">
      <div className="conv-head">
        <h2>Triggers</h2>
        <span className="muted trigger-lede">
          Work that starts by itself. Only you make or change a trigger; no agent can.{' '}
          <Hint doc={GUIDE.triggers}>
            It runs with nobody watching, doing only what you allowed. A trigger sends its message by the clock, when files change, or on a request from outside. Its work asks nobody: it does only
            what its trigger allows, and says afterwards what it would have asked for. “Keep an agent on this project” fills in a trigger that looks the project over every hour, reading only, with a
            message for you to change. {OWN_TOPIC}
          </Hint>
        </span>
        <div className="memory-actions">{triggers.length > 0 && newTrigger}</div>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {gone && (
        <div role="alert" className="alert">
          That trigger is no longer there.
        </div>
      )}
      {made && (
        <section className="trigger-key" aria-label={`The address of ${made.name}`}>
          <h3>{made.name} runs when this address is sent a POST request</h3>
          <div className="trigger-address">
            <code className="mono">{made.address}</code>
            <button
              type="button"
              className="btn btn-small"
              onClick={() => {
                // (No clipboard on a page that is not served securely: the address can still be selected.)
                void navigator.clipboard?.writeText(made.address).then(
                  () => setCopied(true),
                  () => setCopied(false),
                )
              }}
            >
              <Copy size={12} />
              {copied ? 'Copied' : 'Copy the address'}
            </button>
          </div>
          <p className="trigger-key-warn">
            This is shown once: it cannot be read back later. Anyone on this machine who has this address can run the trigger. If it is lost or leaks, make a new key on the trigger; this address then stops working.
          </p>
          <p className="muted trigger-note">The agent gets what the request carries as something to look at, never as an instruction. Only requests from this machine are accepted.</p>
          <div className="role-actions">
            <button type="button" className="btn btn-small" onClick={() => setMade(null)}>
              I have copied it
            </button>
          </div>
        </section>
      )}
      {open && (
        <TriggerForm
          // One form at a time, made anew for each thing it is opened on.
          key={`${open.id ?? 'new'}:${open.initial.name}:${open.allow ? JSON.stringify(open.allow) : ''}`}
          initial={open.initial}
          editing={open.id !== null}
          conversations={conversations}
          allow={open.allow}
          onSubmit={submit}
          onCancel={() => {
            // The form goes, and on an empty page "New trigger" comes back with it: the focus goes there.
            flushSync(() => setOpen(null))
            newRef.current?.querySelector('button')?.focus()
          }}
          onRules={onRules}
          onAddRule={onAddRule}
          onHosts={onHosts}
        />
      )}
      {triggers.length === 0 && !open && (
        <div className="trigger-empty">
          <p className="muted">No trigger yet. Nothing in this project starts by itself.</p>
          {newTrigger}
        </div>
      )}
      {triggers.map(trigger => (
        <TriggerCard
          key={trigger.id}
          trigger={trigger}
          conversation={titleOf(trigger.conversation_id)}
          onSwitch={enabled => onSave(trigger.id, { enabled })}
          onBack={() => onSave(trigger.id, {})}
          onRun={() => onRun(trigger.id)}
          onNewKey={
            trigger.kind === 'webhook' && onNewKey
              ? async () => {
                  const renewed = await onNewKey(trigger.id)
                  if (renewed.key) {
                    setMade({ name: renewed.name, address: `${origin}/api/hooks/${renewed.key}` })
                    setCopied(false)
                  }
                }
              : undefined
          }
          onEdit={() => setOpen({ id: trigger.id, initial: fromTrigger(trigger), allow: null })}
          onDelete={() => onDelete(trigger.id)}
          onShowTurn={runId => onShowTurn(trigger.conversation_id, runId)}
        />
      ))}
      {orphaned.length > 0 && (
        <details className="trigger-record">
          <summary>Changes of deleted triggers ({orphaned.length})</summary>
          <TriggerChanges changes={orphaned} label="Changes of deleted triggers" named />
        </details>
      )}
    </div>
  )
}
