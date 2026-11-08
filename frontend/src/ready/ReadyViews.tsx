import { X } from '@phosphor-icons/react'
import { useEffect, useId, useRef, useState } from 'react'
import { errorText } from '../api/client'
import { NightRow } from './NightRow'
import { WaitRow } from '../backlog/BacklogPage'
import { count, since } from '../board/columns'
import { type RequestHandlers, WaitingCard, WaitingList } from '../chat/MessageList'
import { DecidedForYou } from '../chat/DecidedForYou'
import { PARTS, decidedOf } from '../chat/waiting'
import { wouldReplace } from '../memory/memoryText'
import { Proposal, Suggestion } from '../memory/records'
import type { WaitingKind, Waiting as WaitingRow } from '../chat/waiting'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { READY_PANEL, type ReadyItem, type ReadySource, SOURCES, chatOf, ofChat, readyId } from './ready'

/** Open a chat; `key`: at that card of it (the panel's This chat). Resolves once it is open. */
type OpenChat = (conversationId: string, key?: string) => Promise<void>

const WORD: Record<ReadySource, string> = { chat: 'chat', todo: 'to-do', memory: 'memory', night: 'while away', other: 'other folder' }

/**
 * A chat's cards' words, as the chat's own take them. Another chat sends no events here: once one of its cards is
 * answered, it is read again (`loadReadyChats`); a diff of it opens in its chat.
 */
function handlersOf(state: ConvState, openChat: OpenChat): RequestHandlers & { onDecidePlan: ReturnType<typeof useApp.getState>['decidePlan'] } {
  const s = useApp.getState()
  const id = state.conversation.id
  const then =
    <A extends unknown[]>(act: (...args: A) => Promise<void>) =>
    (...args: A) =>
      act(...args).finally(() => {
        if (useApp.getState().conv?.conversation.id !== id) void useApp.getState().loadReadyChats(id)
      })
  return {
    onOpenChange: changeId => void openChat(id).then(() => useApp.getState().openChange(changeId)),
    onDecide: then(s.decide),
    onDecideCommand: then(s.decideCommand),
    onDecideWeb: then(s.decideWeb),
    onSelectAgent: agentId => s.select(`agent:${agentId}`),
    onDecideSpawn: then(s.decideSpawn),
    onDecideRole: then(s.decideRole),
    onDecideMerge: then(s.decideMerge),
    onCheckMerge: then(s.checkMerge),
    onCommitMerge: then(s.commitMerge),
    onAnswer: then(s.answerQuestion),
    onDecidePlan: then(s.decidePlan),
  }
}

/** Where a row comes from, in words: its agent and chat (and folder), or the list it is on. */
function fromOf(item: ReadyItem, folder: (projectId: string | null) => string | undefined): string {
  if (item.what === 'task') return 'To-do'
  if (item.what === 'memory') return item.suggestion ? 'Memory · for your preferences' : 'Memory'
  if (item.what === 'night') return "While you're away"
  const agent = item.state.agents.find(a => a.id === item.row.agentId)
  const where = item.source === 'other' ? folder(item.state.conversation.project_id) : undefined
  return [agent && `${agent.name || agent.role_name} asks`, `“${item.state.conversation.title}”`, where].filter(Boolean).join(' · ')
}

/** A chat's card, with its chat's words. */
function ChatCard({ state, row, openChat }: { state: ConvState; row: WaitingRow; openChat: OpenChat }) {
  const roles = useApp(s => s.roles)
  const providers = useApp(s => s.providers)
  const on = handlersOf(state, openChat)
  return <WaitingCard state={state} row={row} on={on} onDecidePlan={on.onDecidePlan} known={{ roles, providers }} />
}

/** One thing that waits: where it is from, since when, and its own card, its decision on it (tek-ev §1). */
function ReadyRow({ item, openChat, error, off }: { item: ReadyItem; openChat: OpenChat; error?: string; off?: boolean }) {
  const projects = useApp(s => s.projects)
  const memory = useApp(s => s.memory)
  const chat = chatOf(item)
  const from = fromOf(item, projectId => projects.find(p => p.id === projectId)?.name)
  const s = useApp.getState()
  // A night's job, whether from the night or from its chat's card: what it asks, and the way to its chat - nothing more.
  const night = item.what === 'night' ? item.job : item.what === 'card' && item.row.what === 'night' ? item.row.item.job : null
  return (
    // (Each row a group named by where it is from: their buttons told apart.)
    <li id={readyId(item.key)} tabIndex={-1} className="ready-item" role="group" aria-label={`${WORD[item.source]}: ${from}`}>
      <div className="ready-item-head">
        <span className="tag">{WORD[item.source]}</span>
        <span className="ready-item-from">{from}</span>
        {item.at && <span className="mono muted">{since(item.at)}</span>}
        {chat && (
          <button type="button" className="btn btn-small" onClick={() => void openChat(chat, item.what === 'card' ? item.key : undefined)}>
            Open chat
          </button>
        )}
      </div>
      {night ? (
        <NightRow job={night} onOpen={id => void openChat(id)} />
      ) : item.what === 'card' ? (
        <ChatCard state={item.state} row={item.row} openChat={openChat} />
      ) : item.what === 'task' ? (
        <WaitRow task={item.task} only={item.kind} onDecide={s.decideTask} onChange={s.changeTask} onOpen={id => void openChat(id)} off={off} failed={error} />
      ) : item.what === 'memory' ? (
        item.suggestion ? (
          <Suggestion record={item.record} onAdd={s.addPreference} onReject={s.rejectMemory} />
        ) : (
          <Proposal record={item.record} replaces={memory ? wouldReplace(memory, item.record) : undefined} onApprove={s.approveMemory} onReject={s.rejectMemory} onConfirm={s.confirmMemory} />
        )
      ) : null}
    </li>
  )
}

/** A row's kind, for its part of Ready for you (`PARTS`): a chat's card as its chat counts it; a To-do, memory or night row is a decision. */
const kindOf = (item: ReadyItem): WaitingKind => (item.what === 'card' ? item.row.kind : 'decision')

function ReadyList({ items, openChat, errors = {}, off }: { items: ReadyItem[]; openChat: OpenChat; errors?: Record<string, string>; off?: boolean }) {
  return (
    <ul className="ready-items">
      {items.map(item => (
        <ReadyRow key={item.key} item={item} openChat={openChat} error={errors[item.key]} off={off} />
      ))}
    </ul>
  )
}

interface PanelProps {
  items: ReadyItem[]
  openChat: OpenChat
  /** "Open all as a page". */
  onPage: () => void
  onClose: () => void
}

/**
 * Ready for you's panel, from the right over any page (tek-ev §1): the open chat's first - its list as the chat's tab
 * had it, with what the Lead decided for you - then everything else. It takes the focus, Esc closes it, and the focus
 * goes back where it was.
 */
export function ReadyPanel({ items, openChat, onPage, onClose }: PanelProps) {
  const id = useId()
  const conv = useApp(s => s.conv)
  const at = useApp(s => s.readyPanel.at)
  const roles = useApp(s => s.roles)
  const providers = useApp(s => s.providers)
  const here = ofChat(items, conv?.conversation.id)
  const rest = items.filter(item => !here.includes(item))
  const box = useRef<HTMLElement>(null)
  useEffect(() => {
    const opener = document.activeElement
    box.current?.focus()
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [])
  // Asked to open at a card: the focus goes to it, and it into view.
  useEffect(() => {
    const card = at ? document.getElementById(at) : null
    card?.focus({ preventScroll: true })
    card?.scrollIntoView?.({ block: 'center' })
  }, [at])
  // Esc in it - or with the focus nowhere, a card just answered gone from under it - closes it; a box open in it closes first (its own Esc stops there).
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  })
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const at = document.activeElement
      if (event.key === 'Escape' && (!at || at === document.body || box.current?.contains(at))) close.current()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])
  const on = conv && handlersOf(conv, openChat)
  return (
    <aside ref={box} id={READY_PANEL} tabIndex={-1} className="ready-panel" aria-labelledby={`${id}-head`}>
      <div className="ready-panel-head">
        <h2 id={`${id}-head`}>Ready for you · {items.length}</h2>
        <button type="button" className="icon-btn" aria-label="Close Ready for you" onClick={onClose}>
          <X size={16} />
        </button>
      </div>
      <div className="ready-panel-body">
        {conv && on && (
          <section aria-labelledby={`${id}-here`}>
            <h3 id={`${id}-here`} className="kicker">
              This chat · {here.length}
            </h3>
            <WaitingList state={conv} on={on} onDecidePlan={on.onDecidePlan} known={{ roles, providers }} />
          </section>
        )}
        <section aria-labelledby={`${id}-rest`}>
          <h3 id={`${id}-rest`} className="kicker">
            Elsewhere · {rest.length}
          </h3>
          {rest.length > 0 ? <ReadyList items={rest} openChat={openChat} /> : <p className="muted">Nothing else waits for you.</p>}
        </section>
      </div>
      <div className="ready-panel-foot">
        <button type="button" className="link-btn" onClick={onPage}>
          Open all as a page →
        </button>
      </div>
    </aside>
  )
}

/**
 * Ready for you as a page (tek-ev §1): the same list, oldest first, by where it comes from; and the To-do list's new
 * tasks approved together - one after another, each as its own Approve does it, one that fails left on its row with why.
 */
export function ReadyPage({ items, openChat }: { items: ReadyItem[]; openChat: OpenChat }) {
  const [only, setOnly] = useState<ReadySource | null>(null)
  const conv = useApp(s => s.conv)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const shown = only ? items.filter(item => item.source === only) : items
  // (Of the rows shown: never one a filter hides.)
  const proposals = shown.flatMap(item => (item.what === 'task' && item.kind === 'new task' ? [item] : []))
  async function approveAll() {
    setBusy(true)
    const failed: Record<string, string> = {}
    for (const one of proposals) {
      try {
        await useApp.getState().decideTask(one.task.id, 'approve')
      } catch (err) {
        failed[one.key] = errorText(err)
      }
    }
    setErrors(failed)
    setBusy(false)
  }
  return (
    <div className="memory-page ready-page">
      <div className="conv-head">
        <h2>
          Ready for you <span className="muted ready-count">· {items.length}, oldest first</span>
        </h2>
        {proposals.length > 0 && (
          <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void approveAll()}>
            Approve all {count(proposals.length, 'proposal')}
          </button>
        )}
      </div>
      <div role="group" aria-label="Show" className="board-show">
        <button type="button" className="btn btn-small" aria-pressed={only === null} onClick={() => setOnly(null)}>
          All · {items.length}
        </button>
        {SOURCES.map(([source, word]) => (
          <button key={source} type="button" className="btn btn-small" aria-pressed={only === source} onClick={() => setOnly(source)}>
            {word} · {items.filter(item => item.source === source).length}
          </button>
        ))}
      </div>
      {shown.length === 0 && <p className="muted">Nothing waits for you here.</p>}
      {PARTS.map(([head, kinds]) => {
        const mine = shown.filter(item => kinds.includes(kindOf(item)))
        return (
          mine.length > 0 && (
            <section key={head} aria-label={head}>
              <h3 className="kicker">{head}</h3>
              <ReadyList items={mine} openChat={openChat} errors={errors} off={busy} />
            </section>
          )
        )
      })}
      {/* shortcut: Told you shows the open chat's Decided for you only - the others' are not loaded here; load them if one is missed. */}
      {!only && conv && decidedOf(conv).length > 0 && (
        // (Decided for you is its own card, under its own title: no second heading over it.)
        <section aria-label="Told you">
          <DecidedForYou state={conv} />
        </section>
      )}
    </div>
  )
}
