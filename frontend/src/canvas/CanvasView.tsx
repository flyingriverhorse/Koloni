import { ArrowsInSimple, ArrowsOutSimple, ChartBarHorizontal, CornersOut, Crosshair, Question } from '@phosphor-icons/react'
import {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  type Edge,
  MarkerType,
  type Node,
  type NodeChange,
  Panel,
  ReactFlow,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Team } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { type GraphEdge, type GraphNode, deriveGraph, type GroupData, type TeamData } from './deriveGraph'
import { ArcEdge, LaneEdge, LevelEdge, type LineData, MemberEdge, RequestEdge } from './edges'
import { type Folds, agentOf, foldAll, foldGraph, isGroup, nodeOf, readFolds, unfold, writeFolds } from './foldGraph'
import { AT_ONCE_HEAD, AT_ONCE_PAD, DASH, DOOR_PAD, FILES_HEAD, type Layout, NODE_H, NODE_W, arcWay, crossTalk, frameLine, wallsOf, arced, keepInside, layoutGraph, memberLine, requestFrom, requestLine, stacked } from './layout'
import { AgentNode, AttachmentNode, AwayJobNode, AwayNode, DiscussionNode, FilesNode, PlanNode, PoNode, ReadyNode, RequestNode, RoomNode, RoundNode, TeamNode } from './nodes'
import { useOutputs } from './outputs'
import { SharedNode, useSharedFiles } from './SharedNode'
import { SAID, SAID_LINES, SaidBox } from './Said'
import { saidSide } from './saidSide'
import { type Actions, NodeActions, ToggleGroup } from './toggleGroup'
import { talkColours } from '../agents/teamRun'
import { MOVED } from '../shell/move'
import { usePanel } from '../shell/usePanel'
import { Legend } from './Legend'
import { TimelineStrip } from './TimelineStrip'
import { TurnList } from './TurnList'
import { FIT_MAX_ZOOM, MAX_ZOOM, MIN_ZOOM, type Rect, type Size, centredOn, fitNarrowed, freePart, keepWork } from './viewport'
import { currentTurn, frontTurn, oneTurn, turnOf, turnRows } from './turns'

// The lines of a team's frame, its door and a line across to another frame (K-canvas-dili); a request between teams; a
// team's line to its card (K-shared-bagli).
const edgeTypes = { lane: LaneEdge, arc: ArcEdge, request: RequestEdge, level: LevelEdge, member: MemberEdge }

const nodeTypes = {
  request: RequestNode,
  agent: AgentNode,
  discussion: DiscussionNode,
  room: RoomNode,
  plan: PlanNode,
  po: PoNode,
  team: TeamNode,
  ready: ReadyNode,
  attachment: AttachmentNode,
  files: FilesNode,
  awayjob: AwayJobNode,
  away: AwayNode,
  shared: SharedNode,
  round: RoundNode,
}

interface Props {
  state: ConvState | null
  selectedId: string | null
  onSelect: (nodeId: string | null) => void
  onOpenNode?: (kind: string, refId: string) => void
  /** The turn the user picked to look at; null while the newest turn they started is drawn. */
  turnId?: string | null
  /** Pick a turn: from the turn list, or because something in another turn was selected. */
  onTurn?: (runId: string) => void
  /** Give a topic another name, from the turn list. Throws with the server's reason. */
  onRenameTopic?: (topicId: string, title: string) => Promise<void>
  /**
   * What lies open over the stage - an agent's window, by its agent - or null. It takes no
   * room from the canvas, so the canvas is told: a selected node is moved out from under it.
   */
  over?: string | null
  /** Where the button that opens the turn list is drawn: a place in the top bar; none, no list. */
  turnsIn?: HTMLElement | null
  /** Open Ready for you's panel (tek-ev §1): the Ready for you node's way there. */
  onOpenList?: () => void
  /** Stop one of the chat's teams (slice 84b-2). */
  onStopTeam?: (teamId: string) => Promise<void>
  /** Finish now on a team's looped recipe (batch-17). */
  onFinishTeam?: (teamId: string) => Promise<void>
  /** Every team there is: a chat whose teams have no recipe has its agents framed by their roles (B-101). */
  teams?: Team[]
}

const NO_TEAMS: Team[] = []

const TIMELINE_KEY = 'koloni-timeline-open'

function storedTimeline(): boolean {
  try {
    return localStorage.getItem(TIMELINE_KEY) === '1'
  } catch {
    return false
  }
}

type Positions = Record<string, { x: number; y: number }>
type Sizes = Record<string, { width: number; height: number }>

/** How long the view takes to a fit. */
const FIT_MS = 200
/** How close the view comes when it goes to a node selected from elsewhere. */
const CENTRE_ZOOM = 0.8

/**
 * What lies over the stage (`.stage`, which the canvas fills) without narrowing it: the chat,
 * which floats over its corner or wherever it was moved, the view window, and an agent's or a
 * room's window - where each really is (slice 38e). (Not the two buttons beside the small chat: a
 * strip at the very foot, they would leave no part of the stage whole beside the chat.) And the chat's teams button in
 * the top right corner: a node kept in view is not drawn under it (R73).
 */
const OVER = '.chat, .view-panel:not(.view-panel-wide), .agent-window, .room-window, .chat-teams'
/** What the turn is drawn clear of: the chat, the view window (slice 39) - not one expanded over all of it - and the canvas's buttons, its teams button too. */
const CHAT = '.chat, .view-panel:not(.view-panel-wide), .react-flow__controls, .chat-teams'

/** As a node is drawn at work: an agent running or waiting on its own, a node whose calls run. */
function atWork(data: object): boolean {
  const { status, running } = data as { status?: unknown; running?: unknown }
  return status === 'running' || status === 'waiting' || running === true
}

/** Where those lie, measured from the corner of the part of the stage the turn is drawn on. */
function lyingOver(flow: HTMLElement | null, over = OVER): Rect[] {
  if (!flow) return []
  const corner = flow.getBoundingClientRect()
  return Array.from(flow.closest('.stage')?.querySelectorAll(over) ?? [])
    .map(element => {
      const box = element.getBoundingClientRect()
      return { x: box.left - corner.left, y: box.top - corner.top, width: box.width, height: box.height }
    })
    .filter(box => box.width > 0 && box.height > 0) // (a closed panel lies over nothing)
}

type Point = { x: number; y: number }

/**
 * The lines that go round (the user's, 5 Nov: none under a card, nor over a frame's header), by edge id: talk between
 * agents of two frames, in the margin right of them (`crossTalk`); a frame's own line that would run under a card, or
 * into one beside another of its row, round them (`frameLine`). The rest are drawn as they are. (Once a layout: a route
 * is a search.)
 */
function roundLines({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }, auto: Layout) {
  const byId = new Map(nodes.map(n => [n.id, n]))
  const rect = (id: string) => ({ ...(auto.positions[id] ?? { x: 0, y: 0 }), ...(auto.sizes[id] ?? { width: NODE_W, height: NODE_H }) })
  const placed = nodes.filter(n => !n.parent && auto.positions[n.id])
  const [frames, cards] = [placed.filter(n => n.kind === 'team'), placed.filter(n => n.kind !== 'team')]
  const round: Record<string, { source: string; target: string; points: Point[]; at?: Point }> = {}
  edges.filter(e => e.cross).forEach((e, i) => {
    const [a, b] = [byId.get(e.source)?.team, byId.get(e.target)?.team]
    if (!a || !b || !auto.positions[a] || !auto.positions[b]) return
    const line = crossTalk(rect(e.source), rect(e.target), rect(a), rect(b), frames.map(f => rect(f.id)), cards.map(c => rect(c.id)), i)
    if (line) round[e.id] = { source: e.source, target: e.target, ...line }
  })
  for (const e of edges) {
    const frame = byId.get(e.target)?.team
    const door = byId.get(e.source)?.kind === 'team'
    if (!frame || e.cross || arced(e) || !(door || byId.get(e.source)?.team === frame) || !auto.positions[e.source]) continue
    const { source, target, points } = frameLine(e, rect, door, [...cards.filter(n => n.team === frame).map(n => rect(n.id)), ...wallsOf(rect(frame))])
    if (points) round[e.id] = { source, target, points }
  }
  return round
}

/** An approved plan's line straight down to the Lead under it, or the Lead's to the Assistant PO under the turn: a relation, not a flow - no arrow, no tab stop, nothing read out. */
const planLine = (e: GraphEdge): Edge => ({
  id: e.id,
  source: e.source,
  target: e.target,
  type: 'straight',
  sourceHandle: 'plan-out',
  targetHandle: 'plan-in',
  focusable: false,
  selectable: false,
  domAttributes: { 'aria-hidden': true },
  style: { stroke: 'var(--border-strong)', strokeWidth: 1.5, strokeDasharray: e.po ? DASH.po : DASH.plan },
})

/** The bee over the empty canvas (K-logo), once the conversation is read: played once, muted, then still on its last
 * frame (no `loop`); only the picture where motion is reduced. Decorative. Mounted with the empty state alone, so
 * nothing loads before it. */
function EmptyBee() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    ? <img className="canvas-empty-bee" src="/brand/koloni_ari_vektor.png" width={120} height={120} alt="" aria-hidden="true" />
    : <video className="canvas-empty-bee" src="/brand/koloni-ari.webm" width={120} height={120} autoPlay muted playsInline aria-hidden="true" />
}

/**
 * The canvas draws one message's work at a time: the one picked - in Recent (in the top bar),
 * or in the chat, by a click or its ⋯ - and otherwise the newest that waits, is at work or did
 * work (slice 107). No other turn's nodes are drawn, so turns cannot lie on each other.
 *
 * Mount with `key` set to the conversation id so drags and viewport reset per conversation.
 */
export function CanvasView({ state, selectedId, onSelect, onOpenNode, turnId = null, onTurn, onRenameTopic, over = null, turnsIn = null, onOpenList, onStopTeam, onFinishTeam, teams = NO_TEAMS }: Props) {
  const conversationId = state?.conversation.id
  const rows = useMemo(() => (state ? turnRows(state) : []), [state])
  // (A comparison's later side is picked as the turn it is drawn in.)
  const current = currentTurn(rows, state && turnId ? turnOf(state, turnId) : frontTurn(rows))
  // The topic of the message drawn: of the user's own, it is renamed from Recent.
  const topicId = state?.runs.find(run => run.id === current)?.topic_id
  const topic = state?.topics.find(one => one.id === topicId && one.trigger_id === null) ?? null
  // K-ortak-klasor: the teams' shared folder - what of it the turn wrote is on the cards (K-shared-bagli).
  const sharedFiles = useSharedFiles(state)
  const outputs = useOutputs(state)
  const whole = useMemo(() => (state ? deriveGraph(state, teams, sharedFiles, outputs) : { nodes: [], edges: [] }), [state, teams, sharedFiles, outputs])
  const own = useMemo(() => oneTurn(whole, current), [whole, current])
  // Groups the user opened or closed by hand; the rest open and close by what they are doing.
  const [folds, setFolds] = useState<Folds>(() => (conversationId ? readFolds(conversationId) : {}))
  // The turn as it is drawn.
  const graph = useMemo(() => foldGraph(own, folds), [own, folds])
  const auto = useMemo(() => layoutGraph(graph.nodes, graph.edges), [graph.nodes, graph.edges])
  // The talk line whose words are shown, by its edge's id: it and its two agents stay lit (K-canvas-dili) - while the
  // selection it was picked under stands: another, made here or elsewhere, ends it.
  const [talk, setTalk] = useState<{ line: string; under: string | null } | null>(null)
  const talkLine = talk?.under === selectedId ? talk.line : null
  // K-shared-bagli: a card, or a team's frame, picked: it, its team and its line stay lit - as a talk line does.
  const [light, setLight] = useState<{ id: string; under: string | null } | null>(null)
  const lightId = light?.under === selectedId ? light.id : null
  const selectedNow = useRef(selectedId)
  useEffect(() => {
    selectedNow.current = selectedId
  })
  // Only nodes the user dragged keep a position of their own; the rest follow the layout.
  // (Inside a box a position is counted from the box's corner, so a box that is moved
  // takes what is inside it along.) A node belongs to one turn, so each turn keeps its own.
  // Kept only while the layout still puts the node where it stood when dragged: a click that moved a card a pixel pinned
  // it, and once a round folded above it, it stood under, then out of, its frame (5 Nov).
  // shortcut: a card dragged on purpose goes back too once the layout moves it; keep it by an offset if that is missed.
  const [pins, setPins] = useState<Record<string, { from?: Positions[string]; to: Positions[string] }>>({})
  const dragged = (id: string) => {
    const [pin, at] = [pins[id], auto.positions[id]]
    return pin?.from && at && pin.from.x === at.x && pin.from.y === at.y ? pin.to : undefined
  }
  // (Where a node was dragged, its lines that go round follow it.)
  const round = useMemo(() => {
    const moved = Object.entries(pins).flatMap(([id, pin]) => {
      const at = auto.positions[id]
      return pin.from && at && pin.from.x === at.x && pin.from.y === at.y ? [[id, pin.to] as const] : []
    })
    return roundLines(graph, { ...auto, positions: { ...auto.positions, ...Object.fromEntries(moved) } })
  }, [graph, auto, pins])
  // What React Flow measured each node to be. The nodes are rebuilt from the records on
  // every render, and a node handed back without its size is hidden until measured again.
  const [sizes, setSizes] = useState<Sizes>({})
  const flow = useRef<ReactFlowInstance | null>(null)
  const userMoved = useRef(false)
  const container = useRef<HTMLDivElement>(null)
  // A node selected from elsewhere that the view still has to go to; and what was
  // selected by a click on the canvas itself, which the view does not move for.
  const centre = useRef<string | null>(null)
  const clicked = useRef<string | null>(null)
  // The node the view was last sent to, until the user moves the view themselves.
  const sent = useRef<string | null>(null)

  // The node that is selected, while it is a node of the turn drawn: the one to keep in view.
  const selectedNode = useRef<string | null>(null)
  // How wide the stage has been at its widest since the window last changed size: narrower
  // than that, a panel is open beside it - which is no reason to draw the turn smaller.
  const full = useRef(0)
  const windowResized = useRef(false)
  // The stage is hidden (no width: the project's settings are shown over it), and whether a
  // fit was wanted meanwhile - new work came - to be made when it is shown again.
  const hidden = useRef(false)
  const fitMissed = useRef(false)

  const stageSize = useCallback((): Size | null => {
    const el = container.current
    return el ? { width: el.clientWidth, height: el.clientHeight } : null
  }, [])
  /** Where a node of the turn is and how big, in the turn's own measure; null while it is not drawn or laid out. */
  const rectOf = useCallback((id: string | null): Rect | null => {
    const node = id ? flow.current?.getInternalNode(id) : undefined
    if (!node?.measured.width || !node.measured.height) return null
    return { ...node.internals.positionAbsolute, width: node.measured.width, height: node.measured.height }
  }, [])
  /** The nodes at work, taken together: kept in view as the stage changes; null while none is. */
  const running = useCallback((): Rect | null => {
    const nodes = (flow.current?.getNodes() ?? []).filter(node => atWork(node.data) && node.measured?.width)
    return nodes.length > 0 ? (flow.current?.getNodesBounds(nodes) ?? null) : null
  }, [])
  /** The part of the stage the turn is drawn in: all of it but what the chat covers. */
  const roomIn = useCallback((stage: Size): Rect => freePart(stage, lyingOver(container.current, CHAT)), [])
  /** Every node of the turn, taken together; null while there is none, or one is not laid out yet. */
  const turnBounds = useCallback((): Rect | null => {
    const nodes = flow.current?.getNodes() ?? []
    if (nodes.length === 0 || nodes.some(node => !node.measured?.width)) return null
    return flow.current?.getNodesBounds(nodes) ?? null
  }, [])

  // Till when the view is on its way to a fit: read on the way, it is neither kept nor moved from (84b2 - the follow of the
  // nodes at work read a zoom half way and kept it, the Ready for you it fitted off the stage). A settle asked for meanwhile
  // is made once it is there (`later`).
  const fitting = useRef(0)
  const later = useRef(0)
  useEffect(() => () => window.clearTimeout(later.current), [])
  /**
   * Take the whole turn into view, beside the chat. On the stage at its full width with the
   * chat out of the way that is React Flow's own fit; on one a panel has narrowed the turn is
   * drawn no smaller than it would be there.
   */
  const fit = useCallback(() => {
    const instance = flow.current
    if (!instance) return
    const stage = stageSize()
    if (!stage) return
    if (!stage.width) return void (fitMissed.current = true)
    const room = roomIn(stage)
    if (stage.width >= full.current && room.width === stage.width && room.height === stage.height) {
      fitting.current = performance.now() + FIT_MS
      return void instance.fitView({ duration: FIT_MS, maxZoom: FIT_MAX_ZOOM })
    }
    let tries = 0
    const narrowed = () => {
      const [around, bounds] = [stageSize(), turnBounds()]
      if (!around?.width) return
      // Not laid out yet: it was drawn a moment ago.
      if (!bounds) return void (tries++ < 30 && requestAnimationFrame(narrowed))
      const part = roomIn(around)
      // (As wide as that part would be on the stage at its full width.)
      const ready = instance.getNodes().find(node => node.type === 'ready')
      const view = fitNarrowed(bounds, part, part.width + full.current - around.width, rectOf(selectedNode.current) ?? running(), rectOf(ready?.id ?? null))
      fitting.current = performance.now() + FIT_MS
      void instance.setViewport(view, { duration: FIT_MS })
    }
    narrowed()
  }, [stageSize, turnBounds, rectOf, running, roomIn])
  /**
   * A panel opened or closed beside the stage, the chat grew or shrank over it, or a window
   * opened over it: with none selected, and the view not the user's own, the turn is kept
   * centred beside the chat; the selected node and the nodes at work are kept in view,
   * clear of what lies over the stage - the zoom stays unless they do not fit, and then
   * goes out only as far as that needs (keepWork).
   */
  const settle = useCallback(
    function settleNow(onlySelected = false) {
      const wait = fitting.current - performance.now()
      if (wait > 0) {
        window.clearTimeout(later.current)
        later.current = window.setTimeout(() => settleNow(onlySelected), wait)
        return
      }
      const [instance, stage] = [flow.current, stageSize()]
      if (!instance || !stage?.width) return
      const view = instance.getViewport()
      const node = rectOf(selectedNode.current)
      const bounds = node || onlySelected || userMoved.current ? null : turnBounds()
      const centred = bounds ? centredOn(bounds, roomIn(stage), view.zoom) : view
      // B-149: with the nodes at work, those always worth seeing - a night's report, Ready for you - stay in view.
      const kept = instance.getNodes().filter(one => (atWork(one.data) || one.type === 'away' || one.type === 'ready') && one.measured?.width)
      const next = keepWork(centred, stage, node, kept.length > 0 ? instance.getNodesBounds(kept) : null, lyingOver(container.current))
      // (Straight there: the smooth way draws back a little on its way, and the zoom is to stay.)
      if (next !== view) void instance.setViewport(next, { duration: 200, interpolate: 'linear' })
    },
    [stageSize, turnBounds, rectOf, roomIn],
  )
  /** Put a node in the middle of the canvas beside the chat; false while it is not laid out yet. */
  const goTo = useCallback(
    (id: string): boolean => {
      const [instance, node, stage] = [flow.current, rectOf(id), stageSize()]
      if (!instance || !node || !stage?.width) return false
      // (In the middle of what the chat leaves free.)
      void instance.setViewport(centredOn(node, roomIn(stage), Math.max(instance.getZoom(), CENTRE_ZOOM)), { duration: 200 })
      return true
    },
    [rectOf, stageSize, roomIn],
  )

  // "Follow running": the nodes at work are kept in view as they change - until the user moves the view themselves.
  const [follow, setFollow] = useState(true)
  const working = graph.nodes.filter(n => atWork(n.data)).map(n => n.id).join(' ')
  useEffect(() => {
    if (!follow || !working) return
    // (They are drawn and measured a frame from now.)
    const frame = requestAnimationFrame(() => {
      const [instance, stage, work] = [flow.current, stageSize(), running()]
      if (!instance || !stage?.width || !work || performance.now() < fitting.current) return
      const view = instance.getViewport()
      const next = keepWork(view, stage, rectOf(selectedNode.current), work, lyingOver(container.current))
      if (next !== view) void instance.setViewport(next, { duration: 200 })
    })
    return () => cancelAnimationFrame(frame)
  }, [follow, working, stageSize, running, rectOf])
  const { open: legendOpen, setOpen: openLegend, close: closeLegend, button: legendButton, panel: legendPanel } = usePanel()
  // The turn's timeline, a strip under the canvas (slice 44): closed until opened, then kept so.
  const [timelineOpen, setTimelineOpen] = useState(storedTimeline)
  const timelineButton = useRef<HTMLButtonElement>(null)
  const showTimeline = (open: boolean) => {
    setTimelineOpen(open)
    try {
      localStorage.setItem(TIMELINE_KEY, open ? '1' : '0')
    } catch {
      // it just is not kept
    }
  }

  const nodeCount = graph.nodes.length
  // How far the turn reaches, as laid out: it grows with no node added too - a team's frame widening round its agents
  // pushes "Ready for you" right (slice 84b-2).
  const reach = useMemo(() => {
    const inside = new Set(graph.nodes.filter(n => n.parent).map(n => n.id))
    return Object.entries(auto.positions)
      .filter(([id]) => !inside.has(id))
      // (As measured where the layout does not size it: Ready for you grows wide once its teams are at their end.)
      .reduce((far, [id, at]) => Math.max(far, at.x + (auto.sizes[id]?.width ?? sizes[id]?.width ?? NODE_W)), 0)
  }, [graph.nodes, auto, sizes])
  useEffect(() => {
    // Keep new work in view until the user takes over the viewport.
    if (nodeCount > 0 && !userMoved.current && !centre.current) requestAnimationFrame(fit)
  }, [nodeCount, reach, fit])
  useEffect(() => {
    // A file of the shared folder read later makes a card taller: in view with it (S5).
    if (sharedFiles.length && !userMoved.current && !centre.current) requestAnimationFrame(fit)
  }, [sharedFiles.length, fit])

  useEffect(() => {
    // Another turn is drawn: it is fitted, wherever the view was left on the one before.
    userMoved.current = false
    if (current && !centre.current) requestAnimationFrame(fit)
  }, [current, fit])

  useEffect(() => {
    // The stage narrows when the inspector opens: the turn is not drawn smaller for that. It
    // is fitted anew only when the window itself changed size, or the stage is wider than it
    // has been.
    const el = container.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const onWindow = () => {
      windowResized.current = true
      // (Whoever watches the stage hears of it within this frame; after that it is a panel again.)
      requestAnimationFrame(() => requestAnimationFrame(() => (windowResized.current = false)))
    }
    const observer = new ResizeObserver(() => {
      const stage = stageSize()
      if (!stage) return
      // Hidden: nothing is measured against a stage of no size; the view stays as it was.
      if (!stage.width) return void (hidden.current = true)
      if (hidden.current) {
        // Shown again: new work that came meanwhile is taken into view, unless the view is the user's own.
        hidden.current = false
        full.current = Math.max(full.current, stage.width)
        const missed = fitMissed.current
        fitMissed.current = false
        if (missed && !userMoved.current) fit()
        else settle()
        return
      }
      const anew = windowResized.current || stage.width > full.current
      full.current = windowResized.current ? stage.width : Math.max(full.current, stage.width)
      windowResized.current = false
      // A node the view was sent to stays in the middle of what is left of the stage.
      if (sent.current) goTo(sent.current)
      else if (!anew) settle()
      else if (!userMoved.current) fit()
    })
    observer.observe(el)
    // The chat over the stage, opened, closed or made taller - or the view panel beside it: what they cover changed.
    const stage = el.closest('.stage')
    for (const over of Array.from(stage?.querySelectorAll('.chat, .view-panel') ?? [])) observer.observe(over)
    // Moved, a window is no bigger: it says so itself (shell/move.ts), and what it covers changed.
    const onMoved = () => (sent.current ? goTo(sent.current) : settle())
    stage?.addEventListener(MOVED, onMoved)
    window.addEventListener('resize', onWindow)
    return () => {
      observer.disconnect()
      stage?.removeEventListener(MOVED, onMoved)
      window.removeEventListener('resize', onWindow)
    }
  }, [fit, goTo, settle, stageSize])

  useEffect(() => {
    // A window opened over the stage: a selected node under it is moved out from under it.
    if (!over) return
    // (It is on the page a frame from now.)
    const frame = requestAnimationFrame(() => settle(true))
    return () => cancelAnimationFrame(frame)
  }, [over, settle])

  useEffect(() => {
    // Nodes used to be expanded in place, and which ones was kept here: nothing reads it now.
    try {
      if (conversationId) localStorage.removeItem(`koloni-canvas-expanded:${conversationId}`)
    } catch {
      // storage is closed to the page
    }
  }, [conversationId])

  const remember = useCallback(
    (change: (folds: Folds) => Folds) =>
      setFolds(prev => {
        const next = change(prev)
        if (next !== prev && conversationId) writeFolds(conversationId, next)
        return next
      }),
    [conversationId],
  )

  // What is selected - here, in the chat, in the inspector or in an agent's window - is
  // drawn: the canvas goes to its turn, the closed boxes around it open, and the view goes
  // to it. Once per selection: the user can pick another turn, or close the box again,
  // without it springing back.
  // (A call, a command or a file is drawn as its agent: none is a node of its own - the user's, 5 Nov.)
  const shown = selectedId ? nodeOf(whole, agentOf(state, selectedId)) : undefined
  useEffect(() => {
    selectedNode.current = shown && shown.runId === current ? shown.id : null
  })
  const revealed = useRef<string | null>(null)
  useEffect(() => {
    if (!selectedId) revealed.current = null
    // (Not a node yet, perhaps: its records may still be on their way.)
    if (!selectedId || !shown || revealed.current === selectedId) return
    revealed.current = selectedId
    if (shown.runId !== current) onTurn?.(shown.runId)
    remember(prev => unfold(oneTurn(whole, shown.runId), prev, shown.id))
    if (clicked.current !== selectedId) centre.current = shown.id
    clicked.current = null
  }, [selectedId, shown, whole, current, onTurn, remember])

  useEffect(() => {
    const id = centre.current
    if (!id || !graph.nodes.some(n => n.id === id)) return
    let tries = 0
    let frame = 0
    const go = () => {
      if (!goTo(id)) {
        // Not laid out yet: it was drawn a moment ago.
        if (tries++ < 30) frame = requestAnimationFrame(go)
        return
      }
      centre.current = null
      sent.current = id
      userMoved.current = true // the view is where it was sent; new work does not pull it away
      setFollow(false)
    }
    frame = requestAnimationFrame(go)
    return () => cancelAnimationFrame(frame)
  })

  const toggle = useCallback(
    (nodeId: string) => {
      const node = graph.nodes.find(n => n.id === nodeId)
      if (node && isGroup(node)) remember(prev => ({ ...prev, [nodeId]: !(node.data as GroupData).open }))
      // (An output card: unfolded, or folded again - K-belge-ciktilari.)
      else if (node?.kind === 'shared') remember(prev => ({ ...prev, [nodeId]: !prev[nodeId] }))
    },
    [graph.nodes, remember],
  )
  // The groups of the turn that is drawn, with something inside.
  const foldable = Object.keys(foldAll(own, true)).length > 0
  const pick = useCallback(
    (runId: string) => {
      userMoved.current = false
      centre.current = null
      sent.current = null
      if (runId === current) fit()
      onTurn?.(runId)
    },
    [current, fit, onTurn],
  )
  const actions = useMemo<Actions>(
    () => ({
      openList: () => onOpenList?.(),
      stopTeam: async teamId => onStopTeam?.(teamId),
      finishTeam: async teamId => onFinishTeam?.(teamId),
      showTalk: line => setTalk({ line, under: selectedNow.current }),
      light: id => setLight({ id, under: selectedNow.current }),
      openMemory: () => onOpenNode?.('memory', ''),
      openTodo: () => onOpenNode?.('backlog', ''),
    }),
    [onOpenNode, onOpenList, onStopTeam, onFinishTeam],
  )
  const selectHere = useCallback(
    (id: string) => {
      clicked.current = id
      onSelect(id)
    },
    [onSelect],
  )

  // K-canvas-dili (W): the frame a node is drawn in - its own, or its box's - and where the layout put a node.
  const byId = new Map(graph.nodes.map(n => [n.id, n]))
  const frameOf = (id: string): string | undefined => byId.get(id)?.team ?? (byId.get(id)?.parent ? frameOf(byId.get(id)!.parent!) : undefined)
  const rect = (id: string) => ({ ...(auto.positions[id] ?? { x: 0, y: 0 }), ...(auto.sizes[id] ?? { width: NODE_W, height: NODE_H }) })
  // The discussions' lane, where it stands; and a height above the whole turn, for a line from an agent with no frame.
  const lane = Math.min(...graph.edges.filter(e => e.member).map(e => rect(e.target).x))
  const above = Math.min(...graph.nodes.filter(n => !n.parent && auto.positions[n.id]).map(n => rect(n.id).y)) - DOOR_PAD / 2
  /** How a line of a team's frame, its door or a line across is drawn (`edges.tsx`); any other as React Flow draws it. */
  const lineOf = (e: GraphEdge): Partial<Edge> => {
    const [from, to] = [frameOf(e.source) ?? (e.work ? e.source : undefined), frameOf(e.target)]
    const [s, t] = [rect(e.source), rect(e.target)]
    const data: LineData = { messages: e.messages, last: e.last }
    // To a discussion in the lane: from the member's frame (or over the turn), down the gap left of the lane.
    if (e.member) {
      const framed = frameOf(e.source)
      return { type: 'member', data: { points: memberLine(rect(framed ?? e.source), !!framed, dragged(e.target) ?? t, above) } }
    }
    // Round the cards and headers: talk across two frames, a frame's line that would run under a card.
    const way = round[e.id]
    if (way) return { type: 'member', source: way.source, target: way.target, sourceHandle: null, targetHandle: null, data: { ...data, points: way.points, at: way.at } }
    // K-shared-bagli: to its card, where the layout found it room - else none.
    if (e.shared) return auto.lines[e.id] ? { type: 'level', data: { line: auto.lines[e.id], colour: e.shared.colour, arm: !!e.shared.arm } } : { hidden: true }
    // A request between teams: frame to frame in the gap, past every other box (K-takimlar-arasi).
    if (e.request) {
      const others = graph.nodes.filter(n => !n.parent && n.id !== e.source && n.id !== e.target && auto.positions[n.id]).map(n => rect(n.id))
      const line = requestLine(s, t, others, requestFrom(e, graph.edges))
      return line ? { type: 'request', sourceHandle: 'door-out', targetHandle: 'door-in', data: { line, label: e.request.label, title: e.request.title, open: e.request.open } } : { hidden: true }
    }
    // Into a frame: at its door - the line of the agent that opens its team, and any line from outside (`framed`).
    if (byId.get(e.target)?.kind === 'team') return { type: 'lane', targetHandle: 'door-in', data: { ...data, findings: e.findings } }
    // A frame's line to Ready for you: up or down on a bus right of every frame, not over another frame - left of the
    // discussions' lane where there is one, then over it into Ready (layout.ts).
    if (byId.get(e.target)?.kind === 'ready') return { type: 'lane', data: { bus: lane < Infinity ? lane - DOOR_PAD / 2 : undefined } }
    // B-133: talk between agents framed by no team is its bubble too (count, pair colour, who, a click) - not "2 messages".
    if (!from && !to && e.talk && e.messages) return { type: 'lane', data }
    if (!from || from !== to) return {}
    // Findings back, and talk between two of its agents: on an arc over or under the work line, in the room the layout
    // left in the frame - never under a card (the user, 6 Nov).
    if (arced(e)) {
      const { source, target, turned, band, ring, into } = arcWay(e, graph.nodes, graph.edges, rect, frameOf)
      return { type: 'arc', source, target, sourceHandle: null, targetHandle: { top: 'found-in', foot: 'up-in', side: null }[into], data: { ...data, findings: e.findings, band, ring, turned } }
    }
    if (e.source === from) return { type: 'lane', sourceHandle: 'door-out', data }
    if (stacked(s, t)) return { type: 'lane', data, ...(t.y > s.y ? { sourceHandle: 'found-out', targetHandle: 'found-in' } : { sourceHandle: 'up-out', targetHandle: 'up-in' }) }
    // (Talk with an agent of an earlier column is drawn from that one.)
    return { type: 'lane', data, ...(t.x < s.x && { source: e.target, target: e.source }) }
  }
  // What is lit: the talk line whose words are shown, or the agent selected and its lines; the rest fades (W).
  // (A line of another turn's is not on this one.)
  const talkEdge = talkLine ? graph.edges.find(e => e.id === talkLine) : undefined
  const focus = talkEdge?.id ?? (lightId && byId.has(lightId) ? lightId : null) ?? (shown?.kind === 'agent' || shown?.kind === 'discussion' ? shown.id : null)
  // (A frame picked lights its own line to its card, not a request to another team's: N4.)
  const frameLit = focus === lightId && byId.get(focus ?? '')?.kind === 'team'
  const lit = focus ? graph.edges.filter(e => (frameLit ? e.source === focus && e.shared : e.id === focus || e.source === focus || e.target === focus)) : null
  // (A team lit by its card, or its frame picked: its agents too.)
  const litTeams = new Set(focus === lightId && lit ? [focus, ...lit.map(e => e.source)] : [])
  const litNodes = lit && new Set([focus!, ...lit.flatMap(e => [e.source, e.target]), ...graph.nodes.filter(n => n.team && litTeams.has(n.team)).map(n => n.id)])
  const faded = (id: string): boolean => {
    const node = byId.get(id)
    return !!litNodes && !litNodes.has(id) && !(node?.parent && !faded(node.parent))
  }
  // A dashed box round the agents of a team's steps at once, as the frame draws it: from the frame's corner.
  const atOnce = (frame: GraphNode) =>
    (frame.data as TeamData).columns.flatMap(({ ids, atOnce }) => {
      const drawn = ids.filter(id => auto.positions[id]).map(rect)
      if (!atOnce || drawn.length === 0) return []
      const [corner, x, y] = [rect(frame.id), Math.min(...drawn.map(b => b.x)) - AT_ONCE_PAD, Math.min(...drawn.map(b => b.y)) - AT_ONCE_HEAD]
      const [right, bottom] = [Math.max(...drawn.map(b => b.x + b.width)) + AT_ONCE_PAD, Math.max(...drawn.map(b => b.y + b.height)) + AT_ONCE_PAD]
      return [{ left: x - corner.x, top: y - corner.y, width: right - x, height: bottom - y }]
    })
  // A box is as big as the layout made it; any other node is what was measured, or about a node's.
  const sizeOf = (id: string) =>
    auto.sizes[id] ?? sizes[id] ?? { width: NODE_W, height: NODE_H }
  const nodes: Node[] = graph.nodes.map(n => {
    const sized = auto.sizes[n.id]
    const placed = dragged(n.id) ?? auto.positions[n.id] ?? { x: 0, y: 0 }
    const within = n.parent ? auto.sizes[n.parent] : undefined
    return {
      id: n.id,
      type: n.kind,
      // A box may have become smaller since a node inside it was dragged.
      position: within
        ? keepInside(placed, sizeOf(n.id), within, FILES_HEAD)
        : placed,
      data: n.kind === 'team' ? { ...n.data, boxes: atOnce(n) } : { ...n.data },
      // A box the layout sized is exactly that big; nothing waits to be measured.
      measured: sized ?? sizes[n.id],
      ...(sized && { width: sized.width, height: sized.height }),
      // A box is dragged by its header: the nodes inside it are dragged on their own.
      ...(isGroup(n) && { dragHandle: '.group-head' }),
      // Inside its box, and never dragged out of it.
      ...(n.parent && { parentId: n.parent, extent: 'parent' as const }),
      // A team's frame is drawn behind its agents' boxes, which stand on their own (slice 84b-2): it is not moved. A card
      // stands by its team, and is lit, not selected (K-shared-bagli).
      ...(n.kind === 'team' && { zIndex: -1, draggable: false, selectable: false, focusable: false }),
      ...((n.kind === 'shared' || n.kind === 'round') && { draggable: false, selectable: false, focusable: false }),
      // One call that is selected shows on the tool node that lists it.
      selected: n.id === shown?.id,
      // An agent or a talk line picked: what is not its fades, its frame a little.
      ...(faded(n.id) && { className: n.kind === 'team' ? 'canvas-dim' : 'canvas-faded' }),
    }
  })
  // Who said what on what is lit (W's box): to and from the agent picked, or on the talk line - one of a frame's door,
  // between the agent outside and the frame's agents. Null while neither is.
  const endsOf = (id: string) => new Set(byId.get(id)?.kind === 'team' ? graph.nodes.flatMap(n => (n.team === id && n.agentId ? [n.agentId] : [])) : [byId.get(id)?.agentId ?? ''])
  const said =
    state && (talkEdge || shown?.kind === 'agent')
      ? (() => {
          const [a, b] = talkEdge ? [endsOf(talkEdge.source), endsOf(talkEdge.target)] : [endsOf(shown!.id), null]
          const meets = (one: string, other: string) => a.has(one) && (!b || b.has(other))
          return state.channelMessages
            .filter(m => SAID.has(m.kind) && (meets(m.from_agent_id, m.to_agent_id) || meets(m.to_agent_id, m.from_agent_id)))
            .slice(-SAID_LINES)
        })()
      : null
  const nameOf = (agentId: string) => {
    const agent = state?.agents.find(a => a.id === agentId)
    return agent ? agent.name || agent.role_name : 'an agent'
  }
  const frames = graph.nodes.filter(n => n.kind === 'team')
  const framesOpen = frames.some(n => (n.data as GroupData).open)
  // Who talked with whom: each pair of ends its own colour, on its line and its 💬 (the user, 27 Oct).
  const pairOf = (e: GraphEdge) => [e.source, e.target].sort().join('|')
  const talkHues = talkColours([...new Set(graph.edges.filter(e => e.talk && e.messages).map(pairOf))])
  const whoOf = (id: string) => {
    const node = byId.get(id)
    return node?.kind === 'team' ? (node.data as TeamData).team : nameOf(node?.agentId ?? '')
  }
  const edges: Edge[] = graph.edges.filter(e => !e.plan).map(e => {
    const drawn = lineOf(e)
    const talking = !!e.talk && !!e.messages && !!drawn.type
    const talkHue = e.talk && e.messages ? talkHues.get(pairOf(e)) : undefined
    const colour = e.shared ? e.shared.colour : e.request ? 'var(--request)' : e.findings !== undefined ? 'var(--warn)' : talkHue ?? (talking ? 'var(--tool-team)' : e.active || e.handed ? 'var(--accent)' : 'var(--border-strong)')
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      className: [e.waits && 'edge-waits', e.findings !== undefined && 'edge-findings', e.handed && 'edge-handed', lit && (lit.includes(e) ? 'edge-lit' : 'edge-faded')].filter(Boolean).join(' ') || undefined,
      // Findings handed on: from under the box that found them to the top of the one given them.
      ...(e.findings !== undefined && { sourceHandle: 'found-out', targetHandle: 'found-in' }),
      ...drawn,
      // (Its label, drawn apart from the line, fades with it.)
      ...(drawn.type && {
        data: { ...drawn.data, faded: !!lit && !lit.includes(e), ...(talkHue && { colour: talkHue, who: `${whoOf(e.source)} ↔ ${whoOf(e.target)}` }) },
      }),
      animated: e.active,
      // (Drawn by its own line where it is one of edges.tsx's.)
      label: drawn.type
        ? undefined
        : e.messages
          ? `${e.messages} message${e.messages > 1 ? 's' : ''}`
          : e.findings !== undefined
            ? `${e.findings} finding${e.findings === 1 ? '' : 's'}`
            : undefined,
      // (a findings label in its line's colour: between two boxes close together, the label is most of the line)
      labelStyle: { fill: e.findings !== undefined ? 'var(--warn)' : 'var(--muted)', fontSize: 'var(--text-kicker)' },
      // The canvas's own background (there is no --canvas: that drew the label on black).
      labelBgStyle: { fill: 'var(--bg)' },
      // Which way the work, the findings and the talk go, in a team's frame.
      ...(drawn.type && drawn.type !== 'level' && { markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: colour } }),
      style: {
        // Findings handed on from the agent that found them: a dashed line in the warn colour. A file handed to an
        // agent (slice 85b): dashed, in the accent. Talk in a team's frame, or across to another: in the team colour of
        // the canvas's legend, dotted.
        stroke: colour,
        strokeWidth: lit?.includes(e) ? 3 : e.shared?.arm ? 1.2 : e.active || talking || e.shared ? 2 : e.waits ? 1 : 1.5,
        ...(talking && { strokeLinecap: 'round' as const }),
        // A hand-off to a sub-agent reads differently from an agent's own output.
        // A member's line to its discussion or room: a finer, dotted line. An agent that waits for a file another
        // holds: a thin dashed line to that agent, for as long as it waits. To a card: a team's line plain, an
        // agent's (no team) and a contract's arm dotted.
        strokeDasharray: e.shared ? (e.shared.dotted || e.shared.arm ? DASH.shared : undefined) : e.request?.open ? DASH.request : e.request ? undefined : talking ? DASH.talkLine : e.handed ? DASH.handed : e.findings !== undefined ? DASH.findings : e.waits ? DASH.waits : e.talk ? DASH.talk : e.spawn ? DASH.spawn : undefined,
      },
    }
  })
  edges.push(...graph.edges.filter(e => e.plan).map(e => ({ ...planLine(e), className: lit && !lit.includes(e) ? 'edge-faded' : undefined })))

  function onNodesChange(changes: NodeChange[]) {
    for (const change of changes) {
      if (change.type === 'position' && change.position) {
        const { id, position } = change
        setPins(prev => ({ ...prev, [id]: { from: auto.positions[id], to: position } }))
      } else if (change.type === 'dimensions' && change.dimensions) {
        const { id, dimensions } = change
        setSizes(prev => ({ ...prev, [id]: dimensions }))
      }
    }
  }

  return (
    <div className="canvas">
      {turnsIn &&
        createPortal(
          <TurnList rows={rows} current={current} onPick={pick} conversationId={conversationId} topic={topic} onRename={onRenameTopic} />,
          turnsIn,
        )}
      <div
        className="canvas-flow"
        ref={container}
        onKeyDownCapture={event => {
          // Esc puts away the words of a talk line first; in the box of what was said, it and the pick.
          if (event.key === 'Escape' && (talkLine || (event.target as Element).closest('.canvas-said'))) {
            event.stopPropagation()
            setTalk(null)
            if (!talkLine) onSelect(null)
            return
          }
          // Esc on a node while something is selected closes the inspector, the focus staying on
          // the node (38b). Taken here: React Flow's own Esc would take the focus off it a frame later.
          if (event.key !== 'Escape' || !selectedId || !(event.target as Element).closest('.react-flow__node')) return
          event.stopPropagation()
          onSelect(null)
        }}
      >
        <ToggleGroup.Provider value={toggle}>
          <NodeActions.Provider value={actions}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              onInit={instance => {
                flow.current = instance
                // The first fit is the canvas's own, not React Flow's: it leaves out what the chat covers.
                if (!userMoved.current && !centre.current) requestAnimationFrame(fit)
              }}
              onNodesChange={onNodesChange}
              onNodeClick={(_, node) => {
                const source = graph.nodes.find(n => n.id === node.id)
                // (A frame's header's own buttons do what they do; the frame itself, or a card, lights the two: K-shared-bagli.)
                if (source?.kind === 'team' || source?.kind === 'shared') return setLight({ id: node.id, under: selectedNow.current })
                if (source?.kind === 'round') return // (its line's own button opens and folds it)
                setTalk(null)
                setLight(null)
                // A closed box with something waiting for the user inside opens at one click.
                if (source && isGroup(source)) {
                  const { open, attention } = source.data as GroupData
                  if (!open && attention) toggle(source.id)
                }
                selectHere(node.id)
              }}
              onNodeDoubleClick={(_, node) => {
                const source = graph.nodes.find(n => n.id === node.id)
                if (source) onOpenNode?.(source.kind, source.refId)
              }}
              onPaneClick={() => {
                setTalk(null)
                setLight(null)
                onSelect(null)
              }}
              onMoveStart={event => {
                if (!event) return // the canvas moved itself
                userMoved.current = true
                sent.current = null
                setFollow(false)
              }}
              nodesConnectable={false}
              deleteKeyCode={null}
              minZoom={MIN_ZOOM}
              maxZoom={MAX_ZOOM}
              proOptions={{ hideAttribution: true }}
            >
              <Background variant={BackgroundVariant.Dots} gap={20} color="var(--canvas-dot)" />
              {/* The zoom buttons move the view as a pan does: the canvas no longer follows the agents at work. At the
                  bottom right (slice 66): the open chat, at the left, covered them at the top left. The turn is drawn clear
                  of them (CHAT); the Workspace window ends left of them (base.css), a toast stands beside them (Toasts). */}
              <Controls showInteractive={false} showFitView={false} position="bottom-right" onZoomIn={() => setFollow(false)} onZoomOut={() => setFollow(false)}>
                {/* The canvas's own fit, not React Flow's: it leaves out what the chat covers. */}
                <ControlButton
                  className="react-flow__controls-fitview"
                  title="Fit View"
                  aria-label="Fit View"
                  onClick={() => {
                    userMoved.current = false
                    centre.current = null
                    sent.current = null
                    fit()
                  }}
                >
                  <CornersOut />
                </ControlButton>
                <ControlButton
                  title="Follow running: keep the agents at work in view"
                  aria-label="Follow running"
                  aria-pressed={follow}
                  onClick={() => setFollow(on => !on)}
                >
                  <Crosshair />
                </ControlButton>
                {/* (React Flow's ControlButton takes no ref: the same button, drawn here.) */}
                <button
                  ref={legendButton}
                  type="button"
                  className="react-flow__controls-button"
                  title="What the colours, lines and signs mean"
                  aria-label="Canvas legend"
                  aria-expanded={legendOpen}
                  onClick={() => (legendOpen ? closeLegend() : openLegend(true))}
                >
                  <Question />
                </button>
                <button
                  ref={timelineButton}
                  type="button"
                  className="react-flow__controls-button"
                  title="Timeline: the agents of this message’s work in time"
                  aria-label="Timeline"
                  aria-expanded={timelineOpen}
                  aria-controls="timeline"
                  onClick={() => showTimeline(!timelineOpen)}
                >
                  <ChartBarHorizontal />
                </button>
                {foldable && (
                  <>
                    <ControlButton
                      title="Collapse all"
                      aria-label="Collapse all"
                      onClick={() => remember(prev => ({ ...prev, ...foldAll(own, false) }))}
                    >
                      <ArrowsInSimple />
                    </ControlButton>
                    <ControlButton
                      title="Expand all"
                      aria-label="Expand all"
                      onClick={() => remember(prev => ({ ...prev, ...foldAll(own, true) }))}
                    >
                      <ArrowsOutSimple />
                    </ControlButton>
                  </>
                )}
              </Controls>
              {/* (Only where something was said: picking an agent that said nothing fades the rest, and that is all.) */}
              {said && said.length > 0 && (
                <SaidBox
                  {...saidSide()}
                  title={talkEdge ? `${whoOf(talkEdge.source)} ↔ ${whoOf(talkEdge.target)}` : `What ${whoOf(shown!.id)} said and was told`}
                  said={said}
                  nameOf={nameOf}
                  // (Its pair's colour: the line's it was said on - the agents', or the talk line's picked.)
                  colourOf={m => talkHues.get([`agent:${m.from_agent_id}`, `agent:${m.to_agent_id}`].sort().join('|')) ?? (talkEdge && talkHues.get(pairOf(talkEdge))) ?? 'var(--accent)'}
                  // (The talk line's far end, or those who talked with the agent picked, on the left; the other on the right.)
                  right={m => (talkEdge ? !endsOf(talkEdge.source).has(m.from_agent_id) : m.from_agent_id === shown?.agentId)}
                  // (As a click on the empty canvas: the talk and the pick put away.)
                  onClose={() => {
                    setTalk(null)
                    onSelect(null)
                  }}
                />
              )}
              {/* R52: every team's frame folded to its one line, or opened again. */}
              {frames.length > 0 && (
                <Panel position="bottom-right" className="canvas-fold-all">
                  <button type="button" className="btn btn-small" onClick={() => remember(prev => ({ ...prev, ...Object.fromEntries(frames.map(n => [n.id, !framesOpen])) }))}>
                    {framesOpen ? 'Fold all' : 'Open all'}
                  </button>
                </Panel>
              )}
            </ReactFlow>
          </NodeActions.Provider>
        </ToggleGroup.Provider>
        {graph.nodes.length === 0 && (
          <div className="canvas-empty muted">
            {state && rows.length === 0 && <EmptyBee />}
            {rows.length === 0 ? 'No message yet. Write one to start.' : 'Nothing of this message’s work is on record yet.'}
          </div>
        )}
      </div>
      {timelineOpen && state && current && (
        <TimelineStrip
          // (Another turn, another strip: no cost or time of the one before is said for it.)
          key={current}
          state={state}
          runId={current}
          onOpen={agentId => onOpenNode?.('agent', agentId)}
          onClose={() => {
            showTimeline(false)
            timelineButton.current?.focus()
          }}
        />
      )}
      {legendOpen && (
        <div ref={legendPanel} tabIndex={-1} className="allow-list-panel canvas-legend" role="dialog" aria-label="Canvas legend">
          <Legend />
        </div>
      )}
    </div>
  )
}
