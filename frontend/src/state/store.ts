import { create } from 'zustand'
import { api, errorText } from '../api/client'
import { openEvents } from '../api/sse'
import type {
  Agent,
  AllowedCommand,
  Attachment,
  Availability,
  Away,
  AwayAsk,
  AwayChange,
  BacklogAuto,
  BacklogChoice,
  BacklogTask,
  BacklogTaskChange,
  Board,
  Day,
  DayWords,
  CatalogueDraft,
  Compare,
  CatalogueFill,
  CatalogueUpdate,
  LocalServer,
  LocalServerConfig,
  FilledProvider,
  FillAll,
  TierOrder,
  Tiers,
  CataloguePrice,
  Conversation,
  ConversationsDeleted,
  ClaudeSessionSetup,
  Knowledge,
  KnowledgeIn,
  KnowledgeItem,
  KnowsMode,
  Limits,
  ModelFacts,
  Suggestion,
  PermissionMode,
  FileChange,
  Health,
  FolderBrowse,
  InjectionWarning,
  ListedConversation,
  McpRead,
  McpServer,
  BuiltinTool,
  Skill,
  SkillPreview,
  SkillSource,
  McpServerChange,
  NewMcpServer,
  NewOwnCommand,
  OwnCommand,
  NewRoom,
  Price,
  Project,
  ProjectFile,
  Question,
  MemorySearch,
  NewBacklogTask,
  ProjectMemory,
  Provider,
  ProviderTest,
  RawLines,
  RecordRow,
  SkillRecordRow,
  Role,
  RoleModel,
  Run,
  Snapshot,
  Topic,
  Trigger,
  TriggerChange,
  TriggerCreated,
  TriggerLogEntry,
  NotesOffer,
  TriggerProposal,
  NewTrigger,
  Category,
  Usage,
  Budget,
  Team,
  RolesActivity,
  RolesHistory,
  Recipe,
  RecipeDraft,
  BacklogDraft,
  Recipes,
} from '../api/types'
import type { RoleValues } from '../agents/AgentsPage'
import type { RoleChange } from '../agents/RolePanel'
import type { RecipeActions } from '../agents/RecipesTab'
import type { TeamActions } from '../agents/TeamsBoard'
import type { CategoryActions } from '../agents/RoleLibrary'
import type { TeamsChange } from '../agents/ChatTeams'
import type { ModelChoice } from '../models/ModelPicker'
import type { OfferedModels } from '../models/ModelNameInput'
import type { NewProvider, ProviderChange } from '../models/ModelsPage'
import type { NewFact } from '../memory/forms'
import type { ProjectSettingsValues } from '../shell/ProjectSettings'
import type { SettingsPlace } from '../shell/Settings'
import { startsNewTurn } from '../canvas/turns'
import { inUseBy } from '../shell/inUse'
import type { Cannot } from '../shell/ModelBanner'
import { chatOf, closing, kept, opened, remember, rememberChat, remembered, tabOf } from '../shell/openTabs'
import type { Allow } from '../triggers/triggerText'
import { keyOf } from '../views/views'
import { waitCount } from '../board/waiting'
import { activeRun, applyEvent, fromSnapshot, type ConvState } from './applyEvent'

/** K-dal-takim D2: what else Merge says on a branch's card - keep the branch after it, and which way finished work goes. */
export interface BranchSaid {
  keep_branch?: boolean
  way?: 'merge' | 'pull_request'
}

/** The tabs of the chat panel. (A room has a window of its own over the canvas: AC.) */
export type ChatTab = 'Chat' | 'Talk' | 'Notes'

interface AppStore extends TeamActions, RecipeActions, CategoryActions {
  ready: boolean
  /** Why the first load failed, if it did. */
  loadError: string | null
  projects: Project[]
  /** The open chat's folder (slice 86a): null for a plain chat, or before any chat is open. */
  projectId: string | null
  /** Every chat, of every folder and of none, the latest first. */
  conversations: ListedConversation[]
  /** Read the conversations again: what the list says of each is as old as its last reading. */
  loadConversations(): Promise<void>
  roles: Role[]
  /** The teams of roles (slice 62), and the roles' categories (63b), read with the roles. */
  teams: Team[]
  categories: Category[]
  providers: Provider[]
  conv: ConvState | null
  /**
   * What the user has written and not sent, by conversation (before there is one, by project:
   * "new in <project id>"): kept
   * here, not in the message box, which goes when another page or a hidden chat takes its place.
   */
  drafts: Record<string, string>
  setDraft(conversationId: string, text: string): void
  health: Health | null
  /** What /health says of each provider the chat open then (`of`; null: none, a new one) would run on (`inUseBy`), and of its roles that cannot run, what the bar says. */
  inUse: { of: string | null; readings: Health[]; cannot: Cannot[] } | null
  connection: 'open' | 'reconnecting'
  selectedNodeId: string | null
  /** The agent whose own window is open, if any. */
  agentWindowId: string | null
  /** Whether that window opened with More open on what the agent's CLI wrote itself (its raw stream). */
  agentWindowRaw: boolean
  /** Opens the agent's window - with `raw`, More open on its raw stream. */
  openAgentWindow(agentId: string, raw?: boolean): void
  /** Its More opened or folded in the window: the flag follows it. */
  showAgentRaw(raw: boolean): void
  closeAgentWindow(): void
  /** The discussion whose shared place is open, if any. */
  discussionWindowId: string | null
  openDiscussion(discussionId: string): void
  closeDiscussion(): void
  /** Speak in a discussion, or end it. Both throw ApiError. */
  sayInDiscussion(discussionId: string, content: string): Promise<void>
  endDiscussion(discussionId: string): Promise<void>
  /**
   * How each room's window stands, by the room's id (AC): open, or made small - a tab at the
   * canvas's foot. A room not here has no window; a running one still has its tab.
   */
  roomWindows: Record<string, 'open' | 'small'>
  /** Open a room's window (another open one is made small), the focus going into it. */
  showRoom(roomId: string): void
  /** Make a room's window small: a tab, which the focus goes to. */
  shrinkRoom(roomId: string): void
  /** Close a room's window: a room that is over leaves the canvas (its line in the chat opens it again). */
  closeRoom(roomId: string): void
  /** The tab of the chat panel that is shown. */
  chatTab: ChatTab
  /**
   * Show a tab of the chat; `open`: the chat too, if it is closed; `at`: the element of the tab, by its id, to bring
   * into view - a card, a note.
   */
  showChatTab(tab: ChatTab, open?: boolean, at?: string): void
  /** How many times the chat was asked to open (`showChatTab` with `open`): it opens on each. */
  chatOpenAsked: number
  /** What `showChatTab` was last asked to bring into view; null: nothing. */
  chatAt: string | null
  /** Ready for you's panel (tek-ev §1): open or not, and the row it was asked to bring into view. */
  readyPanel: { open: boolean; at: string | null }
  showReady(open: boolean, at?: string): void
  /** A place in Settings asked for (Ctrl+K, a chat's "run without asking" link, a page's link), each time with a new count: Settings opens on it. */
  settingsAsked: { section: SettingsPlace; n: number } | null
  askSettings(section: SettingsPlace): void
  /** The other chats where something waits, as the Board counts them, read whole: their cards on Ready for you. */
  readyChats: Record<string, ConvState>
  /** Read the chats whose Board row changed since; `again`: that one too, whatever its row says (a decision made on it) - `true`: all of them. */
  loadReadyChats(again?: string | true): Promise<void>
  /** Open a room in the open conversation: a turn of its own, whose message is the goal. Throws ApiError. */
  openRoom(room: NewRoom): Promise<void>
  /** Speak in a room, end it, or add to what it may spend. All throw ApiError. */
  sayInRoom(roomId: string, text: string): Promise<void>
  endRoom(roomId: string): Promise<void>
  /** 29c: pause a running room (true) or resume it (false). Throws ApiError. */
  pauseRoom(roomId: string, paused: boolean): Promise<void>
  /** K-oda-izle: let the turn's Lead follow a room the user opened (true), or stop it. Throws ApiError. */
  followRoom(roomId: string, on: boolean): Promise<void>
  giveRoomMore(roomId: string, more: { posts?: number; tokens?: number; minutes?: number }): Promise<void>
  /**
   * The open project's memory, once something asked for it; null until then. How a source
   * stands is as of the last reading: a file can change on disk without a word.
   */
  memory: ProjectMemory | null
  /** Why the memory could not be read, if it could not. */
  memoryError: string | null
  loadMemory(): Promise<void>
  /** The user's decisions on the memory; each throws ApiError, and the memory is read again. */
  approveMemory(memoryId: string, text?: string): Promise<void>
  rejectMemory(memoryId: string): Promise<void>
  restoreMemory(memoryId: string): Promise<void>
  /** Of a source that moved: these are the same lines. */
  confirmMemory(memoryId: string): Promise<void>
  correctMemory(memoryId: string, changes: { text: string; about: string | null }): Promise<void>
  writeFact(fact: NewFact): Promise<void>
  saveRules(rules: string): Promise<void>
  /** Your own preferences (22b), one text for every project; and a suggested line into them. Each throws ApiError. */
  savePreferences(text: string): Promise<void>
  addPreference(memoryId: string): Promise<void>
  /** What an agent's `recall` would find for these words, in the open project. Throws ApiError. */
  searchMemory(query: string): Promise<MemorySearch>
  /** The open project's backlog, in order, once its page asked for it; null until then. */
  backlog: BacklogTask[] | null
  backlogError: string | null
  /** Its switch, read with it; null until then. */
  backlogAuto: BacklogAuto | null
  loadBacklog(): Promise<void>
  /** Turn on or off the backlog running by itself (off drops what Run the backlog queued). Throws ApiError. */
  setBacklogAuto(on: boolean): Promise<void>
  /** The level and model the chats the backlog opens from now start with (B-350). Throws ApiError. */
  setBacklogChoice(choice: BacklogChoice): Promise<void>
  /** The user's changes to the backlog; each throws ApiError, and the backlog and the board are read again. */
  addTask(task: NewBacklogTask): Promise<void>
  changeTask(taskId: string, change: BacklogTaskChange): Promise<void>
  deleteTask(taskId: string): Promise<void>
  decideTask(taskId: string, decision: 'approve' | 'reject'): Promise<void>
  /** OK to the Orchestrator's word on a proposal of the Assistant PO's at Full auto: it leaves "Decided for you". Throws ApiError. */
  seenTask(taskId: string): Promise<void>
  /** Run the backlog: every todo task is queued, and they start as there is room, each in a new conversation. Throws ApiError. */
  runBacklog(): Promise<void>
  /** What the user typed, written as tasks by a model asked once ("Write it with the Product owner"); nothing is saved. Throws ApiError. */
  draftTasks(text: string): Promise<BacklogDraft>
  /** The open project's night while you're away (slice 106): the one that runs, else its last; null: none, or not read yet. */
  away: Away | null
  loadAway(): Promise<void>
  /**
   * Your word on a "While you're away" card or its night: a change to the card (before Start), Start,
   * Not now, Stop all, or Try again for a job. The card and the night are read again. Throws ApiError.
   */
  awayDo(awayId: string, action: 'change' | 'start' | 'dismiss' | 'stop' | `jobs/${string}/again`, change?: AwayChange): Promise<void>
  /** Yes or no to what a waiting job asks, at its own endpoint (Allow and go on, Refuse). Throws ApiError. */
  answerAsk(ask: AwayAsk, yes: boolean): Promise<void>
  /** Take in a job's kept copies, one after another (Take in, Take in all). Throws ApiError. */
  takeIn(mergeIds: string[]): Promise<void>
  /**
   * The open project's triggers, once they have been read; null until then. Triggers start
   * turns with nobody watching, so only this page - the user - makes or changes one.
   */
  triggers: Trigger[] | null
  triggersError: string | null
  /** The newest things done to the project's triggers, those of deleted ones among them; null until read. */
  triggerChanges: TriggerLogEntry[] | null
  /** Every trigger of every project is held back, and none starts a turn. */
  triggersPaused: boolean
  loadTriggers(): Promise<void>
  /** Each of these throws ApiError with the server's reason; the triggers are read again after. */
  createTrigger(values: NewTrigger): Promise<TriggerCreated>
  /** A webhook's key made anew: the old address stops; the answer carries the new key, this once. */
  newTriggerKey(triggerId: string): Promise<TriggerCreated>
  saveTrigger(triggerId: string, change: TriggerChange): Promise<void>
  deleteTrigger(triggerId: string): Promise<void>
  /** "Run now": the trigger's turn, with nobody asked. Answers with the turn's id. */
  runTrigger(triggerId: string): Promise<string>
  pauseTriggers(paused: boolean): Promise<void>
  /** The allow list of one of the project's conversations: the commands a trigger there can be let run. */
  allowedCommandsOf(conversationId: string): Promise<AllowedCommand[]>
  /** The hosts one of the project's conversations makes GET requests to without asking: the ones a trigger there can be given. */
  allowedHostsOf(conversationId: string): Promise<string[]>
  /** Put a command on a conversation's allow list. It then also runs unasked in that conversation's own turns. */
  addAllowedCommand(conversationId: string, prefix: string): Promise<AllowedCommand>
  /**
   * Something a turn was refused, to be allowed in its trigger: the Triggers page opens that
   * trigger's form with it filled in. Nothing is saved until the user saves.
   */
  triggerDraft: { triggerId: string; allow: Allow } | { proposal: TriggerProposal } | null
  allowInTrigger(triggerId: string, allow: Allow): void
  clearTriggerDraft(): void
  /** An agent's proposed trigger (slice 69): Approve makes it as shown, with the safest leave; Reject puts it away. Throws ApiError. */
  decideProposal(proposalId: string, decision: 'approve' | 'reject'): Promise<void>
  /** Your word on a Project notes offer (K-bilgi 6): the lines its card showed and those ticked (none: Not now). Throws ApiError; the offers are read again either way. */
  answerNotesOffer(offerId: string, lines: string[], add: string[]): Promise<void>
  /** Edit on a proposed trigger's card: the Triggers page opens a new trigger's form with it filled in. Nothing is saved until you save. */
  editProposal(proposal: TriggerProposal): void
  /** Write a note on a turn's shared notebook. Throws ApiError. */
  writeNote(runId: string, content: string): Promise<void>

  /** The first load: the folders and the chats, and the newest chat not put away opened (none: the first message makes a plain one). */
  loadProjects(): Promise<void>
  /** The open chat's main folder changed (null: no folder); with no chat yet, a new one there. Throws ApiError (409: why it may not). */
  setFolder(projectId: string | null): Promise<void>
  /** A folder of the disk made a project (one that is already is answered with). Throws ApiError (422: why it may not). */
  openFolder(path: string): Promise<Project>
  /** The folders in one folder (null: the home folder), for the folder browser. Throws ApiError. */
  browseFolders(path: string | null): Promise<FolderBrowse>
  loadHealth(): Promise<void>
  loadRoles(): Promise<void>
  loadProviders(): Promise<void>
  /** Provider edits; each throws ApiError with the server's reason. */
  createProvider(values: NewProvider): Promise<void>
  saveProvider(providerId: string, values: ProviderChange): Promise<void>
  deleteProvider(providerId: string): Promise<void>
  makeDefaultProvider(providerId: string): Promise<void>
  testProvider(providerId: string, run?: boolean): Promise<ProviderTest>
  /** Model names a provider can offer; never throws for a provider that lists none. */
  providerModels(providerId: string): Promise<OfferedModels>
  /** A team guide proposed from the catalogue; nothing is saved. Throws ApiError. */
  fillFromCatalogue(providerId: string): Promise<CatalogueFill>
  /** The same for a provider not added yet: the catalogue only. Throws ApiError. */
  fillNewFromCatalogue(draft: CatalogueDraft): Promise<CatalogueFill>
  /** Whether each model can be used now; runs no model. Throws ApiError. */
  /** With `free`, only what costs nothing: whether a CLI's command is on this machine. */
  availability(providerId: string, free?: boolean): Promise<Availability>
  /** What is known of a model on a provider: the one being picked. Throws ApiError. */
  modelFacts(providerId: string, model: string): Promise<ModelFacts>
  /** For a provider not added yet: the catalogue's names, a service's address and key name. Throws ApiError. */
  suggest(kind: string, baseUrl: string | null): Promise<Suggestion>
  /** Downloads models.dev's list and keeps it as the catalogue: only ever the user's button. Throws ApiError. */
  updateCatalogue(): Promise<CatalogueUpdate>
  /** Which catalogue is read: its date and counts. Throws ApiError. */
  catalogue(): Promise<CatalogueUpdate>
  /** "Keep the catalogue fresh": downloaded again at the start once a week old. Throws ApiError. */
  keepCatalogueFresh(on: boolean): Promise<CatalogueUpdate>
  /** The model server on this machine: how it is and what it printed. Throws ApiError. */
  localServer(): Promise<LocalServer>
  /** Only ever the user's buttons: its program and arguments kept (when given), then it is started, stopped or started anew. Throws ApiError. */
  runLocalServer(action: 'start' | 'stop' | 'restart', config?: LocalServerConfig): Promise<LocalServer>
  /** Every provider's tiers proposed from the catalogue; nothing is saved. Throws ApiError. */
  fillAll(): Promise<FillAll>
  /** The proposal as the user left it, saved in one go. Throws ApiError. */
  saveFillAll(providers: FilledProvider[]): Promise<void>
  /** Each tier's models in the order they are tried. Throws ApiError. */
  tiers(): Promise<Tiers>
  /** That order as the user set it; the same models as now, each once. Throws ApiError. */
  saveTiers(order: TierOrder): Promise<Tiers>
  /** What the user says models cost: read when the Usage page opens. */
  prices: Price[]
  /** models.dev's price of the models in use, where the user wrote none: read with them. */
  cataloguePrices: CataloguePrice[]
  loadPrices(): Promise<void>
  /** Write, or take away, a model's price. Each throws ApiError. */
  savePrice(price: Price): Promise<void>
  removePrice(modelId: string): Promise<void>
  /** What the agents' models reported, in one project or (null) in all, from a moment on (null: all of it). Throws ApiError. */
  usage(projectId: string | null, since: string | null, runId?: string): Promise<Usage>
  /** The open project's day from a moment on, counted from the record. Throws ApiError. */
  day(since: string): Promise<Day>
  /** The day's numbers in words, by a conversation's model: asked once; `overBudget`: the user's word to ask it over the month's budget. Throws ApiError. */
  dayWords(since: string, conversationId: string, overBudget?: boolean): Promise<DayWords>
  /** This month's spend of the open project against its budget; null till read. */
  budget: Budget | null
  loadBudget(): Promise<void>
  /**
   * The project's board: every conversation's agents at work, and where two conversations want
   * one file. Read when a conversation opens and whenever its events say something moved; the
   * events of the project's other conversations do not come here, so its page reads it again.
   */
  board: Board | null
  boardError: string | null
  /** Every chat's board, of every folder and of none (slice 86a): what waits for the user anywhere. Read with the board. */
  everywhere: Board | null
  loadBoard(): Promise<void>
  /** K-board-sonuc: a new turn in which the Lead opens again its last turn's sub-agents that failed, timed out or went silent. Throws ApiError. */
  rerunFailed(conversationId: string): Promise<void>
  /** What is known of what is left of a provider's plan; `afresh` has it read now: Codex is asked, which starts it, or Claude Code runs one short turn. Throws ApiError. */
  limits(providerId: string, afresh: boolean): Promise<Limits>
  /** The status line command the user adds to their Claude Code settings to keep its reading fresh. Throws ApiError. */
  claudeSetup(): Promise<ClaudeSessionSetup>
  /** For every role, what its agent would run on now in this conversation (null: in a new one); `levels`: with the levels each model takes, which asks the providers. Throws ApiError. */
  roleModels(conversationId: string | null, levels?: boolean): Promise<RoleModel[]>
  /** What was measured of the agents that ended in the last 30 days, by role and model. Throws ApiError. */
  record(): Promise<RecordRow[]>
  /** The same, by skill as well (K-skill-puan): a row for each skill given to the agents of a role and model. Throws ApiError. */
  skillRecord(): Promise<SkillRecordRow[]>
  /**
   * What an agent's CLI wrote itself, from the line numbered after `after` on: as much as one answer carries.
   * Kept nowhere here: its view holds it. `signal` gives the request up. Throws ApiError.
   */
  rawStream(agentId: string, after: number, signal?: AbortSignal): Promise<RawLines>
  /** Choose the model this conversation's agents use. Throws ApiError. */
  setModelChoice(choice: ModelChoice): Promise<void>
  /** Role edits; each throws ApiError with the server's reason. */
  saveRole(roleId: string, values: RoleValues): Promise<void>
  /** Answers with the role made (a stage's "New role…" puts it in that stage). */
  createRole(values: RoleValues): Promise<Role>
  deleteRole(roleId: string): Promise<void>
  resetRole(roleId: string): Promise<void>
  /** A role's kind, on / off or teams, changed at once. Throws ApiError. (A team's changes: `TeamActions`.) */
  patchRole(roleId: string, change: RoleChange): Promise<void>
  /** What the Agents page draws from the record, and a role's latest jobs. Each throws ApiError. */
  roleActivity(): Promise<RolesActivity>
  roleHistory(days: number): Promise<RolesHistory>
  /** K-bilgi: the open project's Knowledge page (with every project's knowledge); null until read. */
  knowledge: KnowledgeItem[] | null
  knowledgeError: string | null
  loadKnowledge(): Promise<void>
  /** Each of these throws ApiError with the server's reason; the page is read again after. */
  addKnowledge(body: KnowledgeIn): Promise<KnowledgeItem>
  saveKnowledge(knowledgeId: string, body: Knowledge): Promise<void>
  deleteKnowledge(knowledgeId: string): Promise<void>
  learnKnowledge(knowledgeId: string): Promise<void>
  /** Its guide copied into another of the user's projects; a guide's section read. */
  copyKnowledge(knowledgeId: string, toProjectId: string, replace?: boolean): Promise<void>
  knowledgeFile(path: string): Promise<ProjectFile>
  /** Try it: a question answered as an expert in it would, from its guide here. */
  tryKnowledge(knowledgeId: string, question: string): Promise<string>
  /** A new expert at once: the role, its knowledge in the open project, the role using it in full. */
  createExpert(role: RoleValues, knowledge: Knowledge): Promise<Role>
  /** A role uses it in full, as a map, or (null) no more; the roles are read again. */
  useKnowledge(knowledgeId: string, roleId: string, mode: KnowsMode | null): Promise<void>
  /** The MCP servers the user connected: read when the Tools page opens. */
  mcpServers: McpServer[]
  loadMcpServers(): Promise<void>
  /** Server edits; each throws ApiError with the server's reason. Adding one answers with it. */
  addMcpServer(values: NewMcpServer): Promise<McpServer>
  saveMcpServer(serverId: string, change: McpServerChange): Promise<void>
  deleteMcpServer(serverId: string): Promise<void>
  /** Start a server once and keep the tools it lists (osv: osv.dev asked first; inProject: its files from a project, as the
   * reading before told them, which the user said to start anyway); answers what that reading found. Throws ApiError. */
  readMcpServer(serverId: string, osv: boolean, inProject?: Record<string, string | null>): Promise<McpRead>
  /** Say which MCP servers (their names) a role's agents may use. Throws ApiError. */
  setRoleServers(roleId: string, mcp: string[]): Promise<void>
  /** KOLONİ's own tools the Tools page switches on or off for every agent (slice 61). */
  builtinTools: BuiltinTool[]
  loadBuiltinTools(): Promise<void>
  /** Throws ApiError. */
  switchBuiltinTool(name: string, on: boolean): Promise<void>
  /** The user's own slash commands offered in this project (its own and every project's): read with the project. */
  ownCommands: OwnCommand[]
  loadOwnCommands(): Promise<void>
  /** Add one (id null) or change one, the whole of it; delete one. Each throws ApiError with the server's reason. */
  saveOwnCommand(commandId: string | null, values: NewOwnCommand): Promise<void>
  deleteOwnCommand(commandId: string): Promise<void>

  /** The skills KOLONİ keeps: read with the roles. */
  skills: Skill[]
  loadSkills(): Promise<void>
  /** What would be kept of a folder or a GitHub repository, before you say yes; nothing is kept. Throws ApiError. */
  previewSkill(source: SkillSource): Promise<SkillPreview>
  /** Keep a copy of a skill, if it is still what its preview's sum says; answers with it. `replace`: in place of the one of its name. Throws ApiError. */
  addSkill(source: SkillSource, scriptsRunUnasked: boolean, sha256: string, replace?: boolean): Promise<Skill>
  /** Give a skill's scripts leave to run without asking, or take it away. Throws ApiError. */
  setSkillLeave(skillId: string, scriptsRunUnasked: boolean): Promise<void>
  /** Switch a skill on or off for every role (off: given to none). Throws ApiError. */
  setSkillOn(skillId: string, on: boolean): Promise<void>
  /** Delete a kept skill: every role loses it. Throws ApiError. */
  deleteSkill(skillId: string): Promise<void>
  openConversation(id: string): Promise<void>
  /** The tabs over the canvas, one per project - its id, or 'none' - in their order (slice 86e); remembered in this browser. */
  tabs: string[]
  /** Go to a project's tab: the chat opened last in it, else its newest, else a new one in it. */
  openTab(tab: string): Promise<void>
  /** Close a project's tab - no chat goes; closing the open one opens its neighbour. */
  closeTab(tab: string): Promise<void>
  /** A new chat, opened: in `projectId` (null: no folder), or else in the open chat's folder. */
  newConversation(projectId?: string | null): Promise<void>
  /** Put a conversation away (true) or bring it back; the list is read again. Throws ApiError. */
  archiveConversation(id: string, archived: boolean): Promise<void>
  /** Delete archived conversations for good (slice 76): the open one gives way to another. Throws ApiError. */
  deleteConversations(ids: string[]): Promise<ConversationsDeleted>
  /** Delete a project from KOLONİ (its folder stays): its tab goes, and an open chat of it gives way to another. Throws ApiError. */
  deleteProject(projectId: string): Promise<void>
  /**
   * Send a message; while a run is active the server queues it. Throws ApiError. `where`
   * names the topic it goes on with, or asks for a new one; with neither the server takes
   * the topic the user was last in.
   */
  send(
    content: string,
    where?: { topic_id?: string; new_topic?: boolean; spoken?: { language: string; style?: string }; over_budget?: boolean; attachments?: string[]; save_to_project?: boolean },
  ): Promise<void>
  /** A file added to the next message (slice 85b), shown at once: its event may come a moment later. */
  attached(attachment: Attachment): void
  /** The ×: a file taken off the next message, with its frames. Throws ApiError. */
  detach(attachmentId: string): Promise<void>
  /** Send the message to the conversation's model and to `second`, side by side, each in a working copy of its own (slice 54); `where`: its topic and the word to go over the month's budget, as `send`'s. Throws ApiError. */
  compare(content: string, second: { provider_id: string; model_id: string | null }, where?: { topic_id?: string; new_topic?: boolean; over_budget?: boolean }): Promise<void>
  loadCompare(compareId: string): Promise<Compare>
  /** Take one side's changes into the project (`runId`), or throw both away (null). Throws ApiError. */
  decideCompare(compareId: string, runId: string | null): Promise<Compare>
  /** Name a topic. Throws ApiError. */
  renameTopic(topicId: string, title: string): Promise<void>
  stop(): Promise<void>
  cancelRun(runId: string): Promise<void>
  setPermissionMode(mode: PermissionMode): Promise<void>
  /** Each new message starts with a plan to approve first, or not. */
  setPlanFirst(on: boolean): Promise<void>
  /** K-39-betik: the open chat's pages run their scripts without asking (true), or ask each time. Throws ApiError. */
  setPageScripts(on: boolean): Promise<void>
  /** Approve a plan turn's plan (`text`: as the user edited it) or turn it down (`text`: why); `overBudget`: the user's word to start it over the month's budget. Throws ApiError. */
  decidePlan(runId: string, decision: 'approve' | 'reject', text?: string, overBudget?: boolean): Promise<void>
  /** "False alarm" on a warning of the open chat (93-A4): counted for its rule, once. Throws ApiError. */
  falseAlarm(warningId: number): Promise<void>
  /** Run once, always run (adds an allow-list rule) or reject a waiting command. */
  decideCommand(commandId: string, decision: 'once' | 'always' | 'reject'): Promise<void>
  removeRule(ruleId: string): Promise<void>
  /** Let a waiting web search or HTTP request go out once, always (keeps a rule), or not. */
  decideWeb(requestId: string, decision: 'once' | 'always' | 'reject'): Promise<void>
  removeWebRule(ruleId: string): Promise<void>
  /** Let GET requests to a host the user wrote go without asking. Throws ApiError. */
  allowHost(conversationId: string, host: string): Promise<void>
  /** K-tarayici-disari A3: add a site the user wrote for the chat's project, maybe marked Ask first. Throws ApiError. */
  allowSite(conversationId: string, host: string, askFirst: boolean): Promise<void>
  /** K-tarayici-disari: mark a site the agents' browsers open Ask first, or take the mark off. */
  setAskFirst(ruleId: string, askFirst: boolean): Promise<void>
  /** Open or decline a sub-agent that waits for a decision. Throws ApiError. */
  decideSpawn(agentId: string, decision: 'approve' | 'reject'): Promise<void>
  /**
   * Take an agent's changes into the project - with whose side is taken of each file that clashes, and what its card
   * showed of each file (nothing is taken where one moved since: a 409) - or discard them. Throws ApiError.
   */
  decideMerge(mergeId: string, decision: 'approve' | 'reject', choices?: Record<string, 'agent' | 'project'>, shown?: Record<string, (string | null)[]>, said?: BranchSaid): Promise<void>
  /** K-dal-takim D2: an agent puts a branch's conflicts together in its worktree; the card asks again. Throws ApiError. */
  resolveMerge(mergeId: string): Promise<void>
  /** K-devam-butce: Continue on a stopped agent's kept card - more steps, and it goes on in its copy. Throws ApiError. */
  continueMerge(mergeId: string): Promise<void>
  /** Run the project's check command on what an agent's card would take. Throws ApiError. */
  checkMerge(mergeId: string, choices: Record<string, 'agent' | 'project'>): Promise<void>
  /** Commit the files that were taken from an agent, they alone, with this message. Throws ApiError. */
  commitMerge(mergeId: string, message: string, hooks?: 'with' | 'without'): Promise<void>
  /** Create or decline a role an agent asked for; or let a path outside the project be opened once, for its folder, or not. Throws ApiError. */
  decideRole(toolCallId: string, decision: 'approve' | 'reject', scope?: 'once' | 'folder' | 'ask_scripts'): Promise<void>
  /** The open chat's extra folders, as they are to be (slice 86b). Throws ApiError with why not. */
  setChatFolders(lists: { also_in: string[]; read_in: string[] }): Promise<void>
  /** The part of the folder's map the open chat's agents work in (K-buyuk-proje); null: all of it. Throws ApiError with why not. */
  setChatPart(part: string | null): Promise<void>
  /** The open chat's teams (slice 84b): who picks them, and the user's rows in Manual. Throws ApiError with why not. */
  setChatTeams(change: TeamsChange): Promise<void>
  /** Stop one of the open chat's teams (slice 84b-2): its agents stop at their next step. Throws ApiError. */
  stopTeam(teamId: string): Promise<void>
  /** Finish now on one of its teams' looped recipe (batch-17): its work to Ready for you. Throws ApiError. */
  finishTeam(teamId: string): Promise<void>
  /** Answer a question an agent is waiting on. Throws ApiError. */
  answerQuestion(questionId: string, answer: string): Promise<void>
  /** "Decided for you" (K-vekil-karar): OK to what the Lead answered for you, or your own answer in its place. Throws ApiError. */
  decidedOk(questionId: string): Promise<void>
  decidedChange(questionId: string, answer: string): Promise<void>
  /** Change where the current project's commands run. Throws ApiError. */
  saveProjectSettings(values: ProjectSettingsValues): Promise<void>
  /** Use what the folder's .koloni/settings.json asks for (slice 86c), as the card showed it; the project as it is then saved. Throws ApiError (409: the file changed since). */
  takeKoloniSettings(asks: Project['koloni']['asks']): Promise<Project>
  select(nodeId: string | null): void
  /**
   * The turn the user picked for the canvas to draw; null while the newest turn they
   * started is drawn. A turn of theirs that starts takes the canvas back to itself.
   */
  turnId: string | null
  showTurn(runId: string | null): void
  /** Draw one turn of a conversation, opening that conversation first when it is another. */
  openTurn(conversationId: string, runId: string): Promise<void>

  /** The Workspace window (slices 42c, 42d) is open. */
  filesOpen: boolean
  /** The file it was last asked to open (its path, or 'preview:' and a server's id), and how many times it was asked: asked again, it opens it again. */
  filesAt: { key: string | null; n: number }
  /** Open the Workspace window, optionally on one file - on the project's own files. */
  openFiles(key?: string): void
  /** K-dallar: the branch the Workspace shows read only, by its full name (Look in the git map); null: the project. */
  filesRef: string | null
  lookAt(ref: string): void
  /** The project's branch as the git map last read it (K-dallar: a Take in card says its copy was made on another). */
  gitBranch: string | null
  /** How many times the git map was asked for from outside the top bar ("Show git" in the chat, slice 70). */
  gitAsked: number
  showGit(): void
  /** Open the Workspace window on a change's file: its latest change is what it shows. */
  openChange(changeId: string): void
  closeFiles(): void
  /** Approve, reject or revert a file change. Throws ApiError with the server's reason. */
  decide(changeId: string, action: 'approve' | 'reject' | 'revert'): Promise<void>
}

let closeEvents: (() => void) | null = null
let generation = 0
// The conversation being opened right now (its snapshot has not come yet), if any.
let opening: string | null = null
// The reads of the board, counted: only the answer to the last one asked is shown.
let boardAsked = 0
let everywhereAsked = 0
// The reads of the conversations list, counted the same way: a slow answer does not overwrite a later one.
let conversationsAsked = 0
let retryTimer: ReturnType<typeof setTimeout> | undefined
let memoryReads = 0
let backlogReads = 0
// The backlog's choice being saved: Run the backlog waits for it - a model name is saved as its field
// is left, which a click on Run the backlog does.
let backlogChoice: Promise<unknown> = Promise.resolve()
let triggerReads = 0
// The Board row each of `readyChats` was read for: read again when it changes.
const readyRows = new Map<string, string>()
let readyReads = 0

/** The rooms' windows with this one open: one open at a time, any other made small. */
const withOpen = (windows: Record<string, 'open' | 'small'>, roomId: string): Record<string, 'open' | 'small'> => ({
  ...Object.fromEntries(Object.keys(windows).map(id => [id, 'small' as const])),
  [roomId]: 'open',
})

/** Put the store and its connection back to the initial state (tests only). */
export function resetStoreForTests(): void {
  closeEvents?.()
  closeEvents = null
  clearTimeout(retryTimer)
  generation += 1
  opening = null
  readyRows.clear()
  useApp.setState(useApp.getInitialState(), true)
}

const readHealth = (id: string | null) => api.get<Health>(id ? `/health?provider_id=${encodeURIComponent(id)}` : '/health')
// The latest loadHealth: an older one, answered late, does not put its readings over a newer one's.
let healthRuns = 0

/** The top bar's: what /health says of each provider the open chat would run on, and the roles of it that cannot run (`inUseBy`). */
async function inUseNow(get: () => AppStore, health: Health | null): Promise<{ readings: Health[]; cannot: Cannot[] }> {
  const chat = get().conv?.conversation ?? null
  try {
    // (Read with the page's first reading, they may not be here yet.)
    if (get().roles.length === 0) await get().loadRoles()
    if (get().providers.length === 0) await get().loadProviders()
    const [rows, tiers] = await Promise.all([get().roleModels(chat?.id ?? null), get().tiers().catch(() => null)])
    const observes = get().projects.some(one => one.id === chat?.project_id && one.observe_reports)
    const { ids, cannot } = inUseBy(chat, rows, { ...get(), tiers, observes })
    // A reading that fails keeps the last one: one glitch neither quiets the bar nor shows it again after a dismissal.
    // (A provider never read before is left out until it is.)
    const last = (id: string) => get().inUse?.readings.find(one => one.provider_id === id) ?? null
    const read = (id: string) => (id === health?.provider_id ? health : readHealth(id).catch(() => last(id)))
    return { readings: (await Promise.all(ids.map(read))).filter(one => one !== null), cannot }
  } catch {
    // (No provider at all, or the roles not read: the one reading there is, as before.)
    return { readings: health ? [health] : [], cannot: [] }
  }
}

export const useApp = create<AppStore>()((set, get) => {
  async function refreshConversations(): Promise<ListedConversation[]> {
    const asked = ++conversationsAsked
    const conversations = await api.get<ListedConversation[]>('/conversations')
    if (asked === conversationsAsked) set({ conversations })
    return conversations
  }

  /** The open chat's "While you're away" cards, read again: their night moved, or you said something on one. */
  async function readCards() {
    const id = get().conv?.conversation.id
    if (!id) return
    const away = await api.get<Away[]>('/conversations/' + id + '/away')
    set(s => (s.conv && s.conv.conversation.id === id ? { conv: { ...s.conv, away } } : s))
  }

  /** The open chat's proposed triggers, read again: one was proposed, approved or put away. */
  async function readProposals() {
    const id = get().conv?.conversation.id
    if (!id) return
    const triggerProposals = await api.get<TriggerProposal[]>('/conversations/' + id + '/trigger-proposals')
    set(s => (s.conv && s.conv.conversation.id === id ? { conv: { ...s.conv, triggerProposals } } : s))
  }

  /** K-bilgi 6: the open chat's Project notes offers, read again: a turn added to one, or one was answered. */
  async function readNotesOffers() {
    const id = get().conv?.conversation.id
    if (!id) return
    const notesOffers = await api.get<NotesOffer[]>('/conversations/' + id + '/notes-offers')
    set(s => (s.conv && s.conv.conversation.id === id ? { conv: { ...s.conv, notesOffers } } : s))
  }

  /** The open chat's folder is now this one: another folder's board, budget, memory, backlog and triggers are not shown for it. */
  function follow(projectId: string | null) {
    if (projectId === get().projectId) return
    // (A reading of the folder left that answers late is not this one's.)
    memoryReads += 1
    backlogReads += 1
    triggerReads += 1
    set({
      projectId,
      board: null,
      boardError: null,
      budget: null,
      memory: null,
      memoryError: null,
      backlog: null,
      backlogError: null,
      backlogAuto: null,
      away: null,
      triggers: null,
      triggersError: null,
      triggerChanges: null,
      knowledge: null,
      knowledgeError: null,
    })
    // A folder made a project since the list was read.
    if (projectId && !get().projects.some(p => p.id === projectId)) void api.get<Project[]>('/projects').then(projects => set({ projects }), () => {})
    // The top bar says how many triggers are on, on every page; the `/` menu offers the folder's own commands.
    void get().loadTriggers()
    void get().loadOwnCommands().catch(() => {})
  }

  /** Take a fresh snapshot and resubscribe, backing off while the server is away. */
  function scheduleReconnect(id: string, attempt: number) {
    clearTimeout(retryTimer)
    retryTimer = setTimeout(
      () => {
        if (get().conv?.conversation.id !== id) return
        // Another conversation is being opened: that is what was clicked last, and a
        // reconnect now would take its place. If it cannot be opened, this one is retried.
        if (opening !== null && opening !== id) return scheduleReconnect(id, attempt)
        get()
          .openConversation(id)
          .catch(() => scheduleReconnect(id, attempt + 1))
      },
      Math.min(1000 * 2 ** attempt, 10000),
    )
  }

  return {
    ready: false,
    loadError: null,
    projects: [],
    projectId: null,
    conversations: [],
    roles: [],
    teams: [],
    categories: [],
    providers: [],
    conv: null,
    health: null,
    inUse: null,
    connection: 'open',
    selectedNodeId: null,
    agentWindowId: null,
    agentWindowRaw: false,
    drafts: {},

    setDraft(conversationId, text) {
      set(s => ({ drafts: { ...s.drafts, [conversationId]: text } }))
    },

    discussionWindowId: null,

    openAgentWindow(agentId, raw = false) {
      set({ agentWindowId: agentId, agentWindowRaw: raw, discussionWindowId: null })
    },

    showAgentRaw(raw) {
      set({ agentWindowRaw: raw })
    },

    openDiscussion(discussionId) {
      set({ discussionWindowId: discussionId, agentWindowId: null, agentWindowRaw: false })
    },

    closeDiscussion() {
      set({ discussionWindowId: null })
    },

    async sayInDiscussion(discussionId, content) {
      await api.post(`/discussions/${discussionId}/posts`, { content })
    },

    roomWindows: {},

    showRoom(roomId) {
      set(s => ({ roomWindows: withOpen(s.roomWindows, roomId) }))
      requestAnimationFrame(() => document.getElementById(`room-${roomId}`)?.focus())
    },

    shrinkRoom(roomId) {
      set(s => ({ roomWindows: { ...s.roomWindows, [roomId]: 'small' } }))
      requestAnimationFrame(() => document.getElementById(`room-tab-${roomId}`)?.focus())
    },

    closeRoom(roomId) {
      set(s => ({ roomWindows: Object.fromEntries(Object.entries(s.roomWindows).filter(([id]) => id !== roomId)) }))
      // Back where it can be opened again: its tab, if it keeps one (something still waits), else its line in the chat.
      requestAnimationFrame(() =>
        (document.getElementById(`room-tab-${roomId}`) ?? document.querySelector<HTMLElement>(`[data-room-line="${roomId}"]`))?.focus(),
      )
    },

    chatTab: 'Chat',
    chatOpenAsked: 0,
    chatAt: null,

    showChatTab(tab, open = false, at) {
      set({ chatTab: tab, chatAt: at ?? null, ...(open && { chatOpenAsked: get().chatOpenAsked + 1 }) })
    },

    readyPanel: { open: false, at: null },
    showReady(open, at) {
      set({ readyPanel: { open, at: at ?? null } })
    },

    settingsAsked: null,
    askSettings(section) {
      set(s => ({ settingsAsked: { section, n: (s.settingsAsked?.n ?? 0) + 1 } }))
    },

    readyChats: {},
    async loadReadyChats(again) {
      // A read after a decision keeps no row: the Board's is still the one from before it, and the chat may ask again
      // with that same row - so the next reading reads it once more.
      const fresh = new Set(again === true ? readyRows.keys() : again ? [again] : [])
      for (const id of fresh) readyRows.delete(id)
      const open = get().conv?.conversation.id
      // Each other chat the Board says waits; read again only when what of its row says it waits changed (no events
      // come from it) - not each step its other agents take meanwhile.
      // shortcut: a chat whose only waiting cards are ones the Board does not count (a proposed trigger, a Project
      // notes offer, a night to start) is not read; they show in their own chat. Count them on the Board if missed.
      const rows = new Map((get().everywhere?.conversations ?? []).filter(c => c.conversation_id !== open && waitCount(c) > 0).map(c => [c.conversation_id, JSON.stringify([c.merges_pending, c.turn?.plan_waits, c.agents.map(a => [a.id, a.status, a.changes_to_approve, a.questions])])]))
      for (const id of readyRows.keys()) if (!rows.has(id)) readyRows.delete(id)
      // (Read every few seconds: a new object only when one went, so nothing is drawn again for nothing.)
      if (Object.keys(get().readyChats).some(id => !rows.has(id))) set(s => ({ readyChats: Object.fromEntries(Object.entries(s.readyChats).filter(([id]) => rows.has(id))) }))
      await Promise.all(
        [...rows].filter(([id, row]) => readyRows.get(id) !== row).map(async ([id, row]) => {
          const mark = fresh.has(id) ? `read ${++readyReads}` : row
          readyRows.set(id, mark)
          try {
            const read = fromSnapshot(await api.get<Snapshot>(`/conversations/${id}`))
            // (Not over a later read's answer.)
            set(s => (readyRows.get(id) === mark ? { readyChats: { ...s.readyChats, [id]: read } } : s))
          } catch {
            // (Not read again at every reading of the Board: when its row changes, or after a decision on it.)
          } finally {
            if (fresh.has(id) && readyRows.get(id) === mark) readyRows.delete(id)
          }
        }),
      )
    },

    async openRoom(room) {
      const conv = get().conv
      if (!conv) return
      // (The turn, its message and the room itself arrive as events, like any turn's.)
      await api.post(`/conversations/${conv.conversation.id}/rooms`, room)
      set({ turnId: null })
    },

    async sayInRoom(roomId, text) {
      await api.post(`/rooms/${roomId}/posts`, { text })
    },

    async endRoom(roomId) {
      await api.post(`/rooms/${roomId}/end`)
    },

    async pauseRoom(roomId, paused) {
      // (How it stands then arrives as an event, like every change of the room.)
      await api.post(`/rooms/${roomId}/${paused ? 'pause' : 'resume'}`)
    },

    async followRoom(roomId, on) {
      await api.post(`/rooms/${roomId}/${on ? 'follow' : 'unfollow'}`)
    },

    async giveRoomMore(roomId, more) {
      await api.post(`/rooms/${roomId}/more`, more)
    },

    async endDiscussion(discussionId) {
      await api.post(`/discussions/${discussionId}/end`)
    },

    async writeNote(runId, content) {
      // The note itself arrives as an event, like everybody else's.
      await api.post(`/runs/${runId}/notes`, { content })
    },

    closeAgentWindow() {
      set({ agentWindowId: null, agentWindowRaw: false })
    },

    triggers: null,
    triggersError: null,
    triggerChanges: null,
    triggersPaused: false,
    triggerDraft: null,

    async loadTriggers() {
      const { projectId } = get()
      if (!projectId) return
      // Only the latest reading counts, as with the memory.
      const mine = ++triggerReads
      try {
        const [triggers, { paused }, triggerChanges] = await Promise.all([
          api.get<Trigger[]>(`/projects/${projectId}/triggers`),
          api.get<{ paused: boolean }>('/triggers/paused'),
          api.get<TriggerLogEntry[]>(`/projects/${projectId}/triggers/changes`),
        ])
        if (mine === triggerReads) set({ triggers, triggersPaused: paused, triggerChanges, triggersError: null })
        // B-353: a chat made since the list was read (by the API, another window) is not "gone": the list is read again.
        const known = get().conversations
        if (triggers.some(t => t.conversation_id && !known.some(c => c.id === t.conversation_id))) void refreshConversations().catch(() => {})
      } catch (err) {
        if (mine === triggerReads) set({ triggersError: errorText(err) })
      }
    },

    async createTrigger(values) {
      const { projectId } = get()
      if (!projectId) throw new Error('no project is open')
      const created = await api.post<TriggerCreated>(`/projects/${projectId}/triggers`, values)
      await get().loadTriggers()
      return created
    },

    async newTriggerKey(triggerId) {
      const renewed = await api.post<TriggerCreated>(`/triggers/${triggerId}/key`)
      await get().loadTriggers()
      return renewed
    },

    async saveTrigger(triggerId, change) {
      await api.patch(`/triggers/${triggerId}`, change)
      await get().loadTriggers()
    },

    async deleteTrigger(triggerId) {
      await api.delete(`/triggers/${triggerId}`)
      await get().loadTriggers()
    },

    async runTrigger(triggerId) {
      const { run_id } = await api.post<{ run_id: string }>(`/triggers/${triggerId}/run`)
      void get().loadTriggers()
      return run_id
    },

    async pauseTriggers(paused) {
      const said = await api.put<{ paused: boolean }>('/triggers/paused', { paused })
      set({ triggersPaused: said.paused })
      await get().loadTriggers()
    },

    async allowedCommandsOf(conversationId) {
      const open = get().conv
      if (open?.conversation.id === conversationId) return open.allowedCommands
      return (await api.get<Snapshot>(`/conversations/${conversationId}`)).allowed_commands
    },

    async allowedHostsOf(conversationId) {
      const open = get().conv
      const rules = open?.conversation.id === conversationId ? open.allowedWeb : ((await api.get<Snapshot>(`/conversations/${conversationId}`)).allowed_web ?? [])
      return rules.filter(rule => rule.kind === 'host').map(rule => rule.host)
    },

    async addAllowedCommand(conversationId, prefix) {
      // (The open conversation hears of it as an event, like any change to its list.)
      return api.post<AllowedCommand>(`/conversations/${conversationId}/allowed-commands`, { prefix })
    },

    allowInTrigger(triggerId, allow) {
      set({ triggerDraft: { triggerId, allow } })
    },

    clearTriggerDraft() {
      set({ triggerDraft: null })
    },

    async decideProposal(proposalId, decision) {
      await api.post(`/trigger-proposals/${proposalId}/${decision}`)
      await Promise.all([readProposals(), get().loadTriggers()])
    },

    async answerNotesOffer(offerId, lines, add) {
      try {
        await api.post(`/notes-offers/${offerId}/answer`, { lines, add })
      } finally {
        // (Changed meanwhile - 409 - the card shows what it holds now.)
        await readNotesOffers().catch(() => {})
      }
    },

    editProposal(proposal) {
      set({ triggerDraft: { proposal } })
    },

    memory: null,
    memoryError: null,

    async loadMemory() {
      const { projectId } = get()
      if (!projectId) return
      // Only the latest reading counts: an earlier one may be older than a change since.
      const mine = ++memoryReads
      try {
        const memory = await api.get<ProjectMemory>('/projects/' + projectId + '/memory')
        if (mine === memoryReads) set({ memory, memoryError: null })
      } catch (err) {
        if (mine === memoryReads) set({ memoryError: errorText(err) })
      }
    },

    backlog: null,
    backlogError: null,
    backlogAuto: null,

    async loadBacklog() {
      const { projectId } = get()
      if (!projectId) return
      // Only the latest reading counts, as with the memory.
      const mine = ++backlogReads
      try {
        const [backlog, backlogAuto] = await Promise.all([
          api.get<BacklogTask[]>('/projects/' + projectId + '/backlog'),
          api.get<BacklogAuto>('/projects/' + projectId + '/backlog/auto'),
        ])
        if (mine === backlogReads) set({ backlog, backlogAuto, backlogError: null })
      } catch (err) {
        if (mine === backlogReads) set({ backlogError: errorText(err) })
      }
    },

    async setBacklogAuto(on) {
      await api.put('/projects/' + get().projectId + '/backlog/auto', { on })
      // A task it started has a conversation of its own now.
      await Promise.all([get().loadBacklog(), get().loadBoard(), refreshConversations()])
    },

    async setBacklogChoice(choice) {
      const saving = api.put<BacklogAuto>('/projects/' + get().projectId + '/backlog/choice', choice)
      backlogChoice = saving.catch(() => {}) // (its error is said beside the choice)
      set({ backlogAuto: await saving })
    },

    async addTask(task) {
      await api.post('/projects/' + get().projectId + '/backlog', task)
      await Promise.all([get().loadBacklog(), get().loadBoard()])
    },

    async changeTask(taskId, change) {
      await api.patch('/backlog/' + taskId, change)
      await Promise.all([get().loadBacklog(), get().loadBoard()])
    },

    async deleteTask(taskId) {
      await api.delete('/backlog/' + taskId)
      await Promise.all([get().loadBacklog(), get().loadBoard()])
    },

    async decideTask(taskId, decision) {
      await api.post('/backlog/' + taskId + '/decide', { decision })
      await Promise.all([get().loadBacklog(), get().loadBoard()])
    },

    async seenTask(taskId) {
      await api.post('/backlog/' + taskId + '/seen')
      await get().loadBacklog()
    },

    draftTasks: text => api.post<BacklogDraft>('/projects/' + get().projectId + '/backlog/draft', { text }),

    async runBacklog() {
      await backlogChoice
      await api.post('/projects/' + get().projectId + '/backlog/next')
      // (The page stays: two may start at once, each opened from its task.)
      await Promise.all([get().loadBacklog(), get().loadBoard(), refreshConversations()])
    },

    away: null,

    async loadAway() {
      const { projectId } = get()
      if (!projectId) return
      const away = await api.get<Away | null>('/projects/' + projectId + '/away')
      if (get().projectId === projectId) set({ away })
    },

    async awayDo(awayId, action, change) {
      if (action === 'change') await api.patch('/away/' + awayId, change)
      else await api.post('/away/' + awayId + '/' + action)
      await Promise.all([get().loadAway(), readCards(), get().loadBacklog(), refreshConversations()])
    },

    async answerAsk(ask, yes) {
      await api.post(`/${ask.kind}/${ask.id}/${yes ? 'approve' : 'reject'}`, ask.kind === 'commands' || ask.kind === 'web-requests' ? { remember: false } : undefined)
      // (Its chat is another as a rule: Ready for you reads the chats again.)
      await Promise.all([get().loadAway(), readCards(), get().loadReadyChats(true)])
    },

    async takeIn(mergeIds) {
      try {
        for (const id of mergeIds) await api.post('/merges/' + id + '/approve')
      } finally {
        // (One refused - a file that changed since, say - and what was taken before it is still shown.)
        await Promise.all([get().loadAway(), readCards(), get().loadReadyChats(true)])
      }
    },

    async approveMemory(memoryId, text) {
      await api.post('/memory/' + memoryId + '/approve', text === undefined ? {} : { text })
      await get().loadMemory()
    },

    async rejectMemory(memoryId) {
      await api.post('/memory/' + memoryId + '/reject')
      await get().loadMemory()
    },

    async restoreMemory(memoryId) {
      await api.post('/memory/' + memoryId + '/restore')
      await get().loadMemory()
    },

    async confirmMemory(memoryId) {
      await api.post('/memory/' + memoryId + '/confirm')
      await get().loadMemory()
    },

    async correctMemory(memoryId, changes) {
      await api.patch('/memory/' + memoryId, changes)
      await get().loadMemory()
    },

    async writeFact(fact) {
      const { projectId } = get()
      if (!projectId) return
      await api.post('/projects/' + projectId + '/memory', fact)
      await get().loadMemory()
    },

    async saveRules(rules) {
      const { projectId } = get()
      if (!projectId) return
      await api.put('/projects/' + projectId + '/rules', { rules })
      await get().loadMemory()
    },

    async savePreferences(text) {
      await api.put('/preferences', { text })
      await get().loadMemory()
    },

    async addPreference(memoryId) {
      await api.post('/memory/' + memoryId + '/add-to-preferences')
      await get().loadMemory()
    },

    async searchMemory(query) {
      const { projectId } = get()
      if (!projectId) return { memory: [], turns: [] }
      return api.get<MemorySearch>('/projects/' + projectId + '/memory/search?q=' + encodeURIComponent(query))
    },

    async loadProjects() {
      let projects: Project[]
      let conversations: ListedConversation[]
      const asked = ++conversationsAsked
      try {
        ;[projects, conversations] = await Promise.all([api.get<Project[]>('/projects'), api.get<ListedConversation[]>('/conversations')])
      } catch (err) {
        set({ loadError: errorText(err) })
        return
      }
      // (A read of the list asked after this one keeps its answer.)
      set(asked === conversationsAsked ? { projects, conversations, loadError: null } : { projects, loadError: null })
      // One put away is not where KOLONİ opens; with none, the first message makes a plain chat (slice 86a).
      // shortcut: it opens on the newest chat, not the tab open last, so a closed tab of the newest comes back; open the last tab's if that is missed.
      const first = conversations.find(c => !c.archived_at)
      // Ready (the page drawn) once that chat is open: a message box shown before would keep what is typed as a new chat's draft, gone when the chat opens.
      try {
        if (first) await get().openConversation(first.id)
      } finally {
        set({ ready: true })
      }
    },

    async setFolder(projectId) {
      const conv = get().conv
      // A chat that has a turn stays in its folder (slice 86e): the other folder's tab, with a new chat in it.
      if (!conv || conv.runs.length > 0) return get().newConversation(projectId)
      const was = tabOf(conv.conversation.project_id)
      const saved = await api.patch<Conversation>(`/conversations/${conv.conversation.id}`, { project_id: projectId })
      // Another chat was opened meanwhile: its folder is the one open.
      if (get().conv?.conversation.id !== saved.id) return void refreshConversations()
      set(s => (s.conv ? { conv: { ...s.conv, conversation: saved } } : s))
      // Its tab goes with it: the one it left becomes the new folder's where no other chat is there (a new chat's "No folder").
      const tab = tabOf(saved.project_id)
      const alone = !get().conversations.some(c => c.id !== saved.id && !c.archived_at && tabOf(c.project_id) === was)
      const left = kept(get().tabs, get().conversations, get().projects)
      const tabs = [...new Set(opened(alone ? left.map(one => (one === was ? tab : one)) : left, tab))]
      set({ tabs })
      remember(tabs)
      rememberChat(tab, saved.id)
      follow(saved.project_id)
      void get().loadBoard()
      await refreshConversations()
    },

    async openFolder(path) {
      const project = await api.post<Project>('/projects', { root_path: path })
      set(s => (s.projects.some(p => p.id === project.id) ? s : { projects: [...s.projects, project] }))
      return project
    },

    browseFolders: path => api.post<FolderBrowse>('/folders/browse', path ? { path } : {}),

    async loadRoles() {
      const [roles, teams, categories] = await Promise.all([api.get<Role[]>('/roles'), api.get<Team[]>('/teams'), api.get<Category[]>('/categories')])
      set({ roles, teams, categories })
    },

    // (Each answers the categories as they are now.)
    async addCategory(name, colour) {
      const before = new Set(get().categories.map(one => one.key))
      const categories = await api.post<Category[]>('/categories', { name, colour })
      set({ categories })
      return categories.find(one => !before.has(one.key))?.key ?? ''
    },

    async changeCategory(key, change) {
      // (A key is hex or a built-in word since 0079; encoded all the same.)
      set({ categories: await api.patch<Category[]>(`/categories/${encodeURIComponent(key)}`, change) })
    },

    async orderCategories(order) {
      set({ categories: await api.put<Category[]>('/categories', { order }) })
    },

    async deleteCategory(key) {
      await api.delete(`/categories/${encodeURIComponent(key)}`)
      set(s => ({ categories: s.categories.filter(one => one.key !== key) }))
    },

    async loadProviders() {
      set({ providers: await api.get<Provider[]>('/providers') })
    },

    async createProvider(values) {
      await api.post('/providers', values)
      await get().loadProviders()
    },

    async saveProvider(providerId, values) {
      await api.patch(`/providers/${providerId}`, values)
      await get().loadProviders()
      void get().loadHealth()
    },

    async deleteProvider(providerId) {
      await api.delete(`/providers/${providerId}`)
      // Roles and the open conversation may have pointed at it.
      await Promise.all([get().loadProviders(), get().loadRoles()])
      const id = get().conv?.conversation.id
      if (id) await get().openConversation(id)
      void get().loadHealth()
    },

    async makeDefaultProvider(providerId) {
      await api.post(`/providers/${providerId}/default`)
      await get().loadProviders()
      void get().loadHealth()
    },

    async testProvider(providerId, run = false) {
      return api.post<ProviderTest>(`/providers/${providerId}/test${run ? '?run=true' : ''}`)
    },

    async providerModels(providerId) {
      return api.get<OfferedModels>(`/providers/${providerId}/models`)
    },

    async fillFromCatalogue(providerId) {
      return api.post<CatalogueFill>(`/providers/${providerId}/fill-from-catalogue`)
    },

    async fillNewFromCatalogue(draft) {
      return api.post<CatalogueFill>('/providers/fill-from-catalogue', draft)
    },

    async availability(providerId, free = false) {
      return api.get<Availability>(`/providers/${providerId}/availability${free ? '?free=true' : ''}`)
    },

    async modelFacts(providerId, model) {
      return api.get<ModelFacts>(`/providers/${providerId}/model-facts?model=${encodeURIComponent(model)}`)
    },

    async suggest(kind, baseUrl) {
      return api.post<Suggestion>('/providers/suggest', { kind, base_url: baseUrl })
    },

    async updateCatalogue() {
      return api.post<CatalogueUpdate>('/catalog/update')
    },

    async catalogue() {
      return api.get<CatalogueUpdate>('/catalog')
    },

    async keepCatalogueFresh(on) {
      return api.put<CatalogueUpdate>('/catalog/fresh', { keep_fresh: on })
    },

    async localServer() {
      return api.get<LocalServer>('/local-server')
    },

    async runLocalServer(action, config) {
      if (config) await api.put<LocalServer>('/local-server', config)
      return api.post<LocalServer>(`/local-server/${action}`)
    },

    async fillAll() {
      return api.post<FillAll>('/providers/fill-all')
    },

    async saveFillAll(providers) {
      set({ providers: await api.post<Provider[]>('/providers/fill-all/save', { providers }) })
    },
    tiers: () => api.get<Tiers>('/tiers'),
    saveTiers: order => api.put<Tiers>('/tiers', order),

    prices: [],
    cataloguePrices: [],

    async loadPrices() {
      const [prices, cataloguePrices] = await Promise.all([api.get<Price[]>('/prices'), api.get<CataloguePrice[]>('/prices/catalogue')])
      set({ prices, cataloguePrices })
    },

    async savePrice(price) {
      set({ prices: await api.put<Price[]>('/prices', price) })
    },

    async removePrice(modelId) {
      await api.delete(`/prices?model_id=${encodeURIComponent(modelId)}`)
      set(s => ({ prices: s.prices.filter(price => price.model_id !== modelId) }))
    },

    async usage(projectId, since, runId) {
      const asked = new URLSearchParams()
      if (projectId) asked.set('project_id', projectId)
      if (since) asked.set('since', since)
      if (runId) asked.set('run_id', runId)
      return api.get<Usage>(`/usage?${asked}`)
    },

    day: since => api.get<Day>(`/projects/${get().projectId}/day?since=${encodeURIComponent(since)}`),
    dayWords: (since, conversationId, overBudget) =>
      api.post<DayWords>(`/projects/${get().projectId}/day/words`, { since, conversation_id: conversationId, over_budget: overBudget }),

    budget: null,
    async loadBudget() {
      const { projectId } = get()
      if (!projectId) return
      const budget = await api.get<Budget>(`/projects/${projectId}/budget`)
      // Not for a project left meanwhile; the same answer is not drawn again (it is read every few seconds).
      if (get().projectId === projectId && JSON.stringify(budget) !== JSON.stringify(get().budget)) set({ budget })
    },

    board: null,
    boardError: null,
    everywhere: null,

    async rerunFailed(conversationId) {
      await api.post(`/conversations/${conversationId}/rerun-failed`)
      await get().loadBoard()
    },

    async loadBoard() {
      // What waits anywhere is read with it, in a plain chat too (the rail's badge, the toasts, the list).
      const all = ++everywhereAsked
      void api.get<Board>('/board').then(
        board => {
          if (all !== everywhereAsked) return
          if (JSON.stringify(board) !== JSON.stringify(get().everywhere)) set({ everywhere: board })
          void get().loadReadyChats()
        },
        () => {}, // (said by the folder's board where there is one; the badge keeps its last reading)
      )
      const { projectId } = get()
      if (!projectId) return
      // Not for a project that was left meanwhile, and not over a later read's answer:
      // what is shown is what was asked for last, whether it came or failed.
      const asked = ++boardAsked
      const mine = () => get().projectId === projectId && asked === boardAsked
      try {
        const board = await api.get<Board>(`/projects/${projectId}/board`)
        // The same answer keeps the board it had: what reads it is not drawn again for nothing (it is read every few seconds).
        const same = JSON.stringify(board) === JSON.stringify(get().board)
        if (mine()) set(same ? { boardError: null } : { board, boardError: null })
      } catch (err) {
        if (mine()) set({ boardError: errorText(err) })
      }
    },

    limits: (providerId, afresh) => (afresh ? api.post<Limits>(`/providers/${providerId}/limits/check`) : api.get<Limits>(`/providers/${providerId}/limits`)),
    claudeSetup: () => api.post<ClaudeSessionSetup>('/limits/claude-session/setup'),
    roleModels: (conversationId, levels) => {
      const query = String(new URLSearchParams({ ...(conversationId ? { conversation_id: conversationId } : {}), ...(levels ? { levels: '1' } : {}) }))
      return api.get<RoleModel[]>(`/roles/models${query ? `?${query}` : ''}`)
    },
    record: () => api.get<{ rows: RecordRow[] }>('/record').then(read => read.rows),
    skillRecord: () => api.get<{ skills: SkillRecordRow[] }>('/record').then(read => read.skills),
    rawStream: (agentId, after, signal) => api.get<RawLines>(`/agents/${agentId}/raw?after=${after}`, signal),

    async setModelChoice(choice) {
      if (!get().conv) await get().newConversation()
      const conv = get().conv
      if (!conv) return
      const saved = await api.patch<Conversation>(`/conversations/${conv.conversation.id}`, choice)
      set(s => (s.conv ? { conv: { ...s.conv, conversation: saved } } : s))
    },

    async saveRole(roleId, values) {
      await api.patch(`/roles/${roleId}`, values)
      await get().loadRoles()
    },

    async createRole(values) {
      const made = await api.post<Role>('/roles', values)
      await get().loadRoles()
      return made
    },

    async deleteRole(roleId) {
      await api.delete(`/roles/${roleId}`)
      await get().loadRoles()
    },

    async resetRole(roleId) {
      await api.post(`/roles/${roleId}/reset`)
      await get().loadRoles()
    },

    async patchRole(roleId, change) {
      await api.patch(`/roles/${roleId}`, change)
      await get().loadRoles()
    },

    async createTeam(name) {
      await api.post('/teams', { name })
      await get().loadRoles()
    },

    async changeTeam(teamId, change) {
      await api.patch(`/teams/${teamId}`, change)
      await get().loadRoles()
    },

    async deleteTeam(teamId) {
      await api.delete(`/teams/${teamId}`)
      await get().loadRoles()
    },

    async addStage(teamId, name) {
      await api.post(`/teams/${teamId}/stages`, { name })
      await get().loadRoles()
    },

    async changeStage(teamId, stageId, change) {
      await api.patch(`/teams/${teamId}/stages/${stageId}`, change)
      await get().loadRoles()
    },

    async orderStages(teamId, order) {
      await api.put(`/teams/${teamId}/stages`, { order })
      await get().loadRoles()
    },

    async deleteStage(teamId, stageId) {
      await api.delete(`/teams/${teamId}/stages/${stageId}`)
      await get().loadRoles()
    },

    // (Its teams change too: the roles are read again with the teams.)
    async placeRole(teamId, roleId, stageId) {
      await api.put(`/teams/${teamId}/roles/${roleId}`, { stage_id: stageId })
      await get().loadRoles()
    },

    recipes: projectId => api.get<Recipes>(projectId ? `/recipes?project_id=${projectId}` : '/recipes'),

    saveRecipe: (recipe, body, projectId) =>
      recipe === null
        ? api.post<Recipe>(projectId ? `/projects/${projectId}/recipes` : '/recipes', body)
        : api.put<Recipe>(recipe.project_id ? `/projects/${recipe.project_id}/recipes/${encodeURIComponent(recipe.file ?? '')}` : `/recipes/${recipe.id}`, body),

    // (A team whose default it was has none now: the teams are read again.)
    async deleteRecipe(recipe) {
      await api.delete(recipe.project_id ? `/projects/${recipe.project_id}/recipes/${encodeURIComponent(recipe.file ?? '')}` : `/recipes/${recipe.id}`)
      await get().loadRoles()
    },

    draftRecipe: text => api.post<RecipeDraft>('/recipes/draft', { text }),

    roleActivity: () => api.get<RolesActivity>('/roles/activity'),
    roleHistory: days => api.get<RolesHistory>(`/roles/history?days=${days}`),

    knowledge: null,
    knowledgeError: null,

    async loadKnowledge() {
      const { projectId } = get()
      if (!projectId) return
      try {
        const knowledge = await api.get<KnowledgeItem[]>(`/projects/${projectId}/knowledge`)
        // (A reading of the folder left that answers late is not this one's.)
        if (get().projectId === projectId) set({ knowledge, knowledgeError: null })
      } catch (err) {
        if (get().projectId === projectId) set({ knowledgeError: errorText(err) })
      }
    },
    async addKnowledge(body) {
      const added = await api.post<KnowledgeItem>(`/projects/${get().projectId}/knowledge`, body)
      await get().loadKnowledge()
      return added
    },
    async saveKnowledge(knowledgeId, body) {
      await api.put(`/knowledge/${knowledgeId}?project_id=${get().projectId}`, body)
      await Promise.all([get().loadKnowledge(), get().loadRoles()])
    },
    async deleteKnowledge(knowledgeId) {
      await api.delete(`/knowledge/${knowledgeId}?project_id=${get().projectId}`)
      await Promise.all([get().loadKnowledge(), get().loadRoles()])
    },
    async learnKnowledge(knowledgeId) {
      await api.post(`/knowledge/${knowledgeId}/learn`, { project_id: get().projectId })
      await get().loadKnowledge()
    },
    async copyKnowledge(knowledgeId, toProjectId, replace = false) {
      await api.post(`/knowledge/${knowledgeId}/copy`, { project_id: get().projectId, to_project_id: toProjectId, replace })
    },
    knowledgeFile: path => api.get<ProjectFile>(`/projects/${get().projectId}/file?path=${encodeURIComponent(path)}`),
    tryKnowledge: async (knowledgeId, question) =>
      (await api.post<{ answer: string }>(`/knowledge/${knowledgeId}/try`, { project_id: get().projectId, question })).answer,
    async createExpert(role, knowledge) {
      const made = await api.post<Role>('/roles/experts', { project_id: get().projectId, role, knowledge })
      await Promise.all([get().loadKnowledge(), get().loadRoles()])
      return made
    },
    async useKnowledge(knowledgeId, roleId, mode) {
      if (mode) await api.put(`/knowledge/${knowledgeId}/roles/${roleId}`, { mode })
      else await api.delete(`/knowledge/${knowledgeId}/roles/${roleId}`)
      await Promise.all([get().loadKnowledge(), get().loadRoles()])
    },

    ownCommands: [],

    async loadOwnCommands() {
      // The folder's own and every folder's; in a plain chat every folder's. Not a folder's that was left meanwhile.
      const { projectId } = get()
      const commands = await api.get<OwnCommand[]>(projectId ? `/own-commands?project_id=${projectId}` : '/own-commands')
      if (get().projectId === projectId) set({ ownCommands: commands })
    },

    async saveOwnCommand(commandId, values) {
      await (commandId ? api.patch(`/own-commands/${commandId}`, values) : api.post('/own-commands', values))
      await get().loadOwnCommands()
    },

    async deleteOwnCommand(commandId) {
      await api.delete(`/own-commands/${commandId}`)
      await get().loadOwnCommands()
    },

    skills: [],

    async loadSkills() {
      set({ skills: await api.get<Skill[]>('/skills') })
    },

    previewSkill: source => api.post<SkillPreview>('/skills/preview', source),

    async addSkill(source, scriptsRunUnasked, sha256, replace = false) {
      const added = await api.post<Skill>('/skills', { ...source, scripts_run_unasked: scriptsRunUnasked, sha256, replace })
      // (A replaced one's roles have it by its new name.)
      await Promise.all([get().loadSkills(), replace ? get().loadRoles() : null])
      return added
    },

    async setSkillLeave(skillId, scriptsRunUnasked) {
      await api.patch(`/skills/${skillId}`, { scripts_run_unasked: scriptsRunUnasked })
      await get().loadSkills()
    },

    async setSkillOn(skillId, on) {
      await api.patch(`/skills/${skillId}`, { enabled: on })
      await get().loadSkills()
    },

    async deleteSkill(skillId) {
      await api.delete(`/skills/${skillId}`)
      await Promise.all([get().loadSkills(), get().loadRoles()])
    },

    mcpServers: [],

    async loadMcpServers() {
      set({ mcpServers: await api.get<McpServer[]>('/mcp-servers') })
    },

    async addMcpServer(values) {
      const made = await api.post<McpServer>('/mcp-servers', values)
      await get().loadMcpServers()
      return made
    },

    async saveMcpServer(serverId, change) {
      await api.patch(`/mcp-servers/${serverId}`, change)
      await get().loadMcpServers()
    },

    async deleteMcpServer(serverId) {
      await api.delete(`/mcp-servers/${serverId}`)
      // The roles that named it no longer do.
      await Promise.all([get().loadMcpServers(), get().loadRoles()])
    },

    async readMcpServer(serverId, osv, inProject) {
      const read = await api.post<McpRead>(`/mcp-servers/${serverId}/read`, { osv, in_project: inProject })
      await get().loadMcpServers()
      return read
    },

    async setRoleServers(roleId, mcp) {
      await api.patch(`/roles/${roleId}`, { mcp })
      await get().loadRoles()
    },

    builtinTools: [],

    async loadBuiltinTools() {
      set({ builtinTools: await api.get<BuiltinTool[]>('/builtin-tools') })
    },

    async switchBuiltinTool(name, on) {
      set({ builtinTools: await api.put<BuiltinTool[]>(`/builtin-tools/${name}`, { on }) })
    },

    async loadHealth() {
      // The open conversation's provider is the one asked (null: the default); a reading of one left meanwhile is not kept.
      const asked = get().conv?.conversation.provider_id ?? null
      const mine = ++healthRuns
      const kept = () => (get().conv?.conversation.provider_id ?? null) === asked
      let health: Health | null = null
      try {
        health = await readHealth(asked)
        if (kept()) set({ health })
      } catch {
        if (kept()) set({ health: null })
      }
      // The top bar's: each provider the open chat would run on, read on the same beat.
      const of = get().conv?.conversation.id ?? null
      const now = await inUseNow(get, health)
      if (mine === healthRuns && kept() && (get().conv?.conversation.id ?? null) === of) set({ inUse: { of, ...now } })
    },

    async openConversation(id) {
      // Only the latest call may install a stream: an earlier one that is still
      // waiting for its snapshot would otherwise leave a second stream behind.
      const mine = ++generation
      const sameAsOpen = get().conv?.conversation.id === id
      if (sameAsOpen) {
        clearTimeout(retryTimer)
        closeEvents?.()
        closeEvents = null
      }
      // Another conversation is let go of only when this one could be read: if it cannot
      // (it was deleted), what is open stays open, with its events - and the caller is told.
      opening = id
      let snapshot: Snapshot
      try {
        snapshot = await api.get<Snapshot>(`/conversations/${id}`)
      } finally {
        if (mine === generation) opening = null
      }
      if (mine !== generation) return
      clearTimeout(retryTimer)
      closeEvents?.()
      closeEvents = null
      follow(snapshot.conversation.project_id)
      void get().loadBoard()
      const sameConversation = get().conv?.conversation.id === id
      // B-150: another chat is a step of the browser's history - its Back opens the one before (App's popstate).
      if (history.state?.chat !== id) history[get().conv ? 'pushState' : 'replaceState']({ chat: id }, '')
      set(
        sameConversation
          ? { conv: fromSnapshot(snapshot) }
          : {
              conv: fromSnapshot(snapshot),
              selectedNodeId: null,
              turnId: null,
              agentWindowId: null,
              agentWindowRaw: false,
              discussionWindowId: null,
              roomWindows: {},
              filesOpen: false,
              filesRef: null,
              filesAt: { key: null, n: get().filesAt.n },
            },
      )
      // Its project's tab, wherever it was opened from: the list, the Board, a toast, Ctrl+K, a new chat.
      const tab = tabOf(snapshot.conversation.project_id)
      const tabs = opened(kept(get().tabs, get().conversations, get().projects), tab)
      set({ tabs })
      remember(tabs)
      rememberChat(tab, id)
      // (One made since the list was read - by a trigger, the backlog, another window - has its tab once the list has it.)
      if (!get().conversations.some(c => c.id === id)) void refreshConversations().catch(() => {})
      closeEvents = openEvents(
        id,
        snapshot.last_event_id,
        (eventId, type, payload) => {
          // An agent added a role: the Agents page and the next spawn should know it.
          if (type === 'role.created') void get().loadRoles().catch(() => {})
          // A skill was added on your card, and given to roles.
          if (type === 'skill.created') void Promise.all([get().loadRoles(), get().loadSkills()]).catch(() => {})
          // The project's memory changed, here or in another conversation: if it is on
          // screen it is read again. (By type: from elsewhere the event has no id.)
          if (type === 'memory.changed' && get().memory) void get().loadMemory()
          // So does its backlog: what waits there is counted on the board too.
          if (type === 'backlog.changed') {
            if (get().backlog) void get().loadBacklog()
            void get().loadBoard()
            // ...and so does a night while you're away (slice 106): its card here, the top bar.
            void readCards().catch(() => {})
            void get().loadAway().catch(() => {})
            // The next task may have started by itself, in a conversation of its own.
            void refreshConversations().catch(() => {})
          }
          // A trigger was made, changed, paused, came due or saw its turn end.
          if (type === 'triggers.changed') {
            void get().loadTriggers()
            // ...and so may a trigger an agent proposed here (slice 69): its card.
            void readProposals().catch(() => {})
          }
          // K-bilgi 6: a turn of the folder added to its Project notes offer, or one was answered.
          if (type === 'notes.offered') void readNotesOffers().catch(() => {})
          // Renamed (its first message names it): its tab keeps the new name once it is left.
          if (type === 'conversation.updated') void refreshConversations().catch(() => {})
          // The board is read again when a file changes hands, a turn stops to ask or goes
          // on, or an agent starts, ends or begins to wait - not for each thing an agent says.
          const was = type === 'agent.updated' && get().conv?.agents.find(a => a.id === (payload as Agent).id)
          const moved = was && (was.status !== (payload as Agent).status || was.waiting_for?.path !== (payload as Agent).waiting_for?.path)
          if (moved || ['claims.changed', 'agent.created', 'run.updated', 'run.finished'].includes(type)) void get().loadBoard()
          // An agent that works with its own tools shows its work in its own window.
          if (type === 'agent.created') {
            const started = payload as { id: string; provider_name: string | null }
            const provider = get().providers.find(p => p.name === started.provider_name)
            if (provider?.mode === 'native' || provider?.mode === 'reads') set({ agentWindowId: started.id })
          }
          // A room is something to watch too: its window opens over the canvas as it opens - the focus left where it is.
          // (Another's window open - the user may be writing in it: the new one comes as a tab beside it.)
          if (type === 'room.created') {
            const roomId = (payload as { id: string }).id
            set(s => ({ roomWindows: Object.values(s.roomWindows).includes('open') ? { ...s.roomWindows, [roomId]: 'small' } : withOpen(s.roomWindows, roomId) }))
          }
          // A discussion is something to watch: its shared place opens as it starts.
          if (type === 'discussion.created') {
            set({ discussionWindowId: (payload as { id: string }).id, agentWindowId: null, agentWindowRaw: false })
          }
          set(s => {
            if (!s.conv || s.conv.conversation.id !== id) return s
            const conv = applyEvent(s.conv, eventId, type, payload)
            // A turn of the user's that starts is the one to look at, whatever was picked;
            // a turn a trigger starts never takes the canvas from what the user is looking at.
            if ((type === 'run.started' || type === 'run.updated') && conv !== s.conv && s.turnId !== null) {
              const run = payload as Run
              if (startsNewTurn(s.conv.runs.find(r => r.id === run.id), run)) return { conv, turnId: null }
            }
            // When a run stops to ask about a file change, that change is the thing to
            // look at: bring it up. Edits the agent may write directly never pause the
            // run, so they stay out of the way.
            if (type === 'run.updated' && conv !== s.conv) {
              const run = payload as Run
              const waiting =
                run.status === 'waiting_approval' &&
                conv.fileChanges.findLast(f => f.run_id === run.id && f.status === 'proposed')
              if (waiting) return { conv, filesOpen: true, filesRef: null, filesAt: { key: keyOf(waiting.path), n: s.filesAt.n + 1 } }
            }
            return { conv }
          })
        },
        () => set({ connection: 'open' }),
        () => {
          set({ connection: 'reconnecting' })
          scheduleReconnect(id, 0)
        },
      )
    },

    async loadConversations() {
      await refreshConversations()
    },

    tabs: remembered(),

    async openTab(tab) {
      const id = chatOf(tab, get().conversations)
      if (id) await get().openConversation(id)
      else await get().newConversation(tab === 'none' ? null : tab)
    },

    async closeTab(tab) {
      const conv = get().conv
      const { tabs, next } = closing(kept(get().tabs, get().conversations, get().projects), tab, conv ? tabOf(conv.conversation.project_id) : null)
      set({ tabs })
      remember(tabs)
      // shortcut: the last tab closed leaves its chat on the canvas (the store has no "no chat open"); add one if that is missed.
      if (next) await get().openTab(next)
    },

    async archiveConversation(id, archived) {
      await api.patch(`/conversations/${id}`, { archived })
      await refreshConversations()
    },

    async deleteConversations(ids) {
      const told: ConversationsDeleted = { deleted: [], refused: [] }
      try {
        // In parts of as many as the server takes at once (ConversationsDeleteIn).
        for (let at = 0; at < ids.length; at += 500) {
          const part = await api.post<ConversationsDeleted>('/conversations/delete', { ids: ids.slice(at, at + 500) })
          told.deleted.push(...part.deleted)
          told.refused.push(...part.refused)
        }
      } finally {
        // (Those a part before a failed one deleted are gone all the same.)
        const left = await refreshConversations()
        const conv = get().conv
        if (conv && told.deleted.includes(conv.conversation.id)) {
          // Its tab's next chat, else the newest left in view, else a new chat: the store has no "no chat open".
          const next = chatOf(tabOf(conv.conversation.project_id), left) ?? left.find(c => !c.archived_at)?.id
          if (next) await get().openConversation(next)
          else await get().newConversation()
        }
      }
      return told
    },

    async deleteProject(projectId) {
      await api.delete(`/projects/${projectId}`)
      // Gone from the page at once, before anything below is read that may fail.
      const left = get().conversations.filter(c => c.project_id !== projectId)
      const projects = get().projects.filter(p => p.id !== projectId)
      // (Its tab goes by itself: neither a chat nor a project has its id any more.)
      const tabs = kept(get().tabs, left, projects)
      ++conversationsAsked // (a list read before the delete would bring its chats back)
      set({ projects, conversations: left, tabs })
      remember(tabs)
      if (get().projectId === projectId) {
        const next = (tabs[0] && chatOf(tabs[0], left)) ?? left.find(c => !c.archived_at)?.id
        if (next) await get().openConversation(next)
        else await get().newConversation(null) // (not the default: that is the gone project's)
      }
      await refreshConversations()
    },

    async newConversation(projectId = get().projectId) {
      const conversation = await api.post<Conversation>('/conversations', { project_id: projectId })
      await get().openConversation(conversation.id)
      await refreshConversations()
    },

    async send(content, where = {}) {
      if (!get().conv) await get().newConversation()
      const conv = get().conv
      if (!conv) return
      await api.post(`/conversations/${conv.conversation.id}/messages`, { content, ...where })
      void refreshConversations()
    },

    async compare(content, second, where = {}) {
      if (!get().conv) await get().newConversation()
      const conv = get().conv
      if (!conv) return
      // The first side is what a message would run on now: the conversation's model, else the first provider.
      const first = conv.conversation.provider_id ?? get().providers[0]?.id
      const sides = [{ provider_id: first, model_id: conv.conversation.provider_id ? conv.conversation.model_id : null }, second]
      await api.post(`/conversations/${conv.conversation.id}/compare`, { content, sides, ...where })
      void refreshConversations()
    },

    loadCompare(compareId) {
      return api.get<Compare>(`/compares/${compareId}`)
    },

    decideCompare(compareId, runId) {
      return runId ? api.post<Compare>(`/compares/${compareId}/choose`, { run_id: runId }) : api.post<Compare>(`/compares/${compareId}/discard`)
    },

    attached(attachment) {
      set(s => (s.conv?.conversation.id === attachment.conversation_id ? { conv: applyEvent(s.conv, null, 'attachment.updated', attachment) } : s))
    },

    async detach(attachmentId) {
      await api.delete(`/attachments/${attachmentId}`)
      // (Its frames go with it: their events follow.)
      set(s => (s.conv ? { conv: applyEvent(s.conv, null, 'attachment.deleted', { id: attachmentId }) } : s))
    },

    async renameTopic(topicId, title) {
      const topic = await api.patch<Topic>(`/topics/${topicId}`, { title })
      // The same record also arrives as an event; applying it twice is harmless.
      set(s => (s.conv ? { conv: applyEvent(s.conv, null, 'topic.updated', topic) } : s))
    },

    async stop() {
      const conv = get().conv
      const run = conv && activeRun(conv)
      if (run) await api.post(`/runs/${run.id}/cancel`)
    },

    async cancelRun(runId) {
      await api.post(`/runs/${runId}/cancel`)
    },

    async setPermissionMode(mode) {
      // The level belongs to a conversation: choosing one before the first message starts it.
      if (!get().conv) await get().newConversation()
      const conv = get().conv
      if (conv) await api.patch(`/conversations/${conv.conversation.id}`, { permission_mode: mode })
    },

    async setPlanFirst(on) {
      // As the level: a setting of a conversation, which choosing it before the first message starts.
      if (!get().conv) await get().newConversation()
      const conv = get().conv
      if (conv) await api.patch(`/conversations/${conv.conversation.id}`, { plan_first: on })
    },

    async setPageScripts(on) {
      const conv = get().conv
      if (!conv) return
      const saved = await api.patch<Conversation>(`/conversations/${conv.conversation.id}`, { page_scripts: on })
      set(s => (s.conv?.conversation.id === saved.id ? { conv: { ...s.conv, conversation: saved } } : s))
    },

    async decidePlan(runId, decision, text, overBudget) {
      await api.post(`/runs/${runId}/plan/${decision}`, decision === 'approve' ? { text, over_budget: overBudget } : { why: text })
    },

    async falseAlarm(warningId) {
      const id = get().conv?.conversation.id
      if (!id) return
      const now = await api.post<InjectionWarning>(`/conversations/${id}/warnings/${warningId}/false-alarm`)
      // Its rule's count is every warning's of that rule.
      set(s => s.conv?.conversation.id !== id ? s : { conv: { ...s.conv, warnings: s.conv.warnings.map(w =>
        w.id === now.id ? now : w.rule === now.rule ? { ...w, false_alarms: now.false_alarms } : w) } })
    },

    async decideCommand(commandId, decision) {
      if (decision === 'reject') await api.post(`/commands/${commandId}/reject`)
      else await api.post(`/commands/${commandId}/approve`, { remember: decision === 'always' })
    },

    async removeRule(ruleId) {
      await api.delete(`/allowed-commands/${ruleId}`)
    },

    async decideWeb(requestId, decision) {
      if (decision === 'reject') await api.post(`/web-requests/${requestId}/reject`)
      else await api.post(`/web-requests/${requestId}/approve`, { remember: decision === 'always' })
    },

    async removeWebRule(ruleId) {
      await api.delete(`/allowed-web/${ruleId}`)
    },

    async allowHost(conversationId, host) {
      // (The list hears of it as an event, like any change to it.)
      await api.post(`/conversations/${conversationId}/allowed-web`, { host })
    },

    async allowSite(conversationId, host, askFirst) {
      // (The list hears of it as an event, like any change to it.)
      await api.post(`/conversations/${conversationId}/allowed-web`, { host, kind: 'page', ask_first: askFirst })
    },

    async setAskFirst(ruleId, askFirst) {
      // (The list hears of it as an event, like any change to it.)
      await api.patch(`/allowed-web/${ruleId}`, { ask_first: askFirst })
    },

    async decideSpawn(agentId, decision) {
      await api.post(`/agents/${agentId}/${decision}`)
    },

    async decideMerge(mergeId, decision, choices, shown, said) {
      await api.post(`/merges/${mergeId}/${decision}`, decision === 'approve' ? { choices: choices ?? {}, shown, ...said } : undefined)
      // (What comes of it - the files taken, the commit offered - arrives as events.)
    },

    async resolveMerge(mergeId) {
      await api.post(`/merges/${mergeId}/resolve`)
    },

    async continueMerge(mergeId) {
      await api.post(`/merges/${mergeId}/continue`)
      // (The card is withdrawn, and the agent's steps come, as events.)
    },

    async checkMerge(mergeId, choices) {
      await api.post(`/merges/${mergeId}/check`, { choices })
    },

    async commitMerge(mergeId, message, hooks) {
      await api.post(`/merges/${mergeId}/commit`, { message, hooks })
    },

    async decideRole(toolCallId, decision, scope) {
      await api.post(`/tool-calls/${toolCallId}/${decision}`, scope && { scope })
    },

    async setChatFolders(lists) {
      const conv = get().conv
      if (!conv) return
      const saved = await api.patch<Conversation>(`/conversations/${conv.conversation.id}`, lists)
      set(s => (s.conv?.conversation.id === saved.id ? { conv: { ...s.conv, conversation: saved } } : s))
    },

    async setChatPart(part) {
      const conv = get().conv
      if (!conv) return
      const saved = await api.patch<Conversation>(`/conversations/${conv.conversation.id}`, { part })
      set(s => (s.conv?.conversation.id === saved.id ? { conv: { ...s.conv, conversation: saved } } : s))
    },

    async setChatTeams(change) {
      const conv = get().conv
      if (!conv) return
      const saved = await api.patch<Conversation>(`/conversations/${conv.conversation.id}`, change)
      set(s => (s.conv?.conversation.id === saved.id ? { conv: { ...s.conv, conversation: saved } } : s))
    },

    async stopTeam(teamId) {
      const conv = get().conv
      if (!conv) return
      const saved = await api.post<Conversation>(`/conversations/${conv.conversation.id}/teams/${teamId}/stop`, {})
      set(s => (s.conv?.conversation.id === saved.id ? { conv: { ...s.conv, conversation: saved } } : s))
    },

    async finishTeam(teamId) {
      const conv = get().conv
      if (!conv) return
      const saved = await api.post<Conversation>(`/conversations/${conv.conversation.id}/teams/${teamId}/finish`, {})
      set(s => (s.conv?.conversation.id === saved.id ? { conv: { ...s.conv, conversation: saved } } : s))
    },

    async answerQuestion(questionId, answer) {
      await api.post(`/questions/${questionId}/answer`, { answer })
    },

    async decidedOk(questionId) {
      const question = await api.post<Question>(`/questions/${questionId}/ok`, {})
      set(s => (s.conv ? { conv: applyEvent(s.conv, null, 'question.updated', question) } : s))
    },

    async decidedChange(questionId, answer) {
      const question = await api.post<Question>(`/questions/${questionId}/change`, { answer })
      set(s => (s.conv ? { conv: applyEvent(s.conv, null, 'question.updated', question) } : s))
    },

    async saveProjectSettings(values) {
      const { projectId } = get()
      if (!projectId) return
      // The image is saved first so that switching to Docker finds it set.
      // (What is left out - another section's settings - is kept as it is: "" would take the image away.)
      const saved = await api.patch<Project>(`/projects/${projectId}`, {
        ...values,
        ...('docker_image' in values && { docker_image: values.docker_image ?? '' }),
      })
      set(s => ({ projects: s.projects.map(p => (p.id === saved.id ? saved : p)) }))
      if ('monthly_budget' in values) void get().loadBudget().catch(() => {})
    },

    async takeKoloniSettings(asks) {
      const at = `/projects/${get().projectId}`
      const put = (project: Project) => set(s => ({ projects: s.projects.map(p => (p.id === project.id ? project : p)) }))
      try {
        const used = await api.post<Project>(`${at}/koloni/use`, { asks })
        put(used)
        return used
      } catch (err) {
        // (The file may have changed since the card showed it: the card shows what it says now.)
        await api.get<Project>(at).then(put, () => {})
        throw err
      }
    },

    select(nodeId) {
      set({ selectedNodeId: nodeId })
    },

    turnId: null,

    showTurn(runId) {
      set({ turnId: runId })
    },

    async openTurn(conversationId, runId) {
      // Opening another conversation forgets the turn picked in the one before: so first that.
      if (get().conv?.conversation.id !== conversationId) await get().openConversation(conversationId)
      if (get().conv?.conversation.id === conversationId) set({ turnId: runId })
    },

    filesOpen: false,
    filesAt: { key: null, n: 0 },
    filesRef: null,
    gitBranch: null,
    gitAsked: 0,

    showGit() {
      set(s => ({ gitAsked: s.gitAsked + 1 }))
    },

    openFiles(key) {
      set(s => ({ filesOpen: true, filesRef: null, filesAt: { key: key ?? null, n: s.filesAt.n + 1 } }))
    },

    lookAt(ref) {
      set(s => ({ filesOpen: true, filesRef: ref, filesAt: { key: null, n: s.filesAt.n + 1 } }))
    },

    openChange(changeId) {
      const change = get().conv?.fileChanges.find(f => f.id === changeId)
      // B-127: one still in a copy is in no file of the project - the window said "It could not be read"; its diff is in the inspector.
      if (change?.status === 'in_copy') return set({ selectedNodeId: `file:${change.id}` })
      get().openFiles(change && keyOf(change.path))
    },

    closeFiles() {
      set({ filesOpen: false })
    },

    async decide(changeId, action) {
      const change = await api.post<FileChange>(`/file-changes/${changeId}/${action}`)
      // The same record also arrives as an event; applying it twice is harmless. (Not into the open chat one of another's, from Ready for you.)
      set(s => (s.conv?.fileChanges.some(f => f.id === change.id) ? { conv: applyEvent(s.conv, null, 'file_change.updated', change) } : s))
    },
  }
})
