import { UsersThree } from '@phosphor-icons/react'
import { type FormEvent, Fragment, useContext, useRef, useState } from 'react'
import { errorText, overWhat } from '../api/client'
import type { NewRoom, Provider, Role } from '../api/types'
import { type LoadModels, ModelNameInput } from '../models/ModelNameInput'
import { CloseMore, usePanel } from '../shell/usePanel'

/** What a room may spend; null: no limit of that. */
export interface RoomLimits {
  posts: number | null
  tokens: number | null
  minutes: number | null
}

interface Props {
  roles: Role[]
  providers: Provider[]
  /** What a room of this conversation may spend unless you say otherwise here. */
  limits: RoomLimits
  /** A turn is at work: a room is a turn of its own, and is not queued behind one. */
  busy: boolean
  onOpen: (room: NewRoom) => Promise<void>
  onModels?: LoadModels
}

interface Member {
  role: string
  /** The provider's id; '' for the model its role would run on anyway. */
  provider: string
  model: string
}

const LIMITS = ['posts', 'tokens', 'minutes'] as const
const [FEWEST, MOST] = [2, 6]
/** A CLI at work with its own tools cannot be held to a room's list of items. */
const ownTools = (provider: Provider) => provider.mode === 'native' || provider.mode === 'reads'
/** A limit as it was written: a whole number from 1, or nothing at all (no limit). */
const isLimit = (text: string) => !text.trim() || (/^\d+$/.test(text.trim()) && Number(text) >= 1)

/**
 * "Work together…": open a room - two to six agents working on one goal at the same time,
 * in one working copy. You name the goal, who is in it (a role each, and a model of your
 * own choosing where you want one) and what it may spend.
 */
export function WorkTogether({ roles: all, providers, limits, busy, onOpen, onModels }: Props) {
  // The Observer is asked one question by KOLONİ, never opened as a member.
  const roles = all.filter(r => !(r.builtin && r.name === 'Observer'))
  const { open, setOpen, close, button, panel } = usePanel<HTMLFormElement>()
  const closeMore = useContext(CloseMore)
  const [goal, setGoal] = useState('')
  const [members, setMembers] = useState<Member[]>([])
  const [budget, setBudget] = useState({ posts: '', tokens: '', minutes: '' })
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The server said the project is over this month's budget: the room waits for the user's word, as a message does.
  const [over, setOver] = useState<string | null>(null)
  const openButton = useRef<HTMLButtonElement>(null)
  const valid = goal.trim().length > 0 && members.every(m => m.role) && LIMITS.every(key => isLimit(budget[key]))

  function toggle() {
    if (open) return close()
    // Opening starts from two members the roles have, and from the conversation's own limits.
    const first = ['Coder', 'Reviewer'].map(name => roles.find(r => r.name === name)?.name ?? roles[0]?.name ?? '')
    setMembers(first.map(role => ({ role, provider: '', model: '' })))
    setBudget({ posts: String(limits.posts ?? ''), tokens: String(limits.tokens ?? ''), minutes: String(limits.minutes ?? '') })
    setError(null)
    setOver(null)
    setOpen(true)
  }

  const change = (at: number, over: Partial<Member>) => setMembers(members.map((m, index) => (index === at ? { ...m, ...over } : m)))

  async function submit(event?: FormEvent, overBudget = false) {
    event?.preventDefault()
    if (!valid || busy) return
    setSending(true)
    setError(null)
    setOver(null)
    // Said whole: what is left empty is no limit, not the conversation's own.
    const limit = (key: (typeof LIMITS)[number]) => (budget[key].trim() ? Number(budget[key]) : null)
    const spend: RoomLimits = { posts: limit('posts'), tokens: limit('tokens'), minutes: limit('minutes') }
    try {
      await onOpen({
        goal: goal.trim(),
        with: members.map(m => {
          const provider = providers.find(p => p.id === m.provider)
          return { role: m.role, ...(provider && { provider: provider.name, ...(m.model.trim() && { model: m.model.trim() }) }) }
        }),
        budget: spend,
        over_budget: overBudget,
      })
      setGoal('')
      close()
      closeMore() // (else More stays open over the room's tab)
    } catch (err) {
      const said = overBudget ? null : overWhat(err)
      if (said) setOver(said)
      else setError(errorText(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="allow-list">
      <button
        ref={button}
        type="button"
        className="btn btn-small"
        aria-expanded={open}
        title="Open a room: two to six agents working on one goal at the same time"
        onClick={toggle}
      >
        <UsersThree size={13} />
        Work together…
      </button>
      {open && (
        <form ref={panel} tabIndex={-1} className="allow-list-panel room-open" aria-label="Work together" onSubmit={submit}>
          <div className="kicker">Work together in a room</div>
          <div className="field">
            <label htmlFor="room-goal">Goal</label>
            <textarea
              id="room-goal"
              className="input"
              rows={3}
              maxLength={4000}
              value={goal}
              placeholder="What they are to do together: it is the message the room works on"
              onChange={e => setGoal(e.target.value)}
            />
          </div>
          <div className="kicker">Members</div>
          {members.map((member, at) => (
            <div key={at} className="room-member" role="group" aria-label={`Member ${at + 1}`}>
              <select className="input" aria-label={`Role of member ${at + 1}`} value={member.role} onChange={e => change(at, { role: e.target.value })}>
                {roles.map(role => (
                  <option key={role.id} value={role.name}>
                    {role.name}
                  </option>
                ))}
              </select>
              <select
                className="input"
                aria-label={`Provider of member ${at + 1}`}
                value={member.provider}
                onChange={e => change(at, { provider: e.target.value, model: '' })}
              >
                <option value="">Its role’s own model</option>
                {providers.map(provider => (
                  <option key={provider.id} value={provider.id} disabled={ownTools(provider) || provider.enabled === false}>
                    {provider.name}
                    {provider.enabled === false ? ' — off' : ownTools(provider) ? ' — works with its own tools' : ''}
                  </option>
                ))}
              </select>
              {member.provider && (
                <ModelNameInput
                  label={`Model of member ${at + 1}`}
                  value={member.model}
                  placeholder={providers.find(p => p.id === member.provider)?.default_model ?? 'The provider’s default'}
                  providerId={member.provider}
                  loadModels={onModels}
                  onChange={model => change(at, { model })}
                />
              )}
              {members.length > FEWEST && (
                <button type="button" className="btn btn-small" onClick={() => setMembers(members.filter((_m, index) => index !== at))}>
                  Remove
                </button>
              )}
            </div>
          ))}
          {members.length < MOST && (
            <button
              type="button"
              className="btn btn-small"
              onClick={() => setMembers([...members, { role: roles[0]?.name ?? '', provider: '', model: '' }])}
            >
              Add a member
            </button>
          )}
          <div className="kicker">What it may spend</div>
          <div className="spawn-limits">
            {LIMITS.map(key => (
              <Fragment key={key}>
                <label htmlFor={`room-${key}`}>
                  {key === 'posts' ? 'Posts by its members' : key === 'tokens' ? 'Tokens sent and written' : 'Minutes'}
                </label>
                <input
                  id={`room-${key}`}
                  className="input"
                  inputMode="numeric"
                  placeholder="none"
                  value={budget[key]}
                  onChange={e => setBudget({ ...budget, [key]: e.target.value })}
                />
              </Fragment>
            ))}
          </div>
          {/* (One place for the project's: not kept from here too.) */}
          <div className="muted cmd-approval-note">This room’s own. A room starts from the project’s limits: Settings › This project › New chats start with.</div>
          {!LIMITS.every(key => isLimit(budget[key])) && (
            <div className="muted cmd-approval-note">A limit is a whole number from 1; left empty, there is none.</div>
          )}
          <div className="muted cmd-approval-note">
            The room is a piece of work of its own, and ends at the first limit it reaches. Its members are opened without a card:
            you name them here. A CLI that works with its own tools cannot be a member. What they change is in one copy of
            the project, taken in when the room is over - you are asked first, unless everybody’s work was over and this
            conversation takes changes without asking. It has no token limit unless you set one: its tokens are all its
            members’ steps sent and wrote (each step resends its context), and the turn’s and the project’s own limits hold
            it. A model that reports no tokens is not held to that limit.
          </div>
          {busy && <div className="muted cmd-approval-note">Something is at work: open the room when it is over.</div>}
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
          {over && (
            <div role="group" aria-label={over} className="composer-warning composer-budget">
              <span role="alert">{over}. Open the room anyway?</span>
              <button type="button" className="btn btn-small" autoFocus onClick={() => void submit(undefined, true)}>
                Go on anyway
              </button>
              <button
                type="button"
                className="btn btn-small"
                onClick={() => {
                  setOver(null)
                  openButton.current?.focus()
                }}
              >
                Cancel
              </button>
            </div>
          )}
          <button ref={openButton} type="submit" className="btn btn-small btn-primary" disabled={!valid || busy || sending}>
            Open the room
          </button>
        </form>
      )}
    </div>
  )
}
