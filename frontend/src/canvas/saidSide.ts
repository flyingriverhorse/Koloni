import type { PanelPosition } from '@xyflow/react'
import type { CSSProperties } from 'react'

const SAID_BOX = { width: 380, height: 320 }
const GAP = 8
/** What else lies over the canvas, that the box opening on its right keeps clear of. */
const WINDOWS = '.chat, .view-panel, .agent-window, .room-window, .changes'

type Place = { position: PanelPosition; style?: CSSProperties }
const rectOf = (selector: string) => document.querySelector(selector)?.getBoundingClientRect()

/** The user's (6 Nov): on the canvas's right, under the Teams button (by its right edge, so left of the inspector too)
 * and above the buttons at its foot and the notes beside them (Toasts: at most 200px tall, 16px up); null where it does
 * not go there - too short, too narrow, or over the chat or another window. */
function rightSide(canvas: DOMRect): Place | null {
  const teams = rectOf('.chat-teams')
  const [top, right] = teams?.width ? [teams.bottom + GAP, teams.right] : [canvas.top + 15, canvas.right - 15]
  const feet = ['.react-flow__controls', '.canvas-fold-all'].map(rectOf).flatMap(b => (b?.height ? [b.top] : []))
  const foot = Math.min(canvas.bottom, window.innerHeight - 216, ...feet) - GAP
  const [left, bottom] = [right - SAID_BOX.width, top + SAID_BOX.height]
  const over = Array.from(document.querySelectorAll(WINDOWS), w => w.getBoundingClientRect()).some(
    w => w.width > 0 && left < w.right && w.left < right && top < w.bottom && w.top < bottom,
  )
  if (bottom > foot || left < canvas.left || over) return null
  return { position: 'top-right', style: { marginTop: top - canvas.top, marginRight: canvas.right - right } }
}

/** Where on the canvas "What was said" opens: on its right (`rightSide`); else (B-132) its top left, unless the chat
 * floating over the canvas is there (live, the box was drawn under it): then its foot, or its top middle. Read as it
 * opens: the chat may have been moved since. Once the user moved the box, it stays where they put it (`useMove`).
 * shortcut: the box is taken to be at most SAID_BOX big; measure it if a longer one is seen under the chat. */
export function saidSide(): Place {
  const [chat, canvas] = [rectOf('.chat'), rectOf('.react-flow')]
  if (!canvas?.width) return { position: 'top-left' }
  const right = rightSide(canvas)
  if (right) return right
  if (!chat || chat.width === 0) return { position: 'top-left' }
  const clear = (x: number, y: number) =>
    x + SAID_BOX.width <= chat.left || x >= chat.right || y + SAID_BOX.height <= chat.top || y >= chat.bottom
  if (clear(canvas.left, canvas.top)) return { position: 'top-left' }
  return { position: clear(canvas.left, canvas.bottom - SAID_BOX.height) ? 'bottom-left' : 'top-center' }
}
