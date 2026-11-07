import { FolderSimple } from '@phosphor-icons/react'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { errorText } from '../api/client'
import type { FolderBrowse } from '../api/types'

type Entry = FolderBrowse['entries'][number]

interface Props {
  /** The folder it opens in; null: the home folder. */
  start: string | null
  /** The folders in one folder, as the server lists them. Throws ApiError with why not. */
  onBrowse: (path: string | null) => Promise<FolderBrowse>
  /** The folder chosen, made the chat's main folder - or, `adding`, one of its extra folders. Throws ApiError with why not: said here. */
  onOpen: (path: string) => Promise<void>
  onCancel: () => void
  /** "+ Add a folder" (slice 86b): the folder chosen is added, not opened. */
  adding?: boolean
}

/**
 * "Open a folder…" (slice 86a): KOLONİ's own folder browser, since a browser does not give a folder's path. The
 * server lists the folders, never a file; a folder KOLONİ never opens as a project shows as blocked and is not
 * chosen, though one can still go inside it (the home folder holds the Desktop).
 */
export function FolderBrowser({ start, onBrowse, onOpen, onCancel, adding = false }: Props) {
  const [path, setPath] = useState(start)
  const [at, setAt] = useState<FolderBrowse | null>(null)
  const [chosen, setChosen] = useState<Entry | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const dialog = useRef<HTMLDivElement>(null)
  // Gone into a folder from the list (its row is gone with it): the keyboard goes to the first folder inside.
  const intoList = useRef(false)

  useEffect(() => {
    // Only the latest reading counts: a folder clicked after it is the one shown.
    let latest = true
    onBrowse(path).then(
      read => {
        if (!latest) return
        const focused = document.activeElement
        intoList.current = !dialog.current?.contains(focused) || Boolean(focused?.closest('.folder-tree'))
        setAt(read)
        setChosen(null)
        setError(null)
      },
      err => {
        if (!latest) return
        setError(errorText(err))
        // Where it was to open cannot be listed (gone since): it opens at home instead.
        if (path !== null && path === start) setPath(null)
      },
    )
    return () => {
      latest = false
    }
  }, [onBrowse, path, start])

  useEffect(() => dialog.current?.focus(), [])
  useEffect(() => {
    if (!intoList.current) return
    intoList.current = false
    ;(dialog.current?.querySelector<HTMLElement>('.folder-tree button') ?? dialog.current)?.focus()
  }, [at])
  // While it is open nothing behind it is reached, as behind the Models page's window: it is drawn beside the app, not in it.
  useEffect(() => {
    const app = document.querySelector('.app')
    app?.setAttribute('inert', '')
    return () => app?.removeAttribute('inert')
  }, [])
  // Esc closes it wherever the focus is in it.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  const here = at?.parts.at(-1)
  const target = chosen ?? (here ? { name: here.name, path: here.path } : null)
  async function open() {
    if (!target) return
    setBusy(true)
    setError(null)
    try {
      await onOpen(target.path)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  // Up and down go from folder to folder; Enter goes into one, as a double-click does.
  const onRowKey = (event: KeyboardEvent<HTMLButtonElement>, entry: Entry) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      setPath(entry.path)
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const item = event.currentTarget.closest('li')
    const next = event.key === 'ArrowDown' ? item?.nextElementSibling : item?.previousElementSibling
    next?.querySelector<HTMLElement>('button')?.focus()
  }

  return createPortal(
    <div className="dialog-back">
      <div ref={dialog} tabIndex={-1} className="provider-dialog folder-browser" role="dialog" aria-modal="true" aria-labelledby="folder-browser-title">
        <h3 id="folder-browser-title">{adding ? 'Add a folder' : 'Open a folder'}</h3>
        {at && (
          <nav className="folder-crumbs" aria-label="Where">
            {at.shortcuts.map(place => (
              <button key={place.path} type="button" className="btn btn-small" onClick={() => setPath(place.path)}>
                {place.name}
              </button>
            ))}
            <ol className="folder-path mono">
              {at.parts.map((part, index) => (
                <li key={part.path}>
                  <button type="button" className="folder-crumb" aria-current={index === at.parts.length - 1 ? 'location' : undefined} onClick={() => setPath(part.path)}>
                    {part.name}
                  </button>
                </li>
              ))}
            </ol>
          </nav>
        )}
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
        {at && (
          <ul className="folder-tree" aria-label={`Folders in ${at.path}`}>
            {at.entries.length === 0 && <li className="muted folder-none">No folders in it.</li>}
            {at.entries.map(entry => (
              <li key={entry.path}>
                <button
                  type="button"
                  className={`folder-row${entry.blocked ? ' folder-blocked' : ''}${entry.hidden ? ' folder-hidden' : ''}`}
                  aria-pressed={entry.blocked ? undefined : chosen?.path === entry.path}
                  title={entry.blocked ? 'KOLONİ never opens this as a project. Double-click to look inside it, where KOLONİ may list it' : undefined}
                  onClick={() => !entry.blocked && setChosen(entry)}
                  onDoubleClick={() => setPath(entry.path)}
                  onKeyDown={event => onRowKey(event, entry)}
                >
                  <FolderSimple size={16} weight="fill" className="folder-icon" aria-hidden />
                  <span className="folder-row-name">{entry.name}</span>
                  {entry.koloni && <span className="tag folder-tag-koloni">KOLONİ project</span>}
                  {entry.git && <span className="tag">git</span>}
                  {entry.blocked && <span className="tag folder-tag-blocked">always blocked</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
        {at?.more && <p className="muted">and more…</p>}
        <p className="muted">Double-click or Enter goes in. Folders KOLONİ never opens as a project show as blocked.</p>
        <div className="folder-buttons">
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={!target || busy} onClick={() => void open()}>
            {`${adding ? 'Add' : 'Open'} "${target?.name ?? '…'}"`}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
