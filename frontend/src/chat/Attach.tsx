import { ClipboardText, FolderSimple, Image as ImageIcon, Paperclip, X } from '@phosphor-icons/react'
import { type CSSProperties, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Attachment, ProjectEntry } from '../api/types'
import { fileUrl, LINK, linkName, MAX_BYTES, shown, type Shown } from './attachments'

/** A coloured square and a name: one file or link, as a chip, a mini in the chat or a node show it. */
function Square({ look }: { look: Shown }) {
  return (
    <span className="file-ic mono" aria-hidden="true">
      {look.label}
    </span>
  )
}

const tone = (look: Shown) => ({ '--c': `var(${look.colour})` }) as CSSProperties

/** What a file in the composer is while it goes up, or why it did not. */
export interface Pending {
  key: string
  name: string
  error: string | null
}

/** The files added to the next message, the links it holds, and those still on their way: each with ×. */
export function Chips({
  files,
  frames,
  noFrames,
  links,
  pending,
  unseen = null,
  onRemove,
  onDismiss,
}: {
  files: Attachment[]
  /** How many frames were taken of each video, by its id. */
  frames: Record<string, number>
  /** Why no frames could be taken of a video, by its id. */
  noFrames: Record<string, string>
  links: string[]
  pending: Pending[]
  /** Why the chat's model will not be shown a picture (`unseenOn`); null: it may be. */
  unseen?: string | null
  onRemove: (id: string) => void
  onDismiss: (key: string) => void
}) {
  if (!files.length && !links.length && !pending.length) return null
  return (
    <ul className="att-chips" aria-label="Attached">
      {files.map(file => {
        const look = shown(file, frames[file.id] ?? 0, noFrames[file.id] ?? null, unseen)
        return (
          <li key={file.id} className="att-chip" style={tone(look)}>
            <Square look={look} />
            <span className="att-text">
              <b title={file.name}>{file.name}</b>
              <span className="att-meta">{look.meta}</span>
            </span>
            <button type="button" className="icon-btn" aria-label={`Remove ${file.name}`} onClick={() => onRemove(file.id)}>
              <X size={12} />
            </button>
          </li>
        )
      })}
      {pending.map(one => (
        <li key={one.key} className="att-chip" style={tone({ label: '', colour: '--file-other', meta: '' })}>
          <span className="file-ic" aria-hidden="true" />
          <span className="att-text">
            <b title={one.name}>{one.name}</b>
            <span className={one.error ? 'att-meta att-warn' : 'att-meta'} role={one.error ? 'alert' : undefined}>
              {one.error ?? 'adding…'}
            </span>
          </span>
          {one.error && (
            <button type="button" className="icon-btn" aria-label={`Dismiss ${one.name}`} onClick={() => onDismiss(one.key)}>
              <X size={12} />
            </button>
          )}
        </li>
      ))}
      {links.map(link => (
        // (The link stays in the message: its chip goes when the text does.)
        <li key={link} className="att-chip" style={tone(LINK)} title="A link in your message: edit the message to take it out">
          <Square look={LINK} />
          <span className="att-text">
            <b>{linkName(link)}</b>
            <span className="att-meta">{LINK.meta}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

/** The files of a message in the chat, small, and its links. */
export function Minis({ files, links }: { files: Attachment[]; links: string[] }) {
  if (!files.length && !links.length) return null
  return (
    <div className="att-minis">
      {files.map(file => {
        const look = shown(file)
        return (
          <span key={file.id} className="att-mini" style={tone(look)} title={look.meta}>
            <i className="mono">{look.label}</i>
            {file.name}
          </span>
        )
      })}
      {links.map(link => (
        <span key={link} className="att-mini" style={tone(LINK)} title={LINK.meta}>
          <i className="mono">URL</i>
          {linkName(link)}
        </span>
      ))}
    </div>
  )
}

/**
 * The 📎 button and its menu: files from this computer, a screenshot on the clipboard, a file
 * of the project. Dropping and pasting are the composer's own. Open, Esc or a click elsewhere
 * closes it; a key typed meanwhile closes it too and goes to the message box (`onType`): the
 * list stands over the box, and what was typed was lost (B-106).
 */
export function AttachMenu({ projectId, onFiles, onProject, onError, onType }: {
  projectId: string | null
  onFiles: (files: File[]) => void
  onProject: (path: string) => void
  onError: (said: string) => void
  /** Puts the focus in the message box. */
  onType: () => void
}) {
  const [open, setOpen] = useState<'menu' | 'project' | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const typed = useRef(onType)
  useLayoutEffect(() => {
    typed.current = onType
  })
  const id = useId()
  function close(back = true) {
    setOpen(null)
    if (back) button.current?.focus()
  }
  useEffect(() => {
    if (!open) return
    const onKey = (event: globalThis.KeyboardEvent) => {
      const target = event.target instanceof Element ? event.target : null
      if (event.key === 'Escape') {
        event.stopPropagation() // (the menu's: the chat stays open)
        setOpen(null)
        button.current?.focus()
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey
        && !(event.key === ' ' && target && box.current?.contains(target))) {
        // (A letter is the message's; a space on one of the menu's items presses it.)
        setOpen(null)
        if (!target?.matches('input, textarea, select')) typed.current()
      }
    }
    const onClick = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(null)
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('click', onClick, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('click', onClick, true)
    }
  }, [open])
  async function screenshot() {
    close(false)
    try {
      for (const item of await navigator.clipboard.read()) {
        const type = item.types.find(t => t.startsWith('image/'))
        if (!type) continue
        const blob = await item.getType(type)
        return onFiles([new File([blob], `screenshot-${new Date().toISOString().slice(11, 19).replaceAll(':', '')}.${type.split('/')[1]}`, { type })])
      }
      onError('There is no picture on the clipboard.')
    } catch {
      // (No clipboard to read on this page, or the browser said no.)
      onError('The clipboard could not be read here: click in the message box and press Ctrl+V.')
    }
  }
  return (
    <div className="att-menu-box" ref={box}>
      <button
        ref={button}
        type="button"
        className="btn btn-small att-clip"
        aria-label="Attach"
        title="Attach files"
        aria-haspopup="menu"
        aria-expanded={open !== null}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(open ? null : 'menu')}
      >
        <Paperclip size={14} />
      </button>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        aria-hidden="true"
        tabIndex={-1}
        onChange={e => {
          onFiles(Array.from(e.target.files ?? []))
          e.target.value = '' // (the same file again is another add)
        }}
      />
      {open === 'menu' && (
        <div id={id} role="menu" className="att-menu">
          <button type="button" role="menuitem" autoFocus onClick={() => (close(false), input.current?.click())}>
            <Paperclip size={13} /> Files from this computer…
          </button>
          <button type="button" role="menuitem" onClick={() => void screenshot()}>
            <ImageIcon size={13} /> A screenshot from the clipboard <span className="muted att-key">Ctrl+V</span>
          </button>
          <button type="button" role="menuitem" disabled={!projectId} title={projectId ? undefined : 'This chat has no project folder'} onClick={() => setOpen('project')}>
            <FolderSimple size={13} /> A file of the project…
          </button>
        </div>
      )}
      {open === 'project' && projectId && (
        <ProjectPicker
          id={id}
          projectId={projectId}
          onPick={path => {
            close()
            onProject(path)
          }}
        />
      )}
    </div>
  )
}

/** The project's tree one folder at a time, as the Files window reads it: a file is picked by a click. */
function ProjectPicker({ id, projectId, onPick }: { id: string; projectId: string; onPick: (path: string) => void }) {
  const [folder, setFolder] = useState('')
  const [entries, setEntries] = useState<ProjectEntry[] | string | null>(null)
  useEffect(() => {
    let current = true
    api.get<ProjectEntry[]>(`/projects/${projectId}/files?path=${encodeURIComponent(folder)}`).then(
      list => current && setEntries(list),
      err => current && setEntries(errorText(err)),
    )
    return () => {
      current = false
    }
  }, [projectId, folder])
  const up = folder.includes('/') ? folder.slice(0, folder.lastIndexOf('/')) : ''
  return (
    <div id={id} role="dialog" aria-label="A file of the project" className="att-menu att-picker">
      <div className="muted att-where mono">{folder || 'the project'}/</div>
      {typeof entries === 'string' && <div role="alert">{entries}</div>}
      <ul>
        {folder && (
          <li>
            <button type="button" onClick={() => setFolder(up)}>
              ..
            </button>
          </li>
        )}
        {Array.isArray(entries) &&
          entries.map(entry => {
            const path = folder ? `${folder}/${entry.name}` : entry.name
            return (
              <li key={entry.name}>
                <button type="button" onClick={() => (entry.kind === 'dir' ? setFolder(path) : onPick(path))}>
                  {entry.kind === 'dir' ? <FolderSimple size={12} /> : <ClipboardText size={12} />} {entry.name}
                  {entry.kind === 'dir' && '/'}
                </button>
              </li>
            )
          })}
      </ul>
    </div>
  )
}

/** A file as it was added, looked at: the picture, the video, or the text a model is given of it. */
export function AttachmentPreview({ file }: { file: Attachment }) {
  const [text, setText] = useState<string | null | undefined>()
  const reads = !['image', 'video', 'executable'].includes(file.kind)
  useEffect(() => {
    if (!reads) return
    let current = true
    api.get<{ text: string | null }>(`/attachments/${file.id}/text`).then(
      told => current && setText(told.text),
      () => current && setText(null),
    )
    return () => {
      current = false
    }
  }, [file.id, reads])
  const look = shown(file)
  return (
    <div className="att-preview">
      <div className="muted">{look.meta}</div>
      {file.kind === 'image' && <img className="view-image" src={fileUrl(file.id)} alt={file.name} />}
      {/* (No Download in its controls: one would keep its address, key and all, in the browser's list of downloads.) */}
      {file.kind === 'video' && file.size <= MAX_BYTES && <video className="view-image" src={fileUrl(file.id)} controls controlsList="nodownload" preload="metadata" aria-label={file.name} />}
      {file.kind === 'video' && file.size > MAX_BYTES && <div className="muted">{file.summary}</div>}
      {reads && text === undefined && <div className="muted">Reading…</div>}
      {reads && text === null && <div className="muted">No text of it is given to a model.</div>}
      {reads && text && <pre className="att-text-preview mono">{text.length > 20000 ? `${text.slice(0, 20000)}\n…` : text}</pre>}
      {file.kind === 'executable' && <div className="muted">Kept by name and size only: it is never read or run.</div>}
    </div>
  )
}
