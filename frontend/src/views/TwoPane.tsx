/**
 * The Workspace window's body (slices 42a, 42c), as VS Code has it: the files on the left, as a tree
 * by their folders, and what is opened on the right. The tree is one stop in the tab order (arrows
 * within it); which folders are open is the caller's (it reads a folder as it opens), the files'
 * width as dragged is kept in this browser. In a narrow window the files are hidden at first, a
 * button away.
 */
import { SidebarSimple } from '@phosphor-icons/react'
import { type KeyboardEvent, type PointerEvent, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'

export interface TreeFile {
  id: string
  /** Where it is in the tree, by '/': the folders it is in, then its name. */
  path: string
  /** What hovering it says: its path, and who wrote it. */
  title: string
  /** How it stands, in words: said after its name. */
  meta: string
  /** What is shown beside its name instead of the words, if not the words. */
  mark?: ReactNode
  /** New: not seen yet. */
  dot?: boolean
  /** A folder: one of its own, though nothing in it is read yet (its `meta`, if any, said after its name: a count). */
  folder?: boolean
  /** A folder before its sibling folders by this (lower first), then by name: the Changes tab's lines, by time. */
  order?: number
  /** Changed in this conversation: its folders are dotted. */
  changed?: boolean
  /** Its folder, said after its name in the muted colour - a flat list (the Changes tab), as VS Code has it. */
  where?: string
}

interface Props {
  /** What this browser keeps the files' width under. */
  name: string
  /** What stands over the files: the "Files" kicker, or the Workspace's Files | Changes tabs. */
  title?: ReactNode
  /** The tree's name for a screen reader: what it lists. */
  label?: string
  /** The top level in the order given; below it folders first, then files, by name. */
  files: TreeFile[]
  selected: string | undefined
  /** A folder asked for from outside (the shared folder, B-163): chosen, and scrolled to once its row is there. */
  reveal?: { key: string; n: number }
  onOpen(id: string): void
  /** A folder, by its key ('/' and its path), open or not. */
  isOpen(key: string): boolean
  onFolder(key: string, open: boolean): void
  /** Above the tree, under its title. */
  head?: ReactNode
  children: ReactNode
}

/**
 * Narrower than this, a window has its files hidden at first. (520 less the 41px the Workspace window gives up to
 * end left of the canvas's buttons, K-66-kalan: it hides them on no stage where it did not before.)
 */
const NARROW = 479
const WIDTH = 200
const LEAST = 120
/** Dragged narrower than this, the files are hidden. */
const GONE = 80
const STEP = 16

/**
 * A box's width as it is laid out: hand `measure` to the box as its ref (it may come later). Null while not laid
 * out, or where nothing is (jsdom).
 */
export function useWidth() {
  const [el, measure] = useState<HTMLElement | null>(null)
  const [width, setWidth] = useState<number | null>(null)
  useLayoutEffect(() => {
    if (!el) return
    setWidth(el.clientWidth || null)
    if (typeof ResizeObserver === 'undefined') return
    const watch = new ResizeObserver(() => setWidth(el.clientWidth || null))
    watch.observe(el)
    return () => watch.disconnect()
  }, [el])
  return { measure, width: el ? width : null }
}

export function stored<T>(key: string, fallback: T, valid: (read: unknown) => boolean): T {
  try {
    const read: unknown = JSON.parse(localStorage.getItem(key) ?? 'null')
    return valid(read) ? (read as T) : fallback
  } catch {
    return fallback
  }
}
export function keep(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // it just does not persist
  }
}

interface Row {
  key: string
  name: string
  level: number
  parent: string | null
  folder: boolean
  file?: TreeFile
  /** A folder with a changed file in it. */
  changed: boolean
  setSize: number
  posInSet: number
}

type Node = { name: string; key: string; kids: Node[]; file?: TreeFile; note?: string; order?: number }
const changedIn = (node: Node): boolean => Boolean(node.file?.changed) || node.kids.some(changedIn)
const byName = (a: Node, b: Node) =>
  Number(Boolean(a.file)) - Number(Boolean(b.file)) || (a.order ?? 0) - (b.order ?? 0) || a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })

/** The rows shown: folders and files depth first, but in closed folders. */
function rowsOf(files: TreeFile[], isOpen: (key: string) => boolean): Row[] {
  const root: Node = { name: '', key: '', kids: [] }
  for (const file of files) {
    const parts = file.path.split('/').filter(Boolean)
    let at = root
    for (const [n, part] of parts.slice(0, file.folder ? undefined : -1).entries()) {
      const key = `/${parts.slice(0, n + 1).join('/')}`
      let next = at.kids.find(kid => kid.key === key)
      if (!next) at.kids.push((next = { name: part, key, kids: [] }))
      at = next
    }
    if (file.folder) Object.assign(at, { note: file.meta || undefined, order: file.order })
    else at.kids.push({ name: parts.at(-1) ?? file.path, key: file.id, kids: [], file })
  }
  const rows: Row[] = []
  const walk = (node: Node, level: number) =>
    (level === 1 ? node.kids : [...node.kids].sort(byName)).forEach((kid, n) => {
      rows.push({ key: kid.key, name: kid.note ? `${kid.name} · ${kid.note}` : kid.name, level, parent: node.key || null, folder: !kid.file, file: kid.file, changed: !kid.file && changedIn(kid), setSize: node.kids.length, posInSet: n + 1 })
      if (!kid.file && isOpen(kid.key)) walk(kid, level + 1)
    })
  walk(root, 1)
  return rows
}

export function TwoPane({ name, title, label = 'Files', files, selected, reveal, onOpen, isOpen, onFolder, head, children }: Props) {
  const box = useWidth()
  const tree = useRef<HTMLDivElement>(null)
  const narrow = (box.width ?? Infinity) < NARROW
  // Hidden or shown by the user; till then, as wide as the window allows.
  const [shown, setShown] = useState<boolean | null>(null)
  // The button pressed goes with what it hid or showed: the focus goes to the other one.
  const toggled = useRef(false)
  const hide = useRef<HTMLButtonElement>(null)
  const show = useRef<HTMLButtonElement>(null)
  function showFiles(yes: boolean) {
    toggled.current = true
    setShown(yes)
  }
  const open = shown ?? !narrow
  const [width, setWidth] = useState(() => stored(`koloni-${name}-files-width`, WIDTH, read => typeof read === 'number' && read >= LEAST && read < 2000))
  const [active, setActive] = useState<string | undefined>(selected)
  const drag = useRef<{ x: number; width: number } | null>(null)

  // A file opened from outside - a tab, a button, "View diff" - has its folders opened, and is where the arrows start.
  // (only as it is opened: a folder the user closes after stays closed)
  const where = files.find(f => f.id === selected)?.path
  useEffect(() => {
    if (!selected || where === undefined) return
    setActive(selected)
    const parts = where.split('/').filter(Boolean)
    for (const n of parts.slice(0, -1).keys()) onFolder(`/${parts.slice(0, n + 1).join('/')}`, true)
    // (as it is opened, not as the caller's callback changes)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, where])

  useEffect(() => {
    if (!toggled.current) return
    toggled.current = false
    ;(shown ? hide : show).current?.focus()
  }, [shown])

  const rows = rowsOf(files, isOpen)
  // (its row is there once the folders over it are read)
  const revealAt = reveal ? rows.findIndex(row => row.key === reveal.key) : -1
  useEffect(() => {
    if (!reveal || revealAt < 0) return
    setActive(reveal.key)
    tree.current?.querySelectorAll<HTMLElement>('[role="treeitem"]')[revealAt]?.scrollIntoView?.({ block: 'nearest' })
    // (once as it is asked for: not again as the tree around it changes)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reveal?.n, revealAt >= 0])
  const at = rows.findIndex(row => row.key === active)
  const current = at >= 0 ? at : 0
  function go(index: number) {
    const row = rows[Math.max(0, Math.min(rows.length - 1, index))]
    if (!row) return
    setActive(row.key)
    tree.current?.querySelectorAll<HTMLElement>('[role="treeitem"]')[rows.indexOf(row)]?.focus()
  }
  const toggle = (row: Row) => onFolder(row.key, !isOpen(row.key))
  function choose(row: Row) {
    setActive(row.key)
    if (row.file) onOpen(row.file.id)
    else toggle(row)
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const row = rows[current]
    if (!row) return
    const opened = row.folder && isOpen(row.key)
    const moves: Record<string, () => void> = {
      ArrowDown: () => go(current + 1),
      ArrowUp: () => go(current - 1),
      Home: () => go(0),
      End: () => go(rows.length - 1),
      ArrowRight: () => (row.folder ? (opened ? go(current + 1) : toggle(row)) : undefined),
      ArrowLeft: () => (opened ? toggle(row) : row.parent && go(rows.findIndex(r => r.key === row.parent))),
      Enter: () => choose(row),
      ' ': () => choose(row),
    }
    if (!moves[event.key]) return
    event.preventDefault()
    moves[event.key]()
  }

  // (the files leave the other pane 160px at least)
  const most = Math.max(LEAST, (box.width ?? 2000) - 160)
  // (a width kept in a wider window is held to this one)
  const across = Math.min(width, most)
  function resize(next: number) {
    if (next < GONE) return setShown(false)
    const kept = Math.round(Math.max(LEAST, Math.min(most, next)))
    setWidth(kept)
    keep(`koloni-${name}-files-width`, kept)
  }
  const edge = {
    onPointerDown(event: PointerEvent<HTMLDivElement>) {
      if (event.button !== 0) return
      drag.current = { x: event.clientX, width: across }
      event.currentTarget.setPointerCapture?.(event.pointerId)
    },
    onPointerMove(event: PointerEvent<HTMLDivElement>) {
      const start = drag.current
      if (start) resize(start.width + event.clientX - start.x)
    },
    onPointerUp() {
      drag.current = null
    },
    onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
      const by = { ArrowLeft: -STEP, ArrowRight: STEP }[event.key]
      if (!by) return
      event.preventDefault()
      resize(across + by)
    },
  }

  return (
    <div ref={box.measure} className="two-pane">
      {open && (
        <>
          <div className="two-pane-files" style={{ width: across }}>
            <div className="two-pane-head">
              {title ?? <span className="two-pane-title">Files</span>}
              <button ref={hide} type="button" className="icon-btn" aria-label="Hide files" title="Hide files" onClick={() => showFiles(false)}>
                <SidebarSimple size={14} />
              </button>
            </div>
            {head}
            <div ref={tree} role="tree" aria-label={label} className="tree" onKeyDown={onKeyDown}>
              {rows.map((row, n) => (
                <div
                  key={row.key}
                  role="treeitem"
                  aria-level={row.level}
                  aria-setsize={row.setSize}
                  aria-posinset={row.posInSet}
                  aria-expanded={row.folder ? isOpen(row.key) : undefined}
                  // (the folder asked for is chosen only while no file is: one row chosen at a time)
                  aria-selected={row.file ? row.key === selected : !selected && row.key === reveal?.key && row.key === active ? true : undefined}
                  aria-label={row.file ? [row.name, row.file.where && `in ${row.file.where}`, row.file.dot && 'new', row.file.meta].filter(Boolean).join(' ') : row.changed ? `${row.name} changed` : row.name}
                  title={row.file?.title}
                  tabIndex={n === current ? 0 : -1}
                  className={`tree-row${row.folder ? ' tree-folder' : ''}`}
                  style={{ paddingLeft: 8 + (row.level - 1) * 12 + (row.folder ? 0 : 16) }}
                  onClick={() => choose(row)}
                >
                  <span className="tree-name">{row.name}</span>
                  {row.file?.where && <span className="tree-where">{row.file.where}</span>}
                  {(row.file?.dot || row.changed) && <span className={row.changed ? 'tree-changed' : 'view-dot'} aria-hidden />}
                  {row.file && <span className="tree-meta mono">{row.file.mark ?? row.file.meta}</span>}
                </div>
              ))}
            </div>
          </div>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize files"
            aria-valuenow={across}
            aria-valuemin={LEAST}
            aria-valuemax={most}
            tabIndex={0}
            className="two-pane-edge"
            title="Drag, or the arrow keys: wider or narrower; to the left edge, hidden"
            {...edge}
          />
        </>
      )}
      {!open && (
        <div className="two-pane-rail">
          <button ref={show} type="button" className="icon-btn" aria-label="Show files" title="Show files" onClick={() => showFiles(true)}>
            <SidebarSimple size={14} />
          </button>
        </div>
      )}
      <div className="two-pane-main">{children}</div>
    </div>
  )
}
