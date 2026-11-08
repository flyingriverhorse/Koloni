import type {
  Agent,
  AllowedCommand,
  AllowedWeb,
  Attachment,
  Away,
  BoardPost,
  ChannelMessage,
  Claim,
  Command,
  Conversation,
  Discussion,
  DiscussionPost,
  FileChange,
  InjectionWarning,
  Merge,
  Message,
  PendingRole,
  PendingSkill,
  Question,
  Room,
  RoomItem,
  RoomPost,
  Run,
  Snapshot,
  ToolCall,
  NotesOffer,
  Topic,
  TriggerProposal,
  WebRequest,
} from '../api/types'
import { turnTeams } from '../agents/teamRun'

/** Everything the UI knows about one conversation; chat, canvas and Changes derive from it. */
export interface ConvState {
  conversation: Conversation
  messages: Message[]
  runs: Run[]
  /** The pieces of work the turns go on with, in the order they began. */
  topics: Topic[]
  toolCalls: ToolCall[]
  fileChanges: FileChange[]
  commands: Command[]
  allowedCommands: AllowedCommand[]
  /** The web searches and HTTP requests you were asked about, decided or not. */
  webRequests: WebRequest[]
  /** What this conversation does on the web without asking: search, or GET from a host. */
  allowedWeb: AllowedWeb[]
  agents: Agent[]
  channelMessages: ChannelMessage[]
  /** Roles an agent asked to create and you have not decided on yet. */
  pendingRoles: PendingRole[]
  /** Skills an agent asked to add and you have not decided on yet. */
  pendingSkills: PendingSkill[]
  /** Everything agents asked you, answered or not. */
  questions: Question[]
  /** Discussions between agents, and everything said in them (also by you). */
  discussions: Discussion[]
  discussionPosts: DiscussionPost[]
  /** The rooms you opened, their lists of items and everything said in them (also by you). */
  rooms: Room[]
  roomItems: RoomItem[]
  roomPosts: RoomPost[]
  /** The shared notebook of every turn: what agents and you noted for the others. */
  boardPosts: BoardPost[]
  /**
   * The files of the project that an agent holds right now, until its work is done: another
   * agent that wants one waits for it. The holder may be an agent of another conversation.
   */
  claims: Claim[]
  /**
   * The working copies of this conversation's agents on their way into the project: one an
   * agent has while you are asked about its changes, and afterwards how that ended.
   */
  merges: Merge[]
  /** The files you attached (slice 85b): those sent with messages, and those added to the next one. */
  attachments: Attachment[]
  /** The "While you're away" cards the Lead put in this chat, with their nights (slice 106). */
  away: Away[]
  /** The triggers its agents proposed (slice 69), decided or not. */
  triggerProposals: TriggerProposal[]
  notesOffers: NotesOffer[]
  /** Where text from outside read like orders to an agent (93-A4), oldest first. */
  warnings: InjectionWarning[]
  lastEventId: number
  thinkingRunId: string | null
  thinkingAgentId: string | null
  /**
   * The agents whose model is thinking right now, each for itself: agents work at the same
   * time. One is in it from its model's thinking until that model writes or its step ends.
   */
  thinkingAgents: string[]
  /** The agents whose older history their own model is summarising right now (slice 59b), until their step goes on. */
  summarisingAgents: string[]
  /** What the CLIs of agents at work last said of their context and plan (89j), by agent; on no record. */
  live: Record<string, AgentLive>
  /** How many files were put before you since this was read (`view.shown`): a file `show` named, or one a command made (R161). */
  shown: number
}

/** What an agent's CLI says while it works (89j): its context's fill, and Codex's plan - its words are data. */
export interface AgentLive {
  context: { used: number; window: number } | null
  plan: { step: string; status: 'pending' | 'inProgress' | 'completed' }[] | null
  /** Qoder's free model queued (K-qoder-kuyruk): how long so far and at most, and whether it says the service is up. */
  queue: { elapsed_s: number | null; max_s: number | null; available: boolean | null } | null
}

export const TERMINAL: ReadonlySet<Run['status']> = new Set([
  'completed',
  'failed',
  'cancelled',
  'interrupted',
])

export function fromSnapshot(s: Snapshot): ConvState {
  return {
    conversation: s.conversation,
    messages: s.messages,
    runs: s.runs,
    // (A server from before topics sends none.)
    topics: s.topics ?? [],
    toolCalls: s.tool_calls,
    fileChanges: s.file_changes,
    commands: s.commands,
    allowedCommands: s.allowed_commands,
    // (A server from before the web tools sends neither.)
    webRequests: s.web_requests ?? [],
    allowedWeb: s.allowed_web ?? [],
    agents: s.agents,
    channelMessages: s.channel_messages,
    pendingRoles: s.pending_roles,
    // (A server from before skills sends none.)
    pendingSkills: s.pending_skills ?? [],
    questions: s.questions,
    discussions: s.discussions,
    discussionPosts: s.discussion_posts,
    // (A server from before rooms sends none.)
    rooms: s.rooms ?? [],
    roomItems: s.room_items ?? [],
    roomPosts: s.room_posts ?? [],
    boardPosts: s.board_posts,
    // (A server from before files were held sends none.)
    claims: s.claims ?? [],
    // (A server from before working copies sends none.)
    merges: s.merges ?? [],
    attachments: s.attachments ?? [],
    away: s.away ?? [],
    triggerProposals: s.trigger_proposals ?? [],
    notesOffers: s.notes_offers ?? [],
    warnings: s.warnings ?? [],
    lastEventId: s.last_event_id,
    thinkingRunId: null,
    thinkingAgentId: null,
    thinkingAgents: [],
    summarisingAgents: [],
    live: {},
    shown: 0,
  }
}

const without = (agents: string[], agentId: string | null | undefined): string[] =>
  agentId && agents.includes(agentId) ? agents.filter(id => id !== agentId) : agents

function upsert<T extends { id: string }>(list: T[], item: T): T[] {
  const index = list.findIndex(x => x.id === item.id)
  if (index === -1) return [...list, item]
  const next = list.slice()
  next[index] = item
  return next
}

/**
 * Fold one server event into the state. Persistent events carry an id and are
 * applied at most once; transient ones (id null) are applied as they arrive.
 */
export function applyEvent(
  state: ConvState,
  id: number | null,
  type: string,
  payload: unknown,
): ConvState {
  if (id !== null) {
    if (id <= state.lastEventId) return state
    state = { ...state, lastEventId: id }
  }
  switch (type) {
    case 'run.started':
    case 'run.updated':
      return { ...state, runs: upsert(state.runs, payload as Run) }
    case 'run.finished':
      return {
        ...state,
        runs: upsert(state.runs, payload as Run),
        thinkingRunId: null,
        thinkingAgentId: null,
        thinkingAgents: [],
        summarisingAgents: [],
      }
    case 'run.thinking': {
      const { run_id, agent_id, summarising } = payload as { run_id: string; agent_id?: string; summarising?: boolean }
      if (summarising && agent_id) return { ...state, summarisingAgents: [...without(state.summarisingAgents, agent_id), agent_id].sort() }
      return {
        ...state,
        thinkingRunId: run_id,
        thinkingAgentId: agent_id ?? null,
        thinkingAgents: agent_id ? [...without(state.thinkingAgents, agent_id), agent_id].sort() : state.thinkingAgents,
      }
    }
    case 'agent.created':
    case 'agent.updated':
      return { ...state, agents: upsert(state.agents, payload as Agent) }
    case 'channel.created':
      return { ...state, channelMessages: upsert(state.channelMessages, payload as ChannelMessage) }
    case 'discussion.created':
    case 'discussion.updated':
      return { ...state, discussions: upsert(state.discussions, payload as Discussion) }
    case 'discussion_post.created':
      return { ...state, discussionPosts: upsert(state.discussionPosts, payload as DiscussionPost) }
    case 'injection.warned':
      // (Kept, so it has an id: the warning's own - which a snapshot read meanwhile may have too.)
      if (id === null || state.warnings.some(w => w.id === id)) return state
      return { ...state, warnings: [...state.warnings, { ...(payload as Omit<InjectionWarning, 'id'>), id }] }
    case 'room.created':
    case 'room.updated':
      return { ...state, rooms: upsert(state.rooms, payload as Room) }
    case 'room_item.created':
    case 'room_item.updated':
      return { ...state, roomItems: upsert(state.roomItems, payload as RoomItem) }
    case 'room_post.created':
    case 'room_post.updated':
      return { ...state, roomPosts: upsert(state.roomPosts, payload as RoomPost) }
    case 'board.posted':
      return { ...state, boardPosts: upsert(state.boardPosts, payload as BoardPost) }
    case 'question.created':
    case 'question.updated':
      return { ...state, questions: upsert(state.questions, payload as Question) }
    case 'role_request.created': {
      const request = payload as PendingRole
      const others = state.pendingRoles.filter(r => r.tool_call_id !== request.tool_call_id)
      return { ...state, pendingRoles: [...others, request] }
    }
    case 'role_request.resolved': {
      const { tool_call_id } = payload as { tool_call_id: string }
      return { ...state, pendingRoles: state.pendingRoles.filter(r => r.tool_call_id !== tool_call_id) }
    }
    case 'skill_request.created': {
      const request = payload as PendingSkill
      const others = state.pendingSkills.filter(r => r.tool_call_id !== request.tool_call_id)
      return { ...state, pendingSkills: [...others, request] }
    }
    case 'skill_request.resolved': {
      const { tool_call_id } = payload as { tool_call_id: string }
      return { ...state, pendingSkills: state.pendingSkills.filter(r => r.tool_call_id !== tool_call_id) }
    }
    case 'message.created':
    case 'message.completed': {
      const message = payload as Message
      // A model step of its own begins or ends here: whatever it was thinking, it is not now.
      const mine = message.role === 'assistant'
      const thinkingAgents = mine ? without(state.thinkingAgents, message.agent_id) : state.thinkingAgents
      const summarisingAgents = mine ? without(state.summarisingAgents, message.agent_id) : state.summarisingAgents
      return { ...state, thinkingAgents, summarisingAgents, messages: upsert(state.messages, message) }
    }
    case 'message.delta': {
      const { message_id, text } = payload as { message_id: string; text: string }
      const message = state.messages.find(m => m.id === message_id)
      if (!message || message.status !== 'streaming') return state
      return {
        ...state,
        thinkingRunId: null,
        thinkingAgentId: null,
        thinkingAgents: without(state.thinkingAgents, message.agent_id),
        summarisingAgents: without(state.summarisingAgents, message.agent_id),
        messages: upsert(state.messages, { ...message, content: message.content + text }),
      }
    }
    case 'message.sync': {
      const { message_id, content } = payload as { message_id: string; content: string }
      const message = state.messages.find(m => m.id === message_id)
      if (!message || message.status !== 'streaming') return state
      return { ...state, messages: upsert(state.messages, { ...message, content }) }
    }
    case 'tool_call.created':
    case 'tool_call.updated':
      return { ...state, toolCalls: upsert(state.toolCalls, payload as ToolCall) }
    case 'file_change.created':
    case 'file_change.updated':
      return { ...state, fileChanges: upsert(state.fileChanges, payload as FileChange) }
    case 'command.created': {
      // Whatever the server left out, a command on screen always has an output to show.
      const created = payload as Omit<Command, 'output'> & { output?: string }
      return { ...state, commands: upsert(state.commands, { ...created, output: created.output ?? '' }) }
    }
    case 'command.updated': {
      // Updates carry the command's facts but not its output, which streams separately.
      const update = payload as Omit<Command, 'output'> & { output?: string }
      const known = state.commands.find(c => c.id === update.id)
      const merged: Command = { ...update, output: update.output ?? known?.output ?? '' }
      return { ...state, commands: upsert(state.commands, merged) }
    }
    case 'command.output': {
      const { command_id, text } = payload as { command_id: string; text: string }
      const command = state.commands.find(c => c.id === command_id)
      if (!command || command.status !== 'running') return state
      return {
        ...state,
        commands: upsert(state.commands, { ...command, output: command.output + text }),
      }
    }
    case 'command.sync': {
      const { command_id, output } = payload as { command_id: string; output: string }
      const command = state.commands.find(c => c.id === command_id)
      if (!command || command.status !== 'running') return state
      return { ...state, commands: upsert(state.commands, { ...command, output }) }
    }
    case 'allowed_commands.updated':
      return { ...state, allowedCommands: (payload as { rules: AllowedCommand[] }).rules }
    case 'web_request.updated':
      return { ...state, webRequests: upsert(state.webRequests, payload as WebRequest) }
    case 'allowed_web.updated':
      return { ...state, allowedWeb: (payload as { rules: AllowedWeb[] }).rules }
    case 'conversation.updated': {
      const conversation = payload as Conversation
      // B-107: a turn keeps its teams' rows as last seen; the chat's teams changed after it do not change it.
      const runs = state.runs.map(run => (conversation.teams.some(row => row.state?.run_id === run.id) ? { ...run, teams: turnTeams({ conversation, runs: [run] }, run.id) } : run))
      return { ...state, conversation, runs }
    }
    case 'topic.created':
    case 'topic.updated':
      return { ...state, topics: upsert(state.topics, payload as Topic) }
    case 'merge.updated':
      return { ...state, merges: upsert(state.merges, payload as Merge) }
    case 'attachment.created':
    case 'attachment.updated':
      return { ...state, attachments: upsert(state.attachments, payload as Attachment) }
    case 'attachment.deleted':
      return { ...state, attachments: state.attachments.filter(one => one.id !== (payload as { id: string }).id) }
    case 'agent.live': {
      // The latest, whole; nothing in it: its CLI has ended.
      const { agent_id, ...shown } = payload as AgentLive & { agent_id: string }
      const { [agent_id]: _was, ...others } = state.live
      return { ...state, live: shown.context || shown.plan || shown.queue ? { ...others, [agent_id]: shown } : others }
    }
    case 'view.shown':
      return { ...state, shown: state.shown + 1 }
    case 'claims.changed':
      // Who holds which file now, all of it: said again whenever it changes.
      return { ...state, claims: (payload as { claims: Claim[] }).claims }
    default:
      return state
  }
}

/** The run the agent is working on right now; queued runs are not active. */
export function activeRun(state: ConvState): Run | null {
  return state.runs.find(r => r.status === 'running' || r.status === 'waiting_approval') ?? null
}
