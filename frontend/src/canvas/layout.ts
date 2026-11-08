import type { AgentData, GraphEdge, GraphNode, GroupData, TeamData } from './deriveGraph'
import type { SharedData } from './sharedColumn'

/** How the lines that are not plain are dashed: on the canvas, and in its legend. */
export const DASH = { waits: '3 4', talk: '2 5', spawn: '6 5', findings: '8 3', handed: '5 4', talkLine: '1 5', request: '7 4', shared: '2 3', plan: '4 4', po: '4 2 1 2' }

export const NODE_W = 220
// The user's (5 Nov): every node is small, three lines at most - its name, its state, what it did, counted; the rest is
// in the side panel. One height for all of them (canvas.css .node-head and .node-body).
export const NODE_H = 80
export const COL_GAP = 70
export const ROW_GAP = 28
/** Between two boxes one under the other that a findings line joins: room for the line to be seen. */
export const FOUND_GAP = 64

// The box of the files attached to a message: its head, and its files stacked under it.
export const GROUP_PAD = 14
export const IN_GAP = 14
export const TALL: ReadonlySet<string> = new Set(['discussion', 'room'])
// A chat team's frame (slice 84b-2): drawn round its agents' boxes, with its header (name, recipe, step strip) above
// them and, once its recipe is at its end, a line of what it did under them. Folded, it is one box of its own.
export const TEAM_HEAD = 76
export const TEAM_PAD = 16
export const TEAM_FOOT = 30
export const TEAM_W = 2 * NODE_W + COL_GAP
export const TEAM_SHUT_H = 96
// K-canvas-dili (W): in a frame, room left of its first column for the fork from its door; above and under its rows
// for a findings arc; and between two frames for a line across, with its label.
export const DOOR_PAD = 40
export const ARC_ROOM = 48
/** Between two findings arcs of a frame on one side - a loop's rounds -, and so as much more room. */
export const ARC_STEP = 18
export const FRAME_GAP = 44
/** Around the agents of steps at once, a dashed box: this much round them, and over them for its name. */
export const AT_ONCE_PAD = 10
export const AT_ONCE_HEAD = 22
/** How many agents of steps at once stand side by side in a row. */
export const AT_ONCE_ROW = 3
// The user's (4 Nov): in a step with rounds, an earlier round's line - as wide as two agents side by side - and a
// finished agent of the newest round, a chip. (canvas.css draws them.)
export const ROUND_W = 2 * NODE_W + ROW_GAP
export const ROUND_H = 32
export const CHIP_H = 32

// K-shared-bagli, batch-26 (the user's): what a team shared, noted and remembered is a small card at its frame's
// top-right - its width, a line for whose it is, a row for each thing, its padding and border - joined by a very short
// line; the gap between a frame and its card, and between two cards. (canvas.css draws them.)
export const CARD_W = 234
export const BLOCK_WHO = 18
export const BLOCK_ROW = 20
export const BLOCK_PAD = 6
const CARD_EDGE = 1
export const CARD_GAP = 24
/** Where a frame's line to Ready for you leaves it, over its foot (canvas.css .team-out), and room over that for its handle. */
export const TEAM_OUT = 18
const OUT_ROOM = 12
/** Where the lines come into Ready for you, under its top (canvas.css .ready-door); the discussions' lane starts under that. */
const READY_DOOR = 24
const LANE_UNDER = 2 * ROW_GAP
/** Where a member's line comes into a discussion in the lane: by its header. */
const MEMBER_IN = 20

/** A card's height; and how far down it its line comes in: by whose it is, or by its first row. */
export const blockSize = (data: SharedData) => ({
  height: (data.who ? BLOCK_WHO : 0) + data.rows.length * BLOCK_ROW + 2 * (BLOCK_PAD + CARD_EDGE),
  door: CARD_EDGE + BLOCK_PAD + (data.who ? BLOCK_WHO : BLOCK_ROW) / 2,
})

// A file attached to a message (slice 85b): a small node under its request, or in the box of them.
export const FILE_H = 52
export const FILES_HEAD = 40

interface Point {
  x: number
  y: number
}
interface Size {
  width: number
  height: number
}

export interface Layout {
  /** Where each node stands: on the canvas, or - inside a box - from the box's corner. */
  positions: Record<string, Point>
  /**
   * How big each box is. Every other node is as big as it is drawn: what a node holds
   * opens in a panel over the canvas, and never makes the node, or its box, any bigger.
   */
  sizes: Record<string, Size>
  /** K-shared-bagli: a card's line - from its team's frame (or agent's box), or a contract's arm - by the line's id; none where none is drawn. */
  lines: Record<string, Line>
}

type Line = { x1: number; y1: number; x2: number; y2: number }

/**
 * Left-to-right, one block per run: the request, then the agent tree. Every agent is a
 * box sized from what is inside it (tools, own sub-agents, commands, files, top to
 * bottom). The boxes of its sub-agents stand in the next column, level with it and one
 * under the other; a room it opened stands there too, outside every box. Discussions and rooms between teams stand in a lane
 * of their own right of the turn, in the order they began. What the turn's
 * teams shared (K-shared-bagli) is a card at each frame's top-right; everyone's beside the Lead. The canvas draws
 * one turn at a time; handed more, each run starts below everything the one before used.
 */
export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[] = []): Layout {
  const positions: Record<string, Point> = {}
  const sizes: Record<string, Size> = {}
  const lines: Record<string, Line> = {}
  // shortcut: only a findings line between two boxes stacked next to each other opens the gap; one that skips a box crosses it.
  const found = (a: GraphNode, b: GraphNode) =>
    edges.some(e => e.findings !== undefined && [e.source, e.target].includes(a.id) && [e.source, e.target].includes(b.id))
  // batch-26: a frame as tall as its card at its top-right and the line to Ready for you under it (`TEAM_OUT`).
  const cardRoom = (frame: GraphNode) => {
    const card = nodes.find(n => n.id === `shared:${frame.runId}:${frame.id}`)
    return card ? blockSize(card.data as SharedData).height + TEAM_OUT + OUT_ROOM : 0
  }
  const inside = new Map<string, GraphNode[]>()
  for (const node of nodes) {
    if (node.parent) inside.set(node.parent, [...(inside.get(node.parent) ?? []), node])
  }

  /** Size a box and place what is inside it: an agent is one node (a chip in a round), a frame folded one box, the
   * files of a message their box. */
  const box = (group: GraphNode): Size => {
    const held = inside.get(group.id) ?? []
    let size: Size
    if (group.kind === 'agent') size = { width: NODE_W, height: (group.data as AgentData).chip ? CHIP_H : NODE_H }
    else if (group.kind === 'team') size = { width: TEAM_W, height: Math.max(TEAM_SHUT_H, cardRoom(group)) } // (only a folded one is placed as a box)
    else if (held.length === 0) size = { width: NODE_W, height: FILES_HEAD } // ("6 files", folded)
    else {
      let y = FILES_HEAD
      for (const node of held) {
        positions[node.id] = { x: GROUP_PAD, y }
        y += FILE_H + IN_GAP
      }
      size = { width: NODE_W + 2 * GROUP_PAD, height: y - IN_GAP + GROUP_PAD }
    }
    sizes[group.id] = size
    return size
  }

  let top = 0
  for (const runId of new Set(nodes.map(n => n.runId))) {
    const own = nodes.filter(n => n.runId === runId)
    top += planAbove(own, top, positions)
    // A folded team frame stands where its agents would, under the Lead.
    const agents = own.filter(n => n.kind === 'agent' || (n.kind === 'team' && (n.data as GroupData).open === false))
    const key = (agent: GraphNode) => agent.agentId ?? agent.id
    const parentOf = (agent: GraphNode) => (agent.data as Partial<AgentData>).parentId ?? null
    const roots = agents.filter(a => !agents.some(p => key(p) === parentOf(a)))
    // The shared places: rooms, and discussions by their opener. One between teams (its lines `member`) is in the lane
    // (below): by its opener, its lines to members in other frames ran through the frames between (the user, 4 Nov).
    const lane = own.filter(n => TALL.has(n.kind) && edges.some(e => e.member && e.target === n.id))
    const talks = ['room', 'discussion'].flatMap(kind => own.filter(n => n.kind === kind && !lane.includes(n)))
    // A room whose opener is not drawn stands by the turn's first agent.
    const opener = (talk: GraphNode) => (agents.some(a => key(a) === talk.agentId) ? talk.agentId : roots[0] && key(roots[0]))
    const byId = new Map(own.map(n => [n.id, n]))
    // An open frame whose work line is known (K-canvas-dili): laid out by it, not as a tree.
    const columnsOf = (team?: string) => (team ? ((byId.get(team)?.data as Partial<TeamData> | undefined)?.columns ?? []) : [])
    const lanedFrames = new Set<string>()
    // Room above and under a frame's rows for an arc between two of its agents (findings back, talk); above them, for the name of a
    // dashed box of steps at once.
    // (Its arcs each on a band of their own: as much more room for each.)
    const arcOf = (team?: string) => {
      const arcs = edges.filter(e => team && arced(e) && byId.get(e.source)?.team === team && byId.get(e.target)?.team === team).length
      return arcs ? ARC_ROOM + (arcs - 1) * ARC_STEP : 0
    }
    // Everyone's card - the Lead's, contracts/, decisions/, or only the way to all the shared files: beside the Lead,
    // level with it, on a short line from it; what hangs off the Lead starts under it.
    const everyone = own.find(n => n.kind === 'shared' && n.id === `shared:${runId}:top`)
    const head = (team: string) => TEAM_HEAD + Math.max(arcOf(team), columnsOf(team).some(column => column.atOnce) ? AT_ONCE_HEAD : 0)
    const foot = (team: string) => TEAM_PAD + TEAM_FOOT + arcOf(team)

    /** A frame laid out by its work line: a column for each of its steps, left to right; returns the height used. */
    const lanes = (team: string, x: number, y: number): number => {
      lanedFrames.add(team)
      let [left, bottom] = [x, y]
      for (const { ids, rounds, atOnce } of columnsOf(team)) {
        // A row a node; in a step with rounds (the user's, 4 Nov; B-391: Evolve's candidates) an agent beside the one before
        // it of its round, two to a row, and the agents of steps at once (the user's, 5 Nov) side by side, AT_ONCE_ROW to a
        // row - a helper on a row of its own under them -, and a round's line a row of its own. (A line that would run
        // through a card beside goes round it: `laneLine`.)
        const rows = rowsOf(ids.flatMap(id => byId.get(id) ?? []), ids, new Set(rounds?.flat()), atOnce)
        let [top, width, end] = [y, NODE_W, y]
        for (const row of rows) {
          let [x, height] = [left, 0]
          for (const node of row) {
            positions[node.id] = { x, y: top }
            const size = node.kind === 'agent' ? box(node) : node.kind === 'round' ? (sizes[node.id] = { width: ROUND_W, height: ROUND_H }) : { width: NODE_W, height: NODE_H }
            x += size.width + ROW_GAP
            height = Math.max(height, size.height)
          }
          end = top + height
          top = end + (row[0].kind === 'round' ? IN_GAP : ROW_GAP)
          width = Math.max(width, x - ROW_GAP - left)
        }
        if (rows.length === 0) continue // (none of it drawn)
        bottom = Math.max(bottom, end)
        left += width + COL_GAP
      }
      return bottom - y
    }

    /** Place an agent's box and, right of it, all that hangs off it; returns the height used. */
    const place = (agent: GraphNode, x: number, y: number): number => {
      positions[agent.id] = { x, y }
      const { width, height } = box(agent)
      const next = x + width + COL_GAP
      let below = y + (everyone && agent === roots[0] ? blockSize(everyone.data as SharedData).height + ROW_GAP : 0)
      let before: GraphNode | null = null
      const talk = (node: GraphNode) => {
        positions[node.id] = { x: next, y: below }
        below += (NODE_H) + ROW_GAP
      }
      // (One in a team's frame stands at the head of the frame, below.)
      for (const one of talks.filter(t => opener(t) === key(agent) && !t.team)) {
        talk(one)
        before = one
      }
      // B-152: one team's together, in the order the teams came - a team's frame is round all of its own, so a team
      // opened again after another's (a request's lead) would draw its frame over the other's.
      const children = agents.filter(a => parentOf(a) === key(agent) && a !== agent)
      const teamsIn = [...new Set(children.map(a => a.team))]
      children.sort((a, b) => teamsIn.indexOf(a.team) - teamsIn.indexOf(b.team))
      for (const child of children) {
        if (child.team && lanedFrames.has(child.team)) continue // (laid out with its frame)
        // Room for a team frame's foot where one ends, and for its header where one starts; between two, for a line across.
        if (child.team !== before?.team) {
          below += (before?.team ? foot(before.team) + (child.team ? FRAME_GAP : 0) : 0) + (child.team ? head(child.team) : 0)
          // A room in a team's step (slice 84e), or a discussion among its agents only: at the head of its frame, over
          // its agents, whoever opened it. (In a frame laid out by its work line, in its column.)
          if (child.team && !columnsOf(child.team).length) talks.filter(t => t.team === child.team && !positions[t.id]).forEach(talk)
        }
        if (before && found(before, child)) below += FOUND_GAP - ROW_GAP
        below += (child.team && columnsOf(child.team).length ? lanes(child.team, next, below) : place(child, next, below)) + ROW_GAP
        before = child
      }
      if (before?.team) below += foot(before.team)
      return Math.max(height, below - ROW_GAP - y)
    }

    let used = 0
    for (const root of roots) used += place(root, NODE_W + COL_GAP, top + used) + ROW_GAP
    // An agent opened by one of a frame laid out by its work line, not in that frame (one the user declined): under the rest.
    for (const agent of agents.filter(a => !positions[a.id])) used += place(agent, NODE_W + COL_GAP, top + used) + ROW_GAP
    for (const node of own) {
      if (node.kind === 'request') positions[node.id] = { x: 0, y: top }
      // A plan turn's plan stands under its request: at the turn's start.
      if (node.id === `plan:${runId}`) positions[node.id] = { x: 0, y: top + NODE_H + ROW_GAP }
    }
    // Each open team frame round its agents' boxes; where the teams meet, right of all of it.
    for (const frame of own.filter(n => n.kind === 'team' && (n.data as GroupData).open !== false)) {
      const members = own.filter(n => n.team === frame.id && positions[n.id])
      if (members.length === 0) continue
      const right = (n: GraphNode) => positions[n.id].x + (sizes[n.id]?.width ?? NODE_W)
      const bottom = (n: GraphNode) => positions[n.id].y + (sizes[n.id]?.height ?? (NODE_H))
      // (Left of its agents, room for the fork from its door.)
      const [x, y] = [Math.min(...members.map(n => positions[n.id].x)) - DOOR_PAD, Math.min(...members.map(n => positions[n.id].y)) - head(frame.id)]
      positions[frame.id] = { x, y }
      const done = (frame.data as GroupData).finished ? TEAM_FOOT : 0
      sizes[frame.id] = {
        width: Math.max(TEAM_W, Math.max(...members.map(right)) + TEAM_PAD + arcOf(frame.id) - x),
        height: Math.max(Math.max(...members.map(bottom)) + TEAM_PAD + done + arcOf(frame.id) - y, cardRoom(frame)),
      }
    }
    // K-shared-bagli, batch-26: the cards - before what stands right of the turn, so that it stands right of them.
    // Everyone's beside the Lead. A team's at its frame's top-right, its line straight across from the frame's right
    // edge, level with the frame's header. An agent's, with no team, right of the turn level with its row: its line at
    // the first height in its box that crosses no box. A contract's on an arm from its request's line, low in the gap.
    // Each card, where it would lie on a box or another card, moves right past it.
    // shortcut: a line that would still cross a box is not drawn (the card stays); route it round if that is met.
    const cards = own.filter(n => n.kind === 'shared')
    if (cards.length) {
      const rectOf = (id: string) => ({ ...positions[id], ...(sizes[id] ?? { width: NODE_W, height: NODE_H }) })
      const placed = own.filter(n => positions[n.id] && !n.parent && n.kind !== 'shared')
      const boxesBut = (...ids: string[]) => placed.filter(n => !ids.includes(n.id)).map(n => rectOf(n.id))
      const taken: (Point & Size)[] = []
      const put = (card: GraphNode, at: Point): Point & Size => {
        const spot = { ...at, width: CARD_W, height: blockSize(card.data as SharedData).height }
        const hits = () => [...boxesBut(), ...taken].filter(b => overlaps(spot, b))
        for (let hit = hits(); hit.length; hit = hits()) spot.x = Math.max(...hit.map(b => b.x + b.width)) + CARD_GAP
        positions[card.id] = { x: spot.x, y: spot.y }
        sizes[card.id] = { width: CARD_W, height: spot.height }
        taken.push(spot)
        return spot
      }
      const lineOf = (card: GraphNode) => edges.find(e => e.target === card.id && e.shared)
      // (The card just put is where the line ends: not one it could cross.)
      const draw = (id: string, line: Line, ...but: string[]) => {
        if (!crosses(line, [...boxesBut(...but), ...taken.slice(0, -1)])) lines[id] = line
      }
      const lead = roots[0]
      if (everyone) {
        const spot = put(everyone, lead ? { x: positions[lead.id].x + (sizes[lead.id]?.width ?? NODE_W) + COL_GAP, y: positions[lead.id].y } : { x: NODE_W + COL_GAP, y: top })
        // Its short line from the Lead's right edge, level with the card's name, as a team's card has.
        const line = lineOf(everyone)
        if (line && positions[line.source]) {
          const from = rectOf(line.source)
          const y = spot.y + blockSize(everyone.data as SharedData).door
          draw(line.id, { x1: from.x + from.width, y1: y, x2: spot.x, y2: y }, line.source)
        }
      }
      const fromOf = (card: GraphNode) => byId.get(lineOf(card)?.source ?? '')
      const others = cards.filter(card => card !== everyone).sort((a, b) => (positions[fromOf(a)?.id ?? '']?.y ?? Infinity) - (positions[fromOf(b)?.id ?? '']?.y ?? Infinity))
      const arm = (card: GraphNode) => Boolean(lineOf(card)?.shared?.arm)
      for (const card of others.filter(card => !arm(card) && fromOf(card)?.kind === 'team')) {
        const line = lineOf(card)!
        const from = rectOf(line.source)
        const spot = put(card, { x: from.x + from.width + CARD_GAP, y: from.y })
        const y = spot.y + blockSize(card.data as SharedData).door
        draw(line.id, { x1: from.x + from.width, y1: y, x2: spot.x, y2: y }, line.source)
      }
      // An agent's, with no team: right of all of it, one under the other. (One whose box is not drawn: there, with no line.)
      const x = Math.max(...[...boxesBut(), ...taken].map(b => b.x + b.width)) + COL_GAP
      let floor = top
      for (const card of others.filter(card => !arm(card) && fromOf(card)?.kind !== 'team')) {
        const line = lineOf(card)
        const from = line && positions[line.source] ? rectOf(line.source) : null
        const { door } = blockSize(card.data as SharedData)
        const across = from && requestLine(from, { x, y: floor + door - REQUEST_INSET, width: CARD_W, height: Infinity }, [...boxesBut(line!.source), ...taken], 0)
        const spot = put(card, { x, y: across ? across.y1 - door : Math.max(floor, from?.y ?? top) })
        if (across) draw(line!.id, { ...across, x2: spot.x }, line!.source)
        floor = spot.y + spot.height + CARD_GAP
      }
      // A request's contract: low in the gap between the two frames, right of both, on an arm from the request's line.
      // shortcut: frames stand one under the other here (every team's lead hangs off the Lead, a request's too), so a
      // request between two has its arm. Two side by side - a layout that makes them - would leave its contract's card
      // at the turn's top, right of the frames, with no line; give it one then.
      for (const card of others.filter(arm)) {
        const line = lineOf(card)!
        const request = edges.find(e => e.id === line.shared!.arm)
        const ask = request && positions[request.source] && positions[request.target] ? requestLine(rectOf(request.source), rectOf(request.target), boxesBut(request.source, request.target), requestFrom(request, edges)) : null
        const ends = request ? [request.source, request.target].map(id => byId.get(id)?.team ?? id).filter(id => positions[id]).map(rectOf) : []
        const right = Math.max(0, ...ends.map(r => r.x + r.width)) + CARD_GAP
        const low = ask && ask.x1 === ask.x2 ? Math.max(ask.y1, ask.y2) - BLOCK_PAD : null
        const spot = put(card, { x: right, y: low === null ? top : low - blockSize(card.data as SharedData).door })
        if (ask && low !== null) draw(line.id, { x1: ask.x1, y1: low, x2: spot.x, y2: low })
      }
      used = Math.max(used, ...taken.map(card => card.y + card.height - top))
    }
    // A shared place opened by an agent of a frame laid out by its work line, and not in that frame: right of the turn.
    const unplaced = talks.filter(t => !positions[t.id])
    if (unplaced.length > 0) {
      const placed = own.filter(n => positions[n.id] && !n.parent)
      const x = Math.max(...placed.map(n => positions[n.id].x + (sizes[n.id]?.width ?? NODE_W))) + COL_GAP
      unplaced.forEach((talk, i) => (positions[talk.id] = { x, y: top + i * (NODE_H + ROW_GAP) }))
    }
    // The discussions' lane: one column right of the frames and their cards, left of Ready for you (the user, 4 Nov), one
    // under the other in the order they began (deriveGraph's); their members' lines and Ready's come down the gap left of
    // it (`memberLine`, CanvasView). Under the height the lines come into Ready at, so that they pass over it.
    if (lane.length > 0) {
      const placed = own.filter(n => positions[n.id] && !n.parent)
      const x = Math.max(...placed.map(n => positions[n.id].x + (sizes[n.id]?.width ?? NODE_W))) + COL_GAP
      const first = own.some(n => n.kind === 'ready') ? READY_DOOR + LANE_UNDER : 0
      lane.forEach((talk, i) => (positions[talk.id] = { x, y: top + first + i * (NODE_H + ROW_GAP) }))
      used = Math.max(used, first + lane.length * (NODE_H + ROW_GAP))
    }
    for (const ready of own.filter(n => n.kind === 'ready')) {
      const placed = own.filter(n => positions[n.id] && !n.parent)
      // (Right of the cards too: the frames' lines to it leave their frames low, under their cards - canvas.css.)
      positions[ready.id] = { x: Math.max(...placed.map(n => positions[n.id].x + (sizes[n.id]?.width ?? NODE_W))) + COL_GAP, y: top }
    }
    // A night while you were away (slice 106): its jobs one under the other right of the turn, its report right of them.
    const jobs = own.filter(n => n.kind === 'awayjob')
    if (jobs.length > 0) {
      const placed = own.filter(n => positions[n.id] && !n.parent)
      const x = Math.max(...placed.map(n => positions[n.id].x + (sizes[n.id]?.width ?? NODE_W))) + COL_GAP
      jobs.forEach((job, i) => (positions[job.id] = { x, y: top + i * (NODE_H + ROW_GAP) }))
      for (const report of own.filter(n => n.kind === 'away')) positions[report.id] = { x: x + NODE_W + COL_GAP, y: top }
      used = Math.max(used, jobs.length * (NODE_H + ROW_GAP))
    }
    used += poUnder(own, top + used, positions)
    const plans = own.some(n => n.id === `plan:${runId}`) ? 2 : 1
    // The files of its message, under its request (and plan): one under the other, or their box.
    let under = top + plans * (NODE_H + ROW_GAP)
    for (const node of own.filter(n => n.kind === 'files' || (n.kind === 'attachment' && !n.parent))) {
      positions[node.id] = { x: 0, y: under }
      under += (node.kind === 'files' ? box(node).height : FILE_H) + IN_GAP
    }
    top += Math.max(under - top, used)
  }
  return { positions, sizes, lines }
}

/** The approved plan a work turn carries out (`planned:`), over where its Lead stands; returns the room it takes. */
function planAbove(own: GraphNode[], top: number, positions: Record<string, Point>): number {
  const plan = own.find(n => n.id.startsWith('planned:'))
  if (!plan) return 0
  positions[plan.id] = { x: NODE_W + COL_GAP, y: top }
  return NODE_H + ROW_GAP
}

/**
 * The Assistant PO asked once the turn ended (`po:`): under all of the turn, in its Lead's column - its line straight down
 * from the Lead; returns the room it takes.
 * shortcut: another agent with no opener stands under the Lead in that column and the line runs over it; route it round if
 * such a turn is seen with a PO.
 */
function poUnder(own: GraphNode[], top: number, positions: Record<string, Point>): number {
  const po = own.find(n => n.kind === 'po')
  if (!po) return 0
  positions[po.id] = { x: NODE_W + COL_GAP, y: top }
  return NODE_H + ROW_GAP
}

/** A column's nodes in rows: an agent of a round or of steps at once beside the one before it of its round, so many to a row. */
function rowsOf(nodes: GraphNode[], ids: string[], inRounds: Set<string>, atOnce: boolean): GraphNode[][] {
  const rows: GraphNode[][] = []
  const rowOf = new Map<string | undefined, GraphNode[]>()
  const most = atOnce ? AT_ONCE_ROW : 2
  for (const node of nodes) {
    const side = node.kind === 'agent' && (atOnce || inRounds.has(node.id)) && !ids.includes(`agent:${(node.data as AgentData).parentId}`)
    const row = side ? rowOf.get(node.round) : undefined
    if (row && row.length < most) row.push(node)
    else {
      rows.push([node])
      if (side) rowOf.set(node.round, rows[rows.length - 1])
    }
  }
  return rows
}

const overlaps = (a: Point & Size, b: Point & Size) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

/** Whether a straight line crosses any of the boxes (touching a box's edge is not crossing it). */
export function crosses(line: Line, boxes: (Point & Size)[]): boolean {
  const [left, right, top, bottom] = [Math.min(line.x1, line.x2), Math.max(line.x1, line.x2), Math.min(line.y1, line.y2), Math.max(line.y1, line.y2)]
  return boxes.some(box => left < box.x + box.width && right > box.x && top < box.y + box.height && bottom > box.y)
}

/** Where along the two frames' span a request's line runs: asked both ways, the second way at 30%, not on the first. */
export const requestFrom = (e: GraphEdge, edges: GraphEdge[]) =>
  e.source > e.target && edges.some(f => f.request && f.source === e.target && f.target === e.source) ? 0.3 : 0.7

/**
 * A member's line to a discussion in the lane (the user, 4 Nov: joined by lines, none through a frame): out of its frame's
 * right edge low, under its card, where its line to Ready leaves - or, an agent with no frame, up over the turn at
 * `over` - across to a bus in the gap left of the lane, down (or up) it and in at the discussion's head.
 * shortcut: an agent with no frame under another in its column (not the Lead) goes up through it; route it round if met.
 */
export function memberLine(from: Point & Size, framed: boolean, to: Point, over: number): Point[] {
  const start = framed ? [{ x: from.x + from.width, y: from.y + from.height - TEAM_OUT }] : [{ x: from.x + from.width / 2, y: from.y }, { x: from.x + from.width / 2, y: over }]
  const [bus, y] = [to.x - DOOR_PAD, to.y + MEMBER_IN]
  return [...start, { x: bus, y: start[start.length - 1].y }, { x: bus, y }, { x: to.x, y }]
}

/** Where a request's line keeps from a frame's corner, so it never runs along an edge of either frame; and its step. */
export const REQUEST_INSET = 24
const REQUEST_STEP = 16

/**
 * K-takimlar-arasi: a request between two teams' frames - one short straight line in the gap between them, frame edge to
 * frame edge: down (or up) where one stands over the other, across where they stand side by side, at the first place
 * along their shared span (from 70% of it, the mockup's - or `from` that share of it) that crosses none of `boxes`. Null:
 * no such place. (K-shared-bagli: an agent's line to its card, from the top of the span.)
 * shortcut: frames that overlap, or stand neither over nor beside each other, get no line (the badges still say who
 * asked whom). (Several one way are one line - deriveGraph; the other way, `requestFrom`.)
 */
export function requestLine(a: Point & Size, b: Point & Size, boxes: (Point & Size)[], from = 0.7): Line | null {
  const down = b.y >= a.y + a.height || a.y >= b.y + b.height
  const across = b.x >= a.x + a.width || a.x >= b.x + b.width
  if (down === across) return null
  // Along the span both frames share (x for a line down, y for one across), keeping off their edges.
  const [lo, hi] = down ? [Math.max(a.x, b.x), Math.min(a.x + a.width, b.x + b.width)] : [Math.max(a.y, b.y), Math.min(a.y + a.height, b.y + b.height)]
  const [low, high] = [lo + REQUEST_INSET, hi - REQUEST_INSET]
  if (low > high) return null
  const first = Math.max(low, Math.min(high, lo + (hi - lo) * from))
  const tries = [...Array(Math.ceil((high - low) / REQUEST_STEP) + 1).keys()].flatMap(i => [first - i * REQUEST_STEP, first + i * REQUEST_STEP]).filter(at => at >= low && at <= high)
  for (const at of tries) {
    const line = down
      ? { x1: at, y1: a.y < b.y ? a.y + a.height : a.y, x2: at, y2: a.y < b.y ? b.y : b.y + b.height }
      : { x1: a.x < b.x ? a.x + a.width : a.x, y1: at, x2: a.x < b.x ? b.x : b.x + b.width, y2: at }
    if (!crosses(line, boxes)) return line
  }
  return null
}

/** A place inside a box of this size for a node of that size: the nearest to where it was. */
export function keepInside(position: Point, size: Size, within: Size, head = 0): Point {
  return {
    x: Math.max(0, Math.min(position.x, within.width - size.width)),
    // Never over the box's header: that is where it is folded and dragged from.
    y: Math.max(head, Math.min(position.y, within.height - size.height)),
  }
}

/**
 * Of a frame's line between two of its nodes, one over the other (a round's line over the next round's two cards, a
 * helper under its opener): it goes out of the foot and into the top - round the side it ran back under the line it left
 * and behind the card beside (the user, 5 Nov).
 */
export const stacked = (s: Point & Size, t: Point & Size) => t.x < s.x + s.width && s.x < t.x + t.width

/** K-canvas-dili: a frame's lines drawn on an arc over or under its work line - findings handed back, and talk between two of its agents (the user, 6 Nov: never under a card). */
export const arced = (e: GraphEdge) => e.findings !== undefined || (!!e.talk && !!e.messages)

// How far an arc goes out right of its agent (in the room the layout leaves, ARC_ROOM), and how round it turns.
const ARC_HOOK = 40
const ARC_TURN = 16
// (Half way between a column and the fork into it, DOOR_PAD / 2 left of it.)
const ARC_SIDE = DOOR_PAD / 4

/**
 * An arc of a frame (`arced`): which way it is drawn - talk from the end further right, so its hook never turns back on
 * it -, the band it runs on - over the work line to the top agent of a column, under it to any other: into its top, its
 * foot, or with agents over and under it, its side -, and which band out it is: the one from the agent nearest the line
 * nearest it, so rounds of a loop and talk lie apart; `turned`, drawn from its target. `rect`: where the layout put a node;
 * `frameOf`: the frame it is in.
 */
export function arcWay(e: GraphEdge, nodes: GraphNode[], edges: GraphEdge[], rect: (id: string) => Point & Size, frameOf: (id: string) => string | undefined) {
  const way = (f: GraphEdge) => (f.messages && rect(f.target).x > rect(f.source).x ? { ...f, source: f.target, target: f.source } : f)
  const frame = frameOf(e.source)
  const column = (f: GraphEdge, above: boolean) =>
    nodes.some(n => frameOf(n.id) === frame && !n.parent && n.id !== f.target && Math.abs(rect(n.id).x - rect(f.target).x) < 1 && rect(n.id).y < rect(f.target).y === above)
  const arcs = edges.filter(f => arced(f) && frameOf(f.source) === frame && frameOf(f.target) === frame).map(way)
  const me = way(e)
  const [box, over, under] = [rect(frame ?? ''), !column(me, true), !column(me, false)]
  const ring = arcs
    .filter(f => !column(f, true) === over)
    .sort((a, b) => (rect(b.source).y - rect(a.source).y) * (over ? -1 : 1))
    .findIndex(f => f.id === e.id)
  const [room, foot] = [ARC_ROOM + (arcs.length - 1) * ARC_STEP, (nodes.find(n => n.id === frame)?.data as GroupData | undefined)?.finished ? TEAM_FOOT : 0]
  const band = over ? box.y + TEAM_HEAD + room - (ARC_ROOM * 3) / 4 - ring * ARC_STEP : box.y + box.height - TEAM_PAD - foot - room + ARC_ROOM / 2 + ring * ARC_STEP
  return { source: me.source, target: me.target, turned: me !== e, band, ring, into: over ? ('top' as const) : under ? ('foot' as const) : ('side' as const) }
}

/**
 * An arc's path: out of the right of the agent it starts at, up (or down) beside it, back over (or under) the work line on
 * its band, and down (or up) into the other - or, `side`, up beside it, between its column and the fork into it.
 * shortcut: the hook goes ARC_HOOK out right whatever stands there - an agent beside it in a round's row, or a far band's
 * hook past COL_GAP into the next column; leave room right of the agent if that is seen.
 */
export function arcPath(sourceX: number, sourceY: number, targetX: number, targetY: number, band: number, ring: number, side: boolean): string {
  // (An arc on a band further out goes out further: it passes beside those inside it, not over them.)
  const [hook, turn] = [sourceX + ARC_HOOK + ring * ARC_TURN, Math.sign(targetY - band) * ARC_TURN]
  const into = side
    ? `L ${targetX - ARC_SIDE} ${band} L ${targetX - ARC_SIDE} ${targetY} L ${targetX} ${targetY}`
    : `L ${targetX + ARC_TURN} ${band} Q ${targetX} ${band}, ${targetX} ${band + turn} L ${targetX} ${targetY}`
  return `M ${sourceX} ${sourceY} C ${hook} ${sourceY}, ${hook} ${band}, ${sourceX} ${band} ${into}`
}

type Rect = Point & Size

/** A frame's header - its name, recipe, step strip and buttons -: no line crosses it. Right of where its door line turns in. */
export const headOf = (frame: Rect): Rect => ({ x: frame.x + DOOR_PAD / 2, y: frame.y, width: frame.width - DOOR_PAD / 2, height: TEAM_HEAD })

/** What a frame's own line goes round besides its cards: its header, and its outline - thin, just outside it (B-97). */
export const wallsOf = (f: Rect): Rect[] => [
  headOf(f),
  { x: f.x - EDGE, y: f.y - EDGE, width: f.width + 2 * EDGE, height: EDGE },
  { x: f.x - EDGE, y: f.y + f.height, width: f.width + 2 * EDGE, height: EDGE },
  { x: f.x - EDGE, y: f.y, width: EDGE, height: f.height },
  { x: f.x + f.width, y: f.y, width: EDGE, height: f.height },
]

/**
 * The legs of a frame's line as React Flow draws it (`LaneEdge`), straight, between its handles: one node over the other
 * (`stacked`) from the middle of the one's foot to the middle of the other's top (or top to foot, the other above),
 * across half way; else out of the right side - a frame's door, 38px down its left edge, too - across to DOOR_PAD / 2
 * left of the target, and in at its left.
 */
export function laneLegs(s: Rect, t: Rect, door: boolean): Line[] {
  const side = (b: Rect) => b.y + b.height / 2
  if (!door && stacked(s, t)) {
    const [sx, tx] = [s.x + s.width / 2, t.x + t.width / 2]
    const [out, into] = t.y > s.y ? [s.y + s.height, t.y] : [s.y, t.y + t.height]
    const mid = (out + into) / 2
    return [{ x1: sx, y1: out, x2: sx, y2: mid }, { x1: sx, y1: mid, x2: tx, y2: mid }, { x1: tx, y1: mid, x2: tx, y2: into }]
  }
  const [sx, sy, cx, ty] = [door ? s.x : s.x + s.width, door ? s.y + 38 : side(s), t.x - DOOR_PAD / 2, side(t)]
  return [{ x1: sx, y1: sy, x2: cx, y2: sy }, { x1: cx, y1: sy, x2: cx, y2: ty }, { x1: cx, y1: ty, x2: t.x, y2: ty }]
}

/**
 * A frame's line between two of its nodes (the user's, 5 Nov: none under a card, nor over the frame's header): as React
 * Flow draws it (`laneLegs`) - null - or, where that would cross one of `boxes`, its way round them (`route`). One that
 * stands beside another in its row (steps at once) is gone into from above and left from below.
 */
export function laneLine(s: Rect, t: Rect, door: boolean, boxes: Rect[]): Point[] | null {
  const others = boxes.filter(b => !same(b, s) && !same(b, t))
  // (In its row, ROW_GAP from it: of its step, not of the next column - COL_GAP away.)
  const beside = (b: Rect) => others.some(o => Math.abs(o.y - b.y) < 1 && Math.min(Math.abs(o.x - b.x - b.width), Math.abs(b.x - o.x - o.width)) <= ROW_GAP)
  const [out, into] = [!door && beside(s), beside(t)]
  // (One right over the other goes into its top as drawn - a round's line into the cards of its row: f470d2d3.)
  if ((stacked(s, t) || (!out && !into)) && !laneLegs(s, t, door).some(leg => crosses(leg, others))) return null
  // (From a door: out of a point on the frame's left edge, inward. Where no way goes so - a round's line right over the
  // card - by any side.)
  const from = door ? { x: s.x, y: s.y + 38, width: 0, height: 0 } : s
  const sides: Side[] | undefined = door ? ['right'] : undefined
  return route(from, t, others, PORT, out ? ['foot'] : sides, into ? ['top'] : undefined) ?? route(from, t, others, PORT, sides)
}

const same = (a: Point & Partial<Size>, b: Point & Partial<Size>) => a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height

/**
 * Talk between agents of two frames (the user's, 5 Nov): out of its frame by its right side, along the margin right of the
 * frames, and in at the other's right side to its agent - never through a frame between, a header or a card; its label
 * on the longest leg outside both frames. `cards`: every node not a frame; `i`: which such line it is, so that they lie apart.
 */
export function crossTalk(a: Rect, b: Rect, frameA: Rect, frameB: Rect, frames: Rect[], cards: Rect[], i: number): { points: Point[]; at: Point } | null {
  const edges = (f: Rect) => [headOf(f), { ...f, height: EDGE }, { ...f, y: f.y + f.height - EDGE, height: EDGE }, { ...f, width: EDGE }]
  const boxes = [...cards.filter(c => !same(c, a) && !same(c, b)), ...edges(frameA), ...edges(frameB), ...frames.filter(f => !same(f, frameA) && !same(f, frameB))]
  // (Apart from the lines before it where there is room; where a frame's foot leaves none, as close as any.)
  const points = route(a, b, boxes, PORT + i * TALK_STEP) ?? route(a, b, boxes, PORT) ?? route(a, b, boxes, PORT / 3)
  if (!points) return null
  const inside = (p: Point, f: Rect) => p.x > f.x && p.x < f.x + f.width && p.y > f.y && p.y < f.y + f.height
  const legs = points.slice(1).map((p, k) => [points[k], p] as const)
  const outside = legs.filter(([p, q]) => ![frameA, frameB].some(f => inside({ x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 }, f)))
  const [p, q] = (outside.length ? outside : legs).reduce((x, y) => (len(y) > len(x) ? y : x))
  return { points, at: { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 } }
}

const len = ([p, q]: readonly [Point, Point]) => Math.abs(p.x - q.x) + Math.abs(p.y - q.y)
/** How far a line keeps from a box, and goes straight out of one before it turns; two talk lines across lie this far apart. */
const PORT = 12
const TALK_STEP = 8
/** A frame's edge, as thin as a box: a line across between two frames leaves and comes in by a side, not by its top or foot. */
const EDGE = 2
/** What a turn costs a line, as so much length: few turns, a line easy to follow. */
const BEND = 40

type Side = 'right' | 'left' | 'top' | 'foot'
const SIDES: Side[] = ['right', 'left', 'top', 'foot']
const OUT: Record<Side, Point> = { right: { x: 1, y: 0 }, left: { x: -1, y: 0 }, top: { x: 0, y: -1 }, foot: { x: 0, y: 1 } }
const port = (b: Rect, side: Side): Point => ({
  x: side === 'right' ? b.x + b.width : side === 'left' ? b.x : b.x + b.width / 2,
  y: side === 'top' ? b.y : side === 'foot' ? b.y + b.height : b.y + b.height / 2,
})

/**
 * A square line from a side of `from` to a side of `to` that crosses none of `boxes`, keeping `gap` from them: the
 * shortest, a turn counted as BEND more, over the lanes each box's sides leave (a small grid; Dijkstra). Null: none.
 * `sides`, `into`: where it may leave `from` and come into `to` - any side where not said.
 */
export function route(from: Rect, to: Rect, boxes: Rect[], gap = PORT, sides: Side[] = SIDES, into: Side[] = SIDES): Point[] | null {
  const stub = (b: Rect, side: Side) => ({ x: port(b, side).x + OUT[side].x * gap, y: port(b, side).y + OUT[side].y * gap })
  const free = (p: Point, q: Point) => !crosses({ x1: p.x, y1: p.y, x2: q.x, y2: q.y }, [...boxes, from, to])
  const starts = sides.filter(side => free(port(from, side), stub(from, side)))
  const ends = into.filter(side => free(stub(to, side), port(to, side)))
  const lanes = (tips: number[], edges: (b: Rect) => number[]) => [...new Set([...tips, ...boxes.flatMap(edges)])].sort((p, q) => p - q)
  const tips = [...starts.map(s => stub(from, s)), ...ends.map(s => stub(to, s))]
  const grid = new Grid(
    lanes(tips.map(p => p.x), b => [b.x - gap, b.x + b.width + gap]),
    lanes(tips.map(p => p.y), b => [b.y - gap, b.y + b.height + gap]),
  )
  for (const side of starts) grid.push(grid.keyOf(stub(from, side), SIDES.indexOf(side)), 0)
  for (let next = grid.pop(); next; next = grid.pop()) {
    const state = grid.at(next.k)
    const { p, d } = state
    const end = ends.find(side => same(stub(to, side), p) && inward(SIDES[d], side))
    if (end) {
      const points = grid.back(next.k)
      return straight([port(from, starts.find(s => same(stub(from, s), points[0]))!), ...points, port(to, end)])
    }
    for (const { k, q, n } of grid.around(state)) if (free(p, q)) grid.push(k, next.c + Math.abs(q.x - p.x) + Math.abs(q.y - p.y) + (n === d ? 0 : BEND), next.k)
  }
  return null
}

/** Come in straight: the last leg goes in the way it comes - the way out of the side it comes in at, turned round. */
const inward = (way: Side, side: Side) => OUT[way].x === -OUT[side].x && OUT[way].y === -OUT[side].y

/**
 * `route`'s search: a state is a point of the grid of lanes and the way it was come to (0-3, as SIDES), by its key; its
 * cost so far, where it came from, and the states still to look at, cheapest first (a binary heap).
 */
class Grid {
  private cost = new Map<number, number>()
  private from = new Map<number, number>()
  private heap: { c: number; k: number }[] = []
  private xs: number[]
  private ys: number[]
  constructor(xs: number[], ys: number[]) {
    this.xs = xs
    this.ys = ys
  }

  key(i: number, j: number, d: number) {
    return (i * this.ys.length + j) * 4 + d
  }

  /** A point's key, its lane found by its place (only where a search starts). */
  keyOf(p: Point, d: number) {
    return this.key(this.xs.indexOf(p.x), this.ys.indexOf(p.y), d)
  }

  at(k: number) {
    const [i, j] = [Math.floor(k / 4 / this.ys.length), Math.floor(k / 4) % this.ys.length]
    return { i, j, d: k % 4, p: { x: this.xs[i], y: this.ys[j] } }
  }

  /** The next points of the grid each way from a state: each one's key (come to that way), the point, and the way. */
  around({ i, j }: { i: number; j: number }): { k: number; q: Point; n: number }[] {
    const steps = [[1, 0], [-1, 0], [0, -1], [0, 1]].map(([di, dj], n) => [n, i + di, j + dj] as const)
    return steps
      .filter(([, x, y]) => x >= 0 && y >= 0 && x < this.xs.length && y < this.ys.length)
      .map(([n, x, y]) => ({ k: this.key(x, y, n), q: { x: this.xs[x], y: this.ys[y] }, n }))
  }

  push(k: number, c: number, from?: number) {
    if (c >= (this.cost.get(k) ?? Infinity)) return
    this.cost.set(k, c)
    if (from !== undefined) this.from.set(k, from)
    const heap = this.heap
    heap.push({ c, k })
    for (let n = heap.length - 1, up = (n - 1) >> 1; n > 0 && heap[up].c > heap[n].c; n = up, up = (n - 1) >> 1) [heap[n], heap[up]] = [heap[up], heap[n]]
  }

  /** The cheapest state left (one pushed again cheaper is passed over); none: the search is over. */
  pop(): { c: number; k: number } | undefined {
    let top = this.take()
    while (top && top.c > (this.cost.get(top.k) ?? Infinity)) top = this.take()
    return top
  }

  /** The top of the heap, taken off it. */
  private take() {
    const heap = this.heap
    const top = heap[0]
    const last = heap.pop()
    if (heap.length && last) {
      heap[0] = last
      this.sink()
    }
    return top
  }

  private sink() {
    const heap = this.heap
    for (let n = 0, m = this.least(n); m !== n; n = m, m = this.least(n)) [heap[n], heap[m]] = [heap[m], heap[n]]
  }

  /** Of a node of the heap and its two children, the cheapest. */
  private least(n: number) {
    return [2 * n + 1, 2 * n + 2].filter(c => c < this.heap.length).reduce((a, c) => (this.heap[c].c < this.heap[a].c ? c : a), n)
  }

  /** The points a state was come to by, from the first. */
  back(k: number): Point[] {
    const points: Point[] = []
    for (let n: number | undefined = k; n !== undefined; n = this.from.get(n)) {
      const { p } = this.at(n)
      if (!points.length || !same(points[0], p)) points.unshift(p)
    }
    return points
  }
}

/** Without the points a line only passes through straight. */
function straight(points: Point[]): Point[] {
  return points.filter((p, k) => {
    const [a, b] = [points[k - 1], points[k + 1]]
    return !a || !b || !((a.x === p.x && p.x === b.x) || (a.y === p.y && p.y === b.y))
  })
}

/**
 * A frame's own line - from its door, or between two of its nodes, not on an arc - as the canvas draws it: its ends (talk
 * with an agent of an earlier column is drawn from that one), and its points where it goes round a card (`laneLine`);
 * none: React Flow draws it from its handles (`laneLegs`). `boxes`: the frame's nodes and its walls (`wallsOf`).
 */
export function frameLine(e: GraphEdge, rect: (id: string) => Point & Size, door: boolean, boxes: (Point & Size)[]): { source: string; target: string; points: Point[] | null } {
  const [s, t] = [rect(e.source), rect(e.target)]
  const turned = !door && !stacked(s, t) && t.x < s.x
  const [source, target] = turned ? [e.target, e.source] : [e.source, e.target]
  return { source, target, points: laneLine(rect(source), rect(target), door, boxes) }
}
