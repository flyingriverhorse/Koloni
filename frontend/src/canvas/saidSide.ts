import type { PanelPosition } from '@xyflow/react'
import type { CSSProperties } from 'react'

const SAID_BOX = { width: 380, height: 320 }
const GAP = 8
/** What else lies over the canvas, that the box opening on its right keeps clear of. */
const WINDOWS = '.chat, .view-panel, .agent-window, .changes'

type Place = { position: PanelPosition; style?: CSSProperties }
const rectOf = (selector: string) => document.querySelector(selector)?.getBoundingClientRect()

/** Whether the box, its top left corner here, would lie over the chat or another window over the canvas. */
const overWindow = (left: number, top: number) =>
  Array.from(document.querySelectorAll(WINDOWS), w => w.getBoundingClientRect()).some(
    w =>
      w.width > 0 &&
      left < w.right &&
      w.left < left + SAID_BOX.width &&
      top < w.bottom &&
      w.top < top + SAID_BOX.height,
  )

/** The user's (6 Nov): on the canvas's right, under the Teams button (by its right edge, so left of the inspector too)
 * and above the buttons at its foot and the notes beside them (Toasts: at most 200px tall, 16px up); null where it does
 * not go there - too short, too narrow, or over the chat or another window. */
function rightSide(canvas: DOMRect): Place | null {
  const teams = rectOf('.chat-teams')
  const [top, right] = teams?.width ? [teams.bottom + GAP, teams.right] : [canvas.top + 15, canvas.right - 15]
  const feet = ['.react-flow__controls', '.canvas-fold-all'].map(rectOf).flatMap(b => (b?.height ? [b.top] : []))
  const foot = Math.min(canvas.bottom, window.innerHeight - 216, ...feet) - GAP
  const left = right - SAID_BOX.width
  if (top + SAID_BOX.height > foot || left < canvas.left || overWindow(left, top)) return null
  return { position: 'top-right', style: { marginTop: top - canvas.top, marginRight: canvas.right - right } }
}

/** Beside the open chat's column at the canvas's left (0.1.4), at the canvas's top (React Flow's 15px panel margin);
 * null where the canvas is too narrow for it there or another window lies there. */
function pastChat(chat: DOMRect, canvas: DOMRect): Place | null {
  const left = chat.right + GAP
  if (left + SAID_BOX.width > canvas.right || overWindow(left, canvas.top + 15)) return null
  return { position: 'top-left', style: { marginLeft: left - canvas.left } }
}

/** Where on the canvas "What was said" opens: on its right (`rightSide`); else (B-132) its top left, unless the chat
 * over the canvas is there (live, the box was drawn under it): then its foot, or just past the open chat's column, or
 * its top middle. Read as it opens: the chat may have been opened, closed or widened since. Once the user moved the
 * box, it stays where they put it (`useMove`).
 * shortcut: the box is taken to be at most SAID_BOX big; measure it if a longer one is seen under the chat. And with
 * Workspace beside the column too, nowhere is clear: its top middle lies under that window; upgrade if it is met. */
export function saidSide(): Place {
  const [chat, canvas] = [rectOf('.chat'), rectOf('.react-flow')]
  if (!canvas?.width) return { position: 'top-left' }
  const right = rightSide(canvas)
  if (right) return right
  if (!chat || chat.width === 0) return { position: 'top-left' }
  const clear = (x: number, y: number) =>
    x + SAID_BOX.width <= chat.left || x >= chat.right || y + SAID_BOX.height <= chat.top || y >= chat.bottom
  if (clear(canvas.left, canvas.top)) return { position: 'top-left' }
  if (clear(canvas.left, canvas.bottom - SAID_BOX.height)) return { position: 'bottom-left' }
  return pastChat(chat, canvas) ?? { position: 'top-center' }
}
