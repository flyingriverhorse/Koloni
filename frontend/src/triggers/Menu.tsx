import type { KeyboardEvent, MouseEvent, ReactNode } from 'react'
import { usePanel } from '../shell/usePanel'

interface Props {
  /** The button's accessible name; the list is named by it too. */
  name: string
  className: string
  /** What the button shows. */
  face: ReactNode
  title?: string
  /** Wide enough for a line under each item's name. */
  wide?: boolean
  /** `role="menuitem"` buttons: a pick closes the list. */
  children: ReactNode
}

/** A short list of actions behind a button, as a message's ⋯: Esc or a click elsewhere closes it, the arrows move in it. */
export function Menu({ name, className, face, title, wide, children }: Props) {
  const { open, setOpen, close, button, panel } = usePanel()
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'))
    const at = items.indexOf(document.activeElement as HTMLButtonElement)
    const to = ({ ArrowDown: at + 1, ArrowUp: at < 0 ? -1 : at - 1, Home: 0, End: -1 } as Record<string, number>)[event.key]
    if (to === undefined || items.length === 0) return
    event.preventDefault()
    items[(to + items.length) % items.length].focus()
  }
  const picked = (event: MouseEvent<HTMLDivElement>) => {
    const item = (event.target as Element).closest<HTMLButtonElement>('[role="menuitem"]')
    if (item && !item.disabled) close()
  }
  return (
    <>
      <button
        ref={button}
        type="button"
        className={className}
        aria-label={name}
        title={title}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}
      >
        {face}
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className={`allow-list-panel msg-menu${wide ? ' menu-wide' : ''}`} role="menu" aria-label={name} onKeyDown={move} onClick={picked}>
          {children}
        </div>
      )}
    </>
  )
}
