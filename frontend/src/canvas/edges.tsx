import { BaseEdge, type Edge, EdgeLabelRenderer, type EdgeProps, Position, getSmoothStepPath } from '@xyflow/react'
import { useContext } from 'react'
import { DOOR_PAD, arcPath } from './layout'
import { NodeActions } from './toggleGroup'

/** What the canvas hands a line of a team's frame (K-canvas-dili). */
export type LineData = {
  /** Talk on it: how many messages, and the last thing said. */
  messages?: number
  last?: string
  /** Its pair's colour (`talkColours`), and who the two are: "Coder ↔ Tester". */
  colour?: string
  who?: string
  /** Findings handed back: how many. */
  findings?: number
  /** A findings arc: the height it goes over or under the work line at, inside its frame, and which band out it is. */
  band?: number
  ring?: number
  /** An arc drawn from the end it goes to (`arcWay`): its arrow at its start. */
  turned?: boolean
  /** Another agent or line is picked: its label and doors fade with it. */
  faded?: boolean
  /** A request between teams (K-takimlar-arasi): where its line runs (`requestLine`), its label, and whether it is at work. */
  line?: { x1: number; y1: number; x2: number; y2: number }
  label?: string
  /** Every request on it, in full: who asked whom for what, and how it stands. */
  title?: string
  open?: boolean
  /** K-shared-bagli: a contract's arm from its request's line - its door only at its card. */
  arm?: boolean
  /** A line to Ready for you: the bus it bends on, left of the discussions' lane where there is one. */
  bus?: number
  /** A line through corners: a member's to a discussion in the lane (`memberLine`), one round the cards (`route`). */
  points?: { x: number; y: number }[]
  /** Where its talk is said on it; none: half way along its longest leg. */
  at?: { x: number; y: number }
}
type Line = Edge<LineData>

/** Its talk, as said on it: how many messages (the last words on hover) - on an arc, with room, in words; a click shows who said what, and only its lines. */
function TalkLabel({ id, data, x, y, words = false }: { id: string; data: LineData; x: number; y: number; words?: boolean }) {
  const { showTalk } = useContext(NodeActions)
  return (
    <EdgeLabelRenderer>
      <button
        type="button"
        className={`edge-talk nodrag nopan${data.faded ? ' edge-faded' : ''}`}
        // (The words stay in the text colour: the pair's colour is on the border and the dot, never text to read.)
        style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`, ...(data.colour && { borderColor: data.colour }) }}
        title={[data.who, data.last && `the last: ${data.last}`].filter(Boolean).join(' · ') || undefined}
        aria-label={`${data.who ? `${data.who}: ` : ''}${data.messages} message${data.messages === 1 ? '' : 's'}${data.last ? `, the last: ${data.last}` : ''}`}
        onClick={event => {
          event.stopPropagation() // (not a click on the empty canvas)
          showTalk?.(id)
        }}
      >
        {data.colour && <span className="edge-talk-dot" style={{ background: data.colour }} aria-hidden="true" />}💬 {data.messages}
        {words && ` message${data.messages === 1 ? '' : 's'}`}
      </button>
    </EdgeLabelRenderer>
  )
}

/**
 * A line in a team's frame: from one column of its work line to the next, square, bent on the bus just left of the
 * column it goes to - so the lines into a step share one fork and the lines out of it one join; between two of one
 * column, straight up or down.
 */
export function LaneEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style, data }: EdgeProps<Line>) {
  // (From a frame's door, on its left edge: inward.)
  const from = sourcePosition === Position.Left ? Position.Right : sourcePosition
  const across = from === Position.Right && targetPosition === Position.Left
  const [path, x, y] = getSmoothStepPath({ sourceX, sourceY, sourcePosition: from, targetX, targetY, targetPosition, borderRadius: 8, ...(across && { centerX: data?.bus ?? targetX - DOOR_PAD / 2 }) })
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      {data?.messages && <TalkLabel id={id} data={data} x={x} y={y} />}
      {data?.findings !== undefined && <FindingsLabel data={data} x={x} y={y} />}
    </>
  )
}

/** How many findings a line carries, in its colour. */
function FindingsLabel({ data, x, y, back = false }: { data: LineData; x: number; y: number; back?: boolean }) {
  return (
    <EdgeLabelRenderer>
      <div className={`edge-arc nodrag nopan${data.faded ? ' edge-faded' : ''}`} style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}>
        {data.findings} finding{data.findings === 1 ? '' : 's'}
        {back && ' back'}
      </div>
    </EdgeLabelRenderer>
  )
}

/**
 * Findings handed back - a red arc out of the right of the agent that found them, up (or down) beside it, back over (or
 * under) the work line, and down (or up) into the one given them -, and talk between two agents of a frame, the same way
 * in its pair's colour: never across the line, nor under a card (`arcPath`).
 */
export function ArcEdge({ id, sourceX, sourceY, targetX, targetY, targetPosition, markerEnd, style, data }: EdgeProps<Line>) {
  const [band, mid] = [data?.band ?? Math.min(sourceY, targetY) - 40, (sourceX + targetX) / 2]
  const path = arcPath(sourceX, sourceY, targetX, targetY, band, data?.ring ?? 0, targetPosition === Position.Left)
  return (
    <>
      <BaseEdge id={id} path={path} {...(data?.turned ? { markerStart: markerEnd } : { markerEnd })} style={style} />
      {data?.messages && <TalkLabel id={id} data={data} x={mid} y={band} words />}
      {data?.findings !== undefined && <FindingsLabel data={data} x={mid} y={band} back />}
    </>
  )
}

/**
 * A request between teams (K-takimlar-arasi): one short line in the gap between the two frames, frame edge to frame edge -
 * dashed while it is at work, solid once it is answered - with its label on it. Where it runs is `requestLine`'s.
 */
export function RequestEdge({ id, markerEnd, style, data }: EdgeProps<Line>) {
  if (!data?.line) return null
  const { x1, y1, x2, y2 } = data.line
  // (Across, the gap is a column's: the label is held to it.)
  const most = x1 === x2 ? 260 : Math.abs(x2 - x1) - 8
  return (
    <>
      <BaseEdge id={id} path={`M ${x1} ${y1} L ${x2} ${y2}`} markerEnd={markerEnd} style={style} />
      <EdgeLabelRenderer>
        <div
          className={`edge-request nodrag nopan${data.open ? '' : ' edge-request-done'}${data.faded ? ' edge-faded' : ''}`}
          style={{ transform: `translate(-50%, -50%) translate(${(x1 + x2) / 2}px, ${(y1 + y2) / 2}px)`, maxWidth: most }}
          title={data.title ?? data.label}
        >
          {data.label}
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

/**
 * A line through its corners, square: a member's to a discussion in the lane (`memberLine`), and one round the cards and
 * headers (the user's, 5 Nov) - talk between two frames in the margin right of them (`crossTalk`), a frame's own line
 * that would run under a card (`laneLine`) -, with its talk on it.
 */
export function MemberEdge({ id, markerEnd, style, data }: EdgeProps<Line>) {
  const points = data?.points ?? []
  if (!points.length) return null
  const legs = points.slice(1).map((p, i) => [points[i], p] as const)
  const [p, q] = legs.reduce((a, b) => (Math.abs(b[1].x - b[0].x) + Math.abs(b[1].y - b[0].y) > Math.abs(a[1].x - a[0].x) + Math.abs(a[1].y - a[0].y) ? b : a))
  const at = data?.at ?? { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 }
  return (
    <>
      <BaseEdge id={id} path={points.map((p, i) => `${i ? 'L' : 'M'} ${p.x} ${p.y}`).join(' ')} markerEnd={markerEnd} style={style} />
      {data?.messages && <TalkLabel id={id} data={data} x={at.x} y={at.y} />}
    </>
  )
}

/**
 * K-shared-bagli: a team's line to its card - one short straight line from its frame's edge, a dot at
 * each end, in its colour - or a contract's thin arm from its request's line. Where it runs is the layout's.
 * (Filled, and small: hollow rings at both ends of so short a line read as a broken one - the user, 28 Oct.)
 */
export function LevelEdge({ id, style, data }: EdgeProps<Line>) {
  if (!data?.line) return null
  const { x1, y1, x2, y2 } = data.line
  const door = `edge-door${data.faded ? ' edge-faded' : ''}`
  const dot = { stroke: data.colour, fill: data.colour }
  return (
    <>
      <BaseEdge id={id} path={`M ${x1} ${y1} L ${x2} ${y2}`} style={style} />
      {!data.arm && <circle className={door} style={dot} cx={x1} cy={y1} r={3} />}
      <circle className={door} style={dot} cx={x2} cy={y2} r={3} />
    </>
  )
}
