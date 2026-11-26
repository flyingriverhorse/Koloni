import { CaretDown, CaretUp, ChatsCircle, FolderSimple } from '@phosphor-icons/react'
import {
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { waitingIn } from '../board/waiting'
import { inProject } from '../changes/copies'
import { currentTurn, turnOf, turnRows } from '../canvas/turns'
import type { Project, Provider, Role } from '../api/types'
import { activeRun, type ConvState } from '../state/applyEvent'
import { type ChatTab, useApp } from '../state/store'
import { AutoReader } from '../voice/useAutoRead'
import { LANGUAGE_TAG, cannotRead, useVoice } from '../voice/voice'
import { ModelPicker } from '../models/ModelPicker'
import { modelName } from '../shell/modelName'
import { NotesPanel } from '../notes/NotesPanel'
import { notebookRun } from '../notes/notesText'
import { RoomTabs, RoomWindow } from '../room/RoomWindow'
import { waitsForYou } from '../room/roomText'
import { WorkTogether } from '../room/WorkTogether'
import { unseenOn } from './attachments'
import { ChannelPanel } from './ChannelPanel'
import { ChatSheet } from './ChatSheet'
import { HEIGHT, NARROWEST, WIDEST, WIDTH_KEY, latestOf, storedWidth, unreadOf, waitingCards } from './chatLine'
import { ofChat } from '../ready/ready'
import { useReady } from '../ready/useReady'
import { nextTopic, titleOf } from '../topics/topics'
import { AskCard } from './AskCard'
import { ChatTodoQueue } from './TodoQueue'
import type { Second } from './Compare'
import { Composer, type ComposerTopic } from './Composer'
import { judgeWordsOf } from './levels'
import { MessageList, type RequestHandlers } from './MessageList'
import { ChatStoryStrip } from './StoryStrip'
import { DecidedLine } from './DecidedLine'
import { toFront } from '../shell/move'
import { testsRun } from '../shell/sections/afterChangeWords'
import { FilesWindow } from '../views/FilesWindow'
import { keyOf, useViews } from '../views/views'

const OPEN_KEY = 'koloni-chat-open'
/** What each tab is, said on hover: the user found Talk and Notes easy to forget. */
const TAB_HINTS = {
  Chat: 'Your conversation with the Orchestrator',
  Talk: 'What the agents say to each other, to hand work on or ask one another',
  Notes: 'A shared notebook: you and the agents leave notes here, kept from message to message and given to new agents',
} as const
/** How much an arrow key moves the open chat's right edge, in px. */
const STEP = 20

function storedOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) !== '0'
  } catch {
    return true
  }
}

function keep(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // the preference just does not persist
  }
}

const tabId = (name: string) => `chat-tab-${name.replaceAll(' ', '-')}`

/** The Workspace button's name, with what waits for you and whether something is new. */
const workspaceLabel = (waiting: number | null, fresher: boolean) =>
  ['Workspace', waiting !== null && `${waiting} waiting`, fresher && 'new'].filter(Boolean).join(' ')

/**
 * The open column's right edge (0.1.4): dragged, or moved with the arrow keys, it makes the chat wider or narrower,
 * and the width is kept. It is written on the stage, whose windows beside the chat follow it (base.css --chat-w).
 */
function WidthEdge({ open }: { open: boolean }) {
  const [width, setWidth] = useState(storedWidth)
  const edge = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  // (By its own element: a child's layout effect runs before the chat's ref is set.)
  const stage = () => edge.current?.closest('.chat')?.parentElement
  useLayoutEffect(() => {
    const at = stage()
    at?.style.setProperty('--chat-open-w', `${width}px`)
    return () => void at?.style.removeProperty('--chat-open-w')
  }, [width])
  /** The widest it may be: 60% of the stage, never over WIDEST nor under NARROWEST (base.css says the same). */
  function widest() {
    const across = stage()?.getBoundingClientRect().width
    return across ? Math.max(NARROWEST, Math.min(WIDEST, Math.floor(across * 0.6))) : WIDEST
  }
  // As its separator tells it. shortcut: measured as it opens and as it is resized, not as the window changes
  // size; upgrade to a ResizeObserver if a reader is ever told a stale figure.
  const [most, setMost] = useState(WIDEST)
  useLayoutEffect(() => setMost(widest()), [open])
  // (a width kept on a wider stage is drawn at this one's most, base.css)
  const across = Math.min(width, most)
  function resize(next: number) {
    const top = widest()
    setMost(top)
    const kept = Math.round(Math.max(NARROWEST, Math.min(top, next)))
    setWidth(kept)
    keep(WIDTH_KEY, String(kept))
  }
  const end = () => void (dragging.current = false)
  return (
    <div
      ref={edge}
      className="chat-edge"
      role="separator"
      aria-orientation="vertical"
      aria-label="Chat width"
      aria-valuemin={NARROWEST}
      aria-valuemax={most}
      aria-valuenow={across}
      tabIndex={0}
      title="Drag, or the arrow keys: wider or narrower"
      onPointerDown={event => {
        if (event.button !== 0) return
        dragging.current = true
        event.currentTarget.setPointerCapture?.(event.pointerId)
      }}
      // Dragged: as wide as from the stage's left edge, where the column starts, to the pointer.
      onPointerMove={event => {
        const left = stage()?.getBoundingClientRect().left
        if (dragging.current && left !== undefined) resize(event.clientX - left)
      }}
      onPointerUp={end}
      onLostPointerCapture={end}
      onKeyDown={event => {
        const by = { ArrowLeft: -STEP, ArrowRight: STEP }[event.key]
        if (!by) return
        event.preventDefault()
        // (From what the stage draws now: `most` may be from a smaller stage, the separator's shortcut.)
        resize(Math.min(width, widest()) + by)
      }}
    />
  )
}

/**
 * The topic the next message goes on with - the one the line above the message box names -, and the one other place it
 * could go: a trigger's topic the user chose to write into while that turn was on screen (looking at a trigger's turn
 * is not that choice, and another turn on screen ends it), or the way back out of it.
 */
function useNextTopic(conv: ConvState | null, shown: string | null) {
  const [into, setInto] = useState<{ turn: string; topic: string } | null>(null)
  // (Ended, not put aside: back on that turn later, it has to be chosen again.)
  if (into && into.turn !== shown) setInto(null)
  const next = conv ? nextTopic(conv, shown, into && into.turn === shown ? into.topic : null) : null
  // Sent to the topic the line names, by its id: never to another the server might take.
  const topicOf = (fresh: boolean) =>
    fresh && next ? { new_topic: true } : next?.kind === 'topic' ? { topic_id: next.topic.id } : {}
  return { topicOf, goesTo: goesToOf(conv, next), other: otherOf(conv, next, shown, setInto), setInto }
}

type Next = ReturnType<typeof nextTopic> | null

/** The topic the line above the message box names. */
function goesToOf(conv: ConvState | null, next: Next): ComposerTopic | 'new' | null {
  if (next?.kind === 'topic' && conv)
    return { title: titleOf(conv, next.topic), scheduled: next.topic.trigger_id !== null }
  return next?.kind === 'new' ? 'new' : null
}

/** The one other place a message could go: into the trigger's topic on screen, or back out of it. */
function otherOf(
  conv: ConvState | null,
  next: Next,
  shown: string | null,
  setInto: (into: { turn: string; topic: string } | null) => void,
) {
  const instead = next?.instead ?? null
  if (!conv || !next) return null
  if (next.kind === 'topic' && next.topic.trigger_id !== null) {
    return {
      label: instead ? `Continue ${titleOf(conv, instead)} instead` : 'Start a new topic instead',
      onPick: () => setInto(null),
    }
  }
  return instead && shown
    ? {
        label: `Write into ${titleOf(conv, instead)} instead`,
        onPick: () => setInto({ turn: shown, topic: instead.id }),
      }
    : null
}

/**
 * The Workspace window (slices 42c, 42d) beside the chat: the project's tree, what agents changed, wrote or showed in it,
 * and the servers they keep running. Opened from its buttons, on a file asked for, or by itself on what comes new.
 * `button`: beside the small box while the chat is closed (`dock`), or at the open chat's foot (`chat`).
 */
function useWorkspace(open: boolean, conv: ConvState | null) {
  const decide = useApp(s => s.decide)
  const filesOpen = useApp(s => s.filesOpen)
  const filesAt = useApp(s => s.filesAt)
  const filesRef = useApp(s => s.filesRef)
  const gitSwitches = useApp(s => s.gitSwitches)
  const openFiles = useApp(s => s.openFiles)
  const project = useApp(s => s.projects.find(p => p.id === s.projectId))
  // What waits for you here, as the Board counts it (38f-2): no number till it is read.
  const waitingHere = useApp(s => waitingIn(s.everywhere, s.conv?.conversation.id))
  const [wide, setWide] = useState(false)
  const { views, fresh, see } = useViews(conv, filesOpen)
  // Its two buttons: at the foot of the open chat, and beside the small box while the chat is closed.
  const footButton = useRef<HTMLButtonElement>(null)
  const filesButton = useRef<HTMLButtonElement>(null)
  // The button that opened it - the chat's, the small box's: the focus goes back there.
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => {
    // (opened, over the other windows)
    const window = filesOpen && document.getElementById('files-window')
    if (window) toFront(window)
  }, [filesOpen, filesAt])
  // What comes new - a file an agent shows or writes to be seen, a server once its address is
  // known - opens Workspace at it, the focus left where it is. Open already, it goes there only if it
  // opened by itself and was not touched since; else it is marked new there.
  const opened = useRef(new Set<string>())
  const byItself = useRef(false)
  const arrived = views.find(
    v => fresh.includes(v.id) && !opened.current.has(v.id) && (v.kind !== 'server' || v.command.preview_url),
  )
  const arrivedKey = arrived && (arrived.kind === 'server' ? `preview:${arrived.id}` : keyOf(arrived.path))
  useEffect(() => {
    if (!arrived || !arrivedKey) return
    opened.current.add(arrived.id)
    if (useApp.getState().filesOpen && !byItself.current) return
    byItself.current = true
    useApp.getState().openFiles(arrivedKey)
  }, [arrived, arrivedKey])
  function closeFiles() {
    byItself.current = false
    useApp.getState().closeFiles()
    setWide(false)
    // Back to the button that opened it; opened by itself, or that one gone or hidden with the chat
    // (the chat's own stays in the page, hidden, while it is closed): the one shown now.
    const was = opener.current
    const back = was?.isConnected && !was.closest('[hidden]') ? was : (open ? footButton : filesButton).current
    opener.current = null
    requestAnimationFrame(() => back?.focus())
  }

  // The Workspace button, where the user put it (42d): not in the top bar nor the open chat's header
  // (19 Oct) - beside the small box while the chat is closed, and open, a small file-shaped one at its
  // foot that glows while something is new or waits (20 Oct). Its number: what waits for you; beside
  // the small box, its dot: something new.
  const fresher = fresh.length > 0 && !filesOpen
  const glows = !filesOpen && (fresh.length > 0 || (waitingHere ?? 0) > 0)
  // (A plain chat has no folder, so no Workspace either.)
  const files = (className: string, own: typeof filesButton, glow: boolean) =>
    project && (
      <button
        ref={own}
        type="button"
        className={`${className}${glow ? ' glow' : ''}`}
        aria-expanded={filesOpen}
        aria-controls="files-window"
        // (named in words, as it reads: "Workspace 2 waiting new")
        aria-label={workspaceLabel(waitingHere, fresher)}
        title="Workspace: the project's files, what agents changed, wrote or showed, and what waits for you"
        onClick={event => {
          if (filesOpen) return closeFiles()
          opener.current = event.currentTarget
          byItself.current = false
          openFiles()
        }}
      >
        <FolderSimple size={14} />
        <span className="dock-label">Workspace</span>
        {waitingHere !== null && <span className="mono dock-count">{waitingHere}</span>}
        {fresher && <span className="view-dot" aria-hidden />}
      </button>
    )
  // (0.1.5: the open chat's is the first under its message box, by its name, glowing while something is new or waits.)
  const button = (where: 'dock' | 'chat') =>
    where === 'dock' ? files('dock-btn', filesButton, false) : files('btn btn-small composer-files', footButton, glows)
  const window = project && (
    <FilesWindow
      // (anew in another conversation: its tabs were that one's; and on another branch, looked at or switched to -
      // its folders were read on the one before)
      key={`${project.id} ${conv?.conversation.id} ${filesRef} ${gitSwitches}`}
      project={project}
      branch={filesRef}
      changes={inProject(conv?.fileChanges ?? [])}
      views={views}
      fresh={fresh}
      agents={conv?.agents ?? []}
      open={filesOpen}
      at={filesAt}
      height={HEIGHT}
      expanded={wide}
      onExpand={() => setWide(!wide)}
      onClose={closeFiles}
      onSeen={see}
      onDecide={decide}
      // (used: what comes new is marked there, not opened over it)
      onTouch={() => (byItself.current = false)}
    />
  )
  return { button, window }
}

/** The closed chat's one line: what is unread, what happened last, what waits for you; a click opens the chat. */
function ClosedLine({
  unread,
  latest,
  waits,
  onOpen,
}: {
  unread: number
  latest: string
  waits: number
  onOpen: () => void
}) {
  return (
    <button type="button" className="chat-line" aria-expanded={false} title="Open the chat" onClick={onOpen}>
      <ChatsCircle size={16} color="var(--accent)" />
      <span className="chat-title">Chat</span>
      {unread > 0 && (
        <>
          <span aria-hidden> · </span>
          <span className="chat-unread">{unread} unread</span>
        </>
      )}
      {latest && (
        <>
          <span aria-hidden> · </span>
          <span className="chat-summary">{latest}</span>
        </>
      )}
      {waits > 0 && (
        <span className="chat-waits">
          {waits} {waits === 1 ? 'waits' : 'wait'} for you
        </span>
      )}
      <CaretUp className="chat-line-open" size={14} aria-hidden />
    </button>
  )
}

/** The open chat's top: its tabs, how many messages it holds, and Hide. */
function ChatTabs({
  tab,
  handoffs,
  notes,
  count,
  onHide,
}: {
  tab: ChatTab
  handoffs: number
  notes: number
  count: number
  onHide: () => void
}) {
  const setTab = useApp(s => s.showChatTab)
  return (
    <div className="chat-top">
      <div className="tabs chat-tabs" role="tablist">
        {(['Chat', 'Talk', 'Notes'] as const).map(name => (
          <button
            key={name}
            type="button"
            role="tab"
            id={tabId(name)}
            aria-controls="chat-tabpanel"
            aria-selected={tab === name}
            className="tab"
            title={TAB_HINTS[name]}
            onClick={() => setTab(name)}
          >
            {name}
            {name === 'Talk' && handoffs > 0 && <span className="mono muted"> {handoffs}</span>}
            {name === 'Notes' && notes > 0 && <span className="mono muted"> {notes}</span>}
          </button>
        ))}
      </div>
      <span className="mono muted chat-count" title="Messages in the chat">
        {count}
      </span>
      <button
        type="button"
        className="icon-btn"
        aria-expanded
        aria-label="Hide chat"
        title="Hide chat"
        onClick={onHide}
      >
        <CaretDown size={14} />
      </button>
    </div>
  )
}

/**
 * Whether the chat is open, and its toggle: opened by the user (the focus into its box, or back to its line), by the
 * canvas's Ready for you (K-bekleyenler: on the tab of what it was asked for), and closed by Esc.
 */
function useChatOpen(conv: ConvState | null, tab: ChatTab) {
  const setTab = useApp(s => s.showChatTab)
  const [open, setOpen] = useState(storedOpen)
  // The canvas's Ready for you asks for the list (K-bekleyenler): the chat opens, if it was closed, on that tab.
  const openAsked = useApp(s => s.chatOpenAsked)
  const [openedFor, setOpenedFor] = useState(openAsked)
  if (openedFor !== openAsked) {
    setOpenedFor(openAsked)
    setOpen(true)
  }
  useEffect(() => {
    if (openAsked) keep(OPEN_KEY, '1')
  }, [openAsked])
  // ...and on what it was asked for in it: the card of Ready for you, the note (K-hazir-satir, K-shared-bagli).
  const at = useApp(s => s.chatAt)
  useEffect(() => {
    if (!at) return
    // (Drawn a frame from now, its tab's turn picked first.)
    // (A place made to take the focus - the Checked section - takes it too: a keyboard's user is there.)
    const frame = requestAnimationFrame(() => {
      const place = document.getElementById(at)
      place?.scrollIntoView({ block: 'center' })
      if (place?.getAttribute('tabindex') === '-1') place.focus({ preventScroll: true })
    })
    return () => cancelAnimationFrame(frame)
  }, [at, openAsked, tab])
  const box = useRef<HTMLElement>(null)
  // Opened or closed by the user just now: the focus goes into the box, or back to its line.
  const moved = useRef(false)
  useEffect(() => {
    if (!moved.current) return
    moved.current = false
    box.current?.querySelector<HTMLElement>(open ? '.composer-input' : '.chat-line')?.focus()
  }, [open])

  function toggle() {
    moved.current = true
    // Opened while a card waits: on the chat, where it is - and, a room's card among them, Ready for you's panel too,
    // which has it (the room's window opens only at your word).
    if (!open && conv && waitingCards(conv) > 0) {
      setTab('Chat')
      if (conv.rooms.some(room => waitsForYou(conv, room))) useApp.getState().showReady(true)
    }
    setOpen(!open)
    keep(OPEN_KEY, open ? '0' : '1')
  }
  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape' && open) toggle()
  }
  return { open, toggle, onKeyDown, box }
}

/** What the chat holds, counted for its top and its closed line: its messages, those unread, Talk's and Notes', the latest. */
function useCounts(conv: ConvState | null, open: boolean) {
  const subAgents = new Set(conv?.agents.filter(a => a.depth > 0).map(a => a.id))
  // A note the lead was handed from the notebook is counted with the notes, not here.
  const inChat =
    conv?.messages.filter(m => m.content && !m.board_post_id && !(m.agent_id && subAgents.has(m.agent_id))) ?? []
  // What the chat held when it was last open, per conversation; one first met closed counts as read.
  // shortcut: kept while the panel is on screen, so a reload or another page starts with nothing unread,
  // and open on another tab counts as read; upgrade to a read mark on the server if the user misses one.
  const [seen, setSeen] = useState<Record<string, ReadonlySet<string>>>({})
  const convId = conv?.conversation.id
  const known = convId ? seen[convId] : undefined
  if (convId && (!known || (open && inChat.some(m => !known.has(m.id)))))
    setSeen({ ...seen, [convId]: new Set(inChat.map(m => m.id)) })
  // The notebook the Notes tab shows: the turn at work, or the last one.
  const notebook = conv && notebookRun(conv)
  return {
    count: inChat.length,
    unread: known ? unreadOf(inChat, known) : 0,
    handoffs: conv?.channelMessages.length ?? 0,
    notes: conv?.boardPosts.filter(p => p.run_id === notebook?.id).length ?? 0,
    latest: conv ? latestOf(conv, inChat) : '',
  }
}

/** What a turn sent now would run on, unless a role has a model of its own; as the model button names it ("provider · model"). */
function chosenOf(providers: Provider[], conv: ConvState | null) {
  const chosen = providers.find(p => p.id === conv?.conversation.provider_id) ?? providers[0]
  const model = (conv?.conversation.provider_id && conv.conversation.model_id) || chosen?.default_model
  return { chosen, first: chosen ? `${chosen.name}${model ? ` · ${modelName(model)}` : ''}` : '' }
}

/** The tab's own content: Notes, Talk, or the chat's messages with every card in them. */
function ChatPane({ conv, tab }: { conv: ConvState | null; tab: ChatTab }) {
  const usage = useApp(s => s.usage)
  const turnUsage = useCallback((runId: string) => usage(null, null, runId), [usage])
  const providers = useApp(s => s.providers)
  const roles = useApp(s => s.roles)
  const prices = useApp(s => s.prices)
  const app = useApp.getState()
  if (tab === 'Notes') return <NotesPanel state={conv} onWrite={app.writeNote} />
  if (!conv) return <div className="msg-list msg-empty muted">Send a message to start.</div>
  if (tab === 'Talk') return <ChannelPanel state={conv} />
  return (
    <MessageList
      state={conv}
      onRemoveQueued={runId => void useApp.getState().cancelRun(runId)}
      {...handlersOf()}
      onDecidePlan={app.decidePlan}
      onOpenDiscussion={id => useApp.getState().openDiscussion(id)}
      onOpenRoom={app.showRoom}
      roles={roles}
      providers={providers}
      onUsage={turnUsage}
      prices={prices}
      onLoadCompare={app.loadCompare}
      onDecideCompare={app.decideCompare}
      onShowTurn={app.showTurn}
      onShowGit={app.showGit}
    />
  )
}

/** The cards' words, as the chat and a room's window take them. */
function handlersOf(): RequestHandlers {
  const app = useApp.getState()
  return {
    onOpenChange: app.openChange,
    onDecide: app.decide,
    onDecideCommand: app.decideCommand,
    onDecideWeb: app.decideWeb,
    onSelectAgent: agentId => useApp.getState().select(`agent:${agentId}`),
    onDecideSpawn: app.decideSpawn,
    onDecideRole: app.decideRole,
    onDecideMerge: app.decideMerge,
    onCheckMerge: app.checkMerge,
    onCommitMerge: app.commitMerge,
    onAnswer: app.answerQuestion,
  }
}

/** The rooms' windows over the canvas, and their tabs at its foot (AC). */
function Rooms({ conv }: { conv: ConvState | null }) {
  const roomWindows = useApp(s => s.roomWindows)
  const roles = useApp(s => s.roles)
  const providers = useApp(s => s.providers)
  if (!conv) return null
  const app = useApp.getState()
  return (
    <>
      <RoomTabs state={conv} windows={roomWindows} onOpen={app.showRoom} />
      {conv.rooms
        .filter(room => roomWindows[room.id] === 'open')
        .map(room => (
          <RoomWindow
            key={room.id}
            state={conv}
            room={room}
            on={handlersOf()}
            roles={roles}
            providers={providers}
            onSay={app.sayInRoom}
            onEnd={app.endRoom}
            onMore={app.giveRoomMore}
            onPause={app.pauseRoom}
            onFollow={app.followRoom}
            onShrink={() => useApp.getState().shrinkRoom(room.id)}
            onClose={() => useApp.getState().closeRoom(room.id)}
          />
        ))}
    </>
  )
}

/** Another way to start a turn, under More: a room ("Work together…"), where there are roles to fill it. */
function roomStarter(
  conv: ConvState | null,
  roles: Role[],
  providers: Provider[],
  project: Project | undefined,
): ReactNode {
  if (!conv || roles.length === 0) return null
  // (The project's: every chat of it follows them - tek-ev.)
  const limits = project
    ? { posts: project.room_posts, tokens: project.room_tokens, minutes: project.room_minutes }
    : {
        posts: conv.conversation.room_posts,
        tokens: conv.conversation.room_tokens,
        minutes: conv.conversation.room_minutes,
      }
  return (
    <WorkTogether
      // (What was written in it is not carried to another conversation.)
      key={`room-${conv.conversation.id}`}
      roles={roles}
      providers={providers}
      limits={limits}
      busy={activeRun(conv) !== null}
      onOpen={useApp.getState().openRoom}
      onModels={useApp.getState().providerModels}
    />
  )
}

/** The conversation's model: its button, where there is a provider to choose from. */
function modelPicker(conv: ConvState | null, providers: Provider[], roles: Role[]): ReactNode {
  if (providers.length === 0) return null
  const app = useApp.getState()
  return (
    <ModelPicker
      key={conv?.conversation.id ?? 'none'}
      providers={providers}
      providerId={conv?.conversation.provider_id ?? null}
      modelId={conv?.conversation.model_id ?? null}
      leadAuto={conv?.conversation.lead_auto ?? false}
      leadEffort={conv?.conversation.lead_effort ?? null}
      onSave={app.setModelChoice}
      onModels={app.providerModels}
      onFacts={app.modelFacts}
      lead={roles.find(role => role.name === 'Lead')}
      hasHistory={(conv?.runs.length ?? 0) > 0}
      onRouting={(id, models) => app.saveProvider(id, { models })}
      onOffers={app.readOffers}
    />
  )
}

export function ChatPanel() {
  const conv = useApp(s => s.conv)
  const providers = useApp(s => s.providers)
  const roles = useApp(s => s.roles)
  const turnId = useApp(s => s.turnId)
  const tab = useApp(s => s.chatTab)
  // The turn on screen: the one picked, else the newest - not the canvas's front (slice 107), so
  // the next message goes on with the topic last written in, whatever work the canvas shows.
  const shown = useMemo(
    () => (conv ? currentTurn(turnRows(conv), turnId && turnOf(conv, turnId)) : null),
    [conv, turnId],
  )
  const { topicOf, goesTo, other, setInto } = useNextTopic(conv, shown)
  const location = useApp(s => s.projects.find(p => p.id === s.projectId)?.exec_location)
  const { open, toggle, onKeyDown, box } = useChatOpen(conv, tab)
  const workspace = useWorkspace(open, conv)
  const project = useApp(s => s.projects.find(p => p.id === s.projectId))
  const { count, unread, handoffs, notes, latest } = useCounts(conv, open)
  const { chosen, first } = chosenOf(providers, conv)
  const waits = conv ? waitingCards(conv) : 0
  // What waits for you anywhere but here: To-do, Memory, the night, other chats (tek-ev decision 2).
  const ready = useReady()
  const elsewhere = ready.length - ofChat(ready, conv?.conversation.id).length
  const app = useApp.getState()
  // Closed, the chat is a small box in its corner; open, a column the stage's height at its left edge (0.1.4).
  const chat = (
    <section ref={box} className={open ? 'chat' : 'chat chat-closed'} aria-label="Chat" onKeyDown={onKeyDown}>
      {!open && <ClosedLine unread={unread} latest={latest} waits={waits} onOpen={toggle} />}
      {/* Hidden, not gone, while closed: an answer, a draft or a choice half made in it stays. */}
      <div className="chat-body" hidden={!open}>
        <WidthEdge open={open} />
        <ChatTabs tab={tab} handoffs={handoffs} notes={notes} count={count} onHide={toggle} />
        <ChatStoryStrip conv={conv} tab={tab} />
        {/* Decided for you, in one line: Ready for you says each (karar defteri). */}
        <DecidedLine conv={conv} />
        {/* The tab's own content scrolls in what the tabs and the message box leave (base.css .chat-pane). */}
        {/* (B-142: its tabs' panel, by name, for a screen reader) */}
        <div className="chat-pane" role="tabpanel" id="chat-tabpanel" aria-labelledby={tabId(tab)}>
          <ChatPane conv={conv} tab={tab} />
        </div>
      </div>
      {/* The Orchestrator's question, just over the message box (0.1.5). */}
      <AskCard conv={conv} open={open} tab={tab} onAnswer={app.answerQuestion} />
      {/* 0.1.8: the chat's To-do queue, over the box: what waits, and that your message goes first. */}
      <ChatTodoQueue conv={conv} open={open} />
      {/* Open, under the chat; closed, the small box's one line - the same box, the same draft. */}
      <Composer
        compact={!open}
        unseen={unseenOn(chosen)}
        running={conv !== null && activeRun(conv) !== null}
        permissionMode={conv?.conversation.permission_mode ?? 'ask'}
        onSend={async (content, fresh, overBudget, files) => {
          // Auto-read of a short summary: the Lead is asked for the line to say, in the language and manner chosen.
          await useApp
            .getState()
            .send(content, { ...topicOf(fresh), ...spokenOf(), ...(overBudget && { over_budget: true }), ...files })
          // Writing into a trigger's topic was chosen for that one message.
          setInto(null)
        }}
        topic={goesTo}
        other={other}
        scope={conv?.conversation.id}
        onStop={() => void useApp.getState().stop()}
        onPermissionMode={mode => void useApp.getState().setPermissionMode(mode)}
        planFirst={conv?.conversation.plan_first}
        onPlanFirst={on => void useApp.getState().setPlanFirst(on)}
        judge={project?.full_auto_judge}
        judgeWords={judgeWordsOf(project)}
        judgeRisky={project?.judge_risky}
        onJudge={
          conv?.conversation.project_id
            ? on => void useApp.getState().saveProjectSettings({ full_auto_judge: on })
            : undefined
        }
        checks={
          conv && project
            ? {
                chat: conv.conversation.after_change,
                project: project.after_change,
                command: testsRun(project, false),
                rounds: project.fix_rounds,
                onChange: value => void useApp.getState().setAfterChange(value),
              }
            : undefined
        }
        location={location}
        // This chat's own settings; what it takes from its project is the project's, in Settings (tek-ev).
        sheet={conv && <ChatSheet sheet />}
        compare={compareOf(providers, first, topicOf, () => setInto(null))}
        workspace={workspace.button('chat')}
        // What waits for you outside this chat (tek-ev §1): quiet words under the box, which open Ready for you.
        waits={{ count: elsewhere, onOpen: () => useApp.getState().showReady(true) }}
        beside={roomStarter(conv, roles, providers, project)}
        model={modelPicker(conv, providers, roles)}
      />
    </section>
  )
  return (
    <>
      {chat}
      <AutoReader />
      {!open && <div className="chat-dock">{workspace.button('dock')}</div>}
      <Rooms conv={conv} />
      {workspace.window}
    </>
  )
}

/** Auto-read of a short summary: the Lead is asked for the line to say, in the language and manner chosen. */
function spokenOf() {
  const { autoRead, mode, language, style } = useVoice.getState()
  if (!autoRead || mode !== 'summary' || cannotRead() || !LANGUAGE_TAG.test(language)) return {}
  return { spoken: { language, ...(style.trim() ? { style: style.trim() } : {}) } }
}

/** Compare (slice 54): the message to two models side by side, the conversation's first; none without a provider. */
function compareOf(providers: Provider[], first: string, topicOf: (fresh: boolean) => object, done: () => void) {
  if (providers.length === 0) return undefined
  return {
    providers,
    first,
    onCompare: async (content: string, second: Second, fresh: boolean, overBudget?: boolean) => {
      await useApp.getState().compare(content, second, { ...topicOf(fresh), ...(overBudget && { over_budget: true }) })
      done()
    },
    onModels: useApp.getState().providerModels,
  }
}
