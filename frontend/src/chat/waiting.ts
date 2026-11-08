import { isReadyCard } from '../agents/teamRun'
import type { Agent, Away, AwayJob, BacklogTask, Command, FileChange, Merge, NotesOffer, PendingRole, PendingSkill, Question, Run, ToolCall, TriggerProposal, WebRequest } from '../api/types'
import { keptToTake } from '../changes/copies'
import type { ConvState } from '../state/applyEvent'
import { asksOutside } from './toolSummary'

/** What a row of Ready for you is (K-bekleyenler): a question, a decision on a card, a copy ready for Take in. */
export type WaitingKind = 'question' | 'decision' | 'ready'

/** One thing that waits for you, with the record its card is drawn from; `current`: false for a question no longer asked. */
export type Waiting = { kind: WaitingKind; key: string; agentId: string | null; current: boolean } & (
  | { what: 'question'; item: Question }
  | { what: 'command'; item: Command }
  | { what: 'change'; item: FileChange }
  | { what: 'web'; item: WebRequest }
  | { what: 'spawn'; item: Agent }
  | { what: 'role'; item: PendingRole }
  | { what: 'skill'; item: PendingSkill }
  | { what: 'outside'; item: ToolCall }
  | { what: 'plan'; item: Run }
  | { what: 'merge'; item: Merge }
  | { what: 'away'; item: Away }
  | { what: 'night'; item: { away: Away; job: AwayJob } }
  | { what: 'trigger'; item: TriggerProposal }
  | { what: 'notes'; item: NotesOffer }
)

export const KINDS: WaitingKind[] = ['question', 'decision', 'ready']

/**
 * Ready for you's parts (sample A): what needs your answer - a question or a yes or no - and what is ready to take in.
 * What only told you (Decided for you) comes last, under "Told you", and is not counted.
 */
export const PARTS: [string, WaitingKind[]][] = [
  ['Needs your answer', ['question', 'decision']],
  ['Ready to take in', ['ready']],
]

const decision = { kind: 'decision' as const, current: true }

/**
 * B-156: whether a turn's copy holds anything to take in, as its records say - a change in it, or a command that ran.
 * shortcut: a command that ran counts whether or not it wrote anything (what it wrote is on record only once taken in,
 * B-126); upgrade if a turn whose commands wrote nothing is seen counted as a copy to take in.
 */
const holdsWork = (conv: ConvState, runId: string) =>
  conv.fileChanges.some(f => f.run_id === runId && f.status === 'in_copy') || conv.commands.some(c => c.run_id === runId && c.started_at !== null)

/**
 * Everything of the chat that waits for you, in one list, whatever the chat could draw (B-99): its questions still asked -
 * and its last turn's never answered, no longer current - the cards that wait for a yes or a no (a Take in that met a
 * clash too, B-128), and the copies kept for Take in. A question answered and then asked again (superseded) waits for
 * nothing: its new card does. The one count of what waits, wherever it is shown (`waitingCards`).
 */
export function waitingOf(conv: ConvState): Waiting[] {
  const last = conv.runs.at(-1)
  // A recipe's "Ready for you" card over a copy that changed nothing still asks (Ask for changes), as a decision.
  const ready = (q: Question): WaitingKind => (!isReadyCard(q) ? 'question' : holdsWork(conv, q.run_id) ? 'ready' : 'decision')
  const rows: Waiting[] = [
    ...conv.questions
      .filter(q => q.status === 'pending' || (q.run_id === last?.id && (q.status === 'cancelled' || q.status === 'interrupted')))
      .map(q => ({ kind: ready(q), key: q.id, agentId: q.agent_id, current: q.status === 'pending', what: 'question' as const, item: q })),
    ...conv.commands.filter(c => c.status === 'proposed').map(c => ({ ...decision, key: c.id, agentId: c.agent_id, what: 'command' as const, item: c })),
    ...conv.fileChanges.filter(f => f.status === 'proposed').map(f => ({ ...decision, key: f.id, agentId: f.agent_id, what: 'change' as const, item: f })),
    ...conv.webRequests.filter(w => w.status === 'proposed').map(w => ({ ...decision, key: w.id, agentId: w.agent_id, what: 'web' as const, item: w })),
    // (Its opener is the one that asks.)
    ...conv.agents.filter(a => a.status === 'proposed').map(a => ({ ...decision, key: a.id, agentId: a.parent_agent_id, what: 'spawn' as const, item: a })),
    ...conv.pendingRoles.map(r => ({ ...decision, key: r.tool_call_id, agentId: r.agent_id, what: 'role' as const, item: r })),
    ...conv.pendingSkills.map(s => ({ ...decision, key: s.tool_call_id, agentId: s.agent_id, what: 'skill' as const, item: s })),
    ...conv.toolCalls.filter(asksOutside).map(t => ({ ...decision, key: t.id, agentId: t.agent_id, what: 'outside' as const, item: t })),
    // (Only the newest turn's plan can still be approved.)
    ...(last?.plan?.status === 'proposed' ? [{ ...decision, key: last.id, agentId: null, what: 'plan' as const, item: last }] : []),
    // B-146: a "While you're away" card that waits for its Start, and a night's job that waits for your word.
    ...conv.away.filter(a => a.status === 'planned').map(a => ({ ...decision, key: a.id, agentId: null, what: 'away' as const, item: a })),
    ...conv.away.flatMap(a =>
      a.status === 'planned' ? [] : a.jobs.filter(job => job.state === 'waits').map(job => ({ ...decision, key: `${a.id}:${job.task_id}`, agentId: null, what: 'night' as const, item: { away: a, job } })),
    ),
    // Slice 69: a trigger an agent proposed, until your Approve, Edit or Reject.
    ...conv.triggerProposals.filter(p => p.status === 'proposed').map(p => ({ ...decision, key: p.id, agentId: null, what: 'trigger' as const, item: p })),
    // K-bilgi 6: what turns found for the Project notes, until your Add or Not now - it holds no turn.
    ...conv.notesOffers.filter(o => o.status === 'waiting').map(o => ({ ...decision, key: o.id, agentId: null, what: 'notes' as const, item: o })),
    ...conv.merges
      .filter(m => m.status === 'pending' || keptToTake(m))
      .map(m => ({ kind: m.status === 'pending' ? ('decision' as const) : ('ready' as const), key: m.id, agentId: m.agent_id, current: true, what: 'merge' as const, item: m })),
  ]
  return rows.sort((a, b) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind))
}

/** What the Lead answered for you while you were away and you have not said OK to (K-vekil-karar): its "Decided for you". */
export const decidedOf = (conv: ConvState): Question[] =>
  conv.questions.filter(q => q.status === 'answered' && q.lead_why != null && q.seen_at == null)

/** The Assistant PO's proposals of this chat the Orchestrator decided at Full auto, not yet OK'd: one added and still on the
 *  list, or one said no to and still proposed (the user's own word since takes it off).
 *  shortcut: shown in the chat's Decided for you only - the pill's "decided" count, Ready's Told you and the canvas count
 *  `decidedOf` alone; count these there too if one is missed. */
export const decidedTasks = (backlog: BacklogTask[] | null, chat: string): BacklogTask[] =>
  (backlog ?? []).filter(task => task.po?.chat === chat && !task.po.seen && (task.po.lead === 'add' ? task.status !== 'proposed' : task.po.lead === 'no' && task.status === 'proposed'))

// What a row of the list is, in the canvas's one line: one, and more than one.
const WORDS: Record<Exclude<Waiting['what'], 'question'>, [string, string]> = {
  command: ['command', 'commands'],
  change: ['change', 'changes'],
  web: ['web request', 'web requests'],
  spawn: ['agent to open', 'agents to open'],
  role: ['role', 'roles'],
  skill: ['skill', 'skills'],
  outside: ['folder outside the project', 'folders outside the project'],
  plan: ['plan', 'plans'],
  merge: ['Take in to finish', 'Take ins to finish'],
  away: ['away card to start', 'away cards to start'],
  night: ['away job waiting', 'away jobs waiting'],
  trigger: ['trigger to approve', 'triggers to approve'],
  notes: ['offer for Project notes', 'offers for Project notes'],
}

/** What can be answered now, in one line - "1 question · 1 command · 1 copy to take in" - as the canvas says it. */
export function waitingSummary(rows: Waiting[]): string {
  const said = new Map<string, [number, [string, string]]>()
  for (const row of rows.filter(one => one.current)) {
    const words: [string, string] = row.kind === 'ready' ? ['copy to take in', 'copies to take in'] : row.what === 'question' ? ['question', 'questions'] : WORDS[row.what]
    said.set(words[0], [(said.get(words[0])?.[0] ?? 0) + 1, words])
  }
  return [...said.values()].map(([n, [one, more]]) => `${n} ${n === 1 ? one : more}`).join(' · ')
}

/** A row's element on the Ready for you list, by its key: where the chat's ready line opens the list (K-hazir-satir). */
export const waitingId = (key: string) => `waiting-${key}`
