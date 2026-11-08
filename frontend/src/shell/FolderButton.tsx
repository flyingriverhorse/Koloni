import { CaretDown, FolderSimple, X } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { ApiError, api, errorText } from '../api/client'
import type { Conversation, FolderBrowse, Folders, ListedConversation, Project, ProjectMap } from '../api/types'
import { since } from '../board/columns'
import { FolderBrowser } from './FolderBrowser'
import { type Access, type FolderRow, HOLDS, holds, listsOf, rowsOf, WIDE } from './Folders'
import { usePanel } from './usePanel'


type Lists = ReturnType<typeof listsOf>

interface Props {
  /** The open chat's main folder; null: a plain chat. */
  project: Project | null
  projects: Project[]
  /** Every chat, the latest first: a folder was last used when its newest chat was. */
  conversations: ListedConversation[]
  /** The open chat, where it is in `project`: its other folders are in the panel. Null: none shown. */
  conversation: Conversation | null
  /** The chat's other folders as they are to be. Throws ApiError with why not. */
  onFolders: (lists: Lists) => Promise<void>
  /** These, as the folder's default: what a new chat in it starts with. Throws ApiError. */
  onDefault: (lists: Lists) => Promise<void>
  /** The chat's main folder changed (null: none). Throws ApiError: a 409 says why it may not. */
  onMove: (projectId: string | null) => Promise<void>
  /** The part of the main folder its agents work in (null: all of it). Throws ApiError with why not. */
  onPart: (part: string | null) => Promise<void>
  /** A new chat in this folder (null: none), opened. */
  onNew: (projectId: string | null) => Promise<void>
  /** A folder of the disk made a project. Throws ApiError with why not. */
  onOpenFolder: (path: string) => Promise<Project>
  onBrowse: (path: string | null) => Promise<FolderBrowse>
}

/** Where a path's folder is: the parent of `C:\a\b` is `C:\a`, of `C:\a` the drive `C:\`, of `/a` the root. */
export function parentOf(path: string): string {
  const up = path.replace(/[\\/][^\\/]+[\\/]?$/, '')
  return /^[A-Za-z]:$/.test(up) ? `${up}\\` : up || '/'
}

/** A chat's (or its folder's default) other folders, each once: one in both lists is one to write in, as the server has it. */
const rowsOfChat = (lists: Lists) => rowsOf(lists.also_in, lists.read_in.filter(f => !lists.also_in.includes(f)))

/** Whether two pairs of lists hold the same folders, in any order. */
const same = (a: Lists, b: Lists) => [a.also_in, a.read_in].every((list, at) => [...list].sort().join('\n') === [...[b.also_in, b.read_in][at]].sort().join('\n'))

/** A path by its last two names (`Desktop\Skyulf`); the whole of it is said in its title. */
const short = (path: string) => path.replace(/^.*[\\/](?=[^\\/]+[\\/][^\\/]+$)/, '')

const said = (access: Access) => (access === 'write' ? 'read & write' : 'read')

const row = (p: Project, at?: string) => (
  <>
    <FolderSimple size={16} weight="fill" className="folder-icon" aria-hidden />
    <span className="folder-row-name">
      <b>{p.name}</b>
      <span className="mono muted folder-row-path">
        {p.root_path}
        {at && ` · ${since(at)} ago`}
      </span>
    </span>
  </>
)

interface ChoicesProps {
  projects: Project[]
  /** Every chat, the latest first: a folder was last used when its newest chat was. */
  conversations: ListedConversation[]
  /** The folder not offered, as its tab ('none': no folder): the open chat's. */
  except?: string
  onPick: (to: Project | null) => void
  /** "Open a folder…": KOLONİ's folder browser, to open where it is said (null: the home folder). */
  onBrowse: (start: string | null) => void
}

/** The folders to go to (slice 86a), the latest used first, "Open a folder…" and "No folder": the folder button's, and the tabs' "+" (86e). */
export function FolderChoices({ projects, conversations, except, onPick, onBrowse }: ChoicesProps) {
  const usedAt = (p: Project) => conversations.find(c => c.project_id === p.id)?.updated_at
  const recent = projects
    .filter(p => p.id !== except)
    .map(p => [p, usedAt(p)] as const)
    .sort(([a, aAt], [b, bAt]) => Date.parse(bAt ?? b.created_at) - Date.parse(aAt ?? a.created_at))
  // Beside the folder worked in last: its parent, or the home folder.
  const near = projects.find(p => p.id === except)?.root_path ?? recent[0]?.[0].root_path
  return (
    <ul className="folder-list">
      {recent.map(([p, at]) => (
        <li key={p.id}>
          <button type="button" className="folder-row" onClick={() => onPick(p)}>
            {row(p, at)}
          </button>
        </li>
      ))}
      <li>
        <button type="button" className="folder-row" onClick={() => onBrowse(near ? parentOf(near) : null)}>
          Open a folder…
        </button>
      </li>
      {except !== 'none' && (
        <li>
          <button type="button" className="folder-row" onClick={() => onPick(null)}>
            No folder <span className="muted">· a plain chat</span>
          </button>
        </li>
      )}
    </ul>
  )
}

interface AlsoProps {
  project: Project
  projects: Project[]
  conversation: Conversation
  onChange: (lists: Lists) => Promise<void>
  onDefault: (lists: Lists) => Promise<void>
  /** "+ Add a folder": KOLONİ's folder browser opens, to add one to read in. */
  onAdd: () => void
}

/**
 * "Also in this chat" (slice 86b, in the folder button's panel since): each other folder the chat's agents use - read,
 * or read & write, turned with a click -, taken off with ×, added from the folder browser, and saved as the folder's
 * default for its next chats: all of them, or one at a time ("Keep for this project", also for one an agent's card added).
 */
function AlsoInChat({ project, projects, conversation, onChange, onDefault, onAdd }: AlsoProps) {
  // The places never opened, read once there is an other folder to say them of.
  const [never, setNever] = useState<string[]>([])
  const rows = rowsOfChat(conversation)
  const extra = rows.length > 0
  useEffect(() => {
    if (!extra) return
    api.get<Folders>('/folders').then(
      read => setNever(read.never.map(place => place.path)),
      () => {}, // (only what is said of a folder is missed: nothing of it is opened by this)
    )
  }, [extra])
  const [error, setError] = useState<string | null>(null)
  const lists = listsOf(rows)

  async function save(change: () => Promise<void>) {
    setError(null)
    try {
      await change()
    } catch (err) {
      setError(errorText(err))
    }
  }
  const access = (path: string, to: Access) => save(() => onChange(listsOf(rows.map(r => (r.path === path ? { ...r, access: to } : r)))))
  // One folder onto the project's default, at this access, the rest of it kept: not offered for one a default folder holds
  // at that access already (write covers read).
  const defaults = rowsOfChat(project)
  const kept = (r: FolderRow) => defaults.some(d => holds(d.path, r.path) && (d.access === 'write' || r.access === 'read'))
  const keep = (r: FolderRow) => save(() => onDefault(listsOf([...defaults.filter(d => d.path !== r.path), r])))
  const closed = (path: string) => never.some(place => holds(path, place))
  const notes = rows.flatMap(r => [
    ...(closed(r.path) ? [`${r.path}: ${HOLDS}`] : []),
    ...(r.access === 'write' && (closed(r.path) || projects.some(p => holds(r.path, p.root_path))) ? [`${r.path}: ${WIDE}`] : []),
  ])

  return (
    <section aria-label="Also in this chat">
      <div className="kicker">Also in this chat</div>
      {rows.map(row => {
        const other = row.access === 'write' ? 'read' : 'write'
        return (
          <div key={row.path} className="folder-row">
            <span className="mono folder-row-name" title={row.path}>
              {short(row.path)}
            </span>
            <button
              type="button"
              className={`tag chat-folder-access${row.access === 'write' ? ' tag-accent' : ''}`}
              aria-label={`Access to ${row.path}: ${said(row.access)}; click for ${said(other)}`}
              onClick={() => void access(row.path, other)}
            >
              {said(row.access)}
            </button>
            {!kept(row) && (
              <button
                type="button"
                className="link-btn"
                aria-label={`Keep ${row.path} for this project`}
                title={`New chats in ${project.name} start with it too`}
                onClick={() => void keep(row)}
              >
                Keep for this project
              </button>
            )}
            <button
              type="button"
              className="icon-btn"
              aria-label={`Remove ${row.path} from this chat`}
              onClick={() => void save(() => onChange(listsOf(rows.filter(r => r.path !== row.path))))}
            >
              <X size={12} />
            </button>
          </div>
        )
      })}
      <div className="folder-row">
        <button type="button" className="link-btn" onClick={onAdd}>
          + Add a folder
        </button>
        {!same(lists, listsOf(rowsOfChat(project))) && (
          <button type="button" className="link-btn" onClick={() => void save(() => onDefault(lists))}>
            Save as this folder’s default
          </button>
        )}
      </div>
      {notes.map(note => (
        <p key={note} className="tag tag-warn folder-wide">
          {note}
        </p>
      ))}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
    </section>
  )
}

/**
 * K-buyuk-proje: where in its folder the chat's agents work - all of it, or one of the parts its map found. Shown only
 * where the map has a part besides the root (or the chat is set to one); the Lead may still give a sub-agent another.
 */
function PartPicker({ project, conversation, onPart }: { project: Project; conversation: Conversation; onPart: (part: string | null) => Promise<void> }) {
  const [parts, setParts] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.get<ProjectMap>(`/projects/${project.id}/map`).then(
      map => setParts(map.parts.map(part => part.path).filter(path => path !== './')),
      () => {}, // (no map read: no part offered, the chat stays as it is)
    )
  }, [project.id])
  const chosen = conversation.part ?? ''
  if (!parts.length && !chosen) return null
  return (
    <section aria-label="Where agents work">
      <label className="kicker" htmlFor="chat-part">
        Agents work in
      </label>
      <select
        id="chat-part"
        className="input"
        value={chosen}
        onChange={async e => {
          setError(null)
          try {
            await onPart(e.target.value || null)
          } catch (err) {
            setError(errorText(err))
          }
        }}
      >
        <option value="">Whole project</option>
        {[...new Set([...parts, ...(chosen ? [chosen] : [])])].map(path => (
          <option key={path} value={path}>
            {path}
          </option>
        ))}
      </select>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
    </section>
  )
}

/**
 * The folder button in the top bar (slice 86a): the open chat's main folder, and in its panel ("This chat's
 * folders") the folders to switch to - the latest used first -, "Open a folder…" and "No folder". A chat that
 * changed files there keeps its folder: the server says why, and a new chat in the other folder is offered. The
 * chat's other folders are counted on it, and listed in its panel (86b).
 */
export function FolderButton({ project, projects, conversations, conversation, onFolders, onDefault, onMove, onPart, onNew, onOpenFolder, onBrowse }: Props) {
  const { open, setOpen, close, button, panel } = usePanel()
  const [changing, setChanging] = useState(false)
  // What the server refused, and the folder it was refused for: a new chat there is offered for a 409.
  const [refused, setRefused] = useState<{ why: string; to: Project | null; offer: boolean } | null>(null)
  // Where the folder browser opened (false: it is closed), kept as it was when it opened.
  const [browsing, setBrowsing] = useState<string | null | false>(false)
  // The folder browser is open to add one of the chat's other folders.
  const [adding, setAdding] = useState(false)
  // Closed, the browser gives the focus back to this button - once the page behind it is no longer out of reach.
  const browsed = useRef(false)
  useEffect(() => {
    const away = browsing !== false || adding
    if (!away && browsed.current) button.current?.focus()
    browsed.current = away
  }, [browsing, adding, button])
  const others = conversation ? listsOf(rowsOfChat(conversation)) : null
  const count = others ? others.also_in.length + others.read_in.length : 0
  const name = project?.name ?? 'No folder'

  async function move(to: Project | null) {
    setRefused(null)
    try {
      await onMove(to?.id ?? null)
      return true
    } catch (err) {
      setRefused({ why: errorText(err), to, offer: err instanceof ApiError && err.status === 409 })
      setOpen(true)
      return false
    }
  }
  async function newChat(to: Project | null) {
    try {
      await onNew(to?.id ?? null)
      close()
    } catch (err) {
      setRefused({ why: errorText(err), to, offer: false })
    }
  }
  const browse = (start: string | null) => {
    close()
    setBrowsing(start)
  }

  return (
    <>
      <button
        ref={button}
        id="folder-button"
        type="button"
        className="folder-button"
        aria-expanded={open}
        aria-label={`Folder: ${name}${count ? `, and ${count} more folder${count === 1 ? '' : 's'} in this chat` : ''}`}
        title="This chat’s folders"
        onClick={() => {
          if (open) return close()
          setRefused(null)
          setChanging(false)
          setOpen(true)
        }}
      >
        <FolderSimple size={14} weight="fill" className="folder-icon" aria-hidden />
        <span className="folder-button-name">{name}</span>
        {count > 0 && <span className="tag tag-accent">+{count}</span>}
        <CaretDown size={11} aria-hidden />
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel folder-panel" role="dialog" aria-label="This chat’s folders">
          <h3 className="folder-panel-title">This chat’s folders</h3>
          <div className="kicker">Main folder: agents work here, commands run here</div>
          <div className="folder-row folder-row-on">
            {project ? (
              row(project)
            ) : (
              <span className="folder-row-name">
                <b>No folder</b>
                <span className="muted">A plain chat: no files and no commands</span>
              </span>
            )}
            {project && (
              // (At work too: a chat that has a turn keeps its folder, a new chat opens in the other - slice 86e.)
              <button type="button" className="btn btn-small" aria-expanded={changing} onClick={() => setChanging(!changing)}>
                Change <CaretDown size={11} aria-hidden />
              </button>
            )}
          </div>
          {project && conversation && <PartPicker project={project} conversation={conversation} onPart={onPart} />}
          {refused && (
            <div role="alert" className="folder-refused">
              <p className="alert">{refused.why}</p>
              {refused.offer && (
                <button type="button" className="btn btn-small btn-primary" onClick={() => void newChat(refused.to)}>
                  {refused.to ? `Open a new chat in ${refused.to.name}` : 'Open a new chat with no folder'}
                </button>
              )}
            </div>
          )}
          {project && conversation && (
            <AlsoInChat
              project={project}
              projects={projects}
              conversation={conversation}
              onChange={onFolders}
              onDefault={onDefault}
              onAdd={() => {
                // (The browser stands beside the app: a click in it would close the panel, and the browser in it.)
                close()
                setAdding(true)
              }}
            />
          )}
          {(changing || !project) && (
            <section aria-label="Switch the main folder">
              <div className="kicker">Switch the main folder</div>
              {project && <p className="muted">A chat with messages keeps its folder: a new chat opens in the one you pick.</p>}
              <FolderChoices projects={projects} conversations={conversations} except={project?.id ?? 'none'} onPick={to => void move(to).then(moved => moved && close())} onBrowse={browse} />
            </section>
          )}
        </div>
      )}
      {browsing !== false && (
        <FolderBrowser
          start={browsing}
          onBrowse={onBrowse}
          onCancel={() => setBrowsing(false)}
          onOpen={async path => {
            const to = await onOpenFolder(path)
            setBrowsing(false)
            await move(to)
          }}
        />
      )}
      {adding && project && others && (
        <FolderBrowser
          adding
          // Beside the main folder: the folder it is in.
          start={parentOf(project.root_path)}
          onBrowse={onBrowse}
          onCancel={() => setAdding(false)}
          onOpen={async path => {
            await onFolders({ ...others, read_in: [...others.read_in, path] })
            setAdding(false)
          }}
        />
      )}
    </>
  )
}
