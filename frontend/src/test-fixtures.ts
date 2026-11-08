// Record builders shared by tests.
import { within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type {
  Agent,
  Board,
  BoardPost,
  Command,
  Conversation,
  FileChange,
  MemoryRecord,
  Message,
  ProjectMemory,
  Question,
  Run,
  ToolCall,
  Topic,
} from './api/types'
import type { ConvState } from './state/applyEvent'

export const conversation: Conversation = {
  id: 'c',
  project_id: 'p',
  title: 'Fix greeting',
  permission_mode: 'ask',
  spawn_approval: 'auto',
  spawn_max_depth: 2,
  spawn_max_agents: 6,
  spawn_max_parallel: 2,
  discussion_budget: 200000,
  provider_id: null,
  model_id: null,
  lead_auto: false,
  plan_first: false,
  page_scripts: false,
  lead_work: 'delegates',
  lead_hands_code: true,
  when_away: 'waits',
  away_minutes: 10,
  lead_effort: null,
  room_posts: 40,
  room_tokens: 400000,
  room_minutes: 30,
  room_min_tokens: 60000,
  also_in: [], read_in: [], part: null,
  created_at: '2026-10-05T10:00:00Z',
  updated_at: '2026-10-05T10:00:00Z',
  teams_mode: 'none',
  teams: [],
  archived_at: null,
}

export function run(id: string, status: Run['status'] = 'running', over: Partial<Run> = {}): Run {
  return {
    id,
    conversation_id: 'c',
    status,
    error: null,
    model_id: 'qwen',
    input_tokens: null,
    output_tokens: null,
    created_at: '2026-10-05T10:00:00Z',
    started_at: status === 'queued' ? null : '2026-10-05T10:00:00Z',
    ended_at: null,
    unattended: false,
    trigger_id: null,
    trigger_name: null,
    topic_id: null,
    plan_turn: false,
    plan: null,
    compare_id: null,
    ...over,
  }
}

type BoardTurn = NonNullable<Board['conversations'][number]['turn']>

/** A conversation's last turn as the Board says it: nothing of its agents, model or tokens known. */
export function boardTurn(id: string, status: BoardTurn['status'], ended_at: string | null, over: Partial<BoardTurn> = {}): BoardTurn {
  return { id, status, started_at: null, ended_at, agents: 0, provider_name: null, model_id: null, tokens: null, plan_waits: false, outcomes: [], ...over }
}

/** A topic of the user's own; with `trigger_id`, a trigger's. */
export function topic(id: string, title: string, over: Partial<Topic> = {}): Topic {
  return { id, conversation_id: 'c', title, trigger_id: null, created_at: '2026-10-05T10:00:00Z', ...over }
}

export function userMessage(runId: string, content: string): Message {
  return {
    id: `u-${runId}`,
    conversation_id: 'c',
    run_id: runId,
    agent_id: null,
    role: 'user',
    from_agent_id: null,
    delivered_at: null,
    discussion_id: null,
    board_post_id: null,
    room_post_id: null,
    content,
    status: 'complete',
    created_at: '2026-10-05T10:00:00Z',
  }
}

export function assistantMessage(
  id: string,
  runId: string,
  content: string,
  status: Message['status'] = 'complete',
): Message {
  return {
    id,
    conversation_id: 'c',
    run_id: runId,
    agent_id: runId,
    role: 'assistant',
    from_agent_id: null,
    delivered_at: null,
    discussion_id: null,
    board_post_id: null,
    room_post_id: null,
    content,
    status,
    created_at: '2026-10-05T10:00:01Z',
  }
}

export function toolCall(
  id: string,
  runId: string,
  name: string,
  status: ToolCall['status'],
  args = '{}',
  over: Partial<ToolCall> = {},
): ToolCall {
  return {
    id,
    run_id: runId,
    agent_id: runId,
    message_id: 'm',
    origin: 'koloni',
    parent_call_id: null,
    outside_folder: null,
    why_asked: null,
    seq: Number(id) || 1,
    provider_call_id: id,
    name,
    arguments: args,
    status,
    result: null,
    started_at: null,
    ended_at: null,
    ...over,
  }
}

export function fileChange(id: string, runId: string, over: Partial<FileChange> = {}): FileChange {
  return {
    id,
    run_id: runId,
    agent_id: runId,
    origin: 'koloni',
    tool_call_id: '1',
    path: 'src/a.py',
    kind: 'modify',
    status: 'applied',
    diff: '',
    additions: 3,
    deletions: 1,
    created_at: '2026-10-05T10:00:02Z',
    decided_at: null,
    gone: false,
    ...over,
  }
}

export function command(id: string, runId: string, over: Partial<Command> = {}): Command {
  return {
    id,
    run_id: runId,
    agent_id: runId,
    origin: 'koloni',
    tool_call_id: 't1',
    command: 'pytest -q',
    cwd: '.',
    location: 'host',
    image: null,
    status: 'exited',
    exit_code: 0,
    output: '',
    output_truncated: false,
    timeout_seconds: 120,
    suggested_prefix: 'pytest',
    web_off: false,
    danger: '',
    keep_running: false,
    preview_url: null,
    created_at: '2026-10-05T10:00:02Z',
    started_at: '2026-10-05T10:00:03Z',
    ended_at: '2026-10-05T10:00:05Z',
    ...over,
  }
}

/** A lead agent; by default it shares its run's id so records made by the builders belong to it. */
export function agent(runId: string, status: Agent['status'] = 'running', over: Partial<Agent> = {}): Agent {
  return {
    id: runId,
    run_id: runId,
    parent_agent_id: null,
    tool_call_id: null,
    provider_name: 'Local',
    failure: null,
    failure_resets_at: null,
    model_id: 'qwen',
    model_from: null,
    provider_mode: null,
    compacts_itself: false,
    chosen: false,
    chosen_why: null,
    tier: null,
    asked_how_hard: null,
    role_name: 'Lead',
    name: over.role_name ?? 'Lead',
    tools: ['list_dir', 'read_file', 'search', 'write_file', 'edit_file', 'run_command'],
    mcp: [],
    task: null,
    depth: 0,
    status,
    report: null,
    error: null,
    steps_given: 0,
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    cache_write_tokens: null,
    nano_aiu: null,
    premium_requests: null,
    created_at: '2026-10-05T10:00:00Z',
    started_at: '2026-10-05T10:00:00Z',
    ended_at: null,
    facts_given: [],
    continues_id: null,
    waiting_for: null,
    copy: null,
    sign: null,
    last_event_at: null,
    observation: null,
    observation_note: null,
    observed_by: null,
    effort: null,
    context_window: null,
    summarised: 0,
    summary: null,
    summary_note: null,
    summary_correctable: false,
    ...over,
  }
}

/** A question the lead of a run asked; pending unless told otherwise. */
export function question(id: string, runId: string, over: Partial<Question> = {}): Question {
  return {
    id,
    run_id: runId,
    agent_id: runId,
    tool_call_id: '1',
    question: 'Which greeting?',
    options: [],
    leave: false,
    status: 'pending',
    answer: null,
    created_at: '2026-10-05T10:00:02Z',
    answered_at: null,
    lead_why: null,
    seen_at: null,
    ...over,
  }
}

/** A note on a turn's shared notebook, written by the lead and read by nobody yet. */
export function note(id: string, runId: string, over: Partial<BoardPost> = {}): BoardPost {
  return {
    id,
    run_id: runId,
    agent_id: runId,
    content: 'hello.py is mine',
    seq: Number(id.replace(/\D/g, '')) || 1,
    created_at: '2026-10-05T10:00:03Z',
    read_by: [],
    team_id: null,
    team: null,
    everyone: false,
    koloni: false,
    ...over,
  }
}

/** A note as it was handed to an agent: a message in that agent's own conversation. */
export function handedNote(post: BoardPost, agentId: string): Message {
  return {
    ...assistantMessage(`h-${post.id}-${agentId}`, post.run_id, post.content),
    role: 'agent',
    agent_id: agentId,
    from_agent_id: post.agent_id,
    delivered_at: '2026-10-05T10:00:04Z',
    board_post_id: post.id,
  }
}

export function convState(over: Partial<ConvState> = {}): ConvState {
  return {
    conversation,
    messages: [],
    runs: [],
    topics: [],
    toolCalls: [],
    fileChanges: [],
    commands: [],
    allowedCommands: [],
    webRequests: [],
    allowedWeb: [],
    agents: [],
    channelMessages: [],
    pendingRoles: [],
    pendingSkills: [],
    questions: [],
    discussions: [],
    discussionPosts: [],
    rooms: [],
    roomItems: [],
    roomPosts: [],
    boardPosts: [],
    claims: [],
    merges: [],
    attachments: [],
    away: [],
    triggerProposals: [],
    notesOffers: [],
    warnings: [],
    lastEventId: 0,
    thinkingRunId: null,
    thinkingAgentId: null,
    thinkingAgents: [],
    summarisingAgents: [],
    live: {},
    shown: 0,
    ...over,
  }
}

/** A record of the project's memory: an agent's note in the journal, with no file behind it. */
export function memoryRecord(id: string, over: Partial<MemoryRecord> = {}): MemoryRecord {
  return {
    id,
    project_id: 'p',
    tier: 'note',
    text: 'The greeting is spelled merhaba.',
    about: 'greeting',
    // As the backend works it out: a fact, on a subject work can name.
    given_unasked: over.tier === 'fact' && over.about !== null,
    origin: 'agent',
    agent_id: over.origin === 'user' ? null : 'r',
    agent_name: over.origin === 'user' ? null : 'Lead',
    run_id: 'r',
    conversation_id: 'c',
    observed_at: '2026-10-05T10:00:00Z',
    source: null,
    source_state: over.source ? 'unchanged' : 'none',
    found_at: null,
    excerpt: null,
    source_modified: null,
    modified_in_turn: null,
    checked_how: null,
    status: 'active',
    supersedes_id: null,
    wants_core: false,
    decided_by: null,
    decided_at: null,
    decided_how: null,
    unattended: false,
    created_at: '2026-10-05T10:00:00Z',
    last_change: null,
    by_meaning: false,
    ...over,
  }
}

export function projectMemory(over: Partial<ProjectMemory> = {}): ProjectMemory {
  const core = over.core ?? []
  return {
    core,
    proposals: [],
    journal: [],
    past: [],
    suggestions: [],
    preferences: null,
    rules: null,
    rules_changed_at: null,
    rules_kept: false,
    decisions: [],
    core_chars: core.reduce((sum, record) => sum + record.text.length, 0),
    core_limit: 4000,
    ...over,
  }
}

/**
 * Opens one of an agent's folds (the panel's card or the window's story), by the words its line starts with
 * - its body is drawn only while it is open - and gives it back. Within `root` where both are on the page.
 */
export async function openAgentFold(name: string, root: HTMLElement = document.body): Promise<HTMLElement> {
  // A fold inside the window's Details (its raw steps) is drawn once Details is open.
  if (name !== 'Details' && !within(root).queryByText(name, { selector: 'summary, summary *' })) await openAgentFold('Details', root)
  const summary = within(root).getByText(name, { selector: 'summary, summary *' })
  const fold = summary.closest('details') as HTMLElement
  if (!fold.hasAttribute('open')) await userEvent.click(summary)
  return fold
}
