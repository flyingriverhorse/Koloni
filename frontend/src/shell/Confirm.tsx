import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

type Asked = { text: string; yes: string; no: string; then?: () => void; back: HTMLElement | null }

/**
 * B-337: KOLONİ's own "are you sure?", in place of the browser's `window.confirm` - which
 * locked the page and a browser driven by an agent. Drawn by the caller inside the panel or
 * window it asks for (`shown(onYes)`), so a click on it is no click elsewhere; it takes the
 * focus, keeps Tab between its two buttons, Enter takes the one with the focus (the yes, first),
 * Esc is no. `cancel`: no, also for the caller's Esc or click elsewhere while it asks - the
 * focus goes back to where it was. `ask`'s `then`: what a yes does where `shown` is given
 * nothing (the yes of one action, asked from its handler); `no`: the no's words.
 */
export function useConfirm() {
  const [asked, setAsked] = useState<Asked | null>(null)
  const id = useId()
  const box = useRef<HTMLDivElement>(null)
  const ask = (text: string, yes: string, then?: () => void, no = 'Keep editing') =>
    setAsked({ text, yes, no, then, back: document.activeElement as HTMLElement | null })
  const cancel = () => {
    setAsked(null)
    asked?.back?.focus()
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      cancel()
    } else if (event.key === 'Tab') {
      const [first, last] = Array.from(box.current?.querySelectorAll('button') ?? [])
      if (document.activeElement === (event.shiftKey ? first : last)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first)?.focus()
      }
    }
  }
  const shown = (onYes?: () => void): ReactNode =>
    asked && (
      <div ref={box} role="alertdialog" aria-modal="true" aria-labelledby={id} className="confirm-box" onKeyDown={onKeyDown}>
        <p id={id}>{asked.text}</p>
        <div className="confirm-actions">
          <button
            type="button"
            className="btn btn-primary"
            autoFocus
            onClick={() => {
              setAsked(null)
              ;(onYes ?? asked.then)?.()
            }}
          >
            {asked.yes}
          </button>
          <button type="button" className="btn" onClick={cancel}>
            {asked.no}
          </button>
        </div>
      </div>
    )
  return { asking: asked !== null, ask, cancel, shown }
}
