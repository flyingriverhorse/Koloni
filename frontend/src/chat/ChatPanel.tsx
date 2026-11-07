import { CaretDown, CaretUp, ChatsCircle, DotsSixVertical, FileText, FolderSimple } from '@phosphor-icons/react'
import { type KeyboardEvent, type PointerEvent, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { waitingIn } from '../board/waiting'
import { inProject } from '../changes/copies'
import { currentTurn, turnOf, turnRows } from '../canvas/turns'
import { activeRun } from '../state/applyEvent'
import { useApp } from '../state/store'
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
import { HEIGHT_KEY, LEAST, MOST, TOP, latestOf, storedHeight, unreadOf, waitingCards } from './chatLine'
import { ofChat } from '../ready/ready'
import { useReady } from '../ready/useReady'
import { nextTopic, titleOf } from '../topics/topics'
import { Composer, type ComposerTopic } from './Composer'
import { MessageList, type RequestHandlers } from './MessageList'
import { toFront, useMove } from '../shell/move'
import { FilesWindow } from '../views/FilesWindow'
import { keyOf, useViews } from '../views/views'

const OPEN_KEY = 'koloni-chat-open'
/** What each tab is, said on hover: the user found Talk and Notes easy to forget. */
const TAB_HINTS = {
  Chat: 'Your conversation with the Orchestrator',
  Talk: 'What the agents say to each other, to hand work on or ask one another',
  Notes: 'A shared notebook: you and the agents leave notes here, kept from message to message and given to new agents',
} as const
/** How much a key moves the chat's top edge, as a share of the canvas. */
const STEP = 0.05
/** The least the open box is, in pixels: its tabs, a message and the message box (base.css). */
const FLOOR = 260

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

export function ChatPanel() {
  const conv = useApp(s => s.conv)
  const send = useApp(s => s.send)
  const stop = useApp(s => s.stop)
  const cancelRun = useApp(s => s.cancelRun)
  const setPermissionMode = useApp(s => s.setPermissionMode)
  const openChange = useApp(s => s.openChange)
  const decide = useApp(s => s.decide)
  const decideCommand = useApp(s => s.decideCommand)
  const select = useApp(s => s.select)
  const decideSpawn = useApp(s => s.decideSpawn)
  const decideRole = useApp(s => s.decideRole)
  const answerQuestion = useApp(s => s.answerQuestion)
  const providers = useApp(s => s.providers)
  const roles = useApp(s => s.roles)
  const prices = useApp(s => s.prices)
  const usage = useApp(s => s.usage)
  const turnUsage = useCallback((runId: string) => usage(null, null, runId), [usage])
  const setModelChoice = useApp(s => s.setModelChoice)
  const turnId = useApp(s => s.turnId)
  const tab = useApp(s => s.chatTab)
  const setTab = useApp(s => s.showChatTab)
  // The turn on screen: the one picked, else the newest - not the canvas's front (slice 107), so
  // the next message goes on with the topic last written in, whatever work the canvas shows.
  const shown = useMemo(() => (conv ? currentTurn(turnRows(conv), turnId && turnOf(conv, turnId)) : null), [conv, turnId])
  // The rooms' windows over the canvas, and their tabs at its foot (AC).
  const roomWindows = useApp(s => s.roomWindows)
  // A trigger's topic the user chose to write into, while that turn was on screen: looking
  // at a trigger's turn is not that choice, and another turn on screen ends it.
  const [into, setInto] = useState<{ turn: string; topic: string } | null>(null)
  // (Ended, not put aside: back on that turn later, it has to be chosen again.)
  if (into && into.turn !== shown) setInto(null)
  // The topic the next message goes on with: the one the line above the message box names.
  const next = conv ? nextTopic(conv, shown, into && into.turn === shown ? into.topic : null) : null
  // Sent to the topic the line names, by its id: never to another the server might take.
  const topicOf = (fresh: boolean) => (fresh && next ? { new_topic: true } : next?.kind === 'topic' ? { topic_id: next.topic.id } : {})
  const goesTo: ComposerTopic | 'new' | null =
    next?.kind === 'topic' && conv
      ? { title: titleOf(conv, next.topic), scheduled: next.topic.trigger_id !== null }
      : next?.kind === 'new'
        ? 'new'
        : null
  // The one other place it could go: into the trigger's topic on screen, or back out of it.
  const instead = next?.instead ?? null
  const other =
    !conv || !next
      ? null
      : next.kind === 'topic' && next.topic.trigger_id !== null
        ? { label: instead ? `Continue ${titleOf(conv, instead)} instead` : 'Start a new topic instead', onPick: () => setInto(null) }
        : instead && shown
          ? { label: `Write into ${titleOf(conv, instead)} instead`, onPick: () => setInto({ turn: shown, topic: instead.id }) }
          : null
  const location = useApp(s => s.projects.find(p => p.id === s.projectId)?.exec_location)
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
    const frame = requestAnimationFrame(() => document.getElementById(at)?.scrollIntoView({ block: 'center' }))
    return () => cancelAnimationFrame(frame)
  }, [at, openAsked, tab])
  const [height, setHeight] = useState(storedHeight)
  const box = useRef<HTMLElement>(null)
  // Opened or closed by the user just now: the focus goes into the box, or back to its line.
  const moved = useRef(false)
  useEffect(() => {
    if (!moved.current) return
    moved.current = false
    box.current?.querySelector<HTMLElement>(open ? '.composer-input' : '.chat-line')?.focus()
  }, [open])
  // The open chat, moved about the canvas by its header (slice 38e).
  const move = useMove('koloni-chat-spot', box)

  // The Workspace window (slices 42c, 42d) beside the chat: the project's tree, what agents changed, wrote or
  // showed in it, and the servers they keep running. Opened from its buttons, on a file asked for,
  // or by itself on what comes new.
  const filesOpen = useApp(s => s.filesOpen)
  const filesAt = useApp(s => s.filesAt)
  const filesRef = useApp(s => s.filesRef)
  const gitBranch = useApp(s => s.gitBranch)
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
  const arrived = views.find(v => fresh.includes(v.id) && !opened.current.has(v.id) && (v.kind !== 'server' || v.command.preview_url))
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
  /** The tallest it may be: TOP px left above it, standing 14 px off the canvas's foot (base.css says the same). */
  function tallest() {
    const stage = box.current?.parentElement?.getBoundingClientRect().height
    return stage ? Math.floor(((stage - TOP - 14) / stage) * 100) / 100 : MOST
  }
  // As its separator tells it. shortcut: measured as it opens and as it is resized, not as the
  // window changes size; upgrade to a ResizeObserver if a reader is ever told a stale figure.
  const [most, setMost] = useState(MOST)
  useLayoutEffect(() => setMost(tallest()), [open])
  function resize(share: number) {
    // Never under what the box needs (FLOOR px), never over the canvas less TOP px.
    const stage = box.current?.parentElement?.getBoundingClientRect().height
    const most = tallest()
    setMost(most)
    const least = stage ? Math.min(most, Math.max(LEAST, FLOOR / stage)) : LEAST
    const next = Math.round(Math.min(most, Math.max(least, share)) * 100) / 100
    setHeight(next)
    keep(HEIGHT_KEY, String(next))
  }
  // Dragged from its top edge: as tall as from the pointer down to the canvas's bottom.
  function drag(event: PointerEvent<HTMLDivElement>) {
    if (!event.currentTarget.hasPointerCapture?.(event.pointerId)) return
    const stage = box.current?.parentElement?.getBoundingClientRect()
    const bottom = box.current?.getBoundingClientRect().bottom
    if (stage?.height && bottom) resize((bottom - event.clientY) / stage.height)
  }
  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Escape' && open) toggle()
  }

  const subAgents = new Set(conv?.agents.filter(a => a.depth > 0).map(a => a.id))
  // A note the lead was handed from the notebook is counted with the notes, not here.
  const inChat = conv?.messages.filter(m => m.content && !m.board_post_id && !(m.agent_id && subAgents.has(m.agent_id))) ?? []
  const count = inChat.length
  // What the chat held when it was last open, per conversation; one first met closed counts as read.
  // shortcut: kept while the panel is on screen, so a reload or another page starts with nothing unread,
  // and open on another tab counts as read; upgrade to a read mark on the server if the user misses one.
  const [seen, setSeen] = useState<Record<string, ReadonlySet<string>>>({})
  const convId = conv?.conversation.id
  const known = convId ? seen[convId] : undefined
  if (convId && (!known || (open && inChat.some(m => !known.has(m.id))))) setSeen({ ...seen, [convId]: new Set(inChat.map(m => m.id)) })
  const unread = known ? unreadOf(inChat, known) : 0
  const handoffs = conv?.channelMessages.length ?? 0
  // The notebook the Notes tab shows: the turn at work, or the last one.
  const notebook = conv && notebookRun(conv)
  const notes = conv?.boardPosts.filter(p => p.run_id === notebook?.id).length ?? 0
  // What a turn sent now would run on, unless a role has a model of its own.
  const chosen = providers.find(p => p.id === conv?.conversation.provider_id) ?? providers[0]
  // As the model button names it: the first of two models compared.
  const chosenModel = (conv?.conversation.provider_id && conv.conversation.model_id) || chosen?.default_model
  const first = chosen ? `${chosen.name}${chosenModel ? ` · ${modelName(chosenModel)}` : ''}` : ''

  const waits = conv ? waitingCards(conv) : 0
  // What waits for you anywhere but here: To-do, Memory, the night, other chats (tek-ev decision 2).
  const ready = useReady()
  const elsewhere = ready.length - ofChat(ready, conv?.conversation.id).length
  // The cards' words, as a room's window takes them.
  const on: RequestHandlers = {
    onOpenChange: openChange,
    onDecide: decide,
    onDecideCommand: decideCommand,
    onDecideWeb: useApp.getState().decideWeb,
    onSelectAgent: agentId => select(`agent:${agentId}`),
    onDecideSpawn: decideSpawn,
    onDecideRole: decideRole,
    onDecideMerge: useApp.getState().decideMerge,
    onCheckMerge: useApp.getState().checkMerge,
    onCommitMerge: useApp.getState().commitMerge,
    onAnswer: answerQuestion,
  }
  const latest = conv ? latestOf(conv, inChat) : ''
  // The Workspace button, where the user put it (42d): not in the top bar nor the open chat's header
  // (19 Oct) - beside the small box while the chat is closed, and open, a small file-shaped one at its
  // foot that glows while something is new or waits (20 Oct). Its number: what waits for you; beside
  // the small box, its dot: something new.
  const fresher = fresh.length > 0 && !filesOpen
  const glows = !filesOpen && (fresh.length > 0 || (waitingHere ?? 0) > 0)
  // (A plain chat has no folder, so no Workspace either.)
  const files = (className: string, own: typeof filesButton, label: boolean) => project && (
    <button
      ref={own}
      type="button"
      className={`${className}${!label && glows ? ' glow' : ''}`}
      aria-expanded={filesOpen}
      aria-controls="files-window"
      // (named in words, as it reads: "Workspace 2 waiting new")
      aria-label={['Workspace', waitingHere !== null && `${waitingHere} waiting`, fresher && 'new'].filter(Boolean).join(' ')}
      title="Workspace: the project's files, what agents changed, wrote or showed, and what waits for you"
      onClick={event => {
        if (filesOpen) return closeFiles()
        opener.current = event.currentTarget
        byItself.current = false
        openFiles()
      }}
    >
      {label ? <FolderSimple size={14} /> : <FileText size={16} />}
      {label && <span className="dock-label">Workspace</span>}
      {/* (the small one shows a number only when something waits) */}
      {waitingHere !== null && (label || waitingHere > 0) && <span className="mono dock-count">{waitingHere}</span>}
      {label && fresher && <span className="view-dot" aria-hidden />}
    </button>
  )
  const dock = <div className="chat-dock">{files('dock-btn', filesButton, true)}</div>
  // Closed, the chat is a small box in its corner; open, it is where it was moved to.
  const chat = (
    <section
      ref={box}
      className={open ? `chat${move.moved ? ' moved' : ''}` : 'chat chat-closed'}
      aria-label="Chat"
      style={open ? { ['--h' as string]: `${height * 100}%`, ...move.style } : undefined}
      onKeyDown={onKeyDown}
    >
      {!open && (
        <button type="button" className="chat-line" aria-expanded={false} title="Open the chat" onClick={toggle}>
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
          {waits > 0 && <span className="chat-waits">{waits} {waits === 1 ? 'waits' : 'wait'} for you</span>}
          <CaretUp className="chat-line-open" size={14} aria-hidden />
        </button>
      )}
      {/* Hidden, not gone, while closed: an answer, a draft or a choice half made in it stays. */}
      <div className="chat-body" hidden={!open}>
        <div
          className="chat-edge"
          role="separator"
          aria-orientation="horizontal"
          aria-label="Chat height"
          aria-valuemin={LEAST * 100}
          aria-valuemax={Math.round(most * 100)}
          aria-valuenow={Math.round(Math.min(height, most) * 100)}
          tabIndex={0}
          onPointerDown={event => event.currentTarget.setPointerCapture?.(event.pointerId)}
          onPointerMove={drag}
          onKeyDown={event => {
            const by = event.key === 'ArrowUp' ? STEP : event.key === 'ArrowDown' ? -STEP : 0
            if (by) {
              event.preventDefault()
              resize(height + by)
            }
          }}
        />
        <div className="chat-top" {...move.header}>
          <span className="move-grip" aria-label="Move chat" title="Move chat: drag, or the arrow keys; a double click or Enter puts it back" {...move.handle}>
            <DotsSixVertical size={14} />
          </span>
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
          <button type="button" className="icon-btn" aria-expanded aria-label="Hide chat" title="Hide chat" onClick={toggle}>
            <CaretDown size={14} />
          </button>
        </div>
        {/* The tab's own content scrolls in what the tabs and the message box leave (base.css .chat-pane). */}
        {/* (B-142: its tabs' panel, by name, for a screen reader) */}
        <div className="chat-pane" role="tabpanel" id="chat-tabpanel" aria-labelledby={tabId(tab)}>
        {tab === 'Notes' ? (
          <NotesPanel state={conv} onWrite={useApp.getState().writeNote} />
        ) : tab === 'Talk' && conv ? (
          <ChannelPanel state={conv} />
        ) : conv ? (
          <MessageList
            state={conv}
            onRemoveQueued={runId => void cancelRun(runId)}
            onOpenChange={openChange}
            onDecide={decide}
            onDecideCommand={decideCommand}
            onDecideWeb={useApp.getState().decideWeb}
            onSelectAgent={agentId => select(`agent:${agentId}`)}
            onDecideSpawn={decideSpawn}
            onDecideRole={decideRole}
            onDecidePlan={useApp.getState().decidePlan}
            onDecideMerge={useApp.getState().decideMerge}
            onCheckMerge={useApp.getState().checkMerge}
            onCommitMerge={useApp.getState().commitMerge}
            onAnswer={answerQuestion}
            onOpenDiscussion={id => useApp.getState().openDiscussion(id)}
            onOpenRoom={useApp.getState().showRoom}
            onAllowInTrigger={useApp.getState().allowInTrigger}
            roles={roles}
            providers={providers}
            onUsage={turnUsage}
            prices={prices}
            onLoadCompare={useApp.getState().loadCompare}
            onDecideCompare={useApp.getState().decideCompare}
            onShowTurn={useApp.getState().showTurn}
            onShowGit={useApp.getState().showGit}
          />
        ) : (
          <div className="msg-list msg-empty muted">Send a message to start.</div>
        )}
        </div>
        {/* What waits outside this chat (tek-ev §1): one line, which opens Ready for you's panel. */}
        {elsewhere > 0 && (
          <div className="ready-line">
            <span className="dot" aria-hidden />
            <span>{elsewhere} more {elsewhere === 1 ? 'waits' : 'wait'} elsewhere</span>
            <button type="button" className="btn btn-small" aria-label={`Open Ready for you: ${elsewhere} more wait elsewhere`} onClick={() => useApp.getState().showReady(true)}>
              Open →
            </button>
          </div>
        )}
      </div>
      {/* Open, under the chat; closed, the small box's one line - the same box, the same draft. */}
      <Composer
        compact={!open}
        unseen={unseenOn(chosen)}
        running={conv ? activeRun(conv) !== null : false}
        permissionMode={conv?.conversation.permission_mode ?? 'ask'}
        onSend={async (content, fresh, overBudget, files) => {
          const where = topicOf(fresh)
          // Auto-read of a short summary: the Lead is asked for the line to say, in the language and manner chosen.
          const { autoRead, mode, language, style } = useVoice.getState()
          const spoken = autoRead && mode === 'summary' && !cannotRead() && LANGUAGE_TAG.test(language) ? { spoken: { language, ...(style.trim() ? { style: style.trim() } : {}) } } : {}
          await send(content, { ...where, ...spoken, ...(overBudget && { over_budget: true }), ...files })
          // Writing into a trigger's topic was chosen for that one message.
          setInto(null)
        }}
        topic={goesTo}
        other={other}
        scope={conv?.conversation.id}
        onStop={() => void stop()}
        onPermissionMode={mode => void setPermissionMode(mode)}
        planFirst={conv?.conversation.plan_first ?? false}
        onPlanFirst={on => void useApp.getState().setPlanFirst(on)}
        location={location}
        // This chat's own settings; what it takes from its project is the project's, in Settings (tek-ev).
        sheet={conv && <ChatSheet sheet />}
        compare={
          providers.length > 0
            ? {
                providers,
                first,
                onCompare: async (content, second, fresh, overBudget) => {
                  await useApp.getState().compare(content, second, { ...topicOf(fresh), ...(overBudget && { over_budget: true }) })
                  setInto(null)
                },
                onModels: useApp.getState().providerModels,
              }
            : undefined
        }
        workspace={files('icon-btn composer-files', footButton, false)}
        beside={conv && roles.length > 0 && (
          <WorkTogether
            // (What was written in it is not carried to another conversation.)
            key={`room-${conv.conversation.id}`}
            roles={roles}
            providers={providers}
            // (The project's: every chat of it follows them - tek-ev.)
            limits={{
              posts: project ? project.room_posts : conv.conversation.room_posts,
              tokens: project ? project.room_tokens : conv.conversation.room_tokens,
              minutes: project ? project.room_minutes : conv.conversation.room_minutes,
            }}
            busy={activeRun(conv) !== null}
            onOpen={useApp.getState().openRoom}
            onModels={useApp.getState().providerModels}
          />
        )}
        model={
          providers.length > 0 && (
            <ModelPicker
              key={conv?.conversation.id ?? 'none'}
              providers={providers}
              providerId={conv?.conversation.provider_id ?? null}
              modelId={conv?.conversation.model_id ?? null}
              leadAuto={conv?.conversation.lead_auto ?? false}
              leadEffort={conv?.conversation.lead_effort ?? null}
              onSave={setModelChoice}
              onModels={useApp.getState().providerModels}
              onFacts={useApp.getState().modelFacts}
              lead={roles.find(role => role.name === 'Lead')}
              hasHistory={(conv?.runs.length ?? 0) > 0}
            />
          )
        }
      />
    </section>
  )
  return (
    <>
      {chat}
      <AutoReader />
      {!open && dock}
      {conv && <RoomTabs state={conv} windows={roomWindows} onOpen={useApp.getState().showRoom} />}
      {conv?.rooms
        .filter(room => roomWindows[room.id] === 'open')
        .map(room => (
          <RoomWindow
            key={room.id}
            state={conv}
            room={room}
            on={on}
            roles={roles}
            providers={providers}
            onSay={useApp.getState().sayInRoom}
            onEnd={useApp.getState().endRoom}
            onMore={useApp.getState().giveRoomMore}
            onPause={useApp.getState().pauseRoom}
            onFollow={useApp.getState().followRoom}
            onShrink={() => useApp.getState().shrinkRoom(room.id)}
            onClose={() => useApp.getState().closeRoom(room.id)}
          />
        ))}
      {project && (
        <FilesWindow
          // (anew in another conversation: its tabs were that one's; and on another branch, looked at or switched to -
          // its folders were read on the one before)
          key={`${project.id} ${conv?.conversation.id} ${filesRef} ${gitBranch}`}
          project={project}
          branch={filesRef}
          changes={inProject(conv?.fileChanges ?? [])}
          views={views}
          fresh={fresh}
          agents={conv?.agents ?? []}
          open={filesOpen}
          at={filesAt}
          height={height}
          expanded={wide}
          onExpand={() => setWide(!wide)}
          onClose={closeFiles}
          onSeen={see}
          onDecide={decide}
          // (used: what comes new is marked there, not opened over it)
          onTouch={() => (byItself.current = false)}
        />
      )}
    </>
  )
}
