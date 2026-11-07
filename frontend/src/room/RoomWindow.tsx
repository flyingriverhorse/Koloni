import { Minus, UsersThree, X } from '@phosphor-icons/react'
import { type FormEvent, type KeyboardEvent, Fragment, useState } from 'react'
import { errorText } from '../api/client'
import type { Provider, Role, Room } from '../api/types'
import { hasCard, isKept, keptToTake } from '../changes/copies'
import { MergeCard } from '../changes/MergeCard'
import { NotApplied } from '../changes/NotApplied'
import { SpawnApproval } from '../agents/SpawnApproval'
import { staysOn } from '../agents/staysOn'
import { type RequestHandlers, SubtreeRequests } from '../chat/MessageList'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { inFront } from '../shell/move'
import type { ConvState } from '../state/applyEvent'
import { ITEM, allDone, byWatcher, invitedTo, isRunning, memberName, memberTag, nameIn, once, postHead, roomLine, roomTag, spentLines, waitsForYou, watchedBy } from './roomText'

interface Props {
  state: ConvState
  room: Room
  /** What a card of one of the room's agents is decided with: the same as in the chat. */
  on: RequestHandlers
  roles: Role[]
  providers: Provider[]
  onSay: (roomId: string, text: string) => Promise<void>
  onEnd: (roomId: string) => Promise<void>
  onMore: (roomId: string, more: { posts?: number; tokens?: number; minutes?: number }) => Promise<void>
  /** 29c: pause it (true) or resume it (false). */
  onPause: (roomId: string, paused: boolean) => Promise<void>
  /** K-oda-izle: let the turn's Lead follow a room you opened (true), or stop it (false). */
  onFollow: (roomId: string, on: boolean) => Promise<void>
  /** —: the window becomes a small tab at the canvas's foot. */
  onShrink: () => void
  /** ×: gone from the canvas - only once it is over; a running room keeps its tab (`onShrink`). */
  onClose: () => void
}

const MORE = ['posts', 'tokens', 'minutes'] as const
const at = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
const MARK: Record<string, string> = { done: '✓', dropped: '✗' }
/** K-oda-izle: what the switch that lets the Lead follow a room you opened stands for. */
const FOLLOW_NOTE: Record<Room['lead_follows'], string> = {
  off: 'Off: the Orchestrator takes no part and is given the room’s record when it is over.',
  on: 'On: the Orchestrator reads what is said here, from what was said so far, and may post, ask one more in or end the room. Your words, Pause and End still come first.',
  stopped: 'The Orchestrator stopped following: it is given the room’s record when it is over.',
}
/** In sight beside the switch, never both: what following spends, and why it stopped. */
const FOLLOW_SHOWN: Partial<Record<Room['lead_follows'], string>> = {
  on: 'Its steps count toward the room’s tokens.',
  stopped: 'Stopped: answered, few steps left, or a CLI session.',
}

/**
 * A room in its own window over the canvas (AC): who is in it and what it may spend, its items one
 * line each, the talk, what it asks of you, and - while it runs - a word of yours, more for it, or
 * its end. Once it is over the same window says what came of it: a line, the room's changes for your
 * word ("From you"), the items, and what was said and reported, folded. It holds no focus: the
 * canvas stays usable around it. What its members wrote is shown as text.
 */
export function RoomWindow({ state, room, on, roles, providers, onSay, onEnd, onMore, onPause, onFollow, onShrink, onClose }: Props) {
  const [draft, setDraft] = useState('')
  const [giving, setGiving] = useState(false)
  const [more, setMore] = useState({ posts: '', tokens: '', minutes: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const running = isRunning(room)
  const paused = running && room.paused
  const items = state.roomItems.filter(i => i.room_id === room.id).sort((a, b) => a.number - b.number)
  const posts = state.roomPosts.filter(p => p.room_id === room.id).sort((a, b) => a.number - b.number)
  const talk = once(posts.filter(p => p.type !== 'done'))
  const reports = once(posts.filter(p => p.type === 'done'))
  const open = posts.filter(p => p.open)
  const members = room.members.flatMap(m => state.agents.filter(a => a.id === m.agent_id))
  // The room's one copy on its way into the project: asked about once, in the lead's name - and only
  // this room's, not another copy of the lead's (a recipe's, an earlier room's: their files and commit).
  const merges = state.merges.filter(m => m.room_id === room.id)
  // (B-156: not a kept copy that holds no file - nothing of it is yours to take in.)
  const fromYou = merges.filter(m => hasCard(m) && (!isKept(m) || keptToTake(m)))
  const added = Object.fromEntries(MORE.filter(key => more[key].trim()).map(key => [key, Number(more[key])]))
  const canGive = Object.keys(added).length > 0 && Object.values(added).every(n => Number.isInteger(n) && n >= 1)
  const close = running ? onShrink : onClose
  // What its members wait on you for - not the room's own copy, which is From you.
  const asks = waitsForYou({ ...state, merges: state.merges.filter(m => m.room_id !== room.id) }, room)
  // Who is where: while it runs, and after it while a member left (failed) - "fewer than two working" says who.
  const showMembers = running || room.members.some(m => m.status === 'left')

  async function act(work: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function say(event: FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!text) return
    void act(async () => {
      await onSay(room.id, text)
      setDraft('')
    })
  }

  function give(event: FormEvent) {
    event.preventDefault()
    if (!canGive) return
    void act(async () => {
      await onMore(room.id, added)
      setMore({ posts: '', tokens: '', minutes: '' })
      setGiving(false)
    })
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key !== 'Escape') return
    // Not over a word half written: Esc there is the field's, and the draft stays in sight.
    const field = event.target
    if ((field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) && field.value) return
    event.stopPropagation()
    onShrink() // (once it is over too: it becomes a tab saying how it ended, and the focus has somewhere to go)
  }

  const line = (post: (typeof posts)[number], times: number) => (
    <div key={post.id} className="channel-message">
      <div className="channel-head">
        <span className="mono">
          {post.number}. {nameIn(state, post.agent_id)}
          {postHead(state, post) && <span className="muted"> · {postHead(state, post)}</span>}
          {times > 1 && <span className="muted"> ×{times}</span>}
          {byWatcher(state, room, post.agent_id) && <span className="tag">watching</span>}
        </span>
        <span className="mono muted">{at(post.created_at)}</span>
      </div>
      <div className="channel-body">{post.text}</div>
    </div>
  )

  return (
    <section
      ref={inFront}
      id={`room-${room.id}`}
      role="dialog"
      aria-label={`Room: ${room.goal}`}
      tabIndex={-1}
      className="changes room-window"
      onKeyDown={onKeyDown}
    >
      <div className="changes-bar">
        <UsersThree size={15} color="var(--tool-team)" />
        <span className="changes-title room-title">Room · {room.goal}</span>
        {!running && (
          <span className={`tag ${allDone(state, room) ? 'tag-ok' : 'tag-warn'}`} title={roomLine(room)}>
            {roomTag(state, room)}
          </span>
        )}
        {/* (29c: said as it changes) */}
        <span role="status">
          {paused && (
            <span className="tag tag-warn" title={roomLine(room)}>
              paused
            </span>
          )}
        </span>
        <span className="changes-spacer" />
        {running && (
          <button type="button" className="icon-btn" aria-label="Make the room small" title="Make it small: a tab at the canvas's foot" onClick={onShrink}>
            <Minus size={14} />
          </button>
        )}
        <button type="button" className="icon-btn" aria-label="Close the room" title={running ? 'Close: while it runs it keeps its tab' : 'Close'} onClick={close}>
          <X size={14} />
        </button>
      </div>

      <div className="agent-feed room-panel">
        <section aria-label="The room">
          <div className="mono muted">
            {room.members.map(m => memberName(state, m)).join(' · ')} · opened by {room.agent_id ? nameIn(state, room.agent_id) : 'you'}
          </div>
          {watchedBy(state, room) && <div className="mono muted">{watchedBy(state, room)}</div>}
          {showMembers && (
            <div className="room-members">
              {room.members.map((member, index) => (
                <span key={member.agent_id ?? index} className="tag">
                  {memberTag(state, room, member)}
                </span>
              ))}
            </div>
          )}
          <div className="mono room-spent" role="group" aria-label="Spent of its budget">
            {spentLines(room).join(' · ')}
          </div>
          {!running && room.summary && <p className="room-summary" title={room.summary}>{room.summary}</p>}
        </section>

        {fromYou.length > 0 && (
          <section aria-label="From you" className="room-ask">
            <div className="kicker">From you</div>
            {fromYou.map(merge => (
              <MergeCard
                key={merge.id}
                merge={merge}
                name="The room"
                unfinished={room.outcome !== 'agreed'}
                onDecide={(decision, choices, shown) => on.onDecideMerge(merge.id, decision, choices, shown)}
                onCheck={choices => on.onCheckMerge(merge.id, choices)}
                onCommit={(message, hooks) => on.onCommitMerge(merge.id, message, hooks)}
              />
            ))}
          </section>
        )}
        {merges.map(merge => (
          <NotApplied key={merge.id} merge={merge} name="the room" />
        ))}

        <section aria-label="Items">
          {items.length === 0 && <p className="muted">Nothing is on the list{running ? ' yet' : ''}.</p>}
          {items.map(item => (
            <details key={item.id} className="room-item">
              <summary>
                <span className={`mono room-item-state room-item-${item.status}`}>
                  {MARK[item.status] ? `${MARK[item.status]} ` : ''}
                  {ITEM[item.status]}
                </span>
                <span className="room-item-title">
                  <span className="mono muted">{item.number}.</span> {item.title}
                </span>
                {item.holder_agent_id && <span className="muted room-item-who">{nameIn(state, item.holder_agent_id)}</span>}
              </summary>
              {item.paths.length > 0 && <div className="mono muted">{item.paths.join(' · ')}</div>}
              {item.result ? <div className="channel-body">{item.result}</div> : item.paths.length === 0 && <div className="muted">Nothing more on it.</div>}
            </details>
          ))}
        </section>

        {/* While it runs the talk is open; once it is over it is folded, as the reports are. */}
        <details className="room-fold" open={running} aria-label="Said in the room">
          <summary>
            Said in the room <span className="muted room-fold-count">{talk.length} {talk.length === 1 ? 'message' : 'messages'}</span>
          </summary>
          {talk.length === 0 && <p className="muted">Nothing has been said yet.</p>}
          {talk.map(([post, times]) => line(post, times))}
        </details>
        {reports.length > 0 && (
          <details className="room-fold" aria-label="Reports">
            <summary>
              Reports <span className="muted room-fold-count">{[...new Set(reports.map(([post]) => nameIn(state, post.agent_id)))].join(' · ')}</span>
            </summary>
            {reports.map(([post, times]) => line(post, times))}
          </details>
        )}

        {open.length > 0 && (
          <section aria-label={running ? 'Open questions' : 'Left unanswered'}>
            <div className="kicker">{running ? 'Open questions' : 'Left unanswered'}</div>
            {open.map(post => (
              <div key={post.id} className="channel-message">
                <div className="channel-head">
                  <span className="mono">
                    {post.number}. {nameIn(state, post.agent_id)}
                    {post.to_agent_id && ` to ${nameIn(state, post.to_agent_id)}`}
                  </span>
                </div>
                <div className="channel-body">{post.text}</div>
              </div>
            ))}
          </section>
        )}

        {/* What its agents wait on you for, and what they said or left of their own work: they were opened by no call of the
            lead's, so it is brought here - its only place - while the room runs and after. The box only while something waits. */}
        <div aria-label={asks ? 'Waits for you' : undefined} role={asks ? 'region' : undefined} className={asks ? 'room-ask' : 'room-asks'}>
          {asks && <div className="kicker">Waits for you</div>}
          {members.map(member => (
            <SubtreeRequests key={member.id} root={member} state={state} on={on} known={{ roles, providers }} />
          ))}
          {invitedTo(state, room).map(agent => (
            <SpawnApproval
              key={agent.id}
              agent={agent}
              openedBy={nameIn(state, state.toolCalls.find(t => t.id === agent.tool_call_id)?.agent_id ?? null)}
              stays={staysOn(state, agent, roles, providers)}
              onDecide={decision => on.onDecideSpawn(agent.id, decision)}
            />
          ))}
        </div>

        {running && giving && (
          <form className="room-more" aria-label="Give it more" onSubmit={give}>
            {MORE.map(key => (
              <Fragment key={key}>
                <label htmlFor={`more-${room.id}-${key}`}>More {key}</label>
                <input
                  id={`more-${room.id}-${key}`}
                  className="input"
                  inputMode="numeric"
                  value={more[key]}
                  // A limit the room does not have stays none: there is nothing to add to.
                  disabled={room.budget[key] === null}
                  placeholder={room.budget[key] === null ? 'no limit' : ''}
                  onChange={e => setMore({ ...more, [key]: e.target.value })}
                />
              </Fragment>
            ))}
            <button type="submit" className="btn btn-small btn-primary" disabled={busy || !canGive}>
              Add
            </button>
          </form>
        )}
      </div>
      {/* (Over the buttons: a refusal coming does not move them from under the pointer, B-195.) */}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {running && (
        <form className="discussion-say" onSubmit={say}>
          <input
            className="input"
            aria-label="Say something in the room"
            placeholder="Say something…"
            maxLength={1500}
            value={draft}
            onChange={e => setDraft(e.target.value)}
          />
          <button type="submit" className="btn btn-small btn-primary" disabled={busy || !draft.trim()}>
            Post
          </button>
          <button type="button" className="btn btn-small" aria-expanded={giving} onClick={() => setGiving(!giving)}>
            Give it more
          </button>
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            title={paused ? 'Its members go on where they stopped' : 'Its members finish the step at hand, then post nothing and spend nothing until you resume it'}
            onClick={() => void act(() => onPause(room.id, !paused))}
          >
            {paused ? 'Resume' : 'Pause'}
          </button>
          <button type="button" className="btn btn-small btn-danger" disabled={busy} onClick={() => void act(() => onEnd(room.id))}>
            End
          </button>
        </form>
      )}
      {/* (A room an agent opened is followed - or not - by its own word.) */}
      {running && room.agent_id === null && (
        <label className={`choice room-follow${room.lead_follows === 'stopped' ? ' choice-disabled' : ''}`} htmlFor={`follow-${room.id}`}>
          <input
            id={`follow-${room.id}`}
            type="checkbox"
            role="switch"
            aria-label="Let the Orchestrator follow"
            aria-describedby={`follow-${room.id}-line${FOLLOW_SHOWN[room.lead_follows] ? ` follow-${room.id}-shown` : ''}`}
            checked={room.lead_follows === 'on'}
            disabled={busy || room.lead_follows === 'stopped'}
            onChange={e => void act(() => onFollow(room.id, e.target.checked))}
          />
          {/* (Its note behind ⓘ, but for what it spends or why it stopped - on the same line, one at a time: the switch
              keeps to one line at the window's foot, B-195.) */}
          <span>
            Let the Orchestrator follow <Hint doc={GUIDE.roomWindow} id={`follow-${room.id}-line`}>{FOLLOW_NOTE[room.lead_follows]}</Hint>
            {FOLLOW_SHOWN[room.lead_follows] && (
              <span id={`follow-${room.id}-shown`} className="muted">
                {' '}
                {FOLLOW_SHOWN[room.lead_follows]}
              </span>
            )}
          </span>
        </label>
      )}
    </section>
  )
}

/**
 * The rooms made small (—), and every one that runs or waits for you whose window is not open: a tab each at the
 * canvas's foot - "Room · <topic> · 3 posts", and "waits for you" in the accent colour when
 * something of it does. A click opens its window again; nothing opens it by itself.
 */
export function RoomTabs({ state, windows, onOpen }: { state: ConvState; windows: Record<string, 'open' | 'small'>; onOpen: (roomId: string) => void }) {
  // (A room not opened in this page - after a reload, in another chat - has its tab too while it runs or waits for you.)
  const small = state.rooms.filter(room => windows[room.id] === 'small' || ((isRunning(room) || waitsForYou(state, room)) && windows[room.id] !== 'open'))
  if (small.length === 0) return null
  return (
    <div className="room-tabs" role="group" aria-label="Rooms">
      {small.map(room => {
        const asks = waitsForYou(state, room)
        return (
          <button
            key={room.id}
            id={`room-tab-${room.id}`}
            type="button"
            className={`room-tab${asks ? ' asks' : ''}`}
            title={`Open the room: ${room.goal}`}
            onClick={() => onOpen(room.id)}
          >
            <UsersThree size={13} className={isRunning(room) && !room.paused ? 'pulse' : undefined} />
            <span className="room-tab-topic">Room · {room.goal}</span>{' '}
            <span className="mono">
              · {isRunning(room) ? `${room.spent.posts ?? 0} ${room.spent.posts === 1 ? 'post' : 'posts'}${room.paused ? ' · paused' : ''}` : roomTag(state, room)}
            </span>
            {asks && <>{' '}<span className="tag tag-accent">waits for you</span></>}
          </button>
        )
      })}
    </div>
  )
}
