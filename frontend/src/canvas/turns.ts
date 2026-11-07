import type { Run } from '../api/types'
import { inScratch, isKept } from '../changes/copies'
import type { ConvState } from '../state/applyEvent'
import type { GraphEdge, GraphNode } from './deriveGraph'

/** How a turn stands, by its own record: an outcome nobody has put down yet is "working", as its agents say. */
export type TurnEnded = 'queued' | 'working' | 'done' | 'failed' | 'over budget' | 'stopped' | 'interrupted'

/** The colour each of them is said in: in the turn list, and on a turn's box beside the canvas's turn. */
export const ENDED_COLOR: Record<TurnEnded, string> = {
  queued: 'var(--muted)',
  working: 'var(--accent)',
  done: 'var(--ok)',
  failed: 'var(--del)',
  'over budget': 'var(--del)',
  stopped: 'var(--muted)',
  interrupted: 'var(--warn)',
}

/** One turn of a conversation as the turn list shows it. */
export interface TurnRow {
  runId: string
  /** A trigger started it, and nobody was there to be asked. */
  unattended: boolean
  /** The first line of the message that started it, cut. */
  text: string
  /** The trigger that started it, by the name it had then; null for a turn of the user's. */
  triggerName: string | null
  /** Its work (slice 107): the sub-agents it opened, and the files it changed in the project. */
  agents: number
  files: number
  ended: TurnEnded
  /** Something in it waits for the user's decision or answer. */
  waits: boolean
  /** A working copy of it was kept on disk and is not decided yet: the turn is over, and its changes are still yours to take in or discard. */
  kept: boolean
  /** When it was put on record. */
  at: string
}

/** The time of day, with the day before it when it was not today. */
export function when(iso: string, now = new Date()): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const time = at.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  return at.toDateString() === now.toDateString() ? time : `${at.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${time}`
}

/** How much of the message a row shows (and Undo's card, of each turn's request). */
export const TEXT_CHARS = 60

export const ENDED: Record<Run['status'], TurnEnded> = {
  queued: 'queued',
  running: 'working',
  waiting_approval: 'working',
  completed: 'done',
  failed: 'failed',
  cancelled: 'stopped',
  interrupted: 'interrupted',
}

function waitsIn(state: ConvState, run: Run): boolean {
  const here = <T extends { run_id: string }>(records: T[]) => records.filter(r => r.run_id === run.id)
  return (
    run.status === 'waiting_approval' ||
    run.plan?.status === 'proposed' ||
    here(state.fileChanges).some(f => f.status === 'proposed') ||
    here(state.commands).some(c => c.status === 'proposed') ||
    here(state.questions).some(q => q.status === 'pending') ||
    here(state.pendingRoles).length > 0 ||
    here(state.agents).some(a => a.status === 'proposed')
  )
}

/** The turn a run is listed and drawn as: a comparison's sides (slice 54) are one turn, its first side's. */
export function turnOf(state: Pick<ConvState, 'runs'>, runId: string): string {
  const compare = state.runs.find(run => run.id === runId)?.compare_id
  return (compare && state.runs.find(run => run.compare_id === compare)?.id) || runId
}

/** What these runs did that is work, not only words: the sub-agents opened, and the files changed in the project. */
export function workOf(state: Pick<ConvState, 'agents' | 'fileChanges'>, runIds: string[]): { agents: number; files: number } {
  const changed = state.fileChanges.filter(f => runIds.includes(f.run_id) && (f.status === 'applied' || f.status === 'merged') && !inScratch(f.path))
  return {
    agents: state.agents.filter(a => runIds.includes(a.run_id) && a.depth > 0 && a.started_at).length,
    files: new Set(changed.map(f => f.path)).size,
  }
}

/** "2 agents · 3 files" ("3 files changed"), or "" for a message with no work. */
export function workText({ agents, files }: { agents: number; files: number }, changed = false): string {
  const count = (n: number, one: string) => (n > 0 ? `${n} ${one}${n === 1 ? '' : 's'}` : null)
  return [count(agents, 'agent'), files > 0 && `${count(files, 'file')}${changed ? ' changed' : ''}`].filter(Boolean).join(' · ')
}

const endedOf = (run: Run): TurnEnded =>
  run.status === 'failed' && (run.error ?? '').startsWith('budget:') ? 'over budget' : ENDED[run.status]

/** The turns of a conversation, oldest first. A message taken out of the queue never became one. */
export function turnRows(state: ConvState): TurnRow[] {
  return state.runs
    .filter(run => !(run.status === 'cancelled' && !run.started_at) && turnOf(state, run.id) === run.id)
    .map(run => {
      const sides = run.compare_id ? state.runs.filter(one => one.compare_id === run.compare_id) : [run]
      const asked = state.messages.find(m => m.run_id === run.id && (m.role === 'user' || m.role === 'trigger'))
      const line = (asked?.content ?? '').split('\n').map(part => part.trim()).find(Boolean) ?? ''
      // At work while a side is, or one waits for the other; else as the first that did not end well ended.
      const each = sides.map(endedOf)
      return {
        runId: run.id,
        unattended: run.unattended,
        text: line.length > TEXT_CHARS ? `${line.slice(0, TEXT_CHARS)}…` : line,
        triggerName: run.unattended ? run.trigger_name : null,
        ...workOf(state, sides.map(side => side.id)),
        ended:
          each.includes('working') || (each.includes('queued') && each.some(e => e !== 'queued'))
            ? 'working'
            : (each.find(e => e !== 'done') ?? 'done'),
        waits: sides.some(side => waitsIn(state, side)),
        kept: state.merges.some(m => sides.some(side => side.id === m.run_id) && isKept(m)),
        // (the message's own time, as the chat says it: one clock for both)
        at: asked?.created_at ?? run.created_at,
      }
    })
}

/**
 * What the canvas has in front while nothing is picked (slice 107): the newest message of the
 * user's that waits for them (a plan to approve too), else the newest at work, else the newest
 * whose work opened sub-agents or changed files. Null: none has - the newest is drawn.
 */
export function frontTurn(rows: TurnRow[]): string | null {
  const own = rows.filter(row => !row.unattended)
  return (own.findLast(row => row.waits) ?? own.findLast(row => row.ended === 'working') ?? own.findLast(row => row.agents > 0 || row.files > 0))?.runId ?? null
}

/**
 * The turn the canvas draws: the one the user picked, while it is a turn of this
 * conversation; otherwise the newest turn the user started - a message still in the queue
 * is not drawn in place of the turn at work. A turn a trigger started is never drawn by
 * itself, unless the conversation has no other.
 */
export function currentTurn(rows: TurnRow[], picked: string | null): string | null {
  if (picked && rows.some(row => row.runId === picked)) return picked
  const own = rows.filter(row => !row.unattended)
  const newest = own.findLast(row => row.ended !== 'queued') ?? own[own.length - 1] ?? rows[rows.length - 1]
  return newest?.runId ?? null
}

/**
 * Whether this news of a turn means a turn of the user's has just started: then the canvas
 * goes to it, whatever was picked. `before` is the turn as it was known, if it was.
 */
export function startsNewTurn(before: Run | undefined, after: Run): boolean {
  const atWork = (run: Run) => run.status === 'running' || run.status === 'waiting_approval'
  return !after.unattended && atWork(after) && (before === undefined || before.status === 'queued')
}

interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

/** One turn's part of a conversation's graph: its nodes, and the lines between them. */
export function oneTurn(graph: Graph, runId: string | null): Graph {
  if (!runId) return { nodes: [], edges: [] }
  const nodes = graph.nodes.filter(n => n.runId === runId)
  const own = new Set(nodes.map(n => n.id))
  return { nodes, edges: graph.edges.filter(e => own.has(e.source) && own.has(e.target)) }
}
