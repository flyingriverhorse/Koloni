/**
 * Where the canvas looks: what its view becomes when the stage it is drawn on changes.
 *
 * A panel that opens beside the stage (the inspector, the chat) or a window that lies over
 * it (an agent's) is no reason to draw the turn smaller: the zoom stays, and the view only
 * moves, so that what is selected is still to be seen. Everything here is a pure function
 * of rectangles; the canvas measures them and moves.
 */
import { getViewportForBounds } from '@xyflow/react'

/** A view of the canvas: a point of the turn at (x, y) is drawn at (x * zoom + view.x, y * zoom + view.y). */
export interface View {
  x: number
  y: number
  zoom: number
}

export interface Size {
  width: number
  height: number
}

/** A rectangle: of the turn (a node, all its nodes) or of the stage (something lying over it). */
export interface Rect extends Size {
  x: number
  y: number
}

/**
 * As far out and as close as the canvas goes. A fit takes in the whole turn, so a turn of
 * many nodes is drawn as small as that needs; one of a few nodes is drawn a little closer
 * than life-size, not lost in an empty stage - and never closer than this.
 */
export const MIN_ZOOM = 0.3
export const MAX_ZOOM = 1.6
export const FIT_MAX_ZOOM = 1.25
/** The room a fit leaves around the turn, as a share of it (React Flow's own). */
const FIT_PADDING = 0.1
/** How near the edge of the stage a node may be and still count as in view. */
const EDGE = 8

/** The view React Flow's `fitView` gives a turn on a stage of this size. */
export function fitted(bounds: Rect, stage: Size): View {
  return getViewportForBounds(bounds, stage.width, stage.height, MIN_ZOOM, FIT_MAX_ZOOM, FIT_PADDING)
}

/** The view that has the middle of a rectangle of the turn in the middle of a part of the stage, at a zoom. */
function middleIn(rect: Rect, part: Rect, zoom: number): View {
  return {
    x: part.x + part.width / 2 - (rect.x + rect.width / 2) * zoom,
    y: part.y + part.height / 2 - (rect.y + rect.height / 2) * zoom,
    zoom,
  }
}

/** The view that has the middle of the turn in the middle of the stage - or of a part of it - at the zoom given. */
export function centredOn(bounds: Rect, stage: Size | Rect, zoom: number): View {
  return middleIn(bounds, { x: 0, y: 0, ...stage }, zoom)
}

const overlap = (a: Rect, b: Rect) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

/**
 * The largest part of the stage nothing lies over: the stage, cut beside, above or below
 * whatever lies over it, each piece cut again by what still lies over that piece (slice 38e:
 * two windows in opposite corners leave the part between them, not a strip beside both).
 */
export function freePart(stage: Size, covers: Rect[]): Rect {
  return freeParts(stage, covers)[0]
}

/** Every part of the stage nothing lies over, as `freePart` cuts it: the largest first. */
function freeParts(stage: Size, covers: Rect[]): Rect[] {
  const pieces = (part: Rect): Rect[] => {
    const cover = covers.find(c => overlap(part, c))
    if (!cover) return [part]
    const [left, right] = [Math.max(part.x, cover.x), Math.min(part.x + part.width, cover.x + cover.width)]
    const [top, bottom] = [Math.max(part.y, cover.y), Math.min(part.y + part.height, cover.y + cover.height)]
    return [
      { ...part, width: left - part.x },
      { ...part, x: right, width: part.x + part.width - right },
      { ...part, height: top - part.y },
      { ...part, y: bottom, height: part.y + part.height - bottom },
    ]
      .filter(piece => piece.width > 0 && piece.height > 0)
      .flatMap(pieces)
  }
  const free = pieces({ x: 0, y: 0, ...stage }).sort((a, b) => b.width * b.height - a.width * a.height)
  // (All of it covered: as if nothing were.)
  return free.length > 0 ? free : [{ x: 0, y: 0, ...stage }]
}

/**
 * The view after the stage changed under a selected node - a panel opened beside it, or a
 * window over it (`covers`, in the stage's own measure). The zoom is the one it had. A node
 * that is still wholly to be seen leaves the view where it is; one the stage no longer
 * shows, or that something lies over, is brought to the middle of what is free.
 */
export function keepInView(view: View, stage: Size, node: Rect, covers: Rect[] = [], free = freePart(stage, covers)): View {
  const drawn = drawnAt(view, node)
  const inside = drawn.x >= EDGE && drawn.y >= EDGE && drawn.x + drawn.width <= stage.width - EDGE && drawn.y + drawn.height <= stage.height - EDGE
  if (inside && !covers.some(cover => overlap(drawn, cover))) return view
  return middleIn(node, free, view.zoom)
}

/** Where a rectangle of the turn is drawn on the stage. */
const drawnAt = (view: View, rect: Rect): Rect => ({ x: rect.x * view.zoom + view.x, y: rect.y * view.zoom + view.y, width: rect.width * view.zoom, height: rect.height * view.zoom })

/**
 * A fit on a stage - or a part of it - that a panel has made narrower than it was
 * (`fullWidth`): the turn is drawn no smaller than a fit at the full width would draw it.
 * Where that no longer takes in the whole turn, the turn is centred, and a selected node
 * is kept in view - but never so that Ready for you (`ready`), where the teams meet, is out of it: then the whole turn is
 * fitted in the part (84b2: a turn of small nodes, wide and short, left it off the right edge).
 */
export function fitNarrowed(bounds: Rect, part: Size | Rect, fullWidth: number, selected: Rect | null, ready: Rect | null = null): View {
  // Worked out on the part alone; its corner on the stage (beside the chat) is added once, at the end.
  const stage = { width: part.width, height: part.height }
  const [dx, dy] = 'x' in part ? [part.x, part.y] : [0, 0]
  const at = (view: View) => ({ ...view, x: view.x + dx, y: view.y + dy })
  const here = fitted(bounds, stage)
  const least = fitted(bounds, { width: Math.max(fullWidth, stage.width), height: stage.height }).zoom
  if (here.zoom >= least) return at(here)
  const view = centredOn(bounds, stage, least)
  const kept = selected ? keepInView(view, stage, selected) : view
  const shown = ready && drawnAt(kept, ready)
  const cut = shown && (shown.x < 0 || shown.y < 0 || shown.x + shown.width > stage.width || shown.y + shown.height > stage.height)
  return at(cut ? here : kept)
}

/**
 * The view after the stage changed (a panel opened or closed, the chat grew): the selected
 * node and the nodes at work (`work`, taken together) are kept in view, clear of what lies
 * over the stage - in the free part that holds them closest (B-149: beside a tall chat, the
 * strip above it, not the larger one beside it). Where they do not fit at the zoom the view
 * has, it zooms out just enough - never under the least zoom; at the least, the work is
 * wholly in view and the selected node beside it as far as there is room. Only where that
 * leaves nothing of the selected node is it kept first, at the zoom it had. A selected node
 * alone keeps the zoom, as ever.
 */
export function keepWork(view: View, stage: Size, selected: Rect | null, work: Rect | null, covers: Rect[] = []): View {
  if (!work) return selected ? keepInView(view, stage, selected, covers) : view
  const both = selected ? around(selected, work) : work
  const zoomIn = (part: Rect) => Math.min(view.zoom, (part.width - 2 * EDGE) / both.width, (part.height - 2 * EDGE) / both.height)
  // (Of parts that hold them as close, the largest.)
  const free = freeParts(stage, covers).reduce((best, part) => (zoomIn(part) > zoomIn(best) ? part : best))
  const zoom = zoomIn(free)
  if (zoom === view.zoom) return keepInView(view, stage, both, covers, free)
  if (zoom >= MIN_ZOOM) return middleIn(both, free, zoom)
  const least = into(middleIn(both, free, MIN_ZOOM), work, free)
  return !selected || overlap(drawnAt(least, selected), free) ? least : keepInView(view, stage, selected, covers)
}

/** The view moved as little as puts a rectangle of the turn wholly in a part of the stage (its top left, where it is larger). */
function into(view: View, rect: Rect, part: Rect): View {
  const drawn = drawnAt(view, rect)
  const along = (at: number, size: number, from: number, span: number) => Math.max(from + EDGE, Math.min(at, from + span - EDGE - size)) - at
  return { ...view, x: view.x + along(drawn.x, drawn.width, part.x, part.width), y: view.y + along(drawn.y, drawn.height, part.y, part.height) }
}

/** The rectangle that holds both. */
function around(a: Rect, b: Rect): Rect {
  const [x, y] = [Math.min(a.x, b.x), Math.min(a.y, b.y)]
  return { x, y, width: Math.max(a.x + a.width, b.x + b.width) - x, height: Math.max(a.y + a.height, b.y + b.height) - y }
}
