import { AGENT_STATUS, SUMMARISING, titleOf } from '../agents/agentStatus'
import { failureText } from '../agents/failure'
import { isOwnSubAgent } from '../agents/ownWork'
import type { Agent, Away, AwayJob, ChatTeam, ChatTeamState, Run, SharedFile, Team, View } from '../api/types'
import { type TeamRequest, askerOf, lineLabel, requestsOf, shortWhat, standsLine } from '../agents/teamRequests'
import { chatColours, isReadyCard, endedEarly, filesOf, rowTokens, tokensLine, turnTeams } from '../agents/teamRun'
import { talkOf } from '../chat/TalkRow'
import { atGivenSteps, isKept, pendingMerge } from '../changes/copies'
import { waitLine } from '../claims/claims'
import { discussionLine, nameIn, speakerOf } from '../discussion/discussionText'
import { byWatcher, isRunning, leadOf, memberTag, nameIn as nameInRoom, roomGoal, roomLine, waitsForYou, watchedBy } from '../room/roomText'
import { toolSummary } from '../chat/toolSummary'
import { TERMINAL, type ConvState } from '../state/applyEvent'
import { plannedBy } from '../chat/planText'
import { turnNumbers } from '../topics/topics'
import { turnOf } from './turns'
import { shown } from '../chat/attachments'
import { decidedOf, waitingOf, waitingSummary } from '../chat/waiting'
import { outputCards } from './outputs'
import { type SharedData, sharedColumn } from './sharedColumn'

export type NodeKind =
  | 'request'
  | 'agent'
  | 'discussion'
  | 'room'
  // K-shared-bagli: what a team (or an agent, or everyone) shared, noted and remembered - a card by it.
  | 'shared'
  // A plan turn's plan (slice 49): a small node after its request.
  | 'plan'
  // A chat team's recipe in the turn (slice 84b-2): a frame around its agents, and "Ready for you" where the teams meet.
  | 'team'
  | 'ready'
  // A file the user attached to the turn's message (slice 85b), beside its request; past FOLD_FILES of them, a box of them.
  | 'attachment'
  | 'files'
  // A night while you were away (slice 106), on the turn that put its card: each job's frame, and the morning's report.
  | 'awayjob'
  | 'away'
  // The user's (4 Nov): an earlier round of a step in a team's frame, as one line - its agents under it once opened.
  | 'round'
  // The Assistant PO, asked once the turn ended (the user's, 7 Nov): under its Lead, only where it was asked.
  | 'po'

/** The Assistant PO's request after a turn, as it was recorded (`Run.po`). */
export type PoData = NonNullable<Run['po']>

/** More files than these on a message are one box, "N files", folded until the user opens it. */
export const FOLD_FILES = 4

/** A file of the turn's message: its name and, as its chip says them, its kind and what happened to it. */
export interface AttachmentData {
  name: string
  label: string
  colour: string
  meta: string
}

/** What a group node (an agent, or a CLI's own sub-agent) says about what is inside it. */
export interface GroupData {
  /** How many nodes sit directly inside it; with none there is nothing to open or close. */
  inside: number
  /** What is inside, counted: "3 tools · 2 commands · 1 file". */
  summary: string
  /** Something inside waits for the user's approval or answer. */
  attention: boolean
  /** Its work is over. */
  finished: boolean
  /** Whether its inside is shown; decided where the graph is folded. */
  open: boolean
}

export interface RequestData {
  text: string
  time: string
  queued: boolean
  /** The trigger that started the turn, by its name then; null when the user wrote the message. */
  trigger: string | null
}

/**
 * An agent's node (the user's, 5 Nov): its name and model, its state, and what it did, counted - the rest of it is read
 * in the side panel and its window, from its record.
 */
export interface AgentData extends GroupData {
  role: string
  /** What the agent is called in its turn: its role, numbered when there are several. */
  name: string
  parentId: string | null
  /** Its team's colour, a strip on its left, when it works for a chat team's recipe (slice 84b-2). */
  colour?: string
  /** Where this agent's model steps went; null when not on record. */
  provider: string | null
  modelId: string | null
  /** "settings": the model's name was read from the CLI's own settings. */
  modelFrom: string | null
  /** The lead agent shows how its turn ended; otherwise an agent shows its own state. */
  status: Run['status'] | Agent['status']
  activity: string
  /** While a tool or command of its runs: when that started (the line says for how long); null otherwise. */
  since: string | null
  /** What was counted of its own tool calls; null: nothing. */
  sign: Agent['sign']
  /** Its work was ended for that count (a turn nobody watched): its error says so. */
  signStopped: boolean
  /** What its report found (`findingsLine`): by role on its line, each finding in `detail`; null: its report said nothing of findings. */
  findings: { line: string; detail: string } | null
  /** A finished agent of a step's newest round, where the step had rounds before: one line, its name and how it ended. */
  chip?: { said: string; colour: string }
  /** What it spent, where its provider counts so: "0.45 AI credits", "2 premium requests"; none: not counted. */
  spent?: string | null
}

export interface DiscussionData {
  topic: string
  /** Where it stands: the round, or how it ended. */
  line: string
  members: string[]
  /** The last things said, newest last. */
  last: { who: string; text: string }[]
  /** Whose turn it is, while it runs. */
  speaking: string | null
  running: boolean
}

/** A room: its goal, where it stands, who is in it and how each stands, and the last things said. */
export interface RoomData {
  goal: string
  line: string
  members: string[]
  /** R178: who watches it though no member, and what it may do there; '' where nobody does. */
  watched: string
  /** How far its list is: "2 of 3 items done"; '' while the list is empty. */
  items: string
  last: { who: string; text: string }[]
  running: boolean
  /** A card of one of its agents, or its changes, waits for the user. */
  attention: boolean
}

export interface PlanData {
  status: NonNullable<Run['plan']>['status'] | 'writing'
  /** Who wrote it (`plannedBy`); null while it is being written. */
  by: string | null
}

/** A chat team's recipe in a turn (slice 84b-2): the frame around its agents. Folded only by the user. */
export interface TeamData extends GroupData {
  teamId: string
  team: string
  recipe: string
  colour: string
  /** How the row stands (not `status`: the canvas follows what is at work, and a frame is all of its team). */
  stands: ChatTeamState['status']
  why: string | null
  steps: ChatTeamState['steps']
  /** K-rol-cogul: by step id, "Coder ×2" for each role the step's last pass opened more than one of. */
  many?: Record<string, string[]>
  /** Its agents' reported tokens, as said ("41k tokens + –"). */
  tokens: string
  /** The Lead: where the frame stands, folded. */
  parentId: string | null
  /**
   * What it holds, by node id, in the columns of its work line, left to right - `atOnce`: a group of its recipe's, whose
   * steps run at once (a dashed box); none: laid out as a tree.
   */
  columns: { ids: string[]; atOnce: boolean; rounds?: string[][] }[]
  /** B-101: framed by its roles, on the canvas only (`byRoles`): nothing to stop or finish. */
  byRoles?: boolean
  /** Those dashed boxes, from its corner, as the canvas laid them out; set where it is drawn. */
  boxes?: { left: number; top: number; width: number; height: number }[]
}

/**
 * A step's earlier round in a team's frame (the user's, 4 Nov): "Round 2 · 4 reviewed" and "2 blocking", or "Coder, Coder 2"
 * and "✓ 2"; `result` is '' where nothing of it is known.
 */
export interface RoundData extends GroupData {
  said: string
  result: string
  colour: string
}

/** A job of a night while you were away, and the night's report (slice 106): as the server says them. */
export interface AwayJobData {
  job: AwayJob
}
export interface AwayData {
  away: Away
}

/** Where a turn's teams meet (slice 84b-2): what each did, the checks its agents reported, and the user's word. */
export interface ReadyData {
  /** `kept`: B-101 - a team with no recipe beside one: its own kept copy, Take in or Discard on its row; null: none. */
  rows: { team: string; recipe: string; colour: string; line: string; done: boolean; kept: string | null }[]
  /** "Take in also takes in what Web app left before it stopped." - the one copy goes in whole (B-84); "" for none. */
  alsoTakes: string
  /** Only what agents reported: "Reviewer: no findings"; never a check nobody ran. */
  checks: { text: string; passed: boolean }[]
  /** Who it waits for ("Web app: Build it", "Quality: not started yet"); null once every team is at its end. */
  waits: string | null
  /** The teams whose work is in the project, by name: what was taken in, team by team. */
  inProject: string[]
  /** The picked teams that did not start in the turn (B-84). */
  notStarted: string[]
  /** The pending "Ready for you" card, answered here; null while none is asked. */
  questionId: string | null
  /** Every team that had something to take in is in the project. */
  taken: boolean
  /** Why a team's work is not (all) in the project - Take in left files out, it stopped; null: none such. */
  left: string | null
  /** What waits for you in the whole chat, as its Ready for you list counts it and says it in one line (K-bekleyenler). */
  /** `mine`: of them, this turn's to take in - a Take in's clash, a kept copy (B-142): what makes the node need you. */
  /** `decided`: what the Lead decided for you while you were away, to look at - not waiting (K-vekil-karar). */
  waiting: { count: number; summary: string; mine: number; decided: number }
  /** B-67: the recipe's copy its turn ended with, kept for Take in or Discard (the kept copy's card); null: none. */
  kept: string | null
}

export interface GraphNode {
  id: string
  kind: NodeKind
  runId: string
  /** Id of the record behind the node: message, agent, agent (for tools), command or file change. */
  refId: string
  /** The agent the node is, or belongs to; a request belongs to none. */
  agentId?: string
  /** The group node it sits inside: its agent, or a sub-agent of the CLI's own. */
  parent?: string
  /** The team frame an agent is drawn in (slice 84b-2): not a box it sits inside, but folded with it. */
  team?: string
  /** An agent of a step's earlier round: that round's line, which it is folded into. */
  round?: string
  data:
    | RequestData
    | AgentData
    | DiscussionData
    | RoomData
    | SharedData
    | Record<string, never>
    | PlanData
    | PoData
    | TeamData
    | ReadyData
    | AwayJobData
    | AwayData
    | RoundData
    | AttachmentData
    | GroupData
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  active: boolean
  /** A parent agent handing work to a sub-agent. */
  spawn?: boolean
  /** Two agents that are not parent and child, joined only because they talked. */
  talk?: boolean
  /** A member of a discussion in the lane (between teams): its line is drawn from its frame (`memberLine`), and keeps its agent to light it. */
  member?: boolean
  /** From a file the user attached to an agent it was handed to (slice 85b). */
  handed?: boolean
  /** How many messages the two agents sent each other. */
  messages?: number
  /** The last thing said on a talk line, short, and when. */
  last?: string
  lastAt?: string
  /** The agent that opens a team's agents, to the door of the team's frame (K-canvas-dili). */
  door?: boolean
  /** The work line in a team's frame: from its door, step to step in its recipe's order. */
  work?: boolean
  /** Talk between agents of two teams: agent to agent, out of each frame by its side, in the margin beside them (`crossTalk`). */
  cross?: boolean
  /** From an agent that waits for a file to the agent that holds it. */
  waits?: boolean
  /** From the agent whose report had findings to the one they were handed to: how many. */
  findings?: number
  /** A request between teams (K-takimlar-arasi): one short line from frame to frame, its label; open while it is at work. */
  request?: { label: string; open: boolean; title: string; calls: string[] }
  /** K-shared-bagli: a team's (or an agent's) line to its card, in its colour; a contract's arm from its request's line. */
  shared?: { colour: string; dotted?: boolean; arm?: string }
  /** From an approved plan down to the Lead of its work turn: what it carries out, not a flow - one short dashed line. */
  plan?: boolean
  /** With `plan`: from the Lead down to the Assistant PO asked as its turn ended - the same line, dashed its own way. */
  po?: boolean
}

/**
 * What an agent's report found: on a short line the roles it is for ("3 findings → Coder ×2, UI designer"),
 * and each finding in `detail`; null where it said nothing of findings.
 */
export function findingsLine(findings: Agent['findings']): { line: string; detail: string } | null {
  if (!findings) return null
  if (!findings.length) return { line: 'no findings', detail: 'Its report said it found nothing.' }
  const byRole = new Map<string, number>()
  for (const f of findings) byRole.set(f.role ?? 'no role', (byRole.get(f.role ?? 'no role') ?? 0) + 1)
  const roles = [...byRole].map(([role, n]) => (n > 1 ? `${role} ×${n}` : role)).join(', ')
  // B-192: a suggestion sends no work back - said apart, as Ready for you says it: "1 finding left, 1 suggestion".
  const left = findings.filter(f => f.blocking !== false).length
  const ideas = findings.length - left
  const said = ideas ? [...(left ? [`${plural(left, 'finding')} left`] : []), plural(ideas, 'suggestion')].join(', ') : plural(left, 'finding')
  return {
    line: `${said} → ${roles}`,
    detail: findings.map(f => `${f.what} (${f.kind}${f.blocking === false ? ', suggestion' : ''}) → ${f.role ?? 'no role named'}`).join('\n'),
  }
}

/** Its state in plain words (the user's, 5 Nov): what it does now, or how it ended. */
export function statusWords({ status, activity, findings }: Pick<AgentData, 'status' | 'activity' | 'findings'>): string {
  if (status === 'running') return `Working · ${activity.charAt(0).toLowerCase()}${activity.slice(1)}`
  if (activity === 'Waits for your approval') return 'Waits for your OK'
  if (status === 'completed') return findings && findings.line !== 'no findings' ? `Done · ${findings.line}` : 'Done ✓'
  if (status === 'failed' && !/^(Failed|Stopped)/.test(activity)) return `Failed: ${activity}`
  return activity
}

const ENDED: Partial<Record<AgentData['status'], string>> = {
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Stopped',
  interrupted: 'Interrupted',
  rejected: 'Not started',
}

const OPEN: ReadonlySet<Agent['status']> = new Set(['proposed', 'queued', 'running', 'waiting', 'blocked'])

/** Whether the agent asked the user a question that is still open. */
function wonders(agent: Agent, state: ConvState): boolean {
  return state.questions.some(q => q.agent_id === agent.id && q.status === 'pending')
}

/** Whether something this agent asked for is waiting for the user's decision. */
function asks(agent: Agent, state: ConvState): boolean {
  return (
    state.fileChanges.some(f => f.agent_id === agent.id && f.status === 'proposed') ||
    // What it changed in its working copy waits to be taken into the project.
    pendingMerge(state, agent.id) !== null ||
    state.commands.some(c => c.agent_id === agent.id && c.status === 'proposed') ||
    state.pendingRoles.some(r => r.agent_id === agent.id) ||
    state.pendingSkills.some(r => r.agent_id === agent.id) ||
    wonders(agent, state) ||
    state.agents.some(a => a.parent_agent_id === agent.id && a.status === 'proposed')
  )
}

/** The state an agent node shows. */
function statusOf(agent: Agent, run: Run, state: ConvState): AgentData['status'] {
  if (asks(agent, state)) return 'waiting_approval'
  if (agent.depth > 0) return agent.status
  if (run.status !== 'running' && run.status !== 'waiting_approval') return run.status
  if (agent.status === 'waiting') return 'waiting'
  // It waits for a file another agent holds: that asks nothing of the user.
  if (agent.status === 'blocked') return 'blocked'
  // The turn waits for a decision and no record says whose: it is the lead's.
  const someoneElse = state.agents.some(a => a.run_id === run.id && a.id !== agent.id && asks(a, state))
  return run.status === 'waiting_approval' && !someoneElse ? 'waiting_approval' : 'running'
}

const DOING: Record<string, string> = { read_file: 'reading', edit_file: 'editing', write_file: 'editing' }

/**
 * The tool of an agent's that runs now, in words, and since when: a command by what it runs, a file by
 * what is done to it, any other call by its summary. Null: none runs.
 * shortcut: a CLI's own Read or Edit is said by its tool's name alone (its path is in `file_path`); read that too if it is missed.
 */
function toolNow(agent: Agent, state: ConvState): { what: string; since: string | null } | null {
  const call = state.toolCalls.find(t => t.agent_id === agent.id && t.status === 'running')
  if (!call) return null
  // (A CLI's own command too: it is on record by the call that ran it.)
  const command = state.commands.find(c => c.tool_call_id === call.id)
  if (command) return { what: command.command, since: command.started_at }
  const summary = toolSummary(call)
  const doing = DOING[call.name]
  return { what: doing && summary !== call.name ? doing + summary.slice(call.name.length) : summary, since: call.started_at }
}

/** What an agent is doing right now, read off its own records. */
function activityOf(agent: Agent, run: Run, state: ConvState): string {
  const status = statusOf(agent, run, state)
  if (status === 'waiting_approval' && wonders(agent, state)) return 'Waits for your answer'
  if (status === 'waiting_approval' || status === 'proposed') return 'Waits for your approval'
  // Its provider has as many at work as it lets work at once (the lead too): which, and how full.
  const full = agent.status === 'queued' ? agent.queued_on : null
  if (full) return `queued · ${full.provider} full (${full.at_work}/${full.most})`
  // Only so many agents work at once; this one is next - the lead too, where the room it waits for is kept for it.
  if (agent.status === 'queued') return 'Waiting for a slot'
  // For a file another agent holds, until that one's work is done.
  if (status === 'blocked') return waitLine(agent, state.conversation.id) ?? 'waits for a file'
  if (status === 'waiting') {
    // In a turn whose room still runs: the lead waits for all of it; a member for a post, or -
    // before the work starts - for the others' step in the round that shares it out.
    const room = state.rooms.find(r => r.run_id === run.id && isRunning(r))
    if (room && agent.depth === 0) return 'Waiting for the room'
    if (room && state.toolCalls.some(t => t.agent_id === agent.id && t.name === 'wait_for_post' && t.status === 'running')) {
      return 'Waiting for a post in the room'
    }
    if (room && state.toolCalls.some(t => t.agent_id === agent.id && t.name === 'wait_for_item' && t.status === 'running')) {
      return 'Waiting for an item in the room'
    }
    if (room?.status === 'sharing' && room.members.some(m => m.agent_id === agent.id)) return 'Waiting for the work to be shared out'
    const child = state.agents.findLast(a => a.parent_agent_id === agent.id && OPEN.has(a.status))
    // Waiting for a reply to a message, or for a sub-agent it opened.
    // Waiting for another team's answer (K-takimlar-arasi): at its request, or once its own work is done.
    const request = requestsOf(state, run.id).findLast(r => r.from?.id === agent.id && (r.stands === 'waits' || r.stands === 'at work'))
    if (request && (request.stands === 'waits' || !child)) return `Waiting for ${request.to}`
    const asked = state.toolCalls.findLast(
      t => t.agent_id === agent.id && t.name === 'message_agent' && t.status === 'running',
    )
    if (asked) return `Waiting for ${talkOf(asked).to || 'a reply'}`
    return child ? `Waiting for ${child.name || child.role_name}` : 'Waiting for a sub-agent'
  }
  if (status === 'running') {
    // R130: its model is in Qoder's queue (K-qoder-kuyruk) - waiting there, not working.
    if (state.live[agent.id]?.queue) return 'Queued at Qoder'
    const working = toolNow(agent, state)
    if (working) return working.what
    const writing = state.messages.some(
      m => m.agent_id === agent.id && m.status === 'streaming' && m.content,
    )
    if (writing) return 'Writing reply…'
    if (state.summarisingAgents.includes(agent.id)) return SUMMARISING
    // Each agent for itself: several work, and think, at the same time.
    if (state.thinkingAgents.includes(agent.id)) return 'Thinking…'
    return 'Waiting for the model…'
  }
  if (status === 'failed' && (agent.error ?? run.error) === 'step_limit') return 'Stopped at its step limit'
  // K-devam-butce (B-327): at the end of the steps it was given, the budget - not the app's limit.
  if (status === 'failed' && atGivenSteps(agent.error)) return `Stopped after the ${agent.error!.slice('stopped after the '.length)}`
  // Why its model failed, where its provider said why.
  return (status === 'failed' && failureText(agent)) || (ENDED[status] ?? status)
}

const plural = (count: number, one: string) => `${count} ${one}${count === 1 ? '' : 's'}`

/** What a group holds, in words; nothing that is not there is named. */
function summaryOf(tools: number, commands: number, files: number, subAgents = 0): string {
  return [
    tools && plural(tools, 'tool'),
    commands && plural(commands, 'command'),
    files && plural(files, 'file'),
    subAgents && plural(subAgents, 'own sub-agent'),
  ]
    .filter(Boolean)
    .join(' · ')
}

/** How much of the last thing said a talk line shows. */
const LAST_CHARS = 32

/** A chat team's row of a turn, with how it stands. */
type RanRow = ChatTeam & { state: ChatTeamState }

/** A team at the end of its recipe, for the user or done: "done · 4 files · 2 rounds · 41k tokens". */
function doneLine(state: ConvState, row: RanRow): string {
  // A loop's count is on each step it went back over (R116): the most of them, not their sum.
  // shortcut: two loops over different steps are counted as the longer one; add them if seen.
  const rounds = Math.max(0, ...row.state.steps.map(step => step.round))
  // B-126: what a command wrote is on record only once taken in - the count leaves it out till then.
  const ran = row.state.status !== 'in' && state.commands.some(c => c.started_at && row.state.agents.includes(c.agent_id))
  const files = plural(filesOf(state, row), 'file') + (ran ? " · commands' changes, if any, counted at Take in" : '')
  const parts = ['done', files, ...(rounds ? [plural(rounds, 'round') + ' back'] : [])]
  return [...parts, tokensLine(rowTokens(state.agents, row.state.agents))].join(' · ')
}

const AT_END: ReadonlySet<ChatTeamState['status']> = new Set(['ready', 'done', 'in'])
// G1.2: a team ready with findings left (it says why) is not at its end.
const atEnd = ({ status, why }: ChatTeamState) => AT_END.has(status) && !(status === 'ready' && why)

/**
 * B-101: a chat whose teams have no recipe has no row of a turn's (nothing runs them on the server): its turn's agents
 * are framed by the teams their roles are in - each by the first of the chat's teams it is in, a helper with the agent
 * that opened it. On the canvas only: no Ready for you, nothing to stop or take in.
 */
function byRoles(state: ConvState, run: Run, teams: Team[]): RanRow[] {
  if (state.conversation.teams_mode === 'none') return []
  const rows = state.conversation.teams.flatMap(row => teams.filter(team => team.id === row.team_id).map(team => ({ row, team, agents: [] as string[] })))
  // (K-takimlar-arasi: what a team's lead opened, and all under it, is of its team - a Coder Backend's lead opened is
  // Backend's, though the Web app comes first and has a Coder too; app/agent.py `_team_of`. A lead only where it runs
  // its team: beside another team, and on.)
  const ledBy = (agent: Agent): (typeof rows)[number] | undefined => {
    const opener = state.agents.find(a => a.id === agent.parent_agent_id)
    if (!opener) return undefined
    return rows.find(({ team }) => rows.length > 1 && team.lead_on && team.lead.name === opener.role_name) ?? ledBy(opener)
  }
  for (const agent of state.agents.filter(a => a.run_id === run.id && a.depth > 0)) {
    const own = ledBy(agent) ?? rows.find(({ team }) => team.roles.includes(agent.role_name) || team.lead.name === agent.role_name)
    ;(own ?? rows.find(one => one.agents.includes(agent.parent_agent_id ?? '')))?.agents.push(agent.id)
  }
  const status = run.status === 'running' || run.status === 'waiting_approval' ? ('running' as const) : ('done' as const)
  return rows
    .filter(one => one.agents.length > 0)
    .map(({ row, team, agents }) => ({ ...row, state: { run_id: run.id, team: team.name, recipe: '', status, why: null, steps: [], agents, ended_ready: null, passes: [] } }))
}

/** Agents that are no part of what a step did: failed, stopped, declined, cut off by a restart. */
const ENDED_BADLY = new Set<Agent['status']>(['failed', 'cancelled', 'rejected', 'interrupted'])

const blockingOf = (agent: Agent) => agent.findings?.filter(f => f.blocking !== false).length ?? 0

/**
 * An earlier round of a step, on its one line: "Round 2 · 4 reviewed" and "2 blocking" where its agents reported findings,
 * else who ran it and how many finished - "Round 1 · Coder, Coder 2" and "✓ 2"; then how many ended badly. Only what is on record.
 * `agentIds`: its pass; `drawn`: its nodes, its agents' helpers too. `live`: its turn still runs - once it is over
 * nothing in it waits for the user (K-takim-tur, R185: a card left "proposed" on the page kept a done round open).
 */
function roundData(state: ConvState, agentIds: string[], drawn: GraphNode[], n: number, live: boolean): RoundData {
  const ran = state.agents.filter(a => agentIds.includes(a.id))
  const reviewed = ran.filter(a => a.findings)
  const blocking = reviewed.reduce((sum, a) => sum + blockingOf(a), 0)
  const done = ran.filter(a => a.status === 'completed').length
  const bad = [...ENDED_BADLY].flatMap(status => {
    const count = ran.filter(a => a.status === status).length
    return count ? [`${count} ${ENDED[status]!.toLowerCase()}`] : []
  })
  const names = drawn.flatMap(node => (node.agentId && agentIds.includes(node.agentId) ? [(node.data as AgentData).name] : []))
  const said = `Round ${n + 1} · ${reviewed.length ? `${reviewed.length} reviewed` : names.join(', ')}`
  const groups = drawn.map(node => node.data as GroupData)
  return {
    said,
    result: [reviewed.length ? `${blocking} blocking` : done ? `✓ ${done}` : '', ...bad].filter(Boolean).join(' · '),
    colour: blocking || bad.length ? 'var(--warn)' : 'var(--ok)',
    inside: drawn.length,
    summary: said,
    attention: live && groups.some(group => group.attention),
    finished: !live || groups.every(group => group.finished),
    open: true,
  }
}

/** A finished agent of a step's newest round, the step having had rounds before: its chip - how it ended, nothing more. */
function chipOf(data: AgentData, agent: Agent | undefined): void {
  if (!agent || !data.finished || data.attention) return
  const blocking = blockingOf(agent)
  if (agent.status !== 'completed') data.chip = { said: ENDED[agent.status]!.toLowerCase(), colour: AGENT_STATUS[agent.status][1] }
  else data.chip = blocking ? { said: `${blocking} blocking`, colour: 'var(--warn)' } : { said: '✓', colour: 'var(--ok)' }
}

function teamData(state: ConvState, row: RanRow, colour: string, parentId: string | null): TeamData {
  const { team, recipe, status, why, steps, agents } = row.state
  const now = steps.find(step => step.state === 'now')
  const round = now?.round ? ` · round ${now.round + 1}` : ''
  const finished = atEnd(row.state)
  return {
    teamId: row.team_id,
    team,
    recipe: recipe || 'no recipe',
    colour,
    stands: status,
    why: why ?? null,
    steps,
    // Only a role step drawn more than one (`draws`), by those of its last pass that did not fail, stop or go unopened.
    // shortcut: Ask for changes on a part right after itself adds to its last pass (`recipe_run.opened`): counted at most
    // what it draws; count by round if that is seen. (After a loop went round, its round set back to 0, it is a pass of
    // its own: counted alone, and drawn as the step's newest round.)
    many: Object.fromEntries(
      steps.map(step => {
        const pass = row.state.passes.findLast(one => one.part === step.id)?.agents ?? []
        const went = state.agents.filter(agent => pass.includes(agent.id) && !ENDED_BADLY.has(agent.status))
        return [
          step.id,
          Object.entries(step.draws ?? {}).flatMap(([role, most]) => {
            const count = Math.min(most, went.filter(agent => agent.role_name === role).length)
            return count > 1 ? [`${role} ×${count}`] : []
          }),
        ]
      }),
    ),
    tokens: tokensLine(rowTokens(state.agents, agents)),
    parentId,
    columns: [],
    inside: agents.length,
    // (In with the copy though it ended early, B-84: why it ended is kept.)
    summary: finished ? doneLine(state, row) + (why ? ` · ${why}` : '') : status === 'running' ? `${steps.length ? `at ${now?.name ?? 'its start'}${round}` : 'at work'}${why ? ' · ' + why : ''}` : `${status}${why ? ': ' + why : ''}`,
    attention: status === 'ready',
    finished,
    open: true,
  }
}

function readyData(state: ConvState, run: Run, all: RanRow[]): ReadyData {
  const runId = run.id
  const asked = state.questions.find(q => q.run_id === runId && q.status === 'pending' && isReadyCard(q))
  // B-84: a picked team that did not start (yet) is listed too, and is waited for while the turn runs.
  const notStarted = all.filter(row => row.state.status === 'waiting')
  const rows = all.filter(row => row.state.status !== 'waiting')
  const line = (row: RanRow) => {
    const { status, why, steps } = row.state
    const at = steps.findIndex(step => step.state === 'now')
    if (status === 'waiting') return run.status === 'running' ? 'not started yet' : 'did not start'
    // (A team with no recipe has no steps: at work.)
    if (status === 'running') return steps.length ? `step ${at + 1} of ${steps.length} · ${steps[at]?.name ?? ''}` : 'at work'
    if (atEnd(row.state)) return doneLine(state, row) + (status === 'in' ? ` · in the project${why ? ` · ${why}` : ''}` : '')
    return `${status}${why ? ': ' + why : ''}`
  }
  // What each review role said last: a check that ran, or the findings it left. Nothing for one that said nothing.
  const checks = rows.flatMap(row => {
    const said = new Map<string, Agent>()
    for (const agent of state.agents.filter(a => row.state.agents.includes(a.id) && a.findings)) said.set(agent.role_name, agent)
    // B-192: a suggestion is the user's to read, never "left" - it sent no work back.
    return [...said.values()].map(agent => {
      const left = agent.findings!.filter(f => f.blocking !== false).length
      const ideas = agent.findings!.length - left
      const parts = [...(left ? [`${plural(left, 'finding')} left`] : []), ...(ideas ? [plural(ideas, 'suggestion')] : [])]
      return { text: `${agent.role_name}: ${parts.join(', ') || 'no findings'}`, passed: left === 0 }
    })
  })
  const waiting = [
    ...rows.filter(row => row.state.status === 'running').map(row => `${row.state.team}: ${row.state.steps.find(s => s.state === 'now')?.name ?? 'at work'}`),
    ...(run.status === 'running' ? notStarted.map(row => `${row.state.team}: not started yet`) : []),
  ]
  const lead = state.agents.find(a => a.run_id === runId && a.depth === 0)?.id
  const keptOf = (agents: string[]) => state.merges.find(m => m.run_id === runId && isKept(m) && agents.includes(m.agent_id))?.id ?? null
  // B-110: an agent kept beside the recipe (a role named, the Planner) - its copy its own, in no team's row.
  const rowed = new Set(all.flatMap(row => row.state.agents))
  const beside = state.agents.filter(a => a.run_id === runId && a.id !== lead && !rowed.has(a.id) && keptOf([a.id]))
  const colours = chatColours(state, beside.map(agent => agent.id))
  const now = waitingOf(state).filter(row => row.current)
  return {
    rows: [
      ...all.map(row => ({
        team: row.state.team,
        recipe: row.state.recipe || 'no recipe',
        colour: colours.get(row.team_id)!,
        line: line(row),
        done: atEnd(row.state),
        // (A team with no recipe beside one: its copy is its own, kept in its lead's name.)
        kept: row.state.recipe ? null : keptOf(row.state.agents),
      })),
      ...beside.map(agent => ({ team: agent.name, recipe: 'beside the recipe', colour: colours.get(agent.id)!, line: 'its own kept copy', done: false, kept: keptOf([agent.id]) })),
    ],
    alsoTakes: endedEarly(all, state.fileChanges, runId).left,
    checks,
    waits: waiting.length ? waiting.join('; ') : null,
    inProject: rows.filter(row => row.state.status === 'in').map(row => row.state.team),
    notStarted: notStarted.map(row => row.state.team),
    questionId: asked?.id ?? null,
    taken: rows.some(row => row.state.status === 'in') && rows.every(row => AT_END.has(row.state.status)),
    left: rows.find(row => !AT_END.has(row.state.status) && row.state.status !== 'running')?.state.why ?? null,
    waiting: {
      count: now.length,
      summary: waitingSummary(now),
      mine: now.filter(row => row.what === 'merge' && row.item.run_id === runId).length,
      decided: decidedOf(state).length,
    },
    // (The recipe's copy is kept in its turn's lead's name.)
    kept: state.merges.find(m => m.run_id === runId && isKept(m) && m.agent_id === lead)?.id ?? null,
  }
}

/**
 * `teams`: every team there is, by its roles - a chat whose teams have no recipe has its turns' agents framed by them
 * (B-101), on the canvas only.
 */
export function deriveGraph(state: ConvState, teams: Team[] = [], shared: SharedFile[] = [], outputs: View[] = []): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = []
  const edges: GraphEdge[] = []
  const link = (source: string, target: string, active: boolean, spawn = false) =>
    edges.push({ id: `${source}>${target}`, source, target, active, ...(spawn && { spawn }) })
  // Agents whose spawn line a team frame's door or work line stands for.
  const unspawned = new Set<string>()

  // A spawn call that opened an agent is drawn as that agent, not as a tool call.
  const opened = new Set(state.agents.map(a => a.tool_call_id))
  // Which turn of its topic each turn is: for an agent that goes on from an earlier one.
  const numbers = turnNumbers(state)
  // A comparison's later sides, by run: each with the turn it is drawn in.
  const laterSides = new Map<string, string>()

  for (const run of state.runs) {
    // A message removed from the queue never became work; it stays in the chat only.
    if (run.status === 'cancelled' && !run.started_at) continue
    // What started the turn: the user's message, or - with nobody watching - a trigger's.
    const request = state.messages.find(m => m.run_id === run.id && (m.role === 'user' || m.role === 'trigger'))
    // A comparison's later side hangs under its first side's message: one "You", two Leads.
    const turn = turnOf(state, run.id)
    if (turn !== run.id) laterSides.set(run.id, turn)
    const requestId = `request:${turn}`
    const attached = requestNodes(state, run, request, turn, requestId, nodes, link)
    approvedPlan(state, run, nodes, edges)
    assistantPo(state, run, nodes, edges)

    // A chat team's recipe run in this turn (slice 84b-2): its frame comes before the agents in it (`foldGraph`). As
    // the turn left it (B-107).
    const ran = turnTeams(state, run.id)
    const between = requestsOf(state, run.id)
    const colours = chatColours(state)
    const frameOf = new Map<string, { id: string; colour: string }>()
    const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
    // (A team not started has no agents to frame: Ready for you names it.)
    const frames = [...ran.filter(one => one.state.status !== 'waiting'), ...(ran.length ? [] : byRoles(state, run, teams))]
    for (const row of frames) {
      const frame = { id: `team:${run.id}:${row.team_id}`, colour: colours.get(row.team_id)! }
      for (const id of row.state.agents) frameOf.set(id, frame)
      const data = { ...teamData(state, row, frame.colour, lead?.id ?? null), byRoles: !ran.length }
      nodes.push({ id: frame.id, kind: 'team', runId: run.id, refId: row.team_id, data })
    }

    // A turn still queued has no agent yet: only its request is shown.
    for (const agent of state.agents.filter(a => a.run_id === run.id))
      agentNodes(state, run, agent, nodes, link, { teams, opened, frameOf, request, requestId })

    // K-canvas-dili (W): the agent that opens a team's agents - the Lead - reaches them at their frame's door, and in the
    // frame the work goes left to right in its recipe's order: one fork into each pass of a step, one join out of it,
    // drawn instead of the spawn lines. A loop back is no work line (its findings are). A helper keeps its spawn line.
    for (const row of frames) workLines(state, run, row, nodes, edges, unspawned)

    // K-takimlar-arasi: a request between teams is one short line from the asker's frame to the asked lead's; who asked
    // whom is on their badges. Several from one frame to another are one line (on one place, their labels stacked): each
    // way it stood, counted; every one in full on its title.
    askLines(between, frameOf, edges)

    for (const file of attached) {
      for (const agentId of file.given_to) {
        const [source, target] = [`attachment:${file.id}`, `agent:${agentId}`]
        if (nodes.some(n => n.id === target)) edges.push({ id: `handed:${source}>${target}`, source, target, active: false, handed: true })
      }
    }

    // Where the turn's teams meet: one node for all of them, each team's line drawn to it.
    if (ran.length > 0) {
      const id = `ready:${run.id}`
      nodes.push({ id, kind: 'ready', runId: run.id, refId: run.id, data: readyData(state, run, ran) })
      for (const row of ran.filter(one => one.state.status !== 'waiting')) link(`team:${run.id}:${row.team_id}`, id, row.state.status === 'ready')
    }

    // A night while you were away, started from this turn's card: its jobs hang off the Lead, and each that is done
    // (a plain line) or waits for you (a dashed one) leads to the night's report.
    awayNodes(state, run, nodes, edges, link)

    // K-shared-bagli: what the turn's teams (or agents) shared, noted and remembered - one column right of them.
    const column = sharedColumn(state, run, numbers.get(run.id) ?? null, nodes, edges, shared)
    nodes.push(...column.nodes)
    edges.push(...column.edges)
    // K-belge-ciktilari: what each agent made, a card by its box.
    const made = outputCards(state, run, nodes, outputs)
    nodes.push(...made.nodes)
    edges.push(...made.edges)
  }
  sharedPlaces(state, nodes, edges)
  agentLines(state, nodes, edges, unspawned)
  // (Drawn, laid out and picked as the turn they are: a comparison's sides as its first side's.)
  for (const node of nodes) node.runId = laterSides.get(node.runId) ?? node.runId
  return { nodes, edges: framed(nodes, edges.filter(e => !(e.spawn && unspawned.has(e.target)))) }
}

type Link = (source: string, target: string, active: boolean, spawn?: boolean) => void

/** What started a turn: its request, the files attached to it, and its plan. Returns the files, which are handed on below. */
function requestNodes(state: ConvState, run: Run, request: ConvState['messages'][number] | undefined, turn: string, requestId: string, nodes: GraphNode[], link: Link) {
  if (request && turn === run.id) {
    nodes.push({
      id: requestId,
      kind: 'request',
      runId: run.id,
      refId: request.id,
      data: {
        text: request.content.slice(0, 140),
        time: request.created_at,
        queued: run.status === 'queued',
        trigger: request.role === 'trigger' ? (run.trigger_name ?? '') : null,
      },
    })
  }

  // The files the user attached to it (slice 85b): small nodes beside its request - more than FOLD_FILES, a box of
  // them, folded - each joined by a dashed line to the agents it was handed to (drawn below, once they are).
  const attached = request && turn === run.id ? state.attachments.filter(a => a.message_id === request.id && !a.frame_of) : []
  const box = attached.length > FOLD_FILES ? `files:${run.id}` : undefined
  if (box) {
    const data: GroupData = { inside: attached.length, summary: `${attached.length} files`, attention: false, finished: true, open: true }
    nodes.push({ id: box, kind: 'files', runId: run.id, refId: request!.id, data })
  }
  for (const file of attached) {
    const { label, colour, meta } = shown(file)
    nodes.push({ id: `attachment:${file.id}`, kind: 'attachment', runId: run.id, refId: file.id, ...(box && { parent: box }), data: { name: file.name, label, colour, meta } })
  }

  // A plan turn: what became of its plan, at its start. (Queued, or ended with none, no node.)
  if (request && run.plan_turn && (run.plan || (run.status !== 'queued' && !TERMINAL.has(run.status)))) {
    const data: PlanData = run.plan ? { status: run.plan.status, by: plannedBy(run.plan) } : { status: 'writing', by: null }
    nodes.push({ id: `plan:${run.id}`, kind: 'plan', runId: run.id, refId: run.id, data })
    link(requestId, `plan:${run.id}`, false)
  }
  return attached
}

/**
 * The work turn of an approved plan (the user's, 6 Nov): that plan, small, over its Lead. `approve_plan` starts it as the
 * run right after the plan's turn, which had to be the newest - so no later message is taken for it.
 */
function approvedPlan(state: ConvState, run: Run, nodes: GraphNode[], edges: GraphEdge[]) {
  const before = state.runs[state.runs.indexOf(run) - 1]
  if (!before?.plan_turn || before.plan?.status !== 'approved') return
  const data: PlanData = { status: 'approved', by: plannedBy(before.plan) }
  const id = `planned:${before.id}`
  nodes.push({ id, kind: 'plan', runId: run.id, refId: before.id, data })
  // (A turn not started yet has no Lead to draw it to.)
  const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
  if (lead) edges.push({ id: `${id}>agent:${lead.id}`, source: id, target: `agent:${lead.id}`, active: false, plan: true })
}

/** The Assistant PO asked once the turn ended (`Run.po`): small, under the turn's Lead, on a dashed line down from it. None where it was not asked. */
function assistantPo(state: ConvState, run: Run, nodes: GraphNode[], edges: GraphEdge[]) {
  const lead = state.agents.find(a => a.run_id === run.id && a.depth === 0)
  if (!run.po || !lead) return
  const id = `po:${run.id}`
  nodes.push({ id, kind: 'po', runId: run.id, refId: run.id, data: run.po })
  edges.push({ id: `agent:${lead.id}>${id}`, source: `agent:${lead.id}`, target: id, active: false, plan: true, po: true })
}

/** What came of the Assistant PO's request, counted - "2 proposed · 1 dropped · Orchestrator added 1" - or that it was not heard out. */
export function poSaid(po: PoData): string {
  if (!po.heard) return 'Sent, not heard out'
  const dropped = po.dropped.length + po.dropped_more
  return [`${po.proposed} proposed`, dropped > 0 && `${dropped} dropped`, typeof po.lead_added === 'number' && `Orchestrator added ${po.lead_added}`].filter(Boolean).join(' · ')
}

/** What it spent, as the canvas says tokens: "– tokens" where it said nothing - never 0. */
export function poTokens(po: PoData): string {
  const told = [po.input_tokens, po.output_tokens].filter(n => typeof n === 'number')
  return tokensLine({ tokens: told.length ? told.reduce((sum, n) => sum + n, 0) : null, unreported: told.length < 2 })
}

/** One agent of a turn: its box, the line from whoever opened it, and what it did, in its box. */
function agentNodes(
  state: ConvState,
  run: Run,
  agent: Agent,
  nodes: GraphNode[],
  link: Link,
  { teams, opened, frameOf, request, requestId }: {
    teams: Team[]
    opened: Set<string | null>
    frameOf: Map<string, { id: string; colour: string }>
    request: ConvState['messages'][number] | undefined
    requestId: string
  },
) {
  const agentId = `agent:${agent.id}`
  const status = statusOf(agent, run, state)
  const mine = state.toolCalls.filter(t => t.agent_id === agent.id)
  const subs = mine.filter(isOwnSubAgent)
  const subIds = new Set(subs.map(s => s.id))
  const commands = state.commands.filter(c => c.agent_id === agent.id)
  const changes = state.fileChanges.filter(f => f.agent_id === agent.id)
  // Its tools, counted on its node (the user's, 5 Nov: what it did is in the side panel). A message to another agent is
  // drawn on the line between the two; a command, an agent it opened or a sub-agent is counted apart.
  const shown = mine.filter(
    t =>
      t.name !== 'run_command' &&
      t.name !== 'message_agent' &&
      t.name !== 'discuss' &&
      !opened.has(t.id) &&
      !subIds.has(t.id),
  )

  const data: AgentData = {
    role: agent.role_name,
    name: titleOf(agent.name || agent.role_name, teams),
    parentId: agent.parent_agent_id,
    colour: frameOf.get(agent.id)?.colour,
    provider: agent.provider_name,
    // Its own model; a lead from before models were per agent has its turn's.
    modelId: agent.model_id ?? (agent.depth === 0 ? run.model_id : null),
    modelFrom: agent.model_from ?? null,
    status,
    activity: activityOf(agent, run, state),
    since: status === 'running' ? (toolNow(agent, state)?.since ?? null) : null,
    sign: agent.sign,
    signStopped: agent.status === 'failed' && !!agent.sign && !!agent.error?.includes(agent.sign.text),
    findings: findingsLine(agent.findings),
    inside: 0,
    summary: summaryOf(shown.length, commands.length, changes.length, subs.length),
    attention: asks(agent, state),
    finished: status in ENDED,
    open: true,
  }
  nodes.push({ id: agentId, kind: 'agent', runId: run.id, refId: agent.id, agentId: agent.id, team: frameOf.get(agent.id)?.id, data })
  if (agent.parent_agent_id) link(`agent:${agent.parent_agent_id}`, agentId, OPEN.has(agent.status), true)
  else if (request) link(requestId, agentId, run.status === 'running')
}

/** A team frame's door and work lines, and how its agents are laid out in it. */
function workLines(state: ConvState, run: Run, row: RanRow, nodes: GraphNode[], edges: GraphEdge[], unspawned: Set<string>) {
  const frame = `team:${run.id}:${row.team_id}`
  const mine = new Set(row.state.agents.filter(id => state.agents.some(a => a.id === id && a.run_id === run.id)))
  const parentOf = (id: string) => state.agents.find(a => a.id === id)?.parent_agent_id ?? ''
  const roots = [...mine].filter(id => !mine.has(parentOf(id)))
  if (roots.length === 0) return
  const passes = row.state.passes
    .map(pass => ({ at: row.state.steps.findIndex(step => step.id === pass.part), agents: pass.agents.filter(id => mine.has(id)) }))
    .filter(pass => pass.agents.length > 0)
  const heads = roots.filter(id => !passes.some(pass => pass.agents.includes(id)))
  const at = (id: string) => `agent:${id}`
  const open = (id: string) => state.agents.some(a => a.id === id && OPEN.has(a.status))
  for (const id of passes.length ? [...heads, ...passes.flatMap(pass => pass.agents)] : roots) unspawned.add(at(id))
  edges.push({ id: `door:${parentOf(roots[0])}>${frame}`, source: at(parentOf(roots[0])), target: frame, active: row.state.status === 'running', door: true })
  // From each of `from` to the first of `to`, and from the first of `from` to each of `to`: one fork, one join.
  const fork = (from: string[], to: string[]) => {
    for (const [source, target] of [...to.map(t => [from[0], t]), ...from.slice(1).map(s => [s, to[0]])])
      edges.push({ id: `work:${source}>${target}`, source, target, active: open(target.slice(6)), work: true })
  }
  fork([frame], (heads.length ? heads : passes.length ? passes[0].agents : roots).map(at))
  let before = heads.length ? { at: -1, agents: heads } : null
  for (const pass of passes) {
    // (On, and from a round of a loop to itself to its next - K-evrim's candidates; never back, as a review's loop, nor
    // into a pass off its strip.)
    if (before && pass.at >= before.at && pass.at >= 0) fork(before.agents.map(at), pass.agents.map(at))
    before = pass
  }
  // Laid out so: its lead, then a column for each step, its passes one under the other; a helper under the agent
  // that opened it. (Its passes not known - a row from before, no recipe - it is laid out as a tree.)
  if (passes.length === 0) return
  const columns: TeamData['columns'] = [{ ids: heads, atOnce: false }, ...row.state.steps.map((step, i) => ({ ids: passes.filter(pass => pass.at === i).flatMap(pass => pass.agents), atOnce: step.group }))]
    .map(column => ({ ...column, ids: column.ids.map(at) }))
    .filter(column => column.ids.length > 0)
  if (columns.length === 0) return
  const helped = new Map<string, number>()
  for (const id of [...mine].filter(one => !columns.some(column => column.ids.includes(at(one))))) {
    const opener = at(parentOf(id))
    const { ids } = columns.find(one => one.ids.includes(opener)) ?? columns[columns.length - 1]
    helped.set(opener, (helped.get(opener) ?? 0) + 1)
    const after = ids.indexOf(opener)
    ids.splice(after < 0 ? ids.length : after + helped.get(opener)!, 0, at(id))
  }
  foldRounds(state, run, row, frame, passes, columns, nodes)
  ;(nodes.find(n => n.id === frame)!.data as TeamData).columns = columns
}

function foldRounds(state: ConvState, run: Run, row: RanRow, frame: string, passes: { at: number; agents: string[] }[], columns: TeamData['columns'], nodes: GraphNode[]) {
  const at = (id: string) => `agent:${id}`
  // The user's (4 Nov): a step that ran more than once - a loop's rounds - shows each earlier round (its pass, and the
  // helpers its agents opened) as one line, its agents under it once opened; the newest in full, its finished agents
  // chips. A step that ran once is as before. (A loop to itself - K-evrim's candidates - is a pass a round: B-391.)
  for (const column of columns) {
    const ran = passes.filter(pass => pass.agents.some(id => column.ids.includes(at(id))))
    if (ran.length < 2) continue
    const all: string[][] = ran.map(() => [])
    let k = 0
    for (const id of new Set(column.ids)) {
      // (An agent in two passes - opened again for its step - is of the newest: one at work is never folded away.)
      const own = ran.findLastIndex(pass => pass.agents.some(one => at(one) === id))
      if (own >= 0) k = own
      all[k].push(id)
    }
    const rounds = all.flatMap((ids, n) => (ids.length ? [{ ids, n }] : []))
    if (rounds.length < 2) continue
    for (const [i, { ids, n }] of rounds.entries()) {
      const drawn = nodes.filter(node => ids.includes(node.id))
      if (i === rounds.length - 1) {
        for (const node of drawn) chipOf(node.data as AgentData, state.agents.find(a => a.id === node.agentId))
        continue
      }
      // By its step's id: what the user opened or folded stays with it, whatever columns are drawn before it.
      const id = `round:${frame}:${row.state.steps[ran[n].at]?.id}:${n}`
      for (const node of drawn) node.round = id
      // (Before its agents: what is folded comes after what folds it - `foldGraph`.)
      const first = nodes.findIndex(node => ids.includes(node.id))
      const counted = ran[n].agents.filter(one => ids.includes(at(one)))
      nodes.splice(first < 0 ? nodes.length : first, 0, { id, kind: 'round', runId: run.id, refId: run.id, team: frame, data: roundData(state, counted, drawn, n, run.status === 'running' || run.status === 'waiting_approval') })
      ids.unshift(id)
    }
    column.ids = rounds.flatMap(round => round.ids)
    column.rounds = rounds.map(round => round.ids)
  }
}

/** The lines of requests between a turn's teams. */
function askLines(between: TeamRequest[], frameOf: Map<string, { id: string; colour: string }>, edges: GraphEdge[]) {
  const ways = new Map<string, TeamRequest[]>()
  for (const request of between) {
    const [from, to] = [frameOf.get(request.from?.id ?? ''), frameOf.get(request.lead?.id ?? '')]
    if (from && to && from.id !== to.id) ways.set(`${from.id}>${to.id}`, [...(ways.get(`${from.id}>${to.id}`) ?? []), request])
  }
  for (const [way, asks] of ways) {
    const [source, target] = way.split('>')
    const open = asks.some(r => r.stands === 'waits' || r.stands === 'at work')
    const labels = asks.map(lineLabel)
    const count = (one: string) => labels.filter(l => l === one).length
    const label = [...new Set(labels)].map(one => (count(one) > 1 ? `${one} ×${count(one)}` : one)).join(' · ')
    const title = asks.map(r => `${askerOf(r)} → ${r.to}: ${shortWhat(r.what, 80)} - ${standsLine(r)}`).join('\n')
    edges.push({ id: `ask:${asks[0].call.id}`, source, target, active: open, request: { label, open, title, calls: asks.map(r => r.call.id) } })
  }
}

/** The nights started from a turn's card: their jobs and reports. */
function awayNodes(state: ConvState, run: Run, nodes: GraphNode[], edges: GraphEdge[], link: Link) {
  for (const away of state.away.filter(card => card.run_id === run.id && card.started_at)) {
    const report = `away:${away.id}`
    const lead = nodes.find(n => n.kind === 'agent' && n.runId === run.id && n.agentId && !(n.data as AgentData).parentId)
    for (const job of away.jobs) {
      const id = `awayjob:${away.id}:${job.task_id ?? job.title}`
      nodes.push({ id, kind: 'awayjob', runId: run.id, refId: job.conversation_id ?? away.id, data: { job } })
      if (lead) link(lead.id, id, job.state === 'working')
      if (job.state === 'done' || job.state === 'waits') edges.push({ id: `${id}>${report}`, source: id, target: report, active: false, waits: job.state === 'waits' })
    }
    nodes.push({ id: report, kind: 'away', runId: run.id, refId: away.id, data: { away } })
  }
}

/** The shared places: discussions and rooms, each joined to its members. */
function sharedPlaces(state: ConvState, nodes: GraphNode[], edges: GraphEdge[]) {
  // The frame all these agents are drawn in, as a node's `team`; none where they are not all in one.
  const frameOfAll = (agentIds: string[]): { team?: string } => {
    const teams = new Set(agentIds.map(id => nodes.find(n => n.id === `agent:${id}`)?.team))
    const [team] = teams
    return teams.size === 1 && team ? { team } : {}
  }
  // In a frame laid out by its work line, a shared place stands at the head of its members' column.
  const headOfColumn = (place: string, team: string | undefined, agentIds: string[]) =>
    (nodes.find(n => n.id === team)?.data as TeamData | undefined)?.columns.find(column => agentIds.some(id => column.ids.includes(`agent:${id}`)))?.ids.unshift(place)
  // A discussion is a shared place: one node, joined to everyone who takes part.
  // (In the order they began: the lane of them, layout's, reads top down.)
  for (const discussion of [...state.discussions].sort((a, b) => a.created_at.localeCompare(b.created_at))) {
    const id = `discussion:${discussion.id}`
    if (!nodes.some(n => n.id === `agent:${discussion.agent_id}`)) continue
    const speaker = speakerOf(state, discussion)
    const said = state.discussionPosts.filter(
      p => p.discussion_id === discussion.id && p.kind === 'said' && !p.passed,
    )
    const members = discussion.members.map(m => m.agent_id)
    const framed = frameOfAll(members)
    // Not in one frame, in a turn with frames: in the lane (layout.ts). (In a turn with none, by its opener as before.)
    const laned = !framed.team && nodes.some(n => n.kind === 'team' && n.runId === discussion.run_id)
    nodes.push({
      id,
      kind: 'discussion',
      runId: discussion.run_id,
      refId: discussion.id,
      agentId: discussion.agent_id,
      data: {
        topic: discussion.topic.slice(0, 140),
        line: discussionLine(discussion),
        members: discussion.members.map(m => nameIn(state, m.agent_id)),
        last: said.slice(-2).map(p => ({ who: nameIn(state, p.agent_id), text: p.content.slice(0, 90) })),
        speaking: speaker?.name ?? null,
        running: discussion.status === 'running',
      },
      // Among one team's agents only, it is drawn in their frame, its lines too.
      ...framed,
    })
    headOfColumn(id, framed.team, members)
    for (const member of discussion.members) {
      const source = `agent:${member.agent_id}`
      if (!nodes.some(n => n.id === source)) continue
      edges.push({ id: `${source}>${id}`, source, target: id, active: speaker?.id === member.agent_id, talk: true, ...(laned && { member: true }) })
    }
  }

  // A room is a shared place too: one node, by the lead that waits for it, joined to its members.
  for (const room of state.rooms) {
    const id = `room:${room.id}`
    const lead = leadOf(state, room)
    if (!lead || !nodes.some(n => n.id === `agent:${lead.id}`)) continue
    const items = state.roomItems.filter(i => i.room_id === room.id)
    const said = state.roomPosts.filter(p => p.room_id === room.id).sort((a, b) => a.number - b.number)
    const data: RoomData = {
      goal: roomGoal(state, room).slice(0, 140),
      line: roomLine(room),
      members: room.members.map(m => memberTag(state, room, m)),
      watched: watchedBy(state, room),
      items: items.length ? `${items.filter(i => i.status === 'done').length} of ${items.length} items done` : '',
      last: said.slice(-2).map(p => ({ who: `${nameInRoom(state, p.agent_id)}${byWatcher(state, room, p.agent_id) ? ' (watching)' : ''}`, text: p.text.slice(0, 90) })),
      running: isRunning(room),
      attention: waitsForYou(state, room),
    }
    // A room in a recipe's step (slice 84e) is drawn in the frame its members are in: their team's. One of two teams'
    // members (the Orchestrator's, with their leads - 5 Nov): in the lane, as a discussion between teams is.
    const drawn = room.members.map(m => m.agent_id).filter(one => nodes.some(n => n.id === `agent:${one}`))
    const { team } = frameOfAll(drawn)
    const laned = !team && nodes.some(n => n.kind === 'team' && n.runId === room.run_id)
    nodes.push({ id, kind: 'room', runId: room.run_id, refId: room.id, agentId: lead.id, data, ...(team && { team }) })
    headOfColumn(id, team, drawn)
    for (const member of room.members) {
      const source = `agent:${member.agent_id}`
      if (!nodes.some(n => n.id === source)) continue
      edges.push({ id: `${source}>${id}`, source, target: id, active: data.running && member.status === 'in', talk: true, ...(laned && { member: true }) })
    }
  }
}

/** The lines between agents: talk, findings handed on, and waiting for a file. */
function agentLines(state: ConvState, nodes: GraphNode[], edges: GraphEdge[], unspawned: Set<string>) {
  // Who talked with whom - a message and its reply: counted on the spawn line a parent and child already share, and
  // drawn as a line of its own between any other two, with the last thing said.
  const drawn = new Set(nodes.map(n => n.id))
  for (const message of state.channelMessages) {
    if (message.kind !== 'message' && message.kind !== 'reply' && message.kind !== 'findings') continue
    const [from, to] = [`agent:${message.from_agent_id}`, `agent:${message.to_agent_id}`]
    if (!drawn.has(from) || !drawn.has(to)) continue
    // Findings handed on: a line of their own from the agent that found them, with how many (one line each).
    if (message.kind === 'findings') {
      const findings = message.content.split('\n').filter(line => line.startsWith('- ')).length
      // It flows while the agent it was handed to is at work on them.
      const fixing = state.agents.some(a => a.id === message.to_agent_id && a.status === 'running')
      edges.push({ id: `findings:${message.id}`, source: from, target: to, active: fixing, findings })
      continue
    }
    // (Two a team's work line joins: on that line, not a second one on the same way.)
    const between = edges.find(
      e =>
        ((e.spawn && !unspawned.has(e.target)) || e.work || e.messages) &&
        ((e.source === from && e.target === to) || (e.source === to && e.target === from)),
    )
    const first = message.content.split('\n').find(line => line.trim())?.trim() ?? ''
    const said = { last: first.length > LAST_CHARS ? `${first.slice(0, LAST_CHARS)}…` : first, lastAt: message.created_at }
    if (between) Object.assign(between, { messages: (between.messages ?? 0) + 1 }, message.created_at >= (between.lastAt ?? '') && said)
    else edges.push({ id: `talk:${from}>${to}`, source: from, target: to, active: false, talk: true, messages: 1, ...said })
  }
  // Who waits for whose file: a line of its own from the one that waits to the one that
  // holds, for as long as it waits. (A holder of another conversation is not on this canvas;
  // the waiting agent's box names it.)
  for (const agent of state.agents) {
    const wait = agent.status === 'blocked' ? agent.waiting_for : null
    const [from, to] = [`agent:${agent.id}`, `agent:${wait?.agent_id}`]
    if (!wait || !drawn.has(from) || !drawn.has(to)) continue
    edges.push({ id: `waits:${from}>${to}`, source: from, target: to, active: false, waits: true })
  }
}

/**
 * B-97: no line runs out of a team's frame. A line between a frame's agent and the rest goes to the frame's door
 * instead: talk with the agent that opens the team is counted on the door line, a file handed in, findings from
 * outside, a discussion's line come to the door - one line for the same way. Talk between two frames runs agent to
 * agent, out by their sides (`cross`).
 */
function framed(nodes: GraphNode[], edges: GraphEdge[]): GraphEdge[] {
  const byId = new Map(nodes.map(n => [n.id, n]))
  // A node's frame: its own, or its box's.
  const frameOf = (id: string): string | undefined => {
    const node = byId.get(id)
    return node?.team ?? (node?.parent ? frameOf(node.parent) : undefined)
  }
  const kept: GraphEdge[] = []
  // The lines kept by their way, and by what they are: talk, findings or any other.
  const ways = new Map<string, GraphEdge>()
  const what = (e: GraphEdge) => (e.door || e.messages ? 'talk' : e.findings !== undefined ? 'findings' : 'line')
  const keep = (e: GraphEdge) => {
    kept.push(e)
    ways.set(`${what(e)}:${e.source}>${e.target}`, e)
  }
  for (const e of edges) {
    const [from, to] = [frameOf(e.source), frameOf(e.target)]
    // (A lane discussion's member keeps its agent, to light it; CanvasView draws it from its frame.)
    if (from === to || e.member || byId.get(e.source)?.kind === 'team' || byId.get(e.target)?.kind === 'team') keep(e)
    else if (e.messages && from && to) keep({ ...e, cross: true })
    else {
      const [source, target] = [from ?? e.source, to ?? e.target]
      // (Talk goes either way: on the door line too.)
      const same = ways.get(`${what(e)}:${source}>${target}`) ?? (e.messages ? ways.get(`talk:${target}>${source}`) : undefined)
      if (!same) keep({ ...e, source, target })
      else {
        if (e.messages) Object.assign(same, { messages: (same.messages ?? 0) + e.messages }, (e.lastAt ?? '') >= (same.lastAt ?? '') && { last: e.last, lastAt: e.lastAt })
        if (e.findings !== undefined) same.findings = (same.findings ?? 0) + e.findings
        same.active ||= e.active
      }
    }
  }
  return kept
}
