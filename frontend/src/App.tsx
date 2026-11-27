import { type ReactNode, useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api, download, keyRefused } from './api/client'
import type { Board, Project } from './api/types'
import { AgentsPage } from './agents/AgentsPage'
import { type AgentAsks, AgentWindow } from './agents/AgentWindow'
import { ChatTeams } from './agents/ChatTeams'
import { AwayStatus } from './backlog/Away'
import { BacklogPage, type TodoAsked } from './backlog/BacklogPage'
import { OPEN_TODO } from './chat/TodoCards'
import { doInChat } from './chat/todoActions'
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
import { mayBeOld } from './knowledge/fresh'
import { MemoryPage } from './memory/MemoryPage'
import { ModelsPage } from './models/ModelsPage'
import { FirstSteps } from './shell/FirstSteps'
import { FolderButton } from './shell/FolderButton'
import { openFolderPanel } from './shell/usePanel'
import { Help } from './shell/Help'
import { OpenChats } from './shell/OpenChats'
import { kept, tabOf } from './shell/openTabs'
import { type Place, Palette } from './shell/Palette'
import { PageGuard } from './shell/PageGuard'
import { HoldStatus } from './shell/HoldStatus'
import { Settings, settingsPlaces } from './shell/Settings'
import { Rail, type View } from './shell/Rail'
import { RunStatus } from './shell/RunStatus'
import { Toasts } from './shell/Toasts'
import { TopBar } from './shell/TopBar'
import { GitStatus } from './shell/GitStatus'
import { frontOf } from './shell/move'
import type { ConvState } from './state/applyEvent'
import { useApp } from './state/store'
import { getStoredTheme, toggleTheme, type Theme } from './theme/theme'
import { ToolsPage } from './tools/ToolsPage'
import { continuesFrom } from './topics/topics'
import { UsagePage } from './usage/UsagePage'
import { BudgetPill } from './usage/Budget'
import { TodayView } from './usage/TodayView'
import { DecidedToday } from './ready/DecidedToday'
import { OPEN_DECISIONS, readDecisions } from './ready/decisionLog'
import type { Near } from './usage/limitsText'
import { PlanUse } from './usage/PlanUse'
import { ReadyPage, ReadyPanel } from './ready/ReadyViews'
import { useReady } from './ready/useReady'
import { READY_PANEL } from './ready/ready'
import { waitingId } from './chat/waiting'
import { useDecided } from './chat/DecidedLine'

const HEALTH_POLL_MS = 15000
// (A hash has no order: which of the two is newer is not known, so all three steps are said.)
const UPDATED =
  'KOLONİ was updated: the page and the server differ. Build the page (npm run build), restart KOLONİ, then reload.'
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
// The events of the project's other conversations do not come here: what waits there is read again this often.
const BOARD_POLL_MS = 5000
// The Agents page reads what each role would run on in a new conversation, with the levels each model takes: one function, read once per change of roles.
const roleModelsNow = () => useApp.getState().roleModels(null, true)
// The Models page reads what was used in every project: an API key's spend today, a model's last 30 days.
const usageEverywhere = (since: string) => useApp.getState().usage(null, since)
// The top bar's plan use: only the last reading, never read afresh (Claude Code's would run a turn).
const lastLimits = (providerId: string) => useApp.getState().limits(providerId, false)
/** The top bar's readings, of the open chat's providers: not known while the chat the list leads to is read, nor from another's. */
const readingsOf = ({ inUse, conv, conversations }: ReturnType<typeof useApp.getState>) =>
  inUse?.of === (conv?.conversation.id ?? null) && (conv || !conversations.some(c => !c.archived_at))
    ? inUse.readings
    : null
/** ...and the roles of it that cannot run, with them. */
const cannotOf = (state: ReturnType<typeof useApp.getState>) => (readingsOf(state) ? state.inUse?.cannot : undefined)

/** Whether an agent of the open chat was given facts. */
const factsGiven = (conv: ConvState | null) => conv?.agents.some(a => (a.facts_given?.length ?? 0) > 0) ?? false
/** Each chat's turn of the folder and when it ended, as one string: another when a turn ends. */
const turnsEndedOf = (board: Board | null) =>
  board?.conversations.map(c => `${c.turn?.id}:${c.turn?.ended_at}`).join() ?? ''
/** Whether a list of the facts an agent was given is on screen: an agent's window, or an agent or a turn's memory selected. */
const givenOnScreen = (agentWindowId: string | null, selectedNodeId: string | null) =>
  Boolean(agentWindowId) || /^(agent|memory):/.test(selectedNodeId ?? '')

/** First steps' "Use … for new chats": the default changed, and done only once the reading on show is the new one's. */
const makeDefaultAndRead = async (providerId: string) => {
  await useApp.getState().makeDefaultProvider(providerId)
  await useApp.getState().loadHealth()
}

/** The rail's pages, by their pages' names and the rail's word where it is another: what Ctrl+K finds (and Work's two
 *  tabs, each its own place: `openReady`, `openTodo`). */
const PAGES: [View, string][] = [
  ['canvas', 'Canvas'],
  ['conversations', 'Chats (Conversations)'],
  ['agents', 'Agents'],
  ['models', 'Models'],
  ['tools', 'Tools'],
  ['memory', 'Memory'],
  ['knowledge', 'Memory › Sources (Knowledge)'],
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
  const select = useApp(s => s.select)
  const turnId = useApp(s => s.turnId)
  const openChange = useApp(s => s.openChange)
  const decide = useApp(s => s.decide)
  const memory = useApp(s => s.memory)
  const memoryError = useApp(s => s.memoryError)
  const knowledge = useApp(s => s.knowledge)
  const knowledgeError = useApp(s => s.knowledgeError)
  const prices = useApp(s => s.prices)
  const cataloguePrices = useApp(s => s.cataloguePrices)
  const mcpServers = useApp(s => s.mcpServers)
  const builtinTools = useApp(s => s.builtinTools)
  const board = useApp(s => s.board)
  const everywhere = useApp(s => s.everywhere)
  const budget = useApp(s => s.budget)
  // The plans' windows near their limit, from the top bar's readings: the toasts say each once.
  const [near, setNear] = useState<Near[]>([])
  const backlog = useApp(s => s.backlog)
  const backlogError = useApp(s => s.backlogError)
  const drafter = useApp(s => s.drafter)
  const stories = useApp(s => s.stories)
  const chatList = useApp(s => s.conversations)
  const away = useApp(s => s.away)
  // What waits for your word anywhere (tek-ev §1): the pill, the rail's badge, the panel and the page.
  const waiting = useReady()
  // The chats it has read: the open one and the others that wait (what Chats says waits in them is its rows alone).
  const readyChats = useApp(s => s.readyChats)
  const readyPanel = useApp(s => s.readyPanel)
  const readyTab = useApp(s => s.readyTab)
  const { decided, where: decidedWhere } = useDecided(conv)
  const [view, setView] = useState<View>('canvas')
  // Whether you opened another page since KOLONİ opened: the morning never takes you off it (M1).
  const opened = useRef(false)
  useEffect(() => {
    if (view !== 'canvas') opened.current = true
  }, [view])
  // The morning (slice 106): KOLONİ opened after a night while you were away opens Ready for you, where the night's
  // strip is - until the night has been on screen (the strip, or the report on the canvas, says so). Asked once, of the
  // first answer about the night after the page opens: never over a page you opened meanwhile, nor later (a first read
  // that failed, a night that ends while you are here) - M1.
  const morning = useRef(false)
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
  // Work's two tabs (0.1.10): the rail's Work opens the one shown last; these, the one they name. To-do: its tab, in
  // view - at a task's row, where one is asked (the tab shown first: what takes the focus there is not hidden).
  const [todoAsked, setTodoAsked] = useState<TodoAsked | null>(null)
  const openTodo = (task?: string) => {
    show('ready')
    useApp.setState({ readyTab: 'todo' })
    setTodoAsked(was => ({ task, n: (was?.n ?? 0) + 1 }))
  }
  const openReady = () => {
    show('ready')
    useApp.setState({ readyTab: 'ready' })
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
    void useApp
      .getState()
      .loadRoles()
      .catch(() => {})
    void useApp
      .getState()
      .loadSkills()
      .catch(() => {})
    void useApp
      .getState()
      .loadProviders()
      .catch(() => {})
    // A turn's summary says its cost from them.
    void useApp
      .getState()
      .loadPrices()
      .catch(() => {})
    // A build of the page since this one was loaded (K-yenile-uyarisi): said once, until the page is reloaded.
    const lookForBuild = () => void builtAnew().then(anew => anew && setRebuilt(true))
    lookForBuild()
    // (Not while the tab is out of sight: asked once as it comes back.)
    const poll = () => {
      if (document.hidden) return
      void loadHealth()
      lookForBuild()
    }
    const timer = setInterval(poll, HEALTH_POLL_MS)
    document.addEventListener('visibilitychange', poll)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', poll)
    }
  }, [])

  // The memory is read when it is looked at: every time its page opens (a file may have
  // changed on disk since), and once for each folder - what of it waits for you is on Ready for you.
  const givenFacts = factsGiven(conv)
  useEffect(() => {
    if (!projectId) return
    if (view === 'memory' || !useApp.getState().memory) void useApp.getState().loadMemory()
  }, [view, projectId])
  // So is the To-do list, whatever page is open (Ready for you), and again when the board read counts another number waiting there.
  const backlogWaiting = board?.backlog_waiting
  useEffect(() => {
    if (projectId) void useApp.getState().loadBacklog()
  }, [projectId, backlogWaiting])
  // ...and the memory again as a turn of the folder ends - in any chat: what it put forward waits on Ready for you.
  const turnsEnded = turnsEndedOf(board)
  useEffect(() => {
    if (projectId && useApp.getState().memory) void useApp.getState().loadMemory()
  }, [projectId, turnsEnded])
  // Beside a fact an agent was given stands how its source is "now": so the memory is read
  // again whenever such a list comes on screen - an agent's window, or an agent or a turn's
  // memory selected on the canvas.
  const givenShown = givenOnScreen(agentWindowId, selectedNodeId)
  useEffect(() => {
    if (projectId && givenFacts && givenShown) void useApp.getState().loadMemory()
  }, [projectId, givenFacts, givenShown, agentWindowId, selectedNodeId])

  // What waits for you in every conversation of every folder (the rail's badge, the toasts): read again.
  useEffect(() => {
    // (Not while the tab is out of sight: the first read after it comes back says what changed.)
    const timer = setInterval(() => document.hidden || void useApp.getState().loadBoard(), BOARD_POLL_MS)
    return () => clearInterval(timer)
  }, [])

  // This month's spend against the budget (the strip, the toast, Usage): read as often as what waits.
  useEffect(() => {
    if (!projectId) return
    const read = () => {
      void useApp
        .getState()
        .loadBudget()
        .catch(() => {})
      // ...and the night while you're away (slice 106): the top bar says it on every page.
      const first = !morning.current
      morning.current = true
      void useApp
        .getState()
        .loadAway()
        .then(() => {
          const night = useApp.getState().away
          if (first && night?.status === 'ended' && !night.seen_at && !opened.current) {
            setView('ready')
            useApp.setState({ readyTab: 'ready' })
          }
        })
        .catch(() => {})
    }
    read()
    const timer = setInterval(() => document.hidden || read(), BOARD_POLL_MS)
    return () => clearInterval(timer)
  }, [projectId])

  // K-bilgi: the project's knowledge is read when Memory opens (either part: the sources' tab says how many may be old),
  // and on Agents (a role's Knowledge tab).
  useEffect(() => {
    if (projectId && ['memory', 'knowledge', 'agents'].includes(view)) void useApp.getState().loadKnowledge()
  }, [projectId, view])

  useEffect(() => {
    // The conversations: what the list says of each (changes kept) may be decided since.
    if (view === 'conversations') void useApp.getState().loadConversations()
    // The prices are read when the Usage page opens.
    if (view === 'usage')
      void useApp
        .getState()
        .loadPrices()
        .catch(() => {})
    // The MCP servers when the Tools page opens, and the Agents page (a role is given one there).
    if (view === 'tools' || view === 'agents')
      void useApp
        .getState()
        .loadMcpServers()
        .catch(() => {})
    // And KOLONİ's own tools switched there, which a role's tools are shown with (slice 61).
    if (view === 'tools' || view === 'agents')
      void useApp
        .getState()
        .loadBuiltinTools()
        .catch(() => {})
    // And the backlog, Work's To-do: its events read it again too.
    if (projectId && view === 'ready') void useApp.getState().loadBacklog()
  }, [view, projectId])
  // 0.1.8: a To-do card in a chat (Open it in To-do), a To-do row of Decided for you: To-do, at that task's row.
  const openTodoAt = useRef(openTodo)
  useEffect(() => {
    openTodoAt.current = openTodo
  })
  useEffect(() => {
    const open = (event: Event) => openTodoAt.current((event as CustomEvent<string>).detail)
    window.addEventListener(OPEN_TODO, open)
    return () => window.removeEventListener(OPEN_TODO, open)
  }, [])
  // "Open in Ready for you" (the chat's line, Usage's Today): Work's Ready for you, its Decided for you in view - asked
  // until it is, or the page is left before it could be (then a later visit is as any).
  // ("unseen": at Not seen - the line or Today counted some that wait for your OK)
  const [decisionsAsked, setDecisionsAsked] = useState<'unseen' | 'any' | null>(null)
  useEffect(() => {
    const open = (event: Event) => {
      setView('ready')
      useApp.setState({ readyTab: 'ready' })
      setSettingsOpen(false)
      setDecisionsAsked((event as CustomEvent<boolean>).detail ? 'unseen' : 'any')
    }
    window.addEventListener(OPEN_DECISIONS, open)
    return () => window.removeEventListener(OPEN_DECISIONS, open)
  }, [])
  useEffect(() => {
    if (view === 'ready') return
    // (Left, the page asked for is as any when it opens again: To-do, too, not opened at the task once asked.)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDecisionsAsked(null)
    setTodoAsked(null)
  }, [view])
  const decisionsOpened = useCallback(() => setDecisionsAsked(null), [])
  // (One for the project: Decisions reads again only for another period.)
  const decisionsOf = useCallback(
    (from: string | null, unseen?: boolean) => readDecisions(projectId ?? '', from, unseen),
    [projectId],
  )
  // B-150: the browser's Back (and Forward) opens the chat that was open before (`openConversation` keeps each in its history).
  useEffect(() => {
    const back = (event: PopStateEvent) => {
      const chat = (event.state as { chat?: unknown } | null)?.chat
      // (One deleted since: what is open stays open.)
      if (typeof chat === 'string')
        void useApp
          .getState()
          .openConversation(chat)
          .catch(() => {})
    }
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])

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
          <button type="button" className="btn btn-primary" onClick={() => void useApp.getState().loadProjects()}>
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
  // On the Work page itself the list is there: no panel over it, nor the same cards twice - the pill shows its tab.
  const onReadyPage = view === 'ready' && !settingsOpen
  const panelShown = readyPanel.open && !onReadyPage
  const noFolder = (page: string) => (
    <div className="memory-page">
      <p className="muted">This chat has no folder - pick one with the folder button to use the {page}.</p>
      <button type="button" className="btn btn-small" onClick={openFolderPanel}>
        Choose a folder
      </button>
    </div>
  )
  const firstSteps = () => {
    show('canvas')
    setStepsAgain(true)
  }

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
            onContinue={
              project && canContinue(conv, merge)
                ? { steps: project.continue_steps, run: () => useApp.getState().continueMerge(merge.id) }
                : undefined
            }
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

  /** The rail: its pages, Settings and the theme. */
  const rail = () => (
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
  )

  /** Ready for you's pill, while something waits for you or was decided for you. */
  const readyPill = () => {
    const pillSaid =
      waiting.length > 0
        ? `${waiting.length} ${waiting.length === 1 ? 'waits' : 'wait'} for you`
        : `${decided} decided for you ${decidedWhere}`
    return (
      (waiting.length > 0 || decided > 0) && (
        <button
          type="button"
          className="ready-pill"
          aria-label={pillSaid}
          title={pillSaid}
          aria-expanded={panelShown}
          aria-controls={READY_PANEL}
          onClick={() => (onReadyPage ? openReady() : useApp.getState().showReady(!readyPanel.open))}
        >
          {waiting.length > 0 ? `${waiting.length} ${waiting.length === 1 ? 'waits' : 'wait'}` : `${decided} decided`}
        </button>
      )
    )
  }

  /** The top bar: the folder, git, the title, where commands run, and what is said of the plans, the budget, the night and Stop. */
  const topBar = () => (
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
      <PlanUse
        providers={providers}
        onLimits={lastLimits}
        every={BOARD_POLL_MS}
        onOpen={() => show('usage')}
        onNear={setNear}
      />
      <BudgetPill budget={budget} onOpen={() => show('usage')} />
      {/* (The night at work: its report, on Work's Ready for you.) */}
      <AwayStatus away={away} onOpen={openReady} />
      <HoldStatus
        every={BOARD_POLL_MS}
        onOpen={async id => {
          await useApp.getState().openConversation(id)
          show('canvas')
        }}
      />
      <RunStatus conv={conv} connection={connection} />
      {/* Ready for you's pill (tek-ev §1): how many wait for your word anywhere; it opens the panel, on every page.
          (Nothing waits, but the Lead decided for you meanwhile: that is said, and its OK is in the panel too.) */}
      {/* (Short, so that the bar keeps to one line with the turn's tokens down to 1250 px - B-174; its name says it whole.) */}
      {readyPill()}
      <span ref={setBellIn} className="bell-slot" />
      <Help onFirstSteps={firstSteps} />
    </TopBar>
  )

  /** Another API than the page was built against, or the page built anew. */
  const banner = () =>
    health && health.api_hash !== import.meta.env.VITE_API_HASH ? (
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
    )

  /** The open chats' tabs, over the canvas. */
  const openChats = () =>
    view === 'canvas' &&
    !settingsOpen && (
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
    )

  /** What two chats of the folder both want, over the canvas. */
  const conflicts = () =>
    view === 'canvas' &&
    !settingsOpen && <ConflictStrip board={everywhere} conversationId={conv?.conversation.id ?? null} />

  /** The settings, as a page over the one shown. */
  const settingsPage = () =>
    settingsOpen && (
      <Settings
        project={project}
        picked={section ?? undefined}
        chat={
          conv && project && conv.conversation.project_id === project.id
            ? { id: conv.conversation.id, title: conv.conversation.title }
            : undefined
        }
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
    )

  // The pages of the rail, each drawn as it is shown; a page of a folder, in a plain chat, says it has none.
  const agentsPage = () => (
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
        // Shown only once it is open.
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
  )
  const modelsPage = () => (
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
      onProviders={useApp.getState().loadProviders}
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
  )
  const toolsPage = () => (
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
      // (The skills agents proposed: Ready for you's rows of them; their yes is on their card there.)
      proposals={waiting.flatMap(item => (item.what === 'card' && item.row.what === 'skill' ? [item.row.item] : []))}
      onReady={openReady}
    />
  )
  const readyPage = () => (
    <ReadyPage
      items={waiting}
      openChat={openChat}
      // (The night's whole report: its node on the canvas, as its chat's "On the canvas" opens it.)
      onReport={
        away?.started_at
          ? () =>
              void useApp
                .getState()
                .openTurn(away.conversation_id, away.run_id)
                .then(() => {
                  useApp.getState().select('away:' + away.id)
                  show('canvas')
                })
          : undefined
      }
      // (The open folder's decision log: none for a plain chat's.)
      decisions={
        projectId
          ? {
              onLoad: decisionsOf,
              leftAt: away?.started_at ?? null,
              asked: decisionsAsked,
              onOpened: decisionsOpened,
              onOpenChat: id => void openChat(id),
            }
          : undefined
      }
      todo={todoHalf()}
      // (Its tab's count: the tasks not done - proposals wait on Ready for you -, once the list is read.)
      todoOpen={
        project && backlog ? backlog.filter(task => task.status !== 'proposed' && task.status !== 'done').length : null
      }
    />
  )
  // The tasks whose push the night parked for you and you have not decided: their cells on To-do say so.
  const pushes = new Set(
    waiting.flatMap(item => (item.what === 'parked' && item.row.kind === 'push' ? [item.row.task_id] : [])),
  )
  /** To-do, Work's second tab (0.1.10). */
  const todoHalf = () =>
    !project ? (
      <section className="todo-half" aria-labelledby="todo-head">
        <h2 id="todo-head" tabIndex={-1}>
          To-do
        </h2>
        {noFolder('To-do')}
      </section>
    ) : (
      <BacklogPage
        key={project.id}
        asked={todoAsked}
        pushes={pushes}
        // (The settings over it, or Ready for you's tab shown: a narrow window's story leaves the rail, the top bar and
        // the tabs within reach.)
        covered={settingsOpen || readyTab !== 'todo'}
        backlog={backlog}
        error={backlogError}
        drafter={drafter}
        away={away}
        providers={providers}
        onAdd={useApp.getState().addTask}
        onDraft={useApp.getState().draftTasks}
        onAddTree={useApp.getState().addTree}
        onPlan={async message => {
          await useApp.getState().newConversation(project.id)
          await useApp.getState().send(message)
          setView('canvas')
        }}
        onChange={useApp.getState().changeTask}
        onDelete={useApp.getState().deleteTask}
        onDecide={useApp.getState().decideTask}
        onDoInChat={async (ids, cid) => {
          await doInChat(ids, cid)
          setView('canvas')
        }}
        onOpen={id => {
          void useApp.getState().openConversation(id)
          setView('canvas')
        }}
        stories={stories}
        chats={Object.fromEntries(chatList.map(chat => [chat.id, chat.title]))}
        projectId={project.id}
        tree={{
          onStory: useApp.getState().changeStory,
          onDeleteStory: useApp.getState().deleteStory,
          onNewStory: title => useApp.getState().addStory(title),
        }}
      />
    )
  const usagePage = () => (
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
      decisions={projectId ? period => <DecidedToday onLoad={decisionsOf} period={period} /> : undefined}
      onOpen={id => {
        void useApp.getState().openConversation(id)
        setView('canvas')
      }}
    />
  )
  // 0.1.10: Memory's two parts are one page, the same for either view (what is typed in one stays as the other is shown).
  const memoryPage = () =>
    !project ? (
      noFolder('Memory')
    ) : (
      <MemoryPage
        key={project.id}
        sources={view === 'knowledge'}
        onPart={sources => setView(sources ? 'knowledge' : 'memory')}
        sourcesPart={knowledgePart(project)}
        old={knowledge ? knowledge.filter(item => mayBeOld(item.state)).length : null}
        linked={projects.filter(one => project.memory_links?.includes(one.id)).map(one => one.name)}
        onLinked={() => useApp.getState().askSettings('memory')}
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
        onSaveProjectNotes={async text => {
          if (projectId) await api.put(`/projects/${projectId}/project-notes`, { text })
          await useApp.getState().loadMemory()
        }}
        onSavePreferences={useApp.getState().savePreferences}
        onAddPreference={useApp.getState().addPreference}
        onReload={useApp.getState().loadMemory}
        onSearch={useApp.getState().searchMemory}
        onExport={projectId ? () => download('GET', `/projects/${projectId}/memory/export`) : undefined}
      />
    )
  const knowledgePart = (project: Project) => (
    <KnowledgePage
      items={knowledge}
      error={knowledgeError}
      projectName={project.name}
      providers={providers}
      otherProjects={projects.filter(one => one.id !== project.id)}
      roles={roles}
      onUse={useApp.getState().useKnowledge}
      onReload={useApp.getState().loadKnowledge}
      onAdd={useApp.getState().addKnowledge}
      onSave={useApp.getState().saveKnowledge}
      onDelete={useApp.getState().deleteKnowledge}
      onLearn={useApp.getState().learnKnowledge}
      onTry={useApp.getState().tryKnowledge}
      onCopy={useApp.getState().copyKnowledge}
      onReadFile={useApp.getState().knowledgeFile}
    />
  )
  const conversationsPage = () => (
    <ConversationList
      conversations={conversations}
      projects={projects}
      board={everywhere}
      onArchive={useApp.getState().archiveConversation}
      onDelete={useApp.getState().deleteConversations}
      currentId={conv?.conversation.id ?? null}
      onRefresh={useApp.getState().loadConversations}
      // (What waits for your word: the pill's own rows - each chat's on its row, all of them counted in Now.)
      waiting={waiting}
      readChats={[...(conv ? [conv.conversation.id] : []), ...Object.keys(readyChats)]}
      onReady={openReady}
      onOpen={id => {
        void useApp.getState().openConversation(id)
        setView('canvas')
      }}
      onNew={() => {
        void useApp.getState().newConversation()
        setView('canvas')
      }}
    />
  )

  /** First steps, over the canvas. */
  const stepsCard = () => (
    <FirstSteps
      health={health}
      project={projects.length > 0}
      folder={project?.root_path ?? null}
      // (The list may be read before the first send: the open chat's own turn says it at once.)
      wrote={conversations.some(c => c.wrote) || (conv?.runs.length ?? 0) > 0}
      turn={conv ? conv.runs.length > 0 : conversations.some(c => !c.archived_at) ? undefined : false}
      again={stepsAgain}
      providers={providers}
      pinned={!!providerOpen}
      onProvider={() => go('models', 'new')}
      onUse={makeDefaultAndRead}
      onHidden={() => setStepsAgain(false)}
      onSaysProvider={setStepsSayProvider}
    />
  )
  /** The open chat's teams, over the canvas. */
  const chatTeams = () =>
    conv && (
      <ChatTeams
        conversation={conv.conversation}
        agents={conv.agents}
        runs={conv.runs}
        onStop={useApp.getState().stopTeam}
        onFinish={useApp.getState().finishTeam}
        teams={teams}
        onRecipes={() =>
          useApp
            .getState()
            .recipes(null)
            .then(read => read.recipes)
        }
        onChange={useApp.getState().setChatTeams}
        project={project && conv.conversation.project_id === project.id ? project : null}
        onDefault={useApp.getState().saveProjectSettings}
        roles={roles}
        providers={providers}
        onRoleModels={() => useApp.getState().roleModels(conv.conversation.id)}
        // (The role's own model, as "A model of its own" on its card sets it: no tier left to pick another.)
        onRunOn={(roleId, providerId, modelId) =>
          useApp.getState().patchRole(roleId, {
            provider_id: providerId,
            model_id: modelId,
            tier: null,
            tier_min: null,
            tier_max: null,
          })
        }
      />
    )
  const canvasPage = () => (
    <>
      {/* The canvas fills the stage; the chat lies over its left edge, open, or its bottom left corner, closed. */}
      {/* The window over the canvas pressed or used last is the one in front. */}
      <div
        className="stage"
        onPointerDownCapture={event => frontOf(event.target)}
        onFocusCapture={event => frontOf(event.target)}
      >
        <ChatPanel />
        {stepsCard()}
        <CanvasView
          key={conv?.conversation.id ?? 'none'}
          state={conv}
          selectedId={selectedNodeId}
          onSelect={select}
          turnId={turnId}
          onTurn={useApp.getState().showTurn}
          onRenameTopic={useApp.getState().renameTopic}
          over={agentWindowId ?? discussionWindowId}
          turnsIn={turnsIn}
          onOpenNode={(kind, refId) => {
            if (kind === 'agent') useApp.getState().openAgentWindow(refId)
            if (kind === 'discussion') useApp.getState().openDiscussion(refId)
            if (kind === 'memory') setView('memory')
            // (The Scout's node, opened, or its To-do →.)
            if (kind === 'po' || kind === 'backlog') openTodo()
          }}
          onOpenList={() => useApp.getState().showReady(true)}
          onStopTeam={useApp.getState().stopTeam}
          onFinishTeam={useApp.getState().finishTeam}
          teams={teams}
        />
        {chatTeams()}
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
        {...agentAsks}
        renderChange={change => (
          <>
            <ChangeActions key={change.id} change={change} onDecide={action => decide(change.id, action)} />
            <div className="insp-diff">
              <DiffView diff={change.diff} />
            </div>
          </>
        )}
      />
    </>
  )
  /** Each page of the rail but the canvas, by its view. */
  const pageOf: Partial<Record<View, () => ReactNode>> = {
    agents: agentsPage,
    models: modelsPage,
    tools: toolsPage,
    ready: readyPage,
    usage: usagePage,
    memory: memoryPage,
    knowledge: memoryPage,
    conversations: conversationsPage,
  }
  /** The page shown: the one of its view, else the canvas. */
  const page = () => (pageOf[view] ?? canvasPage)()

  /** The toasts, with their bell in the top bar. */
  const toasts = () => (
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
  )

  /** Ready for you's panel, over every page but its own. */
  const readyPanelOver = () =>
    panelShown && (
      <ReadyPanel
        items={waiting}
        openChat={openChat}
        onPage={() => {
          useApp.getState().showReady(false)
          openReady()
        }}
        onClose={() => useApp.getState().showReady(false)}
      />
    )

  /** Ctrl+K: the pages, Settings, the chats, roles, models, tool servers and settings, and the first steps again. */
  const palette = () => {
    const places: Place[] = [
      ...PAGES.map(([page, name]) => ({ kind: 'Page', name, go: () => show(page) })),
      { kind: 'Page', name: 'Work › Ready for you', go: openReady },
      { kind: 'Page', name: 'Work › To-do', go: () => openTodo() },
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
      ...settingsPlaces(!!project).map(({ place, name, also }) => ({
        kind: 'Setting',
        name,
        also,
        go: () => useApp.getState().askSettings(place),
      })),
      { kind: 'Help', name: 'Show the first steps', go: firstSteps },
    ]
    return (
      <Palette
        places={places}
        onOpen={() =>
          void useApp
            .getState()
            .loadMcpServers()
            .catch(() => {})
        }
        onSearch={words => go('memory', words)}
      />
    )
  }

  return (
    <div className="app">
      {/* Under the project's settings no page of the rail is the one shown. */}
      {rail()}
      {/* Focusable only from code: it takes the focus back from something that went (a dismissed notice). */}
      <div className="main" tabIndex={-1}>
        {topBar()}
        <ModelBanner
          readings={barReadings}
          cannot={barCannot}
          quietFor={stepsSayProvider}
          onModels={() => show('models')}
        />
        {/* The page was built from other code than its server runs: what it reads may not be there. A server
            from before slice 65 does not say, and is other code too. */}
        {banner()}
        {openChats()}
        {conflicts()}
        {settingsPage()}
        {/* Hidden, not gone, under the settings: a message being typed and an open window stay. */}
        <div className="workspace" hidden={settingsOpen}>
          {/* (Memory's two parts are one page: what is typed in one stays as the other is shown.) */}
          <PageGuard key={view === 'knowledge' ? 'memory' : view}>{page()}</PageGuard>
        </div>
      </div>
      {toasts()}
      {readyPanelOver()}
      <AskAboutThis />
      {palette()}
    </div>
  )
}
