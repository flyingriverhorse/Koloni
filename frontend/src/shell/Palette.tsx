import { type KeyboardEvent, useCallback, useEffect, useId, useRef, useState } from 'react'
import { fold } from './fold'

/** Somewhere the palette goes: a page, a conversation, a role, a model, a tool server, a setting. */
export interface Place {
  kind: string
  name: string
  go: () => void
}

interface Props {
  places: Place[]
  /** It opened: what it lists may be read anew. */
  onOpen: () => void
  /** Open slice 22a's search of what was said, with these words. */
  onSearch: (words: string) => void
}

/**
 * Ctrl+K (⌘K): a box that finds a place by its name as it is typed - conversations by their
 * name only; "Search in messages" takes the words to the memory's search. Arrows move, Enter
 * goes, Esc closes; either way the focus goes back to where it was when it opened.
 */
export function Palette({ places, onOpen, onSearch }: Props) {
  const [open, setOpen] = useState(false)
  const [words, setWords] = useState('')
  const [at, setAt] = useState(0)
  const opener = useRef<HTMLElement | null>(null)
  const list = useId()

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      // From anywhere, the message box too.
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.key.toLowerCase() !== 'k') return
      event.preventDefault()
      if (open) return
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      setWords('')
      setAt(0)
      setOpen(true)
      onOpen()
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [open, onOpen])

  /** Back to what opened it; what is gone since leaves it to the page. */
  const back = useCallback(() => (opener.current?.isConnected ? opener.current : document.querySelector<HTMLElement>('.main'))?.focus(), [])
  useEffect(() => {
    if (!open) return
    // While it is open Esc is its own, wherever the focus is: taken before the panels under it hear it (they listen on the document).
    const onEsc = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      setOpen(false)
      back()
    }
    window.addEventListener('keydown', onEsc, true)
    return () => window.removeEventListener('keydown', onEsc, true)
  }, [open, back])

  if (!open) return null
  const wanted = fold(words.trim())
  const shown: Place[] = [
    ...places.filter(place => fold(place.name).includes(wanted)),
    { kind: 'Search', name: wanted ? `Search in messages: “${words.trim()}”` : 'Search in messages', go: () => onSearch(words.trim()) },
  ]
  const active = Math.min(at, shown.length - 1)
  const close = () => {
    setOpen(false)
    back()
  }
  const go = (place: Place) => {
    setOpen(false)
    place.go()
    // Where it went may take the focus itself (the memory's search box); otherwise it goes back.
    requestAnimationFrame(() => {
      if (!document.activeElement || document.activeElement === document.body) back()
    })
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setAt((active + (event.key === 'ArrowDown' ? 1 : shown.length - 1)) % shown.length)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      go(shown[active])
    } else if (event.key === 'Tab') {
      event.preventDefault() // the box is all there is to it
    }
  }
  return (
    <div className="palette-back" onMouseDown={event => event.target === event.currentTarget && close()}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Go to">
        <input
          className="input"
          role="combobox"
          aria-label="Go to"
          aria-expanded="true"
          aria-controls={list}
          aria-autocomplete="list"
          aria-activedescendant={`${list}-${active}`}
          placeholder="A page, a conversation, a role, a model…"
          autoFocus
          value={words}
          onChange={event => {
            setWords(event.target.value)
            setAt(0)
          }}
          onKeyDown={onKeyDown}
        />
        <ul id={list} role="listbox" aria-label="Places" className="palette-list">
          {shown.map((place, index) => (
            <li
              key={`${place.kind}:${place.name}:${index}`}
              id={`${list}-${index}`}
              role="option"
              aria-selected={index === active}
              className="palette-row"
              ref={index === active ? row => row?.scrollIntoView?.({ block: 'nearest' }) : undefined}
              // (A click keeps the focus in the box until it goes.)
              onMouseDown={event => event.preventDefault()}
              onClick={() => go(place)}
            >
              <span className="palette-name">{place.name}</span>
              <span className="muted palette-kind">{place.kind}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
