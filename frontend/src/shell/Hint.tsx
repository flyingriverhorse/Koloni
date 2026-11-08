import { Info } from '@phosphor-icons/react'
import { type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { GuidePlace } from './guide'

interface Props {
  /**
   * Names the explanation, for a field it describes (`aria-describedby="<the note's id> <this id>"`).
   * It is on the page while closed, so the field is described by all of it either way.
   */
  id?: string
  /** Where the guide says more (`GUIDE`): a "Learn more →" link under the text, opened in a new tab. */
  doc?: GuidePlace
  children: ReactNode
}

/** Between the bubble and the window's edge. */
const GAP = 8

/**
 * A short explanation behind a small ⓘ button beside a note:
 * shown while the pointer is on it, kept open by a click, Enter or Space, and closed by Esc,
 * a click anywhere else or the button again. The button is described by it, so a screen
 * reader says it without opening it.
 */
export function Hint({ id, doc, children }: Props) {
  // 'hover' closes when the pointer leaves; 'click' stays until Esc, a click elsewhere or the button.
  const [open, setOpen] = useState<'hover' | 'click' | null>(null)
  const box = useRef<HTMLSpanElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const bubble = useRef<HTMLSpanElement>(null)
  const leaving = useRef(0)
  const own = useId()
  const textId = id ?? own

  useLayoutEffect(() => {
    const shown = bubble.current
    if (!open || !shown) return
    // Fixed, from the button: a scrolling page or panel does not cut it off, and it stays inside the window.
    const put = () => {
      const at = button.current!.getBoundingClientRect()
      const below = at.bottom + 4 + shown.offsetHeight <= window.innerHeight - GAP
      shown.style.left = `${Math.max(GAP, Math.min(at.left, window.innerWidth - shown.offsetWidth - GAP))}px`
      shown.style.top = `${below ? at.bottom + 4 : Math.max(GAP, at.top - 4 - shown.offsetHeight)}px`
    }
    put()
    // Esc is its own while it is open, wherever the focus is: taken before the panel it is in hears it.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      // (Immediate: the Palette listens on the window too.)
      event.stopImmediatePropagation()
      setOpen(null)
      const at = document.activeElement
      if (open === 'click' && (!at || at === document.body || box.current?.contains(at))) button.current?.focus()
    }
    const onClick = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(null)
    }
    window.addEventListener('keydown', onKey, true)
    document.addEventListener('click', onClick, true)
    window.addEventListener('resize', put)
    window.addEventListener('scroll', put, true)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      document.removeEventListener('click', onClick, true)
      window.removeEventListener('resize', put)
      window.removeEventListener('scroll', put, true)
    }
  }, [open])
  useEffect(() => () => clearTimeout(leaving.current), [])

  return (
    <span
      ref={box}
      className="hint"
      onMouseEnter={() => {
        clearTimeout(leaving.current)
        setOpen(was => was ?? 'hover')
      }}
      // (A moment's grace: the pointer crosses the gap from the button to the bubble.)
      onMouseLeave={() => (leaving.current = window.setTimeout(() => setOpen(was => (was === 'hover' ? null : was)), 150))}
      // (In a box's label: a click on the button or in the bubble is not ticking the box.)
      onClick={event => event.preventDefault()}
      // (The focus gone on: the bubble would cover what it went to.)
      onBlur={event => {
        if (!box.current?.contains(event.relatedTarget as Node | null)) setOpen(null)
      }}
    >
      <button
        ref={button}
        type="button"
        className="hint-button"
        aria-label="About this"
        aria-expanded={open !== null}
        aria-describedby={textId}
        onClick={() => setOpen(was => (was === 'click' ? null : 'click'))}
      >
        <Info size={14} weight="bold" aria-hidden />
      </button>
      <span ref={bubble} className="hint-bubble" hidden={!open}>
        {/* (The text alone describes the field: the link is no part of it.) */}
        <span id={textId}>{children}</span>
        {doc && (
          // (Its click kept from the box's, which would cancel it.)
          <a className="hint-more" href={`/guide/${doc}`} target="_blank" rel="noopener noreferrer" onClick={event => event.stopPropagation()}>
            Learn more →
          </a>
        )}
      </span>
    </span>
  )
}
