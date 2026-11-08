import type { components } from './generated'

type Schemas = components['schemas']

export type Project = Schemas['ProjectOut']
export type ProjectDeletePreview = Schemas['ProjectDeletePreviewOut']
export type Health = Schemas['HealthOut']
export type SharedFile = Schemas['SharedFileOut']
export type Conversation = Schemas['ConversationOut']
/** A conversation as the project's list has it: also whether changes of it were kept and wait for a decision. */
export type ListedConversation = Schemas['ConversationListed']
export type ConversationsDeleted = Schemas['ConversationsDeletedOut']
export type Run = Schemas['RunOut']
/** A piece of work in a conversation: the turns that go on with the same thing. */
export type Topic = Schemas['TopicOut']
export type Message = Schemas['MessageOut']
/** A file you added to a message (slice 85b); what it is was decided by the server, from its bytes. */
export type Attachment = Schemas['AttachmentOut']
export type GeminiVoice = Schemas['GeminiVoiceOut']
export type ToolCall = Schemas['ToolCallOut']
export type FileChange = Schemas['FileChangeOut']
/** What undoing a turn (or restoring to before one) does, or - looked ahead - would do. */
export type Undo = Schemas['UndoOut']
export type Snapshot = Schemas['SnapshotOut']
export type PermissionMode = Conversation['permission_mode']
export type Command = Schemas['CommandOut']
export type AllowedCommand = Schemas['AllowedCommandOut']
/** A web search or an HTTP request the user is, or was, asked about before it went out. */
export type WebRequest = Schemas['WebRequestOut']
/** What a conversation's turns do on the web without asking: search, or GET from one host. */
export type AllowedWeb = Schemas['AllowedWebOut']
/** What runs without asking in one chat of a project, for Settings › This project (tek-ev). */
export type ChatRules = Schemas['ChatRulesOut']
export type Role = Schemas['RoleOut']
/** K-uzman: what an expert knows, and how it stands in a project (its Knowledge tab). */
export type Knowledge = Schemas['Knowledge']
export type KnowledgeState = Schemas['KnowledgeStateOut']
/** K-bilgi: a knowledge on the project's Knowledge page, who uses it and how it stands there. */
export type KnowledgeItem = Schemas['KnowledgeOut']
export type KnowsMode = Schemas['KnowsOut']['mode']
/** A knowledge as it is sent: what is left out takes the server's default. */
export type KnowledgeIn = Omit<Knowledge, 'max_pages' | 'max_code_files' | 'search_answering' | 'weekly'> & Partial<Knowledge>
/** How strong the user says a model is, weakest first; a role can ask for one instead of a model. */
export type Tier = NonNullable<Role['tier_min']>
export const TIERS: Tier[] = ['fast', 'balanced', 'strongest']
/** How hard a model is asked to think, lowest first; null is the model's own (Default). */
export type Effort = NonNullable<Role['effort']>
export const EFFORTS: Record<Effort, string> = { off: 'Off', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'XHigh', max: 'Max' }
/** What an agent of a role would run on now, where that comes from, and which providers may be picked for it. */
export type RoleModel = Schemas['RoleModelOut']
/** A group of roles (slice 62): a chat working with some opens only their roles (84b). */
export type Team = Schemas['TeamOut']
/** A label roles are found by on the Agents page (slice 63b): a role's kind is its key. */
export type Category = Schemas['CategoryOut']
export type Colour = Category['colour']
/** Who picks a chat's teams (slice 84b): the Lead, the user, or nobody (any role). */
export type TeamsMode = Conversation['teams_mode']
/** A team a chat works with, and its recipe (null: the team's default); the user's or the Lead's, with its reason. */
export type ChatTeam = Schemas['ChatTeamOut']
/** Where a row's recipe is in a turn (slice 84b-2): its steps done, now and next, and how it stands. */
export type ChatTeamState = Schemas['ChatTeamState']
/** A row as the user picks it. */
export type ChatTeamIn = Schemas['ChatTeamIn']
/** A recipe (slice 84a): the steps of a piece of work, KOLONİ's own (three ready) or a folder's, as its graph is kept. */
export type Recipe = Schemas['RecipeOut']
export type RecipeGraph = Schemas['RecipeGraph']
export type RecipeStep = Schemas['RecipeStep']
/** K-evrim-model: the user's model for one candidate of a step - a provider and one of its models (null: its default). */
export type CandidateModel = Schemas['CandidateModel']
/** The recipes, the folder's files that are not read, and why "Or write it" cannot ask now (null: it can). */
export type Recipes = Schemas['RecipesOut']
/** A model's draft of a recipe, saved nowhere. */
export type RecipeDraft = Schemas['RecipeDraftOut']
/** What the Agents page draws from the record: each role's last agent, and who is at work. */
export type RolesActivity = Schemas['RolesActivityOut']
/** The Agents page's History: jobs by role, teams' and recipes' runs, the latest jobs (`/roles/history`). */
export type RolesHistory = Schemas['RolesHistoryOut']
export type Agent = Schemas['AgentOut']
/** A count of an agent's own tool calls: the same failure, or the same result, so many times. A fact, not a judgement. */
export type Sign = Schemas['SignOut']
/** What was measured of the agents of one role on one model: counts, and the middle one of steps, seconds and tokens. */
export type RecordRow = Schemas['RecordRow']
export type SkillRecordRow = Schemas['SkillRecordRow']
/** A program that speaks MCP, added by the user: its command, the names of its variables and its tools as last read. */
export type McpServer = Schemas['McpServerOut']
export type McpTool = Schemas['McpToolOut']
export type BuiltinTool = Schemas['BuiltinToolOut']
/** A server after its tools were read, and the names of the tools that reading found new, changed and gone. */
export type McpRead = Schemas['McpReadOut']
/** What is sent to add a server, and to change one: its command, variables to set (null: to take away), marks of its tools. */
export type NewMcpServer = Schemas['McpServerIn']
export type McpServerChange = Schemas['McpServerPatch']
/** A server's package as npm or PyPI lists it, before anything of it is downloaded (slice 92). */
export type PackageAbout = Schemas['PackageOut']
/** What code says outright, read as text and never run: never that it is safe. */
export type CodeSeen = Schemas['SeenOut']
export type PackageSeen = Schemas['PackageSeenOut']
/** One of the user's own slash commands (slice 53); `project_id` null: offered in every project. */
export type OwnCommand = Schemas['OwnCommandOut']
export type NewOwnCommand = Schemas['OwnCommandIn']
export type ChannelMessage = Schemas['ChannelMessageOut']
/** A file of the project that an agent holds until its work is done. */
export type Claim = Schemas['ClaimOut']
/** An agent's working copy on its way into the project: the files it changed, each with how it ended. */
export type Merge = Schemas['MergeOut']
export type MergeFile = Schemas['MergeFileOut']
/** One message sent to two models side by side (slice 54): each side's answer, changes and spend. */
export type Compare = Schemas['CompareOut']
export type CompareSide = Schemas['CompareSideOut']
/** Every conversation of a project and its agents at work, and where two conversations want one file. */
export type Board = Schemas['BoardOut']
/** The project's git, read only (slice 70): the top bar's status and its map. */
export type GitStatus = Schemas['GitOut']
/** A file git says is changed in the working tree (K-degisenler): the Workspace's Changes tab. */
export type GitChange = Schemas['GitChangeOut']
/** One of the last works KOLONİ has on record of a file (K-devir-4): the line over it in the Workspace. */
export type FileHistory = Schemas['FileHistoryOut']
export type Handed = Schemas['HandedOut']
/** An agent's working copy as its work goes on (slice 70): each file it changed, with its diff. */
export type WorkingCopy = Schemas['WorkingCopyOut']
/** A task of the project's backlog: what an agent proposed for it waits for your word, its assessment is an opinion. */
export type BacklogTask = Schemas['BacklogTaskOut']
export type NewBacklogTask = Schemas['BacklogTaskIn']
export type BacklogTaskChange = Schemas['BacklogTaskPatch']
/** Whether the backlog works itself, and why it last stopped by itself; and the level and model its chats start with. */
export type BacklogAuto = Schemas['BacklogAutoOut']
export type BacklogChoice = Schemas['BacklogChoiceIn']
/** A model's tasks from the user's note, saved nowhere, and who wrote them. */
export type BacklogDraft = Schemas['BacklogDraftOut']
/** A "While you're away" card the Lead put, and once you started it its night: jobs, places kept out, limits (slice 106). */
export type Away = Schemas['AwayOut']
export type AwayJob = Schemas['AwayJobOut']
/** What a waiting job asks: a yes or a no at its own endpoint, or answered in its chat. */
export type AwayAsk = Schemas['AwayAsk']
export type AwayChange = Schemas['AwayIn']
export type Day = Schemas['DayOut']
export type DayWords = Schemas['DayWordsOut']
export type PendingRole = Schemas['PendingRoleOut']
/** Text from outside that read like orders to an agent (93-A4): the rule and where, never the text. */
export type InjectionWarning = Schemas['WarningOut']
/** A skill KOLONİ keeps (a SKILL.md and files beside it), and one as it is read from a folder before it is kept. */
export type Skill = Schemas['SkillOut']
export type SkillFound = Omit<Skill, 'id' | 'folder' | 'scripts_run_unasked' | 'enabled' | 'needs' | 'version'>
/** What you are shown before a skill is added: its scripts whole, what is not copied, and a sum over what is kept. */
export type SkillPreview = Schemas['SkillPreview']
/** A skill uploaded from this page: a chosen folder's files, or a .zip, each base64. */
export type SkillUpload = Schemas['SkillUpload']
/** Where a skill is taken from: a folder of this machine, a public GitHub repository, or an upload. */
export type SkillSource = { folder: string } | { github: string } | { upload: SkillUpload }
/** A skill an agent asked to add, with the roles to give it, not decided on yet. */
export type PendingSkill = Schemas['PendingSkillOut']
export type Question = Schemas['QuestionOut']
export type Discussion = Schemas['DiscussionOut']
export type DiscussionPost = Schemas['DiscussionPostOut']
export type BoardPost = Schemas['BoardPostOut']
/** Two to four agents working on one goal at the same time, in one working copy: opened by the user, as a turn of its own. */
export type Room = Schemas['RoomOut']
/** One piece of a room's work: it has one holder, and a file is changed only under an item of one's own. */
export type RoomItem = Schemas['RoomItemOut']
/** Something said in a room: by a member, by you ("said"), or by KOLONİ for a member whose work is over or that failed. */
export type RoomPost = Schemas['RoomPostOut']
/** A file of the conversation to be seen beside the chat: one an agent wrote, or put before the user with `show`. */
export type View = Schemas['ViewOut']
export type ProjectEntry = Schemas['ProjectEntryOut']
/** The folders every project's agents may also use, and the places KOLONİ never opens, with why. */
export type Folders = Schemas['FoldersOut']
/** One folder as the folder browser lists it (slice 86a): its path, its parts, the shortcuts, and the folders in it. */
export type FolderBrowse = Schemas['FolderBrowseOut']
/** Past what % of its window an agent KOLONİ compacts is summarised, in every project. */
export type Compaction = Schemas['Compaction']
/** K-cevap-dili: the language every agent writes in, in every project; null: Auto. */
export type AnswerLanguage = Schemas['AnswerLanguage']
export type Storage = Schemas['StorageOut']
export type ProjectFile = Schemas['ProjectFileOut']
export type OthersInstructions = Schemas['OthersInstructionsOut']
export type ProjectMap = Schemas['ProjectMapOut']
export type Frame = Schemas['FrameOut']
/** What is sent to open a room: its goal, its members and - where it is not the conversation's own - what it may spend. */
export type NewRoom = Schemas['RoomIn']
export type Provider = Schemas['ProviderOut']
export type ProviderTest = Schemas['ProviderTestOut']
/** Whether each model of a provider can be used now, and what to run when its CLI is missing or signed out. */
export type Availability = Schemas['AvailabilityOut']
/** A team guide proposed from the catalogue, not saved; how many did not fit. */
export type CatalogueFill = Schemas['CatalogueFillOut']
/** A provider not added yet, as its form has it so far: what its catalogue is found by. */
export type CatalogueDraft = Schemas['CatalogueFillIn']
/** What is known of a model, each fact with where it came from; null where it is not. */
export type ModelFacts = Schemas['ModelFactsOut']
/** What a model may take besides text (slice 85b). */
export type ModelInput = Schemas['ModelInputOut']['kind']
export const INPUTS: ModelInput[] = ['image', 'video', 'audio', 'pdf']
/** What the catalogue offers a provider not added yet. */
export type Suggestion = Schemas['SuggestOut']
/** The catalogue read (or what "Update catalogue" kept): its date and counts. */
export type CatalogueUpdate = Schemas['CatalogueUpdateOut']
/** The model server on this machine (slice 64): its program and arguments, how it is, what it printed (masked). */
export type LocalServer = Schemas['LocalServerOut']
export type LocalServerConfig = Schemas['LocalServerIn']
/** One provider's team guide proposed from the catalogue, every provider at once; nothing is saved. */
export type FilledProvider = Schemas['FillAllProvider']
/** Every provider's proposal, and the catalogue's note for each tier. */
export type FillAll = Schemas['FillAllOut']
/** models.dev's price of a model in use, where the user wrote none. */
export type CataloguePrice = Schemas['CataloguePriceOut']
/** Each tier's models in the order they are tried (slice 81a). */
export type Tiers = Schemas['TiersOut']
export type TierOrder = Schemas['TiersIn']
export type MemoryRecord = Schemas['MemoryOut']
export type ProjectMemory = Schemas['ProjectMemoryOut']
/** What an agent's `recall` would find: records of the memory, and what was said in earlier turns. */
export type MemorySearch = Schemas['MemorySearchOut']
export type SaidInTurn = Schemas['SaidOut']
export type Trigger = Schemas['TriggerOut']
/** Stop everything: whether it holds, what runs and would be held now, and what it stopped. */
export type Hold = Schemas['HoldOut']
export type TriggerRun = Schemas['TriggerRunOut']
/** A trigger an agent proposed (slice 69), on its card until your word. */
export type TriggerProposal = Schemas['TriggerProposalOut']
/** K-bilgi 6: what turns found for the project's Project notes, on a card under a turn until your word. */
export type NotesOffer = Schemas['NotesOfferOut']
/** One thing that was done to a trigger - made, changed, switched, deleted - as its record keeps it. */
export type TriggerLogEntry = Schemas['TriggerChangeOut']
/** A trigger as it is answered once, when it is made: a webhook's key is in it, and nowhere after. */
export type TriggerCreated = Schemas['TriggerCreatedOut']
export type TriggerPermissions = Schemas['TriggerPermissions']
export type TriggerBudget = Schemas['TriggerBudget']
/** What is sent to make a trigger, with every field said. */
export type NewTrigger = Required<Schemas['TriggerIn']> & { permissions: Required<TriggerPermissions> }
/** What is sent to change one: only what is to change. */
export type TriggerChange = Schemas['TriggerPatch']
/** What the agents' models reported, added up three ways. A sum is null when nothing is known. */
export type Usage = Schemas['UsageOut']
export type Budget = Schemas['BudgetOut']
/** What is left of the plan a CLI is signed in to, as the CLI says - or why that is not known (`unknown`). */
export type Limits = Schemas['LimitsOut']
/** The status line command that keeps Claude Code's reading fresh from the user's own sessions, and KOLONİ's script it runs. */
export type ClaudeSessionSetup = Schemas['ClaudeSessionSetupOut']
/** What an agent's CLI wrote itself, as the backend keeps it in memory: lines, and how many earlier ones are gone. */
export type RawLines = Schemas['RawOut']
export type RawLine = Schemas['RawLine']
/** What the user says a model costs, for a million tokens sent and a million written. */
export type Price = Schemas['PriceOut']
/** A restore staged for the next start (K-disa-aktar). */
export type Restored = Schemas['RestoreOut']
/** The restore staged for the next start, and where the newest a start could not apply is kept. */
export type Staged = Schemas['StagedOut']
