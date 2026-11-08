import { type KeyboardEvent, useId, useRef, useState } from 'react'
import type { Role } from '../api/types'
import { fold } from '../shell/fold'

/** `cannotOf`'s lines (chart.ts), as one warning. */
export function Cannot({ said }: { said: string[] }) {
  if (said.length === 0) return null
  return (
    <ul className="role-cannot" aria-label="Will not run">
      {said.map(line => (
        <li key={line}>⚠ {line}</li>
      ))}
    </ul>
  )
}

/**
 * "+ Add a role": a box that finds one of the other roles by name, and "New role…" at the end. Arrows move,
 * Enter picks, Esc closes; the focus goes back to the button. (The palette's way, Ctrl+K.) `title`: where it adds;
 * `kindOf`: a role's category, said beside its name.
 */
export function AddRole({ title, label, others, kindOf, onPick }: { title: string; label: string; others: Role[]; kindOf: (role: Role) => string; onPick: (role: Role | null) => void }) {
  const [open, setOpen] = useState(false)
  const [words, setWords] = useState('')
  const [at, setAt] = useState(0)
  const button = useRef<HTMLButtonElement>(null)
  const list = useId()
  const wanted = fold(words.trim())
  const shown: (Role | null)[] = [...others.filter(role => fold(role.name).includes(wanted)), null]
  const active = Math.min(at, shown.length - 1)
  const close = () => {
    setOpen(false)
    setWords('')
    setAt(0)
    button.current?.focus()
  }
  const pick = (role: Role | null) => {
    close()
    onPick(role)
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setAt((active + (event.key === 'ArrowDown' ? 1 : shown.length - 1)) % shown.length)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      pick(shown[active])
    } else if (event.key === 'Escape') {
      // Its own: the panel beside it is not closed by it.
      event.stopPropagation()
      close()
    }
  }
  return (
    <div className="agents-add-wrap">
      <button ref={button} type="button" className="agents-add" aria-expanded={open} aria-haspopup="listbox" onClick={() => (open ? close() : setOpen(true))}>
        {label}
      </button>
      {open && (
        <div className="agents-add-menu">
          <input
            className="input"
            role="combobox"
            aria-label={`Find a role to add to ${title}`}
            aria-expanded="true"
            aria-controls={list}
            aria-autocomplete="list"
            aria-activedescendant={`${list}-${active}`}
            placeholder="Find a role…"
            autoFocus
            value={words}
            onChange={event => {
              setWords(event.target.value)
              setAt(0)
            }}
            onKeyDown={onKeyDown}
            // (Its own button closes it on its click.)
            onBlur={event => {
              if (event.relatedTarget === button.current) return
              setOpen(false)
              setWords('')
            }}
          />
          <ul id={list} role="listbox" aria-label={`Roles to add to ${title}`} className="palette-list">
            {shown.map((role, index) => (
              <li
                key={role?.id ?? 'new'}
                id={`${list}-${index}`}
                role="option"
                aria-selected={index === active}
                className="palette-row"
                ref={index === active ? row => row?.scrollIntoView?.({ block: 'nearest' }) : undefined}
                // (A click keeps the focus in the box until it picks.)
                onMouseDown={event => event.preventDefault()}
                onClick={() => pick(role)}
              >
                <span className="palette-name">{role ? role.name : 'New role…'}</span>
                {role && (
                  <span className="muted palette-kind">
                    {kindOf(role)}
                    {!role.enabled && ', off'}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
