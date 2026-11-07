import { createContext, useCallback, useLayoutEffect, useRef, useState } from 'react'

/** Between the panel and the window's edge, and between the panel and the row it opens over. */
const GAP = 8

/** Folds the composer's More: for a panel in it whose work, once done, goes on elsewhere (a room opened). */
export const CloseMore = createContext<() => void>(() => {})

/**
 * A panel that opens from a button: of the row under the message box (the
 * conversation's model, the sub-agents' settings, what runs without asking), or elsewhere
 * (Help in the top bar, the canvas's legend). They all open the same way. From the row, the
 * panel stands over it (and over More, for a button in it); from a button elsewhere, over it
 * or - in the top half of the window - under it. It stays inside the window - as wide and as
 * tall as the window leaves it, and what does not fit scrolls in it - and takes the focus. Esc
 * and a click anywhere else close it, and so does its own button; the focus then goes back
 * to that button, unless the click put it somewhere else.
 *
 * The caller draws the button (`ref={button}`, `aria-expanded={open}`) and, while `open`,
 * the panel (`ref={panel}`, `tabIndex={-1}`, class `allow-list-panel`). `mayClose`: asked before
 * Esc or a click elsewhere closes it - a panel with a Save of its own asks there before what was
 * changed is thrown away (B-75).
 */
export function usePanel<P extends HTMLElement = HTMLDivElement>(mayClose?: () => boolean) {
  const [open, setOpen] = useState(false)
  const button = useRef<HTMLButtonElement | null>(null)
  const panel = useRef<P | null>(null)
  const asked = useRef(mayClose)
  useLayoutEffect(() => {
    asked.current = mayClose
  })

  const close = useCallback(() => {
    const at = document.activeElement
    // Back to what opened it; a click on something that takes the focus keeps it there.
    if (!at || at === document.body || panel.current?.contains(at)) button.current?.focus()
    setOpen(false)
  }, [])

  useLayoutEffect(() => {
    const shown = panel.current
    if (!open || !shown) return
    const put = () => {
      // Over the whole row, from its left end: the same place whichever button opened it - and
      // over More, for a button in it, so that the button stays in sight.
      const row = (button.current?.closest('.composer-row') ?? button.current)?.getBoundingClientRect()
      if (!row) return
      // A button high on the page, not the message box's (the top bar's, the canvas's), opens it under itself, inside the window's right edge.
      if (!button.current?.closest('.composer-row') && row.top < window.innerHeight / 2) {
        const left = Math.max(GAP, Math.min(row.left, window.innerWidth - shown.offsetWidth - GAP))
        shown.style.left = `${left}px`
        shown.style.top = `${row.bottom + GAP}px`
        shown.style.bottom = ''
        shown.style.maxWidth = `${Math.max(0, window.innerWidth - left - GAP)}px`
        shown.style.maxHeight = `${Math.max(0, window.innerHeight - row.bottom - 2 * GAP)}px`
        return
      }
      const top = button.current?.closest('.composer-more-panel')?.getBoundingClientRect().top ?? row.top
      // (A button at the right - the canvas's, bottom right - keeps the panel inside the window too.)
      const left = Math.max(GAP, Math.min(row.left, window.innerWidth - shown.offsetWidth - GAP))
      shown.style.left = `${left}px`
      shown.style.top = ''
      shown.style.bottom = `${window.innerHeight - top + GAP}px`
      shown.style.maxWidth = `${Math.max(0, window.innerWidth - left - GAP)}px`
      shown.style.maxHeight = `${Math.max(0, top - 2 * GAP)}px`
    }
    put()
    shown.focus({ preventScroll: true })
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      // A panel open inside this one (a list in ⚙ Chat's sheet) is the one Esc closes: one Esc, one panel.
      if (shown.querySelector('.allow-list-panel')) return
      event.stopPropagation()
      if (asked.current?.() !== false) close()
    }
    const onClick = (event: MouseEvent) => {
      const target = event.target as Node | null
      // (Its own button closes it by itself.)
      if (target && !shown.contains(target) && !button.current?.contains(target) && asked.current?.() !== false) close()
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('click', onClick, true)
    window.addEventListener('resize', put)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('click', onClick, true)
      window.removeEventListener('resize', put)
    }
  }, [open, close])

  return { open, setOpen, close, button, panel }
}
