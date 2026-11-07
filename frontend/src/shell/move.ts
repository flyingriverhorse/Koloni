/**
 * Windows over the canvas that the user moves (slice 38e): the open chat and the view window.
 * Each is dragged by its header, or moved with the arrow keys from its "Move …" handle, inside
 * the stage; where it was put is kept in this browser, and a double click (or Enter on the
 * handle) puts it back in its corner. And of all the stage's windows, the one used last is in front.
 */
import { type CSSProperties, type KeyboardEvent, type MouseEvent, type PointerEvent, type RefObject, useRef, useState } from 'react'

/** Where a moved window is: its left edge and its bottom edge, in px from the stage's left and bottom. */
export interface Spot {
  x: number
  y: number
}

interface Size {
  width: number
  height: number
}

/** How far an arrow key moves a window. */
const STEP = 16

/** The canvas is told when a window was moved: what lies over it changed (CanvasView). */
export const MOVED = 'koloni-window-moved'

/** The place this browser kept; null - the window's own corner - for none, or one that makes no sense. */
export function storedSpot(key: string): Spot | null {
  try {
    const kept: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
    if (typeof kept !== 'object' || kept === null) return null
    const { x, y } = kept as Record<string, unknown>
    return typeof x === 'number' && typeof y === 'number' && x >= 0 && y >= 0 && Number.isFinite(x + y) ? { x, y } : null
  } catch {
    return null
  }
}

function keep(key: string, spot: Spot | null) {
  try {
    if (spot) localStorage.setItem(key, JSON.stringify(spot))
    else localStorage.removeItem(key)
  } catch {
    // the place just does not persist
  }
}

/**
 * How far from the stage's left edge a moved window stays (as far as its own corner, base.css
 * `.chat` left), and from its right edge with its foot beside the canvas's zoom and fit buttons
 * (bottom right, slice 66): clear of them.
 * shortcut: the buttons stand on the timeline while it is open, a little higher than this keeps
 * clear; upgrade if a window is seen over them then.
 */
const EDGE = 14
const CLEAR = 48
/** How far up the stage the canvas's buttons reach: zoom, fit, Follow running, the legend, the timeline (slice 44), collapse and expand all (slice 38f-1). */
const BUTTONS = 232

/** A place for a window of this size that leaves it wholly on the stage (`spot.y` is its foot's height over the stage's foot). */
export function within(spot: Spot, box: Size, stage: Size): Spot {
  const y = Math.round(Math.max(0, Math.min(spot.y, stage.height - box.height)))
  const most = stage.width - box.width - (y < BUTTONS ? CLEAR : 0)
  return { x: Math.round(Math.max(EDGE, Math.min(spot.x, most))), y }
}

/**
 * The windows that lie over the stage: the chat, the view, Changes, an agent's and a discussion's.
 * shortcut: CanvasView's OVER and CHAT name some of them again, each for its own reason (what
 * the turn is kept clear of); a window added here may belong there too - upgrade to one list
 * if they drift.
 */
const WINDOWS = '.chat, .view-panel, .changes'

/** Puts a window in front of the stage's other windows (base.css: `[data-front]`). */
export function toFront(window: Element) {
  const stage = window.closest('.stage') ?? window.parentElement
  for (const other of Array.from(stage?.querySelectorAll(WINDOWS) ?? [])) if (other !== window) other.removeAttribute('data-front')
  window.setAttribute('data-front', '')
}

/** A window that opens comes to the front: its `ref` (one function, so only as it opens). */
export const inFront = (window: Element | null) => void (window && toFront(window))

/** A part of the stage, from its top left corner. */
export interface Area {
  left: number
  top: number
  width: number
  height: number
}

/** The least a window opening in the top right is made, to stay off the chat: its header and a few lines. */
const LEAST = { width: 240, height: 140 }
/** How tall a window's header is (`.changes-bar`, `.view-top`): one opening over another starts below it. */
const HEADER = 36
const GAP = 14

const meets = (a: Area, b: Area) => a.left < b.left + b.width && b.left < a.left + a.width && a.top < b.top + b.height && b.top < a.top + a.height

/**
 * K-38b-sinirlar: where a window that opens in the stage's top right (an agent's, a discussion's) goes. Where its CSS
 * puts it (`want`), unless that lies over the chat: then moved and made smaller - never past `want`'s top or right
 * edge, which the CSS keeps off the inspector and the canvas's buttons - into the biggest part of the stage above,
 * below, left or right of the chat. And it starts below the header of another window it would lie over, so that one
 * is still seen and pressed.
 * shortcut: with no part beside the chat as big as LEAST (a chat dragged nearly as tall as a narrow stage) it lies
 * over the chat, in front, as before; and below a chat moved up it may reach the zoom buttons - upgrade if seen.
 */
export function placeWindow(want: Area, stage: Size, chat: Area | null, others: Area[]): Area {
  let box = want
  if (chat && meets(want, chat)) {
    const [right, foot] = [want.left + want.width, stage.height - GAP]
    // As near where it wants to be as goes inside this part, no bigger than it wants.
    const inside = (left: number, top: number, r: number, b: number): Area => {
      const [width, height] = [Math.min(want.width, r - left), Math.min(want.height, b - top)]
      return { left: Math.max(left, Math.min(want.left, r - width)), top: Math.max(top, Math.min(want.top, b - height)), width, height }
    }
    const ways = [
      inside(GAP, want.top, right, chat.top - GAP),
      inside(GAP, chat.top + chat.height + GAP, right, foot),
      inside(GAP, want.top, chat.left - GAP, foot),
      inside(chat.left + chat.width + GAP, want.top, right, foot),
    ].filter(way => way.width >= LEAST.width && way.height >= LEAST.height)
    box = ways.sort((a, b) => b.width * b.height - a.width * a.height)[0] ?? want
  }
  for (const other of others) {
    const by = other.top + HEADER + GAP - box.top
    if (by > 0 && meets(box, { ...other, height: HEADER }) && box.height - by >= LEAST.height) box = { ...box, top: box.top + by, height: box.height - by }
  }
  return box
}

/**
 * The `ref` of a window that opens in the stage's top right: in front, and placed by `placeWindow` - once, as it
 * opens. Held by its right edge as its CSS holds it, so an inspector coming over the stage later still pushes it left.
 * shortcut: placed only as it opens - a chat opened, moved or made taller later, or a stage grown smaller, is not
 * followed (its px height stays); upgrade to placing it again on MOVED and the stage's resize if it is seen over them.
 */
export function placed(window: HTMLElement | null) {
  const stage = window?.parentElement
  if (!window || !stage) return
  toFront(window)
  const corner = stage.getBoundingClientRect()
  const area = (el: Element): Area => {
    const b = el.getBoundingClientRect()
    return { left: b.left - corner.left, top: b.top - corner.top, width: b.width, height: b.height }
  }
  const chat = stage.querySelector(':scope > .chat')
  const others = Array.from(stage.querySelectorAll(WINDOWS))
    .filter(other => other !== window && other !== chat)
    .map(area)
    .filter(other => other.width > 0)
  const want = area(window)
  const to = placeWindow(want, corner, chat && area(chat), others)
  if (to === want) return
  const inspector = parseFloat(getComputedStyle(window).getPropertyValue('--inspector-w')) || 0
  Object.assign(window.style, {
    top: `${to.top}px`,
    right: `calc(${corner.width - inspector - to.left - to.width}px + var(--inspector-w, 0px))`,
    width: `${to.width}px`,
    height: `${to.height}px`,
    minHeight: `${LEAST.height}px`,
  })
}

/** What was pressed or focused on the stage: the window it is in comes to the front. */
export function frontOf(target: EventTarget | null) {
  const window = target instanceof Element ? target.closest(WINDOWS) : null
  if (window) toFront(window)
}

/**
 * A window the user moves: `win` is the window, the stage its parent. Hand `header` to the
 * part it is dragged by and `handle` to its "Move …" handle; `style` places it once moved
 * (base.css `.moved`, which also keeps it on a stage that has since grown smaller).
 */
export function useMove(key: string, win: RefObject<HTMLElement | null>) {
  const [spot, setSpot] = useState(() => storedSpot(key))
  const drag = useRef<{ x: number; y: number; from: Spot; to?: Spot } | null>(null)

  /**
   * Where the window is now - where it was put, as the stage holds it now (a stage grown smaller
   * since keeps it on itself), or else its corner - and a place for it kept on the stage.
   */
  function measure() {
    const [el, stage] = [win.current, win.current?.parentElement]
    if (!el || !stage) return null
    const [box, area] = [el.getBoundingClientRect(), stage.getBoundingClientRect()]
    const at = (to: Spot) => within(to, box, area)
    return { here: spot ? at(spot) : { x: box.left - area.left, y: area.bottom - box.bottom }, put: at }
  }
  function put(next: Spot | null) {
    setSpot(next)
    keep(key, next)
    win.current?.dispatchEvent(new Event(MOVED, { bubbles: true }))
  }

  const header = {
    onPointerDown(event: PointerEvent<HTMLElement>) {
      // (A press on what is in the header - a tab, a button - is that, not a drag.)
      if (event.button !== 0 || (event.target as Element).closest('button, select, input, textarea, a')) return
      const at = measure()
      if (!at) return
      drag.current = { x: event.clientX, y: event.clientY, from: at.here }
      event.currentTarget.setPointerCapture?.(event.pointerId)
    },
    onPointerMove(event: PointerEvent<HTMLElement>) {
      const [start, at] = [drag.current, measure()]
      if (!start || !at) return
      start.to = at.put({ x: start.from.x + event.clientX - start.x, y: start.from.y - (event.clientY - start.y) })
      setSpot(start.to)
    },
    onPointerUp() {
      const to = drag.current?.to
      drag.current = null
      // Kept where it was let go, and only then: the canvas is told once, not at every step.
      if (to) put(to)
    },
    // (Also after a drag the browser called off: it ends there, as one let go.)
    onLostPointerCapture() {
      header.onPointerUp()
    },
    onDoubleClick(event: MouseEvent<HTMLElement>) {
      if (!(event.target as Element).closest('button, select, input, textarea, a')) put(null)
    },
  }
  const handle = {
    role: 'button',
    tabIndex: 0,
    // A click from a screen reader (no press: detail 0) puts it back, as Enter does. A press is a drag.
    onClick(event: MouseEvent<HTMLElement>) {
      if (event.detail === 0) put(null)
    },
    onKeyDown(event: KeyboardEvent<HTMLElement>) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        return put(null)
      }
      const [dx, dy] = { ArrowLeft: [-STEP, 0], ArrowRight: [STEP, 0], ArrowUp: [0, STEP], ArrowDown: [0, -STEP] }[event.key] ?? [0, 0]
      const at = measure()
      if ((!dx && !dy) || !at) return
      event.preventDefault()
      put(at.put({ x: at.here.x + dx, y: at.here.y + dy }))
    },
  } as const
  const style = (spot ? { '--x': `${spot.x}px`, '--y': `${spot.y}px` } : {}) as CSSProperties
  return { moved: spot !== null, style, header, handle }
}
