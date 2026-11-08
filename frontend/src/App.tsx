import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { download, keyRefused } from './api/client'
import { AgentsPage } from './agents/AgentsPage'
import { type AgentAsks, AgentWindow } from './agents/AgentWindow'
import { ChatTeams } from './agents/ChatTeams'
import { AwayStatus } from './backlog/Away'
import { BacklogPage } from './backlog/BacklogPage'
import { BoardPage } from './board/BoardPage'
import { ConflictStrip } from './board/ConflictStrip'
import { QuestionCard } from './agents/QuestionCard'
import { RoleApproval } from './agents/RoleApproval'
import { SpawnApproval } from './agents/SpawnApproval'
import { staysOn } from './agents/staysOn'
import { keptNote, turnTeams } from './agents/teamRun'
import { CanvasView } from './canvas/CanvasView'
import { canContinue } from './changes/copies'
import { DiscussionWindow } from './discussion/DiscussionWindow'
import { ChangeActions } from './changes/ChangeActions'
import { MergeCard } from './changes/MergeCard'
import { CommandApproval } from './commands/CommandApproval'
import { DiffView } from './changes/DiffView'
import { AskAboutThis } from './chat/AskAboutThis'
import { ChatPanel } from './chat/ChatPanel'
import { Inspector } from './inspector/Inspector'
import { ConversationList } from './shell/ConversationList'
import { ModelBanner } from './shell/ModelBanner'
import { KnowledgePage } from './knowledge/KnowledgePage'
import { MemoryPage } from './memory/MemoryPage'
import { TriggersPage } from './triggers/TriggersPage'
import { TriggersStatus } from './triggers/TriggersStatus'
import { ModelsPage } from './models/ModelsPage'
import { FirstSteps } from './shell/FirstSteps'
import { FolderButton } from './shell/FolderButton'
import { Help } from './shell/Help'
import { OpenChats } from './shell/OpenChats'
import { kept, tabOf } from './shell/openTabs'
import { type Place, Palette } from './shell/Palette'
import { PageGuard } from './shell/PageGuard'
import { HoldStatus } from './shell/HoldStatus'
import { SECTIONS } from './shell/ProjectSettings'
import { APP_SECTIONS, Settings } from './shell/Settings'
import { Rail, type View } from './shell/Rail'
import { RunStatus } from './shell/RunStatus'
import { Toasts } from './shell/Toasts'
import { TopBar } from './shell/TopBar'
import { GitStatus } from './shell/GitStatus'
import { frontOf } from './shell/move'
import { useApp } from './state/store'
import { getStoredTheme, toggleTheme, type Theme } from './theme/theme'
import { ToolsPage } from './tools/ToolsPage'
import { continuesFrom } from './topics/topics'
import { UsagePage } from './usage/UsagePage'
import { BudgetPill } from './usage/Budget'
import { TodayView } from './usage/TodayView'
import type { Near } from './usage/limitsText'
import { PlanUse } from './usage/PlanUse'
import { ReadyPage, ReadyPanel } from './ready/ReadyViews'
import { useReady } from './ready/useReady'
import { READY_PANEL } from './ready/ready'
import { decidedOf, waitingId } from './chat/waiting'

const HEALTH_POLL_MS = 15000
// (A hash has no order: which of the two is newer is not known, so all three steps are said.)
const UPDATED = 'KOLONİ was updated: the page and the server differ. Build the page (npm run build), restart KOLONİ, then reload.'
const REBUILT = "KOLONİ's page was rebuilt: reload to use it."
/** A build's own mark: the entry script its index.html names, hashed by Vite anew each build (the dev server's never changes). */
const entryOf = (page: Document) => page.querySelector('script[type="module"][src]')?.getAttribute('src') ?? null
/** Whether the server now serves another build of the page than this one; false where that cannot be told. */
async function builtAnew(): Promise<boolean> {
  const mine = entryOf(document)
  if (!mine) return false
  try {
    const served = await fetch('/', { cache: 'no-store' })
    const theirs = served.ok ? entryOf(new DOMParser().parseFromString(await served.text(), 'text/html')) : null
    return theirs !== null && theirs !== mine
  } catch {
    return false // not reached this time: asked again with the next health reading
  }
}
// As the Board's own page reads it: the events of the project's other conversations do not come here.
const BOARD_POLL_MS = 5000
// The Agents page reads what each role would run on in a new conversation, with the levels each model takes: one function, read once per change of roles.
const roleModelsNow = () => useApp.getState().roleModels(null, true)
// The Models page reads what was used in every project: an API key's spend today, a model's last 30 days.
const usageEverywhere = (since: string) => useApp.getState().usage(null, since)
// The top bar's plan use: only the last reading, never read afresh (Claude Code's would run a turn).
const lastLimits = (providerId: string) => useApp.getState().limits(providerId, false)
/** The top bar's readings, of the open chat's providers: not known while the chat the list leads to is read, nor from another's. */
const readingsOf = ({ inUse, conv, conversations }: ReturnType<typeof useApp.getState>) =>
  inUse?.of === (conv?.conversation.id ?? null) && (conv || !conversations.some(c => !c.archived_at)) ? inUse.readings : null
/** ...and the roles of it that cannot run, with them. */
const cannotOf = (state: ReturnType<typeof useApp.getState>) => (readingsOf(state) ? state.inUse?.cannot : undefined)

/** The rail's pages, by their pages' names and the rail's word where it is another: what Ctrl+K finds. */
const PAGES: [View, string][] = [
  ['canvas', 'Canvas'],
  ['conversations', 'Chats (Conversations)'],
  ['ready', 'Ready for you'],
  ['board', 'Board'],
  ['backlog', 'To-do'],
  ['agents', 'Agents'],
  ['models', 'Models'],
  ['tools', 'Tools'],
  ['memory', 'Memory'],
  ['knowledge', 'Knowledge'],
  ['triggers', 'Triggers'],
  ['usage', 'Usage'],
]

export function App() {
  const refused = useSyncExternalStore(keyRefused.subscribe, keyRefused.now)
  const ready = useApp(s => s.ready)
  const loadError = useApp(s => s.loadError)
  const projects = useApp(s => s.projects)
  const projectId = useApp(s => s.projectId)
  const conversations = useApp(s => s.conversations)
  const roles = useApp(s => s.roles)
  const teams = useApp(s => s.teams)
  const categories = useApp(s => s.categories)
  const skills = useApp(s => s.skills)
  const providers = useApp(s => s.providers)
  const conv = useApp(s => s.conv)
  const tabs = useApp(s => s.tabs)
  const health = useApp(s => s.health)
  const barReadings = useApp(readingsOf)
  const barCannot = useApp(cannotOf)
  const connection = useApp(s => s.connection)
  const selectedNodeId = useApp(s => s.selectedNodeId)
  const agentWindowId = useApp(s => s.agentWindowId)
  const discussionWindowId = useApp(s => s.discussionWindowId)
  // The room whose window is open over the canvas, if any (AC): the canvas keeps clear of it too.
  const roomWindowId = useApp(s => Object.keys(s.roomWindows).find(id => s.roomWindows[id] === 'open') ?? null)
  const select = useApp(s => s.select)
  const turnId = useApp(s => s.turnId)
  const openChange = useApp(s => s.openChange)
  const decide = useApp(s => s.decide)
  const memory = useApp(s => s.memory)
  const memoryError = useApp(s => s.memoryError)
  const knowledge = useApp(s => s.knowledge)
  const knowledgeError = useApp(s => s.knowledgeError)
  const triggers = useApp(s => s.triggers)
  const triggersError = useApp(s => s.triggersError)
  const triggerChanges = useApp(s => s.triggerChanges)
  const triggersPaused = useApp(s => s.triggersPaused)
  const triggerDraft = useApp(s => s.triggerDraft)
  const prices = useApp(s => s.prices)
  const cataloguePrices = useApp(s => s.cataloguePrices)
  const mcpServers = useApp(s => s.mcpServers)
  const builtinTools = useApp(s => s.builtinTools)
  const board = useApp(s => s.board)
  const everywhere = useApp(s => s.everywhere)
  const budget = useApp(s => s.budget)
  // The plans' windows near their limit, from the top bar's readings: the toasts say each once.
  const [near, setNear] = useState<Near[]>([])
  // Stop everything holds, as the top bar last read it: the triggers' count says so too.
  const [held, setHeld] = useState(false)
  const boardError = useApp(s => s.boardError)
  const backlog = useApp(s => s.backlog)
  const backlogError = useApp(s => s.backlogError)
  const backlogAuto = useApp(s => s.backlogAuto)
  const away = useApp(s => s.away)
  // What waits for your word anywhere (tek-ev §1): the pill, the rail's badge, the panel and the page.
  const waiting = useReady()
  const readyPanel = useApp(s => s.readyPanel)
  const decided = conv ? decidedOf(conv).length : 0
  const pillSaid = waiting.length > 0 ? `${waiting.length} ${waiting.length === 1 ? 'waits' : 'wait'} for you` : `${decided} decided for you`
  const [view, setView] = useState<View>('canvas')
  const [theme, setTheme] = useState<Theme>(getStoredTheme)
  const [settingsWanted, setSettingsOpen] = useState(false)
  // Where Ctrl+K went on a page - a role, a provider, a server, words to search: the page opens
  // on it. A new pick is a new count: a list page is made anew for it, as a click on a row makes
  // its form anew; the memory keeps what is being written in it.
  const [pick, setPick] = useState<{ view: View; id: string; n: number } | null>(null)
  const picked = (where: View) => (pick?.view === where ? pick : undefined)
  // A section of the settings asked for - from Ctrl+K, or a chat's "run without asking" link (the store's, so that the
  // chat can ask): apart, so that the page hidden under them is not made anew. Each new ask opens Settings.
  const section = useApp(s => s.settingsAsked)
  const [heard, setHeard] = useState(section)
  if (section !== heard) {
    setHeard(section)
    if (section) setSettingsOpen(true)
  }
  // The first steps asked for again from Help.
  const [stepsAgain, setStepsAgain] = useState(false)
  const [rebuilt, setRebuilt] = useState(false)
  // The provider First steps say isn't answering: the top bar leaves it to them.
  const [stepsSayProvider, setStepsSayProvider] = useState<string | null>(null)
  // The rail's ⚙ that opens them, where the focus goes back when they are closed.
  const gear = useRef<HTMLButtonElement>(null)
  // Where the canvas puts its turn list, in the top bar.
  const [turnsIn, setTurnsIn] = useState<HTMLSpanElement | null>(null)
  // Where the toasts' bell stands: in the top bar, over nothing.
  const [bellIn, setBellIn] = useState<HTMLSpanElement | null>(null)
  // Another page chosen closes the project's settings.
  const show = (next: View) => {
    setView(next)
    setSettingsOpen(false)
    if (next !== view) setPick(null)
  }
  const go = (where: View, id: string) => {
    show(where)
    setPick(was => ({ view: where, id, n: (was?.n ?? 0) + 1 }))
  }
  // "Open chat" on Ready for you: the chat on the canvas, open - and, for a card of it (`key`), the panel at that card,
  // now under This chat; a To-do, Memory or night row has no card in the chat: the panel closes.
  const openChat = async (id: string, key?: string) => {
    await useApp.getState().openConversation(id)
    useApp.getState().showReady(key !== undefined, key === undefined ? undefined : waitingId(key))
    useApp.getState().showChatTab('Chat', true)
    show('canvas')
  }

  // The first steps are of the open conversation's provider, the top bar of all it would run on: asked again when it is
  // another conversation, or the same on another provider.
  const providerOpen = conv?.conversation.provider_id
  const convOpen = conv?.conversation.id
  useEffect(() => void useApp.getState().loadHealth(), [convOpen, providerOpen])
  useEffect(() => {
    const { loadProjects, loadHealth } = useApp.getState()
    void loadProjects()
    void useApp.getState().loadRoles().catch(() => {})
    void useApp.getState().loadSkills().catch(() => {})
    void useApp.getState().loadProviders().catch(() => {})
    // A turn's summary says its cost from them.
    void useApp.getState().loadPrices().catch(() => {})
    // A build of the page since this one was loaded (K-yenile-uyarisi): said once, until the page is reloaded.
    const lookForBuild = () => void builtAnew().then(anew => anew && setRebuilt(true))
    lookForBuild()
    const timer = setInterval(() => {
      void loadHealth()
      lookForBuild()
    }, HEALTH_POLL_MS)
    return () => clearInterval(timer)
  }, [])

  // The memory is read when it is looked at: every time its page opens (a file may have
  // changed on disk since), and once for each folder - what of it waits for you is on Ready for you.
  const givenFacts = conv?.agents.some(a => (a.facts_given?.length ?? 0) > 0) ?? false
  useEffect(() => {
    if (!projectId) return
    if (view === 'memory' || !useApp.getState().memory) void useApp.getState().loadMemory()
  }, [view, projectId])
  // So is the To-do list, whatever page is open (Ready for you), and again when the Board counts another number waiting there.
  const backlogWaiting = board?.backlog_waiting
  useEffect(() => {
    if (projectId) void useApp.getState().loadBacklog()
  }, [projectId, backlogWaiting])
  // ...and the memory again as a turn of the folder ends - in any chat: what it put forward waits on Ready for you.
  const turnsEnded = board?.conversations.map(c => `${c.turn?.id}:${c.turn?.ended_at}`).join() ?? ''
  useEffect(() => {
    if (projectId && useApp.getState().memory) void useApp.getState().loadMemory()
  }, [projectId, turnsEnded])
  // Beside a fact an agent was given stands how its source is "now": so the memory is read
  // again whenever such a list comes on screen - an agent's window, or an agent or a turn's
  // memory selected on the canvas.
  const givenShown = Boolean(agentWindowId) || /^(agent|memory):/.test(selectedNodeId ?? '')
  useEffect(() => {
    if (projectId && givenFacts && givenShown) void useApp.getState().loadMemory()
  }, [projectId, givenFacts, givenShown, agentWindowId, selectedNodeId])

  // What waits for you in every conversation of every folder (the rail's badge, the toasts): read again -
  // but on the Board's own page, which reads it itself.
  useEffect(() => {
    if (view === 'board') return
    // (Not while the tab is out of sight: the first read after it comes back says what changed.)
    const timer = setInterval(() => document.hidden || void useApp.getState().loadBoard(), BOARD_POLL_MS)
    return () => clearInterval(timer)
  }, [view])

  // This month's spend against the budget (the strip, the toast, Usage): read as often as the Board.
  useEffect(() => {
    if (!projectId) return
    const read = () => {
      void useApp.getState().loadBudget().catch(() => {})
      // ...and the night while you're away (slice 106): the top bar says it on every page.
      void useApp.getState().loadAway().catch(() => {})
    }
    read()
    const timer = setInterval(() => document.hidden || read(), BOARD_POLL_MS)
    return () => clearInterval(timer)
  }, [projectId])

  // K-bilgi: the project's knowledge is read when its page opens, and on Agents (a role's Knowledge tab).
  useEffect(() => {
    if (projectId && (view === 'knowledge' || view === 'agents')) void useApp.getState().loadKnowledge()
  }, [projectId, view])

  // The triggers are read again when their page opens: one may have come due since.
  useEffect(() => {
    if (projectId && view === 'triggers') void useApp.getState().loadTriggers()
    // And the conversations: what the list says of each (changes kept) may be decided since.
    if (view === 'conversations') void useApp.getState().loadConversations()
    // The prices are read when the Usage page opens.
    if (view === 'usage') void useApp.getState().loadPrices().catch(() => {})
    // The MCP servers when the Tools page opens, and the Agents page (a role is given one there).
    if (view === 'tools' || view === 'agents') void useApp.getState().loadMcpServers().catch(() => {})
    // And KOLONİ's own tools switched there, which a role's tools are shown with (slice 61).
    if (view === 'tools' || view === 'agents') void useApp.getState().loadBuiltinTools().catch(() => {})
    // And the backlog: its events read it again too.
    if (projectId && view === 'backlog') void useApp.getState().loadBacklog()
  }, [view, projectId])
  // The morning (slice 106): KOLONİ opened after a night while you were away goes to that night's report on the
  // canvas, at the first reading after the page opens - until the report has been on screen (its node says so).
  const morning = useRef(false)
  useEffect(() => {
    if (!away || morning.current) return
    morning.current = true
    if (away.status !== 'ended' || away.seen_at) return
    void useApp.getState().openTurn(away.conversation_id, away.run_id).then(() => useApp.getState().select('away:' + away.id))
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setView('canvas')
  }, [away])
  // B-150: the browser's Back (and Forward) opens the chat that was open before (`openConversation` keeps each in its history).
  useEffect(() => {
    const back = (event: PopStateEvent) => {
      const chat = (event.state as { chat?: unknown } | null)?.chat
      // (One deleted since: what is open stays open.)
      if (typeof chat === 'string') void useApp.getState().openConversation(chat).catch(() => {})
    }
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])
  // "Allow this in the trigger", from the chat: its page opens, with that trigger's form.
  useEffect(() => {
    // (A request made elsewhere changes which page is shown: that is this state.)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (triggerDraft) setView('triggers')
  }, [triggerDraft])

  // Opened from a bookmark, or left open across a restart: without this start's key the page can do nothing.
  if (refused) {
    return (
      <div className="setup">
        <div className="setup-card" role="alert">
          <h1>Open KOLONİ from the link in its window</h1>
          <p className="muted">Each start of KOLONİ makes a new link.</p>
        </div>
      </div>
    )
  }
  if (loadError) {
    return (
      <div className="setup">
        <div className="setup-card">
          <h1>KOLONİ cannot reach its server</h1>
          <p role="alert" className="alert">
            {loadError}
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void useApp.getState().loadProjects()}
          >
            Try again
          </button>
        </div>
      </div>
    )
  }
  if (!ready) return null

  // The open chat's main folder; none for a plain chat, whose pages of a folder say so (slice 86a).
  const project = projects.find(p => p.id === projectId) ?? null
  const settingsOpen = settingsWanted
  // On the Ready page itself the list is there: no panel over it, nor the same cards twice.
  const onReadyPage = view === 'ready' && !settingsOpen
  const panelShown = readyPanel.open && !onReadyPage
  const noFolder = (page: string) => (
    <div className="memory-page">
      <p className="muted">This chat has no folder - pick one with the folder button to use the {page}.</p>
    </div>
  )
  const firstSteps = () => {
    show('canvas')
    setStepsAgain(true)
  }
  const places: Place[] = [
    ...PAGES.map(([page, name]) => ({ kind: 'Page', name, go: () => show(page) })),
    { kind: 'Page', name: 'Settings', go: () => setSettingsOpen(true) },
    ...conversations.map(c => ({
      kind: 'Conversation',
      name: c.title,
      go: () => {
        void useApp.getState().openConversation(c.id)
        show('canvas')
      },
    })),
    ...roles.map(role => ({ kind: 'Role', name: role.name, go: () => go('agents', role.id) })),
    ...providers.map(provider => ({ kind: 'Model', name: provider.name, go: () => go('models', provider.id) })),
    ...mcpServers.map(server => ({ kind: 'Tool server', name: server.name, go: () => go('tools', server.id) })),
    ...[...(project ? SECTIONS : []), ...APP_SECTIONS.map(([key, name]) => [key, `${name} (the app)`] as const)].map(([key, name]) => ({
      kind: 'Setting',
      name,
      go: () => useApp.getState().askSettings(key),
    })),
    { kind: 'Help', name: 'Show the first steps', go: firstSteps },
  ]

  // What an agent waits on you for: shown with it in the inspector and in its window alike.
  const agentAsks: AgentAsks = conv
    ? {
        renderSpawnApproval: agent => (
          <SpawnApproval
            key={agent.id}
            agent={agent}
            openedBy={conv.agents.find(a => a.id === agent.parent_agent_id)?.name}
            continuesTurn={continuesFrom(conv, agent.id)}
            stays={staysOn(conv, agent, roles, providers)}
            onDecide={decision => useApp.getState().decideSpawn(agent.id, decision)}
            onOpenSkill={name => go('tools', `skill:${name}`)}
          />
        ),
        renderMerge: (merge, agent) => (
          <MergeCard
            key={merge.id}
            merge={merge}
            name={agent.name || agent.role_name}
            unfinished={agent.status === 'failed'}
            also={agent.depth === 0 ? keptNote(turnTeams(conv, merge.run_id), conv.fileChanges, merge.run_id) : ''}
            onDecide={(...said) => useApp.getState().decideMerge(merge.id, ...said)}
            onCheck={choices => useApp.getState().checkMerge(merge.id, choices)}
            onCommit={(message, hooks) => useApp.getState().commitMerge(merge.id, message, hooks)}
            onContinue={project && canContinue(conv, merge) ? { steps: project.continue_steps, run: () => useApp.getState().continueMerge(merge.id) } : undefined}
          />
        ),
        renderQuestion: question => (
          <QuestionCard
            key={question.id}
            question={question}
            onAnswer={answer => useApp.getState().answerQuestion(question.id, answer)}
          />
        ),
        // The chat's own card for a command that waits: in the panel and the agent's window too, answered in any of them.
        renderCommandApproval: command => (
          <CommandApproval
            key={command.id}
            command={command}
            why={conv.toolCalls.find(t => t.id === command.tool_call_id)?.why_asked}
            onDecide={decision => useApp.getState().decideCommand(command.id, decision)}
          />
        ),
        renderRoleApproval: role => (
          <RoleApproval
            key={role.tool_call_id}
            role={role}
            onDecide={decision => useApp.getState().decideRole(role.tool_call_id, decision)}
          />
        ),
      }
    : {}

  return (
    <div className="app">
      {/* Under the project's settings no page of the rail is the one shown. */}
      <Rail
        view={settingsOpen ? null : view}
        onView={show}
        theme={theme}
        onToggleTheme={() => setTheme(toggleTheme())}
        waiting={waiting.length}
        settingsOpen={settingsOpen}
        // (⚙ opens them on their first section: a section asked for before is not asked again.)
        onSettings={() => {
          useApp.setState({ settingsAsked: null })
          setSettingsOpen(open => !open)
        }}
        gear={gear}
      />
      {/* Focusable only from code: it takes the focus back from something that went (a dismissed notice). */}
      <div className="main" tabIndex={-1}>
        <TopBar
          folder={
            <FolderButton
              project={project}
              projects={projects}
              conversations={conversations}
              // (Not while the folder shown is not yet the chat's own.)
              conversation={conv && project && conv.conversation.project_id === project.id ? conv.conversation : null}
              onFolders={useApp.getState().setChatFolders}
              onDefault={useApp.getState().saveProjectSettings}
              onMove={useApp.getState().setFolder}
              onPart={useApp.getState().setChatPart}
              onNew={useApp.getState().newConversation}
              onOpenFolder={useApp.getState().openFolder}
              onBrowse={useApp.getState().browseFolders}
            />
          }
          git={project && <GitStatus projectId={project.id} />}
          title={conv?.conversation.title ?? 'New conversation'}
          location={project?.exec_location}
          turns={view === 'canvas' && !settingsOpen ? setTurnsIn : undefined}
        >
          <PlanUse providers={providers} onLimits={lastLimits} every={BOARD_POLL_MS} onOpen={() => show('usage')} onNear={setNear} />
          <BudgetPill budget={budget} onOpen={() => show('usage')} />
          <AwayStatus away={away} onOpen={() => show('backlog')} />
          <HoldStatus
            every={BOARD_POLL_MS}
            onHeld={setHeld}
            onOpen={async id => {
              await useApp.getState().openConversation(id)
              show('canvas')
            }}
          />
          <TriggersStatus
            triggers={triggers}
            paused={triggersPaused}
            held={held}
            onPause={useApp.getState().pauseTriggers}
            onOpen={() => show('triggers')}
          />
          <RunStatus conv={conv} connection={connection} />
          {/* Ready for you's pill (tek-ev §1): how many wait for your word anywhere; it opens the panel, on every page.
              (Nothing waits, but the Lead decided for you meanwhile: that is said, and its OK is in the panel too.) */}
          {/* (Short, so that the bar keeps to one line with the turn's tokens down to 1250 px - B-174; its name says it whole.) */}
          {(waiting.length > 0 || decided > 0) && (
            <button
              type="button"
              className="ready-pill"
              aria-label={pillSaid}
              title={pillSaid}
              aria-expanded={panelShown}
              aria-controls={READY_PANEL}
              onClick={() => (onReadyPage ? undefined : useApp.getState().showReady(!readyPanel.open))}
            >
              {waiting.length > 0 ? `${waiting.length} ${waiting.length === 1 ? 'waits' : 'wait'}` : `${decided} decided`}
            </button>
          )}
          <span ref={setBellIn} className="bell-slot" />
          <Help onFirstSteps={firstSteps} />
        </TopBar>
        <ModelBanner
          readings={barReadings}
          cannot={barCannot}
          quietFor={stepsSayProvider}
          onModels={() => show('models')}
        />
        {/* The page was built from other code than its server runs: what it reads may not be there. A server
            from before slice 65 does not say, and is other code too. */}
        {health && health.api_hash !== import.meta.env.VITE_API_HASH ? (
          <div role="status" className="banner">
            <span className="banner-text" title={UPDATED}>
              {UPDATED}
            </span>
          </div>
        ) : (
          // The same API, but the page built anew (a change of the page alone): a reload brings it.
          rebuilt && (
            <div className="banner">
              <span role="status" className="banner-text" title={REBUILT}>
                {REBUILT}
              </span>
              <button type="button" className="btn btn-small banner-pick" onClick={() => location.reload()}>
                Reload
              </button>
            </div>
          )
        )}
        {view === 'canvas' && !settingsOpen && (
          <OpenChats
            tabs={kept(tabs, conversations, projects)}
            conversations={conversations}
            projects={projects}
            board={everywhere}
            openTab={conv ? tabOf(conv.conversation.project_id) : null}
            onOpen={tab => void useApp.getState().openTab(tab)}
            onClose={tab => void useApp.getState().closeTab(tab)}
            onOpenFolder={useApp.getState().openFolder}
            onBrowse={useApp.getState().browseFolders}
          />
        )}
        {view === 'canvas' && !settingsOpen && <ConflictStrip board={everywhere} conversationId={conv?.conversation.id ?? null} />}
        {settingsOpen && (
          <Settings
            project={project}
            picked={section ?? undefined}
            chat={conv && project && conv.conversation.project_id === project.id ? { id: conv.conversation.id, title: conv.conversation.title } : undefined}
            dockerAvailable={health?.docker_available ?? false}
            dockerError={health?.docker_error ?? null}
            // Not known yet is not "none": the server refuses it where there is none.
            desktopAvailable={health?.desktop_available ?? true}
            shell={health?.shell ?? null}
            shellNote={health?.shell_note ?? null}
            onSave={useApp.getState().saveProjectSettings}
            onUseKoloni={useApp.getState().takeKoloniSettings}
            spend={budget}
            onClose={() => {
              setSettingsOpen(false)
              gear.current?.focus()
            }}
          />
        )}
        {/* Hidden, not gone, under the settings: a message being typed and an open window stay. */}
        <div className="workspace" hidden={settingsOpen}>
          <PageGuard key={view}>
          {view === 'agents' ? (
            <AgentsPage
              key={picked('agents')?.n}
              picked={picked('agents')?.id}
              roles={roles}
              teams={teams}
              providers={providers}
              skills={skills}
              onOpenSkills={name => go('tools', name ? `skill:${name}` : 'skills')}
              onSave={useApp.getState().saveRole}
              onCreate={useApp.getState().createRole}
              onDelete={useApp.getState().deleteRole}
              onReset={useApp.getState().resetRole}
              onPatch={useApp.getState().patchRole}
              // (The store's own team and category methods, by their names.)
              teamActions={useApp.getState()}
              categories={categories}
              categoryActions={useApp.getState()}
              recipeActions={useApp.getState()}
              knowledgeActions={useApp.getState()}
              knowledge={knowledge ?? undefined}
              onOpenKnowledge={() => setView('knowledge')}
              projectId={projectId}
              onActivity={useApp.getState().roleActivity}
              onHistory={useApp.getState().roleHistory}
              onOpenConversation={async id => {
                // As the Board's: shown only once it is open.
                await useApp.getState().openConversation(id)
                setView('canvas')
              }}
              onOpenTools={name => go('tools', mcpServers.find(server => server.name === name)?.id ?? 'servers')}
              off={builtinTools.filter(tool => !tool.on).map(tool => tool.name)}
              serversOff={mcpServers.filter(server => !server.enabled).map(server => server.name)}
              onModels={useApp.getState().providerModels}
              onFacts={useApp.getState().modelFacts}
              onRecord={useApp.getState().record}
              onRoleModels={roleModelsNow}
              onFillAll={useApp.getState().fillAll}
              onSaveFillAll={useApp.getState().saveFillAll}
            />
          ) : view === 'models' ? (
            <ModelsPage
              key={picked('models')?.n}
              picked={picked('models')?.id}
              providers={providers}
              onCreate={useApp.getState().createProvider}
              onSave={useApp.getState().saveProvider}
              onDelete={useApp.getState().deleteProvider}
              onTest={useApp.getState().testProvider}
              onModels={useApp.getState().providerModels}
              onMakeDefault={useApp.getState().makeDefaultProvider}
              onFill={useApp.getState().fillFromCatalogue}
              onFillNew={useApp.getState().fillNewFromCatalogue}
              onAvailability={useApp.getState().availability}
              onFacts={useApp.getState().modelFacts}
              onSuggest={useApp.getState().suggest}
              onUpdateCatalogue={useApp.getState().updateCatalogue}
              onCatalogue={useApp.getState().catalogue}
              onKeepFresh={useApp.getState().keepCatalogueFresh}
              onLocalServer={useApp.getState().localServer}
              onRunLocalServer={useApp.getState().runLocalServer}
              onFillAll={useApp.getState().fillAll}
              onSaveFillAll={useApp.getState().saveFillAll}
              onTiers={useApp.getState().tiers}
              onSaveTiers={useApp.getState().saveTiers}
              onLimits={useApp.getState().limits}
              onClaudeSetup={useApp.getState().claudeSetup}
              onUsage={usageEverywhere}
              prices={prices}
            />
          ) : view === 'tools' ? (
            <ToolsPage
              key={picked('tools')?.n}
              picked={picked('tools')?.id}
              servers={mcpServers}
              roles={roles}
              onAdd={useApp.getState().addMcpServer}
              onSave={useApp.getState().saveMcpServer}
              onDelete={useApp.getState().deleteMcpServer}
              onRead={useApp.getState().readMcpServer}
              onRoleServers={useApp.getState().setRoleServers}
              builtin={builtinTools}
              onSwitchTool={useApp.getState().switchBuiltinTool}
              skills={skills}
              skillActions={{
                onPreviewSkill: useApp.getState().previewSkill,
                onAddSkill: useApp.getState().addSkill,
                onSkillLeave: useApp.getState().setSkillLeave,
                onSkillOn: useApp.getState().setSkillOn,
                onDeleteSkill: useApp.getState().deleteSkill,
                onSkillRecord: useApp.getState().skillRecord,
                onPatchRole: useApp.getState().patchRole,
              }}
            />
          ) : view === 'ready' ? (
            <ReadyPage items={waiting} openChat={openChat} />
          ) : view === 'board' ? (
            !project ? noFolder('Board') :
            <BoardPage
              // (Each folder's own: what one opened, typed or read is not carried to another.)
              key={project.id}
              board={board}
              error={boardError}
              currentId={conv?.conversation.id ?? null}
              onLoad={useApp.getState().loadBoard}
              onRerun={useApp.getState().rerunFailed}
              waiting={waiting.length}
              onReady={() => show('ready')}
              onOpen={async id => {
                // Only once it is open: one that is gone (deleted since the board was read)
                // is said on the board, not shown as the conversation that was open before.
                await useApp.getState().openConversation(id)
                setView('canvas')
              }}
            />
          ) : view === 'backlog' ? (
            !project ? noFolder('To-do') :
            <BacklogPage
              key={project.id}
              backlog={backlog}
              error={backlogError}
              auto={backlogAuto}
              away={away}
              providers={providers}
              onAuto={useApp.getState().setBacklogAuto}
              onChoice={useApp.getState().setBacklogChoice}
              onModels={useApp.getState().providerModels}
              onAdd={useApp.getState().addTask}
              onDraft={useApp.getState().draftTasks}
              onPlan={async message => {
                await useApp.getState().newConversation(project.id)
                await useApp.getState().send(message)
                setView('canvas')
              }}
              onChange={useApp.getState().changeTask}
              onDelete={useApp.getState().deleteTask}
              onDecide={useApp.getState().decideTask}
              onRun={useApp.getState().runBacklog}
              onOpen={id => {
                void useApp.getState().openConversation(id)
                setView('canvas')
              }}
            />
          ) : view === 'usage' ? (
            <UsagePage
              project={project}
              projects={projects}
              onLoad={useApp.getState().usage}
              budget={budget}
              providers={providers}
              onLimits={useApp.getState().limits}
              prices={prices}
              cataloguePrices={cataloguePrices}
              onPrice={useApp.getState().savePrice}
              onRemovePrice={useApp.getState().removePrice}
              onModels={id => go('models', id)}
              onSettings={() => useApp.getState().askSettings('limits')}
              today={
                project && (
                  // (Each folder's own day: read anew for another.)
                  <TodayView
                    key={project.id}
                    currentId={conv?.conversation.id ?? null}
                    noteAt={project.day_note_at}
                    onLoad={useApp.getState().day}
                    onWords={useApp.getState().dayWords}
                    onOpenTurn={async (id, runId) => {
                      // Shown only once it is open; one that is gone is said under the list.
                      await useApp.getState().openTurn(id, runId)
                      setView('canvas')
                    }}
                  />
                )
              }
              onOpen={id => {
                void useApp.getState().openConversation(id)
                setView('canvas')
              }}
            />
          ) : view === 'memory' ? (
            !project ? noFolder('Memory') :
            <MemoryPage
              key={project.id}
              searchFor={pick?.view === 'memory' ? { words: pick.id, n: pick.n } : undefined}
              memory={memory}
              error={memoryError}
              onApprove={useApp.getState().approveMemory}
              onReject={useApp.getState().rejectMemory}
              onRestore={useApp.getState().restoreMemory}
              onConfirm={useApp.getState().confirmMemory}
              onCorrect={useApp.getState().correctMemory}
              onWrite={useApp.getState().writeFact}
              onSaveRules={useApp.getState().saveRules}
              onSavePreferences={useApp.getState().savePreferences}
              onAddPreference={useApp.getState().addPreference}
              onReload={useApp.getState().loadMemory}
              onSearch={useApp.getState().searchMemory}
              onMeaning={useApp.getState().saveProjectSettings}
              onExport={projectId ? () => download('GET', `/projects/${projectId}/memory/export`) : undefined}
            />
          ) : view === 'knowledge' ? (
            !project ? noFolder('Knowledge page') :
            <KnowledgePage
              key={project.id}
              items={knowledge}
              error={knowledgeError}
              projectName={project.name}
              providers={providers}
              otherProjects={projects.filter(one => one.id !== project.id)}
              onReload={useApp.getState().loadKnowledge}
              onAdd={useApp.getState().addKnowledge}
              onSave={useApp.getState().saveKnowledge}
              onDelete={useApp.getState().deleteKnowledge}
              onLearn={useApp.getState().learnKnowledge}
              onTry={useApp.getState().tryKnowledge}
              onCopy={useApp.getState().copyKnowledge}
              onReadFile={useApp.getState().knowledgeFile}
            />
          ) : view === 'triggers' ? (
            !project ? noFolder('Triggers') :
            <TriggersPage
              key={project.id}
              triggers={triggers}
              error={triggersError}
              changes={triggerChanges}
              conversations={conversations}
              draft={triggerDraft}
              onDraftTaken={useApp.getState().clearTriggerDraft}
              origin={window.location.origin}
              onCreate={useApp.getState().createTrigger}
              onSave={useApp.getState().saveTrigger}
              onDelete={useApp.getState().deleteTrigger}
              onRun={useApp.getState().runTrigger}
              onNewKey={useApp.getState().newTriggerKey}
              onShowTurn={(conversationId, runId) => {
                void useApp.getState().openTurn(conversationId, runId)
                setView('canvas')
              }}
              onRules={useApp.getState().allowedCommandsOf}
              onAddRule={useApp.getState().addAllowedCommand}
              onHosts={useApp.getState().allowedHostsOf}
            />
          ) : view === 'conversations' ? (
            <ConversationList
              conversations={conversations}
              projects={projects}
              board={everywhere}
              triggers={triggers}
              triggersPaused={triggersPaused}
              onArchive={useApp.getState().archiveConversation}
              onDelete={useApp.getState().deleteConversations}
              currentId={conv?.conversation.id ?? null}
              onRefresh={useApp.getState().loadConversations}
              onOpen={id => {
                void useApp.getState().openConversation(id)
                setView('canvas')
              }}
              onNew={() => {
                void useApp.getState().newConversation()
                setView('canvas')
              }}
            />
          ) : (
            <>
              {/* The canvas fills the stage; the chat floats over its bottom left corner. */}
              {/* The window over the canvas pressed or used last is the one in front. */}
              <div className="stage" onPointerDownCapture={event => frontOf(event.target)} onFocusCapture={event => frontOf(event.target)}>
                <ChatPanel />
                <FirstSteps
                  health={health}
                  project={projects.length > 0}
                  folder={project?.root_path ?? null}
                  // (The list may be read before the first send: the open chat's own turn says it at once.)
                  wrote={conversations.some(c => c.wrote) || (conv?.runs.length ?? 0) > 0}
                  turn={conv ? conv.runs.length > 0 : conversations.some(c => !c.archived_at) ? undefined : false}
                  again={stepsAgain}
                  onProvider={() => go('models', 'new')}
                  onHidden={() => setStepsAgain(false)}
                  onSaysProvider={setStepsSayProvider}
                />
                <CanvasView
                  key={conv?.conversation.id ?? 'none'}
                  state={conv}
                  selectedId={selectedNodeId}
                  onSelect={select}
                  turnId={turnId}
                  onTurn={useApp.getState().showTurn}
                  onRenameTopic={useApp.getState().renameTopic}
                  over={agentWindowId ?? discussionWindowId ?? roomWindowId}
                  turnsIn={turnsIn}
                  onOpenNode={(kind, refId) => {
                    if (kind === 'agent') useApp.getState().openAgentWindow(refId)
                    if (kind === 'discussion') useApp.getState().openDiscussion(refId)
                    if (kind === 'room') useApp.getState().showRoom(refId)
                    if (kind === 'memory') setView('memory')
                    // (The Assistant PO's node, opened, or its To-do →.)
                    if (kind === 'po' || kind === 'backlog') setView('backlog')
                  }}
                  onOpenList={() => useApp.getState().showReady(true)}
                  onStopTeam={useApp.getState().stopTeam}
                  onFinishTeam={useApp.getState().finishTeam}
                  teams={teams}
                />
                {conv && (
                  <ChatTeams
                    conversation={conv.conversation}
                    agents={conv.agents}
                    runs={conv.runs}
                    onStop={useApp.getState().stopTeam}
                    onFinish={useApp.getState().finishTeam}
                    teams={teams}
                    onRecipes={() => useApp.getState().recipes(null).then(read => read.recipes)}
                    onChange={useApp.getState().setChatTeams}
                    project={project && conv.conversation.project_id === project.id ? project : null}
                    onDefault={useApp.getState().saveProjectSettings}
                    roles={roles}
                    providers={providers}
                    onRoleModels={() => useApp.getState().roleModels(conv.conversation.id)}
                    // (The role's own model, as "A model of its own" on its card sets it: no tier left to pick another.)
                    onRunOn={(roleId, providerId, modelId) => useApp.getState().patchRole(roleId, { provider_id: providerId, model_id: modelId, tier: null, tier_min: null, tier_max: null })}
                  />
                )}
                {conv && agentWindowId && (
                  <AgentWindow
                    state={conv}
                    memory={memory}
                    providers={providers}
                    agentId={agentWindowId}
                    onClose={useApp.getState().closeAgentWindow}
                    onOpenChange={openChange}
                    {...agentAsks}
                    onSelectAgent={agentId => {
                      select(`agent:${agentId}`)
                      useApp.getState().openAgentWindow(agentId)
                    }}
                  />
                )}
                {conv && discussionWindowId && (
                  <DiscussionWindow
                    state={conv}
                    discussionId={discussionWindowId}
                    onClose={useApp.getState().closeDiscussion}
                    onSay={useApp.getState().sayInDiscussion}
                    onEnd={useApp.getState().endDiscussion}
                  />
                )}
              </div>
              <Inspector
                state={conv}
                providers={providers}
                selectedId={selectedNodeId}
                onClose={() => select(null)}
                onOpenChange={openChange}
                onSelect={select}
                onOpenAgent={agentId => useApp.getState().openAgentWindow(agentId)}
                onOpenDiscussion={id => useApp.getState().openDiscussion(id)}
                onOpenRoom={useApp.getState().showRoom}
                {...agentAsks}
                renderChange={change => (
                  <>
                    <ChangeActions
                      key={change.id}
                      change={change}
                      onDecide={action => decide(change.id, action)}
                    />
                    <div className="insp-diff">
                      <DiffView diff={change.diff} />
                    </div>
                  </>
                )}
              />
            </>
          )}
          </PageGuard>
        </div>
      </div>
      <Toasts
        board={everywhere}
        bellIn={bellIn}
        budget={budget}
        near={near}
        onUsage={() => show('usage')}
        shownId={view === 'canvas' && !settingsOpen ? (conv?.conversation.id ?? null) : null}
        onOpen={id => {
          void useApp.getState().openConversation(id)
          show('canvas')
        }}
      />
      {panelShown && (
        <ReadyPanel
          items={waiting}
          openChat={openChat}
          onPage={() => {
            useApp.getState().showReady(false)
            show('ready')
          }}
          onClose={() => useApp.getState().showReady(false)}
        />
      )}
      <AskAboutThis />
      <Palette places={places} onOpen={() => void useApp.getState().loadMcpServers().catch(() => {})} onSearch={words => go('memory', words)} />
    </div>
  )
}
