import { expect, test } from 'vitest'
import { agent, command, convState, fileChange, note, run, toolCall, userMessage } from '../test-fixtures'
import { deriveGraph, type GraphEdge, type GraphNode, type NodeKind } from './deriveGraph'
import { foldAll, foldGraph } from './foldGraph'
import {
  COL_GAP,
  FILES_HEAD,
  FOUND_GAP,
  NODE_H,
  NODE_W,
  ROW_GAP,
  keepInside,
  layoutGraph,
} from './layout'
import { topicOf } from './thread.fixtures'
import { oneTurn } from './turns'

const node = (id: string, kind: NodeKind, runId: string, parent?: string, data: object = {}) =>
  ({ id, kind, runId, refId: id, parent, agentId: parent?.split(':')[1], data }) as GraphNode
const agentNode = (id: string, parentId: string | null = null, data: object = {}) =>
  ({ id: `agent:${id}`, kind: 'agent', runId: 'a', refId: id, agentId: id, data: { parentId, ...data } }) as unknown as GraphNode

const FIRST = NODE_W + COL_GAP // where a turn's lead stands, right of the request
/** From an agent to the column of those it opened: every agent is one small node (the user's, 5 Nov). */
const STEP = NODE_W + COL_GAP

interface Rect {
  id: string
  x: number
  y: number
  w: number
  h: number
}

/** Where every node is on the canvas itself, and how big, as the layout has it. */
function rects(nodes: GraphNode[]): Map<string, Rect> {
  const { positions, sizes } = layoutGraph(nodes)
  const placed = new Map<string, Rect>()
  for (const n of nodes) {
    // a group comes before what is inside it
    const parent = n.parent ? placed.get(n.parent)! : { x: 0, y: 0 }
    const size = sizes[n.id] ?? { width: NODE_W, height: NODE_H }
    placed.set(n.id, {
      id: n.id,
      x: parent.x + positions[n.id].x,
      y: parent.y + positions[n.id].y,
      w: size.width,
      h: size.height,
    })
  }
  return placed
}
const overlap = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
const contains = (box: Rect, r: Rect) => r.x >= box.x && r.y >= box.y && r.x + r.w <= box.x + box.w && r.y + r.h <= box.y + box.h

/** The two things a layout must always give: boxes hold what is in them, and nothing sits on anything else. */
function expectSound(nodes: GraphNode[]) {
  const placed = rects(nodes)
  for (const n of nodes) {
    if (n.parent) expect(contains(placed.get(n.parent)!, placed.get(n.id)!), `${n.parent} holds ${n.id}`).toBe(true)
    // within one box, and among the boxes themselves - the cards of what was shared too
    for (const other of nodes) {
      if (other.id < n.id && other.parent === n.parent) {
        expect(overlap(placed.get(n.id)!, placed.get(other.id)!), `${n.id} on ${other.id}`).toBe(false)
      }
    }
  }
  // what is inside a box (the files of a message) stays clear of the box's own header
  for (const n of nodes) {
    const box = n.parent && placed.get(n.parent)
    if (box) expect(placed.get(n.id)!.y).toBeGreaterThanOrEqual(box.y + FILES_HEAD)
  }
}

test('an agent with nothing inside is as big as a node, and so is its turn', () => {
  const { positions: pos, sizes } = layoutGraph([
    node('request:a', 'request', 'a'),
    agentNode('a'),
    node('request:b', 'request', 'b'),
  ])
  expect(sizes['agent:a']).toEqual({ width: NODE_W, height: NODE_H })
  expect(pos['request:b']).toEqual({ x: 0, y: NODE_H + ROW_GAP })
})

test('a sub-agent’s box stands right of its parent’s, one under the other, and nothing overlaps', () => {
  const nodes = [
    node('request:a', 'request', 'a'),
    agentNode('lead'),
    agentNode('kid', 'lead'),
    agentNode('grand', 'kid'),
    agentNode('kid2', 'lead'),
    node('request:b', 'request', 'b'),
  ]
  const { positions: pos } = layoutGraph(nodes)
  expect(pos['agent:lead']).toEqual({ x: FIRST, y: 0 })
  // the sub-tree starts level with its parent, one column further right
  expect(pos['agent:kid']).toEqual({ x: FIRST + STEP, y: 0 })
  expect(pos['agent:grand']).toEqual({ x: FIRST + 2 * STEP, y: 0 })
  expect(pos['agent:kid2']).toEqual({ x: FIRST + STEP, y: NODE_H + ROW_GAP })
  // the next turn starts below everything this one used
  expect(pos['request:b']).toEqual({ x: 0, y: NODE_H + ROW_GAP + NODE_H + ROW_GAP })
  expectSound(nodes)
})

test('two boxes one under the other that a findings line joins stand further apart, either way round (slice 84d)', () => {
  const nodes = [node('request:a', 'request', 'a'), agentNode('lead'), agentNode('rev', 'lead'), agentNode('fix', 'lead'), agentNode('test', 'lead')]
  const found = (source: string, target: string): GraphEdge => ({ id: 'f', source, target, active: false, findings: 1 })
  const below = (edges: GraphEdge[]) => {
    const { positions: pos } = layoutGraph(nodes, edges)
    return [pos['agent:fix'].y - (pos['agent:rev'].y + NODE_H), pos['agent:test'].y - (pos['agent:fix'].y + NODE_H)]
  }
  expect(below([])).toEqual([ROW_GAP, ROW_GAP])
  expect(below([found('agent:rev', 'agent:fix')])).toEqual([FOUND_GAP, ROW_GAP])
  expect(below([found('agent:test', 'agent:fix')])).toEqual([ROW_GAP, FOUND_GAP])
  // (any other line between them leaves the gap as it was)
  expect(below([{ id: 't', source: 'agent:rev', target: 'agent:fix', active: false, talk: true }])).toEqual([ROW_GAP, ROW_GAP])
  expect(FOUND_GAP).toBeGreaterThanOrEqual(2 * ROW_GAP)
})

test('a discussion stands outside the boxes, in the column right of the agent that opened it', () => {
  const nodes = [
    node('request:a', 'request', 'a'),
    agentNode('lead'),
    { ...node('discussion:d', 'discussion', 'a'), agentId: 'lead' },
    agentNode('kid', 'lead'),
    agentNode('kid2', 'lead'),
  ]
  const { positions: pos } = layoutGraph(nodes)
  expect(pos['discussion:d']).toEqual({ x: FIRST + STEP, y: 0 })
  expect(pos['agent:kid']).toEqual({ x: FIRST + STEP, y: NODE_H + ROW_GAP })
  expectSound(nodes)
})

test('a discussion opened by the lead, and one by a sub-agent: each in its opener’s next column, nothing overlaps', () => {
  const nodes = [
    node('request:a', 'request', 'a'),
    agentNode('lead'),
    agentNode('kid', 'lead'),
    agentNode('grand', 'kid'),
    agentNode('kid2', 'lead'),
    // opened by a sub-agent: it stands in that agent's next column
    { ...node('discussion:k', 'discussion', 'a'), agentId: 'kid' },
    { ...node('discussion:d', 'discussion', 'a'), agentId: 'lead' },
    node('request:b', 'request', 'b'),
    { ...agentNode('b'), runId: 'b' },
  ]
  const { positions: pos } = layoutGraph(nodes)
  expect(pos['discussion:d']).toEqual({ x: FIRST + STEP, y: 0 })
  expect(pos['agent:kid']).toEqual({ x: FIRST + STEP, y: NODE_H + ROW_GAP })
  expect(pos['discussion:k']).toEqual({ x: FIRST + 2 * STEP, y: pos['agent:kid'].y })
  expect(pos['request:b'].y).toBeGreaterThan(pos['agent:kid2'].y + NODE_H)
  expectSound(nodes)
})

test('records with a discussion and notes: the graph drawn from them is sound, open or closed', () => {
  const ids = ['lead', 'a1', 'a2']
  const state = convState({
    runs: [run('r'), run('s')],
    messages: [userMessage('r', 'x'), userMessage('s', 'y')],
    agents: [
      ...ids.map((id, index) =>
        agent('r', 'completed', { id, parent_agent_id: index ? 'lead' : null, depth: index ? 1 : 0, role_name: `Role ${index}` }),
      ),
      agent('s', 'running', { id: 'next' }),
    ],
    toolCalls: ids.map((id, index) => toolCall(String(index + 1), 'r', 'read_file', 'succeeded', '{}', { agent_id: id })),
    fileChanges: ids.flatMap(id => [1, 2].map(n => fileChange(`f${n}-${id}`, 'r', { agent_id: id }))),
    discussions: [
      {
        id: 'd', run_id: 'r', agent_id: 'lead', tool_call_id: 'x', topic: 'Ship it?', status: 'ended', outcome: 'agreed',
        round: 1, max_rounds: 3, created_at: '2026-10-05T10:00:02Z', ended_at: '2026-10-05T10:00:09Z',
        members: ids.map(id => ({ agent_id: id, status: 'in' as const, opened_here: false })),
      },
    ],
    boardPosts: [note('n1', 'r', { agent_id: 'a1' }), note('n2', 'r', { agent_id: null }), note('n3', 's', { agent_id: 'next' })],
  })
  const whole = deriveGraph(state)
  expect(whole.nodes.filter(n => n.kind === 'shared' || n.kind === 'discussion').map(n => n.id).sort()).toEqual([
    'discussion:d', 'shared:r:agent:a1', 'shared:r:top', 'shared:s:top',
  ])
  expectSound(foldGraph(whole, foldAll(whole, true)).nodes)
  expectSound(foldGraph(whole, foldAll(whole, false)).nodes)
  expectSound(foldGraph(whole, {}).nodes)
})

test('a large turn: six agents, each with tools, commands, files and own sub-agents - each one small node, none overlap', () => {
  const ids = ['lead', 'a1', 'a2', 'a3', 'a4', 'a5']
  const cli = { origin: 'cli' as const }
  let seq = 0
  const state = convState({
    runs: [run('r')],
    messages: [userMessage('r', 'x')],
    agents: ids.map((id, index) =>
      agent('r', 'running', {
        id,
        // a chain and a fan: a1 and a2 under the lead, a3 under a1, a4 and a5 under a2
        parent_agent_id: [null, 'lead', 'lead', 'a1', 'a2', 'a2'][index],
        depth: [0, 1, 1, 2, 2, 2][index],
        role_name: `Role ${index}`,
      }),
    ),
    toolCalls: ids.flatMap(id => [
      toolCall(String(++seq), 'r', 'read_file', 'succeeded', '{}', { agent_id: id }),
      toolCall(`sub-${id}`, 'r', 'claude__Agent', 'running', '{}', { ...cli, agent_id: id, seq: ++seq }),
      toolCall(`in-${id}`, 'r', 'claude__Read', 'succeeded', '{}', { ...cli, agent_id: id, seq: ++seq, parent_call_id: `sub-${id}` }),
      toolCall(`run-${id}`, 'r', 'run_command', 'succeeded', '{}', { ...cli, agent_id: id, seq: ++seq, parent_call_id: `sub-${id}` }),
      toolCall(String(++seq), 'r', 'claude__Grep', 'succeeded', '{}', { ...cli, agent_id: id }),
    ]),
    commands: ids.flatMap(id => [
      command(`k-in-${id}`, 'r', { agent_id: id, tool_call_id: `run-${id}` }),
      ...[1, 2, 3].map(n => command(`k${n}-${id}`, 'r', { agent_id: id })),
    ]),
    fileChanges: ids.flatMap(id => [1, 2, 3, 4].map(n => fileChange(`f${n}-${id}`, 'r', { agent_id: id }))),
  })
  const whole = deriveGraph(state)
  const graph = foldGraph(whole, foldAll(whole, true))
  // 1 request, and an agent's node each: what it did is counted on it (the user's, 5 Nov)
  expect(graph.nodes).toHaveLength(1 + 6)
  expect(graph.nodes.filter(n => n.kind === 'agent').map(n => (n.data as { summary: string }).summary)).toEqual(Array(6).fill('3 tools · 4 commands · 4 files · 1 own sub-agent'))
  expect(Object.values(layoutGraph(graph.nodes).sizes)).toEqual(Array(6).fill({ width: NODE_W, height: NODE_H }))
  expectSound(graph.nodes)

  const started = performance.now()
  for (let i = 0; i < 20; i += 1) layoutGraph(foldGraph(deriveGraph(state), {}).nodes)
  // records to places, twenty times over: each a small part of the time a person would
  // notice (the bound is loose on purpose: the test machine may be busy)
  expect((performance.now() - started) / 20).toBeLessThan(100)
})

test('a node dragged by hand is kept inside its box when the box is smaller than it was', () => {
  const box = { width: 200, height: 300 }
  const size = { width: 100, height: 50 }
  expect(keepInside({ x: 40, y: 60 }, size, box)).toEqual({ x: 40, y: 60 })
  expect(keepInside({ x: 500, y: 290 }, size, box)).toEqual({ x: 100, y: 250 })
  expect(keepInside({ x: -8, y: -3 }, size, box)).toEqual({ x: 0, y: 0 })
  // a box smaller than the node itself: its corner, not a place outside on the other side
  expect(keepInside({ x: 5, y: 5 }, { width: 400, height: 50 }, box)).toEqual({ x: 0, y: 5 })
  // and never over the box's header, where it is folded and dragged from
  expect(keepInside({ x: 40, y: 10 }, size, box, 104)).toEqual({ x: 40, y: 104 })
})

// --- one turn at a time; what a node holds opens over the canvas (slice 18a) ----------------

test('records of three turns: each drawn alone, with its boxes open or closed, is sound and starts at the top', () => {
  const ids = ['lead', 'a1']
  const state = convState({
    runs: [run('r', 'completed'), run('s', 'failed'), run('t')],
    messages: [userMessage('r', 'x'), userMessage('s', 'y'), userMessage('t', 'z')],
    agents: [
      ...ids.map((id, index) => agent('r', 'completed', { id, parent_agent_id: index ? 'lead' : null, depth: index })),
      agent('s', 'failed', { id: 'second' }),
      agent('t', 'running', { id: 'third' }),
    ],
    toolCalls: [...ids, 'second', 'third'].map((id, index) =>
      toolCall(String(index + 1), id === 'second' ? 's' : id === 'third' ? 't' : 'r', 'read_file', 'succeeded', '{}', { agent_id: id }),
    ),
    fileChanges: ids.map(id => fileChange(`f-${id}`, 'r', { agent_id: id })),
    boardPosts: [note('n1', 'r', { agent_id: 'a1' })],
  })
  const whole = deriveGraph(state)
  for (const runId of ['r', 's', 't']) {
    const own = oneTurn(whole, runId)
    for (const folds of [{}, foldAll(own, true), foldAll(own, false)]) {
      const drawn = foldGraph(own, folds).nodes
      expect(drawn.every(n => n.runId === runId)).toBe(true)
      expectSound(drawn)
      // whichever turn it is, it is laid out from the canvas's corner: no room is left for another
      expect(layoutGraph(drawn).positions[`request:${runId}`]).toEqual({ x: 0, y: 0 })
    }
  }
})

// --- the project's memory (slice 17) ------------------------------------------------------

/** A turn with a lead and two sub-agents, a discussion and notes; and a second, plain turn. */
const busy = (over: Parameters<typeof convState>[0] = {}, facts: Record<string, string[]> = {}) => {
  const ids = ['lead', 'a1', 'a2']
  return convState({
    runs: [run('r'), run('s')],
    messages: [userMessage('r', 'x'), userMessage('s', 'y')],
    agents: [
      ...ids.map((id, index) =>
        agent('r', 'completed', {
          id, parent_agent_id: index ? 'lead' : null, depth: index ? 1 : 0, role_name: `Role ${index}`, facts_given: facts[id] ?? [],
        }),
      ),
      agent('s', 'running', { id: 'next' }),
    ],
    toolCalls: ids.map((id, index) => toolCall(String(index + 1), 'r', 'read_file', 'succeeded', '{}', { agent_id: id })),
    fileChanges: [fileChange('f1', 'r', { agent_id: 'a1' })],
    discussions: [
      {
        id: 'd', run_id: 'r', agent_id: 'lead', tool_call_id: 'x', topic: 'Ship it?', status: 'ended', outcome: 'agreed',
        round: 1, max_rounds: 3, created_at: '2026-10-05T10:00:02Z', ended_at: '2026-10-05T10:00:09Z',
        members: ids.map(id => ({ agent_id: id, status: 'in' as const, opened_here: false })),
      },
    ],
    boardPosts: [note('n1', 'r', { agent_id: 'a1' })],
    ...over,
  })
}

test('a turn in which memory played no part is laid out exactly as it was before memory', () => {
  // Pinned from the layout as it stood before the memory node was added.
  const whole = deriveGraph(busy())
  expect(whole.nodes.map(n => n.id)).toMatchInlineSnapshot(`
    [
      "request:r",
      "agent:lead",
      "agent:a1",
      "agent:a2",
      "shared:r:agent:a1",
      "request:s",
      "agent:next",
      "discussion:d",
    ]
  `)
  expect(layoutGraph(foldGraph(whole, foldAll(whole, true)).nodes)).toMatchInlineSnapshot(`
    {
      "lines": {},
      "positions": {
        "agent:a1": {
          "x": 580,
          "y": 108,
        },
        "agent:a2": {
          "x": 580,
          "y": 216,
        },
        "agent:lead": {
          "x": 290,
          "y": 0,
        },
        "agent:next": {
          "x": 290,
          "y": 324,
        },
        "discussion:d": {
          "x": 580,
          "y": 0,
        },
        "request:r": {
          "x": 0,
          "y": 0,
        },
        "request:s": {
          "x": 0,
          "y": 324,
        },
        "shared:r:agent:a1": {
          "x": 870,
          "y": 0,
        },
      },
      "sizes": {
        "agent:a1": {
          "height": 80,
          "width": 220,
        },
        "agent:a2": {
          "height": 80,
          "width": 220,
        },
        "agent:lead": {
          "height": 80,
          "width": 220,
        },
        "agent:next": {
          "height": 80,
          "width": 220,
        },
        "shared:r:agent:a1": {
          "height": 52,
          "width": 234,
        },
      },
    }
  `)
})

test('records with a discussion, notes and memory: the graph drawn from them is sound, open or closed', () => {
  const state = busy(
    {
      toolCalls: [
        toolCall('1', 'r', 'read_file', 'succeeded', '{}', { agent_id: 'lead' }),
        toolCall('2', 'r', 'remember', 'succeeded', '{"text":"The port is 8790."}', { agent_id: 'a1' }),
        toolCall('3', 'r', 'recall', 'succeeded', '{"query":"port"}', { agent_id: 'a2' }),
      ],
    },
    { lead: ['f1'], a1: ['f1'], a2: ['f1'] },
  )
  const whole = deriveGraph(state)
  expect(whole.nodes.filter(n => !n.parent && n.kind !== 'agent' && n.kind !== 'request').map(n => n.id).sort()).toEqual([
    'discussion:d', 'shared:r:agent:a1', 'shared:r:agent:a2', 'shared:r:top',
  ])
  for (const folds of [foldAll(whole, true), foldAll(whole, false), {}]) {
    const drawn = foldGraph(whole, folds)
    expect(drawn.nodes.some(n => n.id === 'shared:r:agent:a2')).toBe(true)
    expectSound(drawn.nodes)
  }
  // K-shared-bagli: the memory's part is on the cards. batch-26 (the user's): everyone's card - the Lead was given a
  // fact - stands beside the Lead, level with it, and what hangs off the Lead starts that much lower; nothing else moves.
  const [before, after] = [deriveGraph(busy()), whole].map(g => layoutGraph(foldGraph(g, foldAll(g, true)).nodes))
  const lower = after.sizes['shared:r:top'].height + ROW_GAP
  for (const id of ['request:r', 'agent:lead']) expect(after.positions[id]).toEqual(before.positions[id])
  expect(after.positions['shared:r:top']).toEqual({ x: before.positions['agent:lead'].x + after.sizes['agent:lead'].width + COL_GAP, y: 0 })
  for (const id of ['agent:a1', 'agent:a2', 'discussion:d']) expect(after.positions[id]).toEqual({ ...before.positions[id], y: before.positions[id].y + lower })
})

// --- topics (slice 18b) ------------------------------------------------------------------------

test.each([1, 3, 12])('a topic of %i turns: whichever turn is drawn, open or closed, boxes hold their own and nothing overlaps', turns => {
  const state = topicOf(turns)
  for (let n = 1; n <= turns; n++) {
    const own = oneTurn(deriveGraph(state), `t${n}`)
    for (const folds of [{}, foldAll(own, true), foldAll(own, false)]) {
      const nodes = foldGraph(own, folds).nodes
      expectSound(nodes)
      expect(layoutGraph(nodes).positions[`request:t${n}`]).toEqual({ x: 0, y: 0 })
    }
  }
})

test('a plan turn’s Plan node stands under its request, and the next turn below both', () => {
  const { positions: pos } = layoutGraph([
    node('request:a', 'request', 'a'),
    node('plan:a', 'plan', 'a'),
    agentNode('a'),
    node('request:b', 'request', 'b'),
  ])
  expect(pos['plan:a']).toEqual({ x: 0, y: NODE_H + ROW_GAP })
  expect(pos['request:b']).toEqual({ x: 0, y: 2 * (NODE_H + ROW_GAP) })
})

test('an approved plan stands over the Lead of its work turn, the request level with the Lead', () => {
  const line: GraphEdge = { id: 'planned:p>agent:a', source: 'planned:p', target: 'agent:a', active: false, plan: true }
  const { positions: pos, lines } = layoutGraph(
    [node('request:b', 'request', 'b'), node('request:a', 'request', 'a'), node('planned:p', 'plan', 'a'), agentNode('a')],
    [line],
  )
  const row = NODE_H + ROW_GAP
  // Its line to the Lead is not routed: straight down, the plan right over it.
  expect(lines[line.id]).toBeUndefined()
  expect(pos['planned:p']).toEqual({ x: FIRST, y: row })
  expect(pos['agent:a']).toEqual({ x: FIRST, y: 2 * row })
  expect(pos['request:a']).toEqual({ x: 0, y: 2 * row })
})

test('the Assistant PO stands under all of its turn, in its Lead’s column, and the next turn under it', () => {
  const { positions: pos } = layoutGraph([
    node('request:a', 'request', 'a'),
    agentNode('a'),
    agentNode('kid', 'a'),
    agentNode('kid2', 'a'),
    node('po:a', 'po', 'a'),
    node('request:b', 'request', 'b'),
  ])
  const row = NODE_H + ROW_GAP
  // (Under the Lead's two sub-agents, beside it: its line straight down from the Lead crosses none.)
  expect(pos['po:a']).toEqual({ x: FIRST, y: 2 * row })
  expect(pos['request:b']).toEqual({ x: 0, y: 3 * row })
})
