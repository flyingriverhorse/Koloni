import type { ChecksData } from './checksNode'
import type { GraphEdge, GraphNode, GroupData } from './deriveGraph'
import type { SharedData } from './sharedColumn'

/** The groups the user opened (true) or closed (false) by hand, by node id. */
export type Folds = Record<string, boolean>

interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export const isGroup = (node: GraphNode) => node.kind === 'team' || node.kind === 'files' || node.kind === 'round'

/**
 * Whether a group shows what is inside it. The user's own choice comes first. Otherwise
 * a group that is at work, or holds something waiting for the user, is open; a round that is over is closed.
 */
function opens(node: GraphNode, folds: Folds): boolean {
  const data = node.data as GroupData
  if (data.inside === 0) return true // nothing to hide
  // A round never hides an agent that waits for the user, whatever was chosen for it before.
  if (node.kind === 'round' && data.attention) return true
  if (typeof folds[node.id] === 'boolean') return folds[node.id]
  // Many files of a message are one box, "N files", until the user opens it (slice 85b).
  if (node.kind === 'files') return false
  // A team's frame folds only when the user says so (design §5: "never by itself").
  return data.attention || !data.finished || node.kind === 'team'
}

/**
 * The graph as it is drawn: what sits inside a closed group is left out, and a line to it is
 * drawn to the group - a folded frame (talk, a lane member), a folded round or a closed box of
 * files (its lines, one of a kind each way) - or left out. (Which turn is drawn is decided
 * before: the canvas hands in one turn's graph.)
 */
export function foldGraph(graph: Graph, folds: Folds): Graph {
  const shut = new Set<string>() // closed groups, and everything hidden inside them
  // What is hidden in a folded team frame, by the frame (its one line): talk with it is drawn to the frame's door. And
  // what is hidden in a folded round, by the round's line, or in a closed box of files, by the box: every line of it is
  // drawn to that.
  const folded = new Map<string, string>()
  const nodes = drawnNodes(graph.nodes, folds, shut, folded)
  return { nodes, edges: drawnEdges(graph.edges, nodes, folded) }
}

type Folded = Map<string, string>

/** The nodes that are drawn; what is hidden is put down in `shut`, and in `folded` by the frame or round it is hidden in. */
function drawnNodes(all: GraphNode[], folds: Folds, shut: Set<string>, folded: Folded): GraphNode[] {
  const nodes: GraphNode[] = []
  for (const node of all) {
    // A group comes before what is inside it - a team's frame before its agents, a round's line before its own.
    if (inShut(node, shut)) {
      shut.add(node.id)
      const frame = hiddenIn(node, shut, folded)
      if (frame) folded.set(node.id, frame)
      continue
    }
    if (!isGroup(node)) {
      nodes.push(withRows(node, folds))
      continue
    }
    const open = opens(node, folds)
    if (!open) shut.add(node.id)
    nodes.push({ ...node, data: { ...(node.data as GroupData), open } as GraphNode['data'] })
  }
  return nodes
}

const inShut = (node: GraphNode, shut: Set<string>) =>
  (node.parent && shut.has(node.parent)) || (node.team && shut.has(node.team)) || (node.round && shut.has(node.round))

/** What a hidden node is drawn as: its folded frame or round, what its box is hidden in, or - a file - its closed box. */
const hiddenIn = (node: GraphNode, shut: Set<string>, folded: Folded) =>
  node.team && shut.has(node.team)
    ? node.team
    : node.round && shut.has(node.round)
      ? node.round
      : (folded.get(node.parent ?? '') ?? (node.kind === 'attachment' ? node.parent : undefined))

function withRows(node: GraphNode, folds: Folds): GraphNode {
  // K-belge-ciktilari: an output card the user unfolded shows all its rows.
  const all = node.kind === 'shared' && folds[node.id] ? (node.data as SharedData).all : undefined
  return all ? { ...node, data: { ...(node.data as SharedData), rows: all } } : node
}

/** The lines that are drawn between the nodes that are (`nodes`): one to what is hidden goes to the frame or round it is hidden in. */
function drawnEdges(all: GraphEdge[], nodes: GraphNode[], folded: Folded): GraphEdge[] {
  const drawn = new Set(nodes.map(n => n.id))
  // (A closed box of files as a folded round: its files' lines one line from it to each agent - 21 Nov.)
  const rounds = new Set(nodes.filter(n => n.kind === 'round' || n.kind === 'files').map(n => n.id))
  const edges: GraphEdge[] = []
  for (const e of all) {
    // (A copy: what is added up on it is not added to the graph it was folded from.)
    if (drawn.has(e.source) && drawn.has(e.target)) edges.push({ ...e })
    // A lane discussion's member in a folded frame: the frame, to light it.
    else if (e.member && folded.has(e.source) && drawn.has(e.target))
      edges.push({ ...e, id: `${e.id}@${folded.get(e.source)}`, source: folded.get(e.source)! })
    else if (e.messages) talkLine(e, e.messages, drawn, folded, edges)
    // An end in a folded round: the round's line - one line of a kind for each way, its findings added up.
    else if ([e.source, e.target].some(id => rounds.has(folded.get(id) ?? ''))) roundLine(e, drawn, folded, edges)
  }
  return edges
}

/** A line's two ends as drawn: each itself, or what it is hidden in (undefined: in nothing that is drawn). */
const endsOf = (e: GraphEdge, drawn: Set<string>, folded: Folded) => [
  drawn.has(e.source) ? e.source : folded.get(e.source),
  drawn.has(e.target) ? e.target : folded.get(e.target),
]

/** Talk with an end that is hidden (`messages`: how many it counts), added to `edges`. */
function talkLine(e: GraphEdge, messages: number, drawn: Set<string>, folded: Folded, edges: GraphEdge[]) {
  const [source, target] = endsOf(e, drawn, folded)
  if (!source || !target || source === target) return
  // (Several on one way, one line: they add up, its last words the newest.)
  const same = edges.find(
    one =>
      one.messages &&
      [one.source, one.target].sort((a, b) => a.localeCompare(b)).join() ===
        [source, target].sort((a, b) => a.localeCompare(b)).join(),
  )
  if (!same) edges.push({ ...e, id: `${e.id}@${source === e.source ? target : source}`, source, target, cross: false })
  else
    Object.assign(
      same,
      { messages: (same.messages ?? 0) + messages },
      (e.lastAt ?? '') >= (same.lastAt ?? '') && { last: e.last, lastAt: e.lastAt },
    )
}

/** A line with an end in a folded round, added to `edges`. */
function roundLine(e: GraphEdge, drawn: Set<string>, folded: Folded, edges: GraphEdge[]) {
  const [source, target] = endsOf(e, drawn, folded)
  if (!source || !target || source === target) return
  const same = edges.find(
    one =>
      one.source === source &&
      one.target === target &&
      !one.work === !e.work &&
      !one.spawn === !e.spawn &&
      (one.findings === undefined) === (e.findings === undefined),
  )
  if (!same) edges.push({ ...e, id: `${e.id}@${source}>${target}`, source, target })
  else
    Object.assign(
      same,
      { active: same.active || e.active },
      e.findings !== undefined && { findings: (same.findings ?? 0) + e.findings },
    )
}

/** Every group of the graph that has something inside, opened or closed. */
export function foldAll(graph: Graph, open: boolean): Folds {
  const groups = graph.nodes.filter(n => isGroup(n) && (n.data as GroupData).inside > 0)
  return Object.fromEntries(groups.map(n => [n.id, open]))
}

/** The node a selection stands for: the node of that id. (A call, a command or a file is its agent's: `agentOf`.) */
export function nodeOf(graph: Graph, selected: string): GraphNode | undefined {
  return graph.nodes.find(n => n.id === selected) ?? inChecks(graph, selected)
}

/** An agent drawn in its turn's Checks box (`settleChecks`) - selected in the chat, say - is shown as that box. */
const inChecks = (graph: Graph, selected: string) =>
  graph.nodes.find(
    n => n.kind === 'checks' && (n.data as ChecksData).loop?.agents.includes(selected.replace(/^agent:/, '')),
  )

type Owned = { id: string; agent_id: string }[]

/**
 * A call, a command or a file selected elsewhere ("call:", "command:", "file:" and its id) is no node of its own (the
 * user's, 5 Nov): it is drawn as its agent's node, by that node's id. Any other selection as it is.
 */
export function agentOf(
  state: { toolCalls: Owned; commands: Owned; fileChanges: Owned } | null,
  selected: string,
): string {
  const [kind, id] = selected.split(/:(.*)/s)
  if (!state) return selected
  const records =
    kind === 'call' ? state.toolCalls : kind === 'command' ? state.commands : kind === 'file' ? state.fileChanges : []
  const agent = records.find(r => r.id === id)?.agent_id
  return agent ? `agent:${agent}` : selected
}

/** The turn (by its id) a selection is in; null when it is no node of the graph. */
export function turnOf(graph: Graph, selected: string): string | null {
  return nodeOf(graph, selected)?.runId ?? null
}

/**
 * The folds with which what is selected is drawn: every closed box around it is opened,
 * and put down as the user's choice - they picked the node. The same folds are handed back
 * when it is drawn already, or is no node of the graph.
 */
export function unfold(graph: Graph, folds: Folds, selected: string): Folds {
  const node = nodeOf(graph, selected)
  if (!node) return folds
  const next = { ...folds }
  let changed = false
  // (And the team frame its agent is drawn in, and the round it is folded into.)
  const agent = graph.nodes.find(a => a.kind === 'agent' && a.agentId === node.agentId)
  const around = [agent?.team, agent?.round].flatMap(id => graph.nodes.find(n => n.id === id) ?? [])
  for (let box = graph.nodes.find(n => n.id === node.parent); box; box = graph.nodes.find(n => n.id === box?.parent))
    around.push(box)
  for (const box of around) {
    if (!opens(box, folds)) {
      next[box.id] = true
      changed = true
    }
  }
  return changed ? next : folds
}

const KEY = 'koloni-canvas-groups'

/** What was opened and closed by hand in a conversation; kept in this browser only. */
export function readFolds(conversationId: string): Folds {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(`${KEY}:${conversationId}`) ?? '{}')
    if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return {}
    return Object.fromEntries(Object.entries(stored).filter(([, open]) => typeof open === 'boolean')) as Folds
  } catch {
    return {} // storage is closed to the page, or holds something else
  }
}

export function writeFolds(conversationId: string, folds: Folds): void {
  try {
    localStorage.setItem(`${KEY}:${conversationId}`, JSON.stringify(folds))
  } catch {
    // Not remembered, then; the canvas works without it.
  }
}
