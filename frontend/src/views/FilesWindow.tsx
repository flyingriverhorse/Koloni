import { ArrowsIn, ArrowsOut, Columns, DotsSixVertical, X } from '@phosphor-icons/react'
import { type KeyboardEvent, Suspense, lazy, useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Agent, FileChange, FileHistory, GitChange, ProjectEntry, ProjectFile, View } from '../api/types'
import { ChangeActions, type ChangeAction } from '../changes/ChangeActions'
import { CHANGE_LABEL } from '../changes/changeLabel'
import { inScratch } from '../changes/copies'
import { DiffView } from '../changes/DiffView'
import { useWorkingCopy } from '../changes/WorkingCopy'
import { AT_WORK } from '../agents/agentStatus'
import { LONGEST_COLOURED, MOST_COLOURED, colourLines, languageOf } from '../changes/highlight'
import { Markdown } from '../chat/Markdown'
import { commandStatus } from '../commands/commandStatus'
import { useMove } from '../shell/move'
import { useApp } from '../state/store'
import { DrawioView } from './DrawioView'
import { OfficeView } from './OfficeView'
import { Preview } from './Preview'
import { CLOSED, LIVE, changeRows, changeTree, changesCount, changesSaid, standsOn } from './changeGroups'
import { TwoPane, type TreeFile, keep, stored, useWidth } from './TwoPane'
import { FOLDER, type Item, PREVIEW_OF, STATUS_WORDS, fileName, keyOf, kindOf, srcOf } from './views'

interface Props {
  project: { id: string; root_path: string }
  /** K-dallar: a branch's full name - the window shows that branch read only, from git (Look in the git map). */
  branch?: string | null
  /** The conversation's changes in the project: each file's latest is the one it shows. */
  changes: FileChange[]
  /** What agents wrote or showed, and the servers they keep running (Previews). */
  views: Item[]
  /** The views not opened yet: a dot each. */
  fresh: string[]
  agents: Agent[]
  open: boolean
  /** The file it was asked to open, and how many times it was asked. */
  at: { key: string | null; n: number }
  /** As tall as the open chat, as a share of the canvas. */
  height: number
  expanded: boolean
  onExpand(): void
  onClose(): void
  /** These views were opened: no longer new. */
  onSeen(ids: string[]): void
  onDecide(changeId: string, action: ChangeAction): Promise<void>
  /** A press or a key in it: it is in use. */
  onTouch?(): void
}

/** What a change did to its file, as VS Code marks it: the letter, its colour, and in words. */
const LETTER: Record<FileChange['kind'], [letter: string, colour: string, words: string]> = {
  create: ['A', 'tree-mark-ok', 'added'],
  modify: ['M', 'tree-mark-warn', 'modified'],
  delete: ['D', 'tree-mark-del', 'deleted'],
}
/** Which list the Workspace's left pane shows: the project's files, or only what changed (K-degisenler). */
// shortcut: remembered per browser, not per project (the folders are per project); key it by the project if users miss that.
const LIST_KEY = 'koloni-files-list'
const LISTS = ['files', 'changes'] as const
type List = (typeof LISTS)[number]
/**
 * The Changes tab's files by name with their folder after it, or ("Show folders as a tree") in their folders - and which
 * of its groups and folders the user opened or shut (all open at first, but Closed).
 */
const SHAPE_KEY = 'koloni-changes-shape'
const OPEN_KEY = 'koloni-changes-open'
const SHAPES = ['flat', 'tree'] as const
type Shape = (typeof SHAPES)[number]
const PREVIEWS = 'Previews'
// What agents changed in their working copies so far (slice 70), each copy one entry: `copy:` and its agent's id.
const COPIES = 'Working copies'
const SPLIT_KEY = 'koloni-diff-split'
/**
 * Narrower than this, a diff is one column whatever was chosen: on a 1280-1366 px screen the window as it opens
 * is wider (577-620 px) once its files are hidden.
 */
const SIDE_BY_SIDE = 560
// three.js comes with it, only once a model opens (slice 58): the app's own bundle stays as it was.
const ModelView = lazy(() => import('./ModelView').catch(() => ({ default: () => <p className="view-empty muted">The 3D view could not be loaded.</p> })))
const outside = (key: string) => /^([a-z]:)?\//i.test(key)
const at = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
// K-dallar: what a question about the project's files adds to read a branch instead.
const onBranch = (branch: string | null) => (branch ? `&ref=${encodeURIComponent(branch)}` : '')
const NONE: never[] = []

/**
 * The Workspace window (slice 42c; named so in 42d), beside the chat as the view window was (slice 39): the project's
 * own tree as VS Code has it, its folders read as they open, what this conversation changed marked
 * on it (M / A / D, a dot while it waits for you) and the servers agents keep running above it.
 * A file opened shows its latest change, or its preview - a page or a drawing in a sandboxed frame
 * of an origin of its own whose script runs only once asked for - or its code, read only. Dragged
 * by its header anywhere on the canvas (slice 38e); kept on the page while closed, as an empty box.
 * On a `branch` (K-dallar) it shows that branch from git, read only: its tree, a file's code, and as Changes what
 * it changed since it left the project's branch - nothing of this conversation's, nothing checked out.
 */
export function FilesWindow({ project, branch = null, changes: ours, views: shown, fresh, agents, open, at: asked, height, expanded, onExpand, onClose, onSeen, onDecide, onTouch }: Props) {
  const changes = branch ? NONE : ours
  const views = branch ? NONE : shown
  const rootName = project.root_path.split(/[\\/]/).filter(Boolean).at(-1) ?? 'project'
  const rootKey = `/${rootName}`
  const [tabs, setTabs] = useState<string[]>([])
  const [chosen, setChosen] = useState<string | null>(null)
  // The pages whose script the user chose to run: they run, written again or not, until the app is left.
  const [running, setRunning] = useState<ReadonlySet<string>>(new Set())
  // K-39-betik: "Always run in this chat" - its pages run their scripts without asking.
  const always = useApp(s => s.conv?.conversation.page_scripts ?? false)
  // (Changes: the chat's merges say how its copies stand; your messages, where each change came from.)
  const merges = useApp(s => s.conv?.merges ?? NONE)
  const messages = useApp(s => s.conv?.messages ?? NONE)
  // B-165: the file the chat's last `show` put before the user, as its result names it - on record, so over a reload too.
  const lastShown = useApp(s => /^shown: (.+) is in the view/.exec(s.conv?.toolCalls.filter(c => c.name === 'show' && c.status === 'succeeded').at(-1)?.result ?? '')?.[1] ?? null)
  const folderKey = `koloni-files-folders-${project.id}`
  const [folders, setFolders] = useState<Record<string, boolean>>(() => stored(folderKey, {}, read => typeof read === 'object' && read !== null && !Array.isArray(read)))
  const [list, setList] = useState<List>(() => stored(LIST_KEY, 'files', read => LISTS.includes(read as List)))
  function chooseList(next: List) {
    setList(next)
    keep(LIST_KEY, next)
  }
  const [shape, setShape] = useState<Shape>(() => stored(SHAPE_KEY, 'flat', read => SHAPES.includes(read as Shape)))
  function chooseShape(next: Shape) {
    setShape(next)
    keep(SHAPE_KEY, next)
  }
  // The groups and folders of Changes the user opened or shut, by their key - this browser's, whatever the project.
  const [changesOpen, setChangesOpen] = useState<Record<string, boolean>>(() => stored(OPEN_KEY, {}, read => typeof read === 'object' && read !== null && !Array.isArray(read)))
  const asTree = list === 'changes' && shape === 'tree'
  const box = useRef<HTMLElement>(null)
  const tabList = useRef<HTMLDivElement>(null)
  const move = useMove('koloni-view-spot', box)
  const moved = move.moved && !expanded
  const who = (id: string | null) => {
    const agent = agents.find(a => a.id === id)
    return agent ? agent.name || agent.role_name : 'an agent'
  }

  function show(key: string) {
    setTabs(was => (was.includes(key) ? was : [...was, key]))
    setChosen(key)
  }
  const [took, setTook] = useState(0)
  // The file asked for on its preview, and by which ask: asked again, it opens on it again.
  const [previewAsk, setPreviewAsk] = useState<{ key: string; n: number } | null>(null)
  const [reveal, setReveal] = useState<{ key: string; n: number } | undefined>()

  // Each file once: the change it stands on (no versions, slice 42c §3) - in Files one in a copy too; in Changes not.
  const latest = standsOn(changes, true)
  const record = standsOn(changes)
  const servers = views.filter(v => v.kind === 'server')
  const files = views.filter((v): v is View => v.kind !== 'server')
  const viewOf = (key: string) => files.find(v => keyOf(v.path) === key)
  const inTree = (path: string) => (outside(path) ? path : `${rootName}/${path}`)
  // Each file's path as written, by its key (which may be folded to one case: `keyOf`).
  const named = new Map<string, string>()
  function nameIn(key: string, path: string) {
    if (!named.has(key)) named.set(key, path.replaceAll('\\', '/'))
    return named.get(key) as string
  }

  // The folders read so far, by their path in the project ('' the root), and when: read again as
  // changes come and are decided, and as it opens - each kept on screen till its new answer comes.
  // B-338: and as the user comes back to the page (a file added outside KOLONİ), at most every 2 s.
  const [back, setBack] = useState(0)
  useEffect(() => {
    if (!open) return
    let last = Date.now()
    const again = () => {
      if (document.visibilityState !== 'visible' || Date.now() - last < 2000) return
      last = Date.now()
      setBack(n => n + 1)
    }
    window.addEventListener('focus', again)
    document.addEventListener('visibilitychange', again)
    return () => {
      window.removeEventListener('focus', again)
      document.removeEventListener('visibilitychange', again)
    }
  }, [open])
  const stamp = `${open} ${back} ${changes.map(c => c.id + c.status).join(' ')}`
  const [read, setRead] = useState<Record<string, { at: string; list: ProjectEntry[] | null }>>({})
  const asking = useRef(new Set<string>())
  // What git says is changed (K-degisenler), asked as the folders are - once a stamp, kept on screen till the new
  // answer comes; null where the project shows no git, or git did not answer (`failed`). The latest question's answer is the one kept.
  const [gitList, setGitList] = useState<{ at: string; list: GitChange[] | null; failed?: boolean }>()
  const gitAsk = useRef(0)
  useEffect(() => {
    if (!open) return
    const n = ++gitAsk.current
    api.get<GitChange[] | null>(`/projects/${project.id}/changes${branch ? `?ref=${encodeURIComponent(branch)}` : ''}`).then(
      found => n === gitAsk.current && setGitList({ at: stamp, list: Array.isArray(found) ? found : null }),
      () => n === gitAsk.current && setGitList({ at: stamp, list: null, failed: true }),
    )
  }, [open, stamp, project.id, branch])
  const inGit = new Map((gitList?.list ?? []).map(c => [keyOf(c.path), c.status]))

  const entries = new Map<string, TreeFile>()
  for (const v of servers)
    entries.set(`preview:${v.id}`, {
      id: `preview:${v.id}`,
      path: `${PREVIEWS}/${v.path}`,
      title: `${v.command.command} · ${commandStatus(v.command).label} · by ${who(v.command.agent_id)}`,
      meta: commandStatus(v.command).label,
      dot: fresh.includes(v.id),
    })
  for (const a of agents.filter(a => !branch && a.copy?.state === 'own' && AT_WORK.has(a.status)))
    entries.set(`copy:${a.id}`, { id: `copy:${a.id}`, path: `${COPIES}/${who(a.id)}'s copy`, title: `What ${who(a.id)} changed in its working copy so far`, meta: 'working copy' })
  entries.set(rootKey, { id: rootKey, path: rootName, folder: true, title: project.root_path, meta: '' })
  for (const [folder, { list }] of Object.entries(read))
    for (const entry of list ?? []) {
      const path = folder ? `${folder}/${entry.name}` : entry.name
      const id = entry.kind === 'dir' ? `${rootKey}/${path}` : keyOf(path)
      if (entry.kind !== 'dir') nameIn(id, path)
      entries.set(id, { id, path: inTree(path), folder: entry.kind === 'dir', title: path, meta: '' })
    }
  for (const v of files) {
    const key = keyOf(v.path)
    const path = nameIn(key, v.path)
    if (!entries.has(key)) entries.set(key, { id: key, path: inTree(path), title: path, meta: STATUS_WORDS[v.status] })
  }
  for (const [key, change] of latest) {
    const [letter, tone, words] = LETTER[change.kind]
    const path = nameIn(key, change.path)
    const live = LIVE.includes(change.status)
    // In the project since its change, and not on disk now: deleted by hand (B-55), as the server read the disk.
    const gone = change.gone
    const said = [CHANGE_LABEL[change.status][0], ...(gone ? ['not on disk now'] : [])]
    entries.set(key, {
      id: key,
      path: inTree(path),
      title: [path, ...said, `by ${who(change.agent_id)}`, at(change.created_at)].join(' · '),
      meta: [words, ...said].join(', '),
      // (A scratch write stays in the tree, where its card opens it; the Changes tab leaves it out.)
      changed: live && !inScratch(change.path),
      mark: gone ? (
        'Gone'
      ) : live ? (
        <>
          <span className={tone}>{letter}</span>
          {change.status === 'proposed' && <span className="tree-wait" />}
        </>
      ) : (
        CHANGE_LABEL[change.status][0]
      ),
    })
  }
  for (const [key, entry] of entries) {
    const view = viewOf(key)
    if (view && fresh.includes(view.id)) entry.dot = true
  }
  // The Changes tab (K-degisenler; sample A, 7 Nov): this chat's record and what git says changed, by what you have to do.
  const changeList = changeRows({ changes, git: gitList?.list, agents, merges, messages, name: who, branch })
  for (const row of changeList) if (!row.key.startsWith('copy:')) nameIn(row.key, row.path)
  const changedRows = changeTree(changeList, asTree)
  function onListKey(event: KeyboardEvent<HTMLDivElement>) {
    const at = LISTS.indexOf(list)
    const to = ({ ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: LISTS.length - 1 } as Record<string, number>)[event.key]
    if (to === undefined) return
    event.preventDefault()
    const next = LISTS[(to + LISTS.length) % LISTS.length]
    chooseList(next)
    event.currentTarget.querySelector<HTMLElement>(`[data-list="${next}"]`)?.focus()
  }

  // Open: what the user left open; till then the root, the Previews, and the folders of a changed file.
  const changedFolders = new Set(
    [...entries.values()].filter(e => e.changed).flatMap(e => e.path.split('/').slice(0, -1).map((_, n, parts) => `/${parts.slice(0, n + 1).join('/')}`)),
  )
  const atFirst = (key: string) => key === rootKey || key === `/${PREVIEWS}` || key === `/${COPIES}` || changedFolders.has(key)
  const isOpen = (key: string) => folders[key] ?? atFirst(key)
  function onFolder(key: string, opened: boolean) {
    setFolders(was => {
      if ((was[key] ?? atFirst(key)) === opened) return was
      const next = { ...was, [key]: opened }
      keep(folderKey, next)
      return next
    })
  }
  function isChangesOpen(key: string) {
    return changesOpen[key] ?? key !== `/${CLOSED}`
  }
  function onChangesFolder(key: string, opened: boolean) {
    setChangesOpen(was => {
      if ((was[key] ?? key !== `/${CLOSED}`) === opened) return was
      // (what is no longer in the list is let go)
      const next = Object.fromEntries(Object.entries({ ...was, [key]: opened }).filter(([at]) => changedRows.some(row => `/${row.path}/`.startsWith(`${at}/`))))
      keep(OPEN_KEY, next)
      return next
    })
  }
  // What the left pane lists: the project's files, or what changed - each with which of its folders are open.
  const pane = list === 'changes' ? { files: changedRows, label: 'Changes', isOpen: isChangesOpen, onFolder: onChangesFolder, on: record } : { files: [...entries.values()], label: 'Files', isOpen, onFolder, on: latest }
  // Each open folder of the project is read, one level, once a stamp.
  const want = (
    open
      ? [rootKey, ...[...entries.values()].filter(e => e.folder).map(e => e.id)]
          .filter(key => isOpen(key) && (key === rootKey || key.startsWith(`${rootKey}/`)))
          .map(key => key.slice(rootKey.length + 1))
          .filter(folder => read[folder]?.at !== stamp)
      : []
  ).join('\n')
  useEffect(() => {
    for (const folder of want ? want.split('\n') : []) {
      const ask = `${stamp}\n${folder}`
      if (asking.current.has(ask)) continue
      asking.current.add(ask)
      const done = (list: ProjectEntry[] | null) => {
        asking.current.delete(ask)
        setRead(was => ({ ...was, [folder]: { at: stamp, list } }))
      }
      // (a folder that is not there - one a change will make, or took away - is empty)
      api.get<ProjectEntry[]>(`/projects/${project.id}/files?path=${encodeURIComponent(folder)}${onBranch(branch)}`).then(
        list => done(Array.isArray(list) ? list : null),
        () => done(null),
      )
    }
  }, [want, stamp, project.id, branch])

  // The files whose change waits for you, by path: "Next waiting" goes through them.
  const waiting = [...latest].filter(([, c]) => c.status === 'proposed').map(([key]) => key).sort()
  const next = () => show(waiting[(waiting.indexOf(chosen ?? '') + 1) % waiting.length])
  // Asked from outside - "View diff", a change that waits: that file, on a tab; its button, with nothing
  // open: what waits, else what is new.
  if (asked.n !== took) {
    setTook(asked.n)
    // A folder (K-shared-bagli: the shared folder, from the canvas's column): it and the folders over it, open -
    // the project's own too - and it chosen in the tree, in view (B-163).
    const parts = asked.key?.startsWith(FOLDER) ? asked.key.slice(FOLDER.length).split('/') : []
    if (parts.length) {
      onFolder(rootKey, true)
      setReveal({ key: `${rootKey}/${parts.join('/')}`, n: asked.n })
    }
    for (const n of parts.keys()) onFolder(`${rootKey}/${parts.slice(0, n + 1).join('/')}`, true)
    const fresher = views.find(v => fresh.includes(v.id))
    // (Else, as it first opens - after a reload too - what was last shown, while it is there: B-165. Its tab closed
    // later, it is not opened again.)
    const shownLast = took === 0 && lastShown !== null && files.find(v => keyOf(v.path) === keyOf(lastShown) && (v.sha || v.too_large))
    const previewing = asked.key?.startsWith(PREVIEW_OF) ? keyOf(asked.key.slice(PREVIEW_OF.length)) : null
    setPreviewAsk(previewing ? { key: previewing, n: asked.n } : null)
    const key = previewing ?? asked.key ?? (chosen ? null : (waiting[0] ?? (fresher && (fresher.kind === 'server' ? `preview:${fresher.id}` : keyOf(fresher.path))) ?? (shownLast ? keyOf(shownLast.path) : null)))
    if (key && !parts.length) show(key)
  }

  // What is shown is seen.
  const server = servers.find(v => `preview:${v.id}` === chosen)
  const shownView = chosen ? (server ?? viewOf(chosen)) : undefined
  const seen = open && shownView && fresh.includes(shownView.id) ? shownView.id : null
  useEffect(() => {
    if (seen) onSeen([seen])
  }, [seen, onSeen])

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== 'Escape') return
    event.stopPropagation()
    onClose()
  }
  function closeTab(key: string) {
    const left = tabs.filter(other => other !== key)
    setTabs(left)
    if (chosen === key) setChosen(left.at(-1) ?? null)
    // (the focus stays among the tabs: on the one shown now)
    requestAnimationFrame(() => tabList.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus())
  }
  const nameOf = (key: string) =>
    key.startsWith('copy:') ? `${who(key.slice(5))}'s copy` : key.startsWith('preview:') ? (servers.find(v => `preview:${v.id}` === key)?.path ?? key) : fileName(named.get(key) ?? key)
  // B-165: two tabs of one name ("index.html" at the root and in game/) - the one in a folder says its folder.
  // shortcut: only its own folder is said, so files in folders of one name (a/game, b/game) still read alike; say more of the path if met.
  const tabName = (key: string) => {
    const [name, path] = [nameOf(key), named.get(key) ?? key]
    return path.includes('/') && tabs.some(other => other !== key && nameOf(other) === name) ? path.split('/').slice(-2).join('/') : name
  }
  const change = chosen ? pane.on.get(chosen) : undefined
  const view = chosen ? viewOf(chosen) : undefined
  return (
    <section
      ref={box}
      id="files-window"
      className={`view-panel${expanded ? ' view-panel-wide' : ''}${moved ? ' moved' : ''}`}
      aria-label="Workspace"
      hidden={!open}
      // (As tall as the chat less the row it stands on: base.css.)
      style={expanded ? undefined : { ['--h' as string]: `${height * 100}%`, ...(moved ? move.style : {}) }}
      onKeyDown={onKeyDown}
      onPointerDownCapture={onTouch}
      onKeyDownCapture={onTouch}
    >
      {open && (
        <>
          <div className="view-top" {...(expanded ? {} : move.header)}>
            {!expanded && (
              <span className="move-grip" aria-label="Move workspace" title="Move workspace: drag, or the arrow keys; a double click or Enter puts it back" {...move.handle}>
                <DotsSixVertical size={14} />
              </span>
            )}
            <div ref={tabList} className="view-tabs" role="tablist" aria-label="Open files">
              {/* A tab's × is for the mouse; from the keyboard Delete closes it (a tablist holds tabs only). */}
              {tabs.map(key => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={key === chosen}
                  aria-keyshortcuts="Delete"
                  className="view-tab"
                  title={`${named.get(key) ?? key} - Delete closes the tab (the file stays in the tree)`}
                  onClick={() => setChosen(key)}
                  onKeyDown={event => event.key === 'Delete' && closeTab(key)}
                >
                  {tabName(key)}
                  <span
                    className="view-tab-close"
                    aria-hidden
                    onClick={event => {
                      event.stopPropagation()
                      closeTab(key)
                    }}
                  >
                    <X size={10} />
                  </span>
                </button>
              ))}
            </div>
            {/* At the right end, as a window's are (the user's, 6 Nov): Expand or Shrink, then Close last. */}
            <button type="button" className="icon-btn" aria-label={expanded ? 'Shrink workspace' : 'Expand workspace'} title={expanded ? 'Shrink workspace' : 'Expand workspace'} onClick={onExpand}>
              {expanded ? <ArrowsIn size={14} /> : <ArrowsOut size={14} />}
            </button>
            <button type="button" className="icon-btn" aria-label="Close workspace" title="Close workspace (Esc)" onClick={onClose}>
              <X size={14} />
            </button>
          </div>
          <TwoPane
            name="files"
            title={
              <div className="two-pane-tabs" role="tablist" aria-label="Show" onKeyDown={onListKey}>
                {LISTS.map(id => (
                  <button key={id} type="button" role="tab" data-list={id} aria-selected={list === id} tabIndex={list === id ? 0 : -1} className="two-pane-title" onClick={() => chooseList(id)}>
                    {/* (no count till git answered the first time: what it lists is not known yet) */}
                    {id === 'files' ? 'Files' : gitList ? `Changes · ${changesCount(changeList, gitList.list)}` : 'Changes'}
                  </button>
                ))}
              </div>
            }
            label={pane.label}
            files={pane.files}
            selected={chosen ?? undefined}
            reveal={reveal}
            onOpen={show}
            isOpen={pane.isOpen}
            onFolder={pane.onFolder}
            head={
              <>
                {branch && (
                  <p className="files-waiting" role="status">
                    <span>
                      <b className="mono">{branch.replace(/^refs\/(heads|remotes)\//, '')}</b> · read only{list === 'changes' && ', against your branch'}
                    </span>
                    <button type="button" className="link-btn" onClick={() => useApp.getState().openFiles()}>
                      Back to the project
                    </button>
                  </p>
                )}
                {list === 'changes' && (
                  <>
                    <p className="files-waiting muted" role="status">
                      {changesSaid(gitList?.at === stamp ? gitList : undefined, changeList.length, rootName, branch)}
                    </p>
                    <label className="files-waiting">
                      <input type="checkbox" checked={shape === 'tree'} onChange={event => chooseShape(event.target.checked ? 'tree' : 'flat')} />
                      Show folders as a tree
                    </label>
                  </>
                )}
                {waiting.length > 0 && (
                  <p className="files-waiting">
                    {/* (files whose change waits: the button counts what waits in the conversation, as the Board does) */}
                    <span>{waiting.length === 1 ? '1 file waits' : `${waiting.length} files wait`}</span>
                    <button type="button" className="link-btn" onClick={next}>
                      Next waiting <span aria-hidden>▸</span>
                    </button>
                  </p>
                )}
              </>
            }
          >
            {server && <Preview key={server.id} command={server.command} who={who(server.command.agent_id)} />}
            {chosen?.startsWith('copy:') && <CopyChanges agentId={chosen.slice(5)} stamp={agents.find(a => a.id === chosen.slice(5))?.last_event_at ?? ''} group={changeList.find(row => row.key === chosen)?.group} />}
            {!server && chosen && !chosen.startsWith('copy:') && (
              <Opened
                // (anew when a change comes to it: a changed file opens on its diff)
                key={`${chosen} ${Boolean(change)} ${inGit.get(chosen) ?? ''} ${list} ${previewAsk?.key === chosen ? previewAsk.n : ''}`}
                path={named.get(chosen) ?? chosen}
                change={change}
                inGit={inGit.get(chosen)}
                // (as VS Code: Explorer opens the code, Source Control the diff)
                asChanged={list === 'changes'}
                gitStamp={gitList?.at ?? ''}
                view={view}
                // B-187: the page the chat last put before the user opens as it was shown, not on its diff - but a change
                // of it that waits for you opens on its diff. So does an output asked for from the canvas (K-belge-ciktilari).
                shown={((lastShown !== null && keyOf(lastShown) === chosen) || previewAsk?.key === chosen) && change?.status !== 'proposed'}
                projectId={project.id}
                branch={branch}
                who={change ? who(change.agent_id) : view ? who(view.agent_id) : null}
                // (Always: only a page of this chat's own - not one of the project's it never made.)
                live={running.has(chosen) || (always && view !== undefined)}
                always={always && view !== undefined}
                onRun={on => setRunning(new Set(on ? [...running, chosen] : [...running].filter(key => key !== chosen)))}
                onDecide={action => (change ? onDecide(change.id, action) : Promise.resolve())}
              />
            )}
            {!chosen && <p className="view-empty muted">Pick a file in the tree.</p>}
          </TwoPane>
        </>
      )}
    </section>
  )
}

/** The way to a copy's card from Changes, by the group it is in: the card takes it in or throws it away. */
const TO_ITS_CARD: Record<string, string> = { 'Waits for you': 'Take in…', Kept: 'Look' }

/** An agent's working copy as its work goes on (slice 70): each file it changed so far, from what it was, with its diff. */
function CopyChanges({ agentId, stamp, group }: { agentId: string; stamp: string; group?: string }) {
  const copy = useWorkingCopy(agentId, stamp)
  const body = useWidth()
  if (copy === undefined) return null
  if (copy === null) return <p className="view-empty muted">Its working copy is not there any more: its work is over.</p>
  if (copy.files.length === 0) return <p className="view-empty muted">Nothing changed in its working copy yet.</p>
  const card = group && TO_ITS_CARD[group]
  return (
    <div ref={body.measure} className="changes-body">
      {card && (
        <p className="view-where">
          <button type="button" className={`btn btn-small${group === 'Kept' ? '' : ' btn-primary'}`} title="Its card, in the agent's window: Take in or Discard there" onClick={() => useApp.getState().select(`agent:${agentId}`)}>
            {card}
          </button>
        </p>
      )}
      {copy.files.map(file => (
        <section key={file.path} aria-label={file.path} className="copy-file" data-ask={file.path}>
          <p className="mono view-where">
            {file.path}{' '}
            <span style={{ color: 'var(--ok)' }}>+{file.additions}</span>{' '}
            <span style={{ color: 'var(--del)' }}>−{file.deletions}</span>
          </p>
          <DiffView diff={file.diff} path={file.path} split={(body.width ?? 0) >= SIDE_BY_SIDE} />
        </section>
      ))}
    </div>
  )
}

interface OpenedProps {
  path: string
  change: FileChange | undefined
  /** What git says of it (K-degisenler): changed in the working tree (a D is gone from disk). */
  inGit: GitChange['status'] | undefined
  /** Opened from the Changes tab: a file git says is changed opens on its diff against HEAD, not its code. */
  asChanged: boolean
  /** When git was last asked: the diff is read again with it. */
  gitStamp: string
  view: View | undefined
  /** The file the chat's last `show` put before the user: it opens on its preview. */
  shown: boolean
  projectId: string
  /** K-dallar: a branch read from git - its code and its diff only: no preview, nothing of KOLONİ's record. */
  branch: string | null
  who: string | null
  /** Its script runs: the user asked, for this page or for every page of the chat (`always`). */
  live: boolean
  always: boolean
  /** Its script runs from now on, or no longer (the page drawn again without it). */
  onRun(on: boolean): void
  onDecide(action: ChangeAction): Promise<void>
}

/** A file opened: its latest change, its preview or its code - a page, a drawing or a note either of the two. */
function Opened({ path, change, inGit, asChanged, gitStamp, view, shown, projectId, branch, who, live, always, onRun, onDecide }: OpenedProps) {
  const [declined, setDeclined] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const runAlways = (on: boolean) => {
    setError(null)
    useApp
      .getState()
      .setPageScripts(on)
      .catch(() => setError('It could not be saved. Try again.'))
  }
  // (a preview is drawn from the project's files, not the branch's)
  const kind = branch ? null : (view?.kind ?? kindOf(path))
  const gone = change?.kind === 'delete' || inGit === 'D'
  // (a change of this conversation shows its own diff; from the Changes tab, what git says changed shows its own)
  const diffed = change !== undefined || (asChanged && inGit !== undefined)
  const toggles = !gone && (kind === 'html' || kind === 'svg' || kind === 'md' || kind === 'model' || kind === 'drawio')
  // (a changed model opens on the model: its diff is numbers; a document's is no text at all)
  const [asCode, setAsCode] = useState((diffed && !DRAWN.has(kind ?? '') && !shown) || !kind)
  const body = useWidth()
  const wide = (body.width ?? Infinity) >= SIDE_BY_SIDE
  const [split, setSplit] = useState(() => stored(SPLIT_KEY, true, read => typeof read === 'boolean'))
  function chooseSplit() {
    setSplit(!split)
    keep(SPLIT_KEY, !split)
  }
  // Where its preview is loaded from: the view's address (it has the text not on disk yet), else the project's.
  const src = view ? srcOf(view) : outside(path) ? null : `/api/projects/${projectId}/raw/${path.split('/').map(encodeURIComponent).join('/')}`
  const showsCode = asCode || !kind || gone
  return (
    <>
      <div className="view-where">
        <p className="mono muted" title={path}>
          {path}
          {who && ` · ${who}`}
          {view?.note && <span className="view-note"> · {view.note}</span>}
        </p>
        {toggles && (
          <div className="files-modes" role="group" aria-label="Show">
            <button type="button" className="view-run" aria-pressed={!asCode} onClick={() => setAsCode(false)}>
              Preview
            </button>
            <button type="button" className="view-run" aria-pressed={asCode} onClick={() => setAsCode(true)}>
              {diffed ? 'Diff' : 'Code'}
            </button>
          </div>
        )}
      </div>
      {!outside(path) && !branch && <LastOnIt projectId={projectId} path={path} stamp={gitStamp} />}
      {/* K-39-betik: the page is drawn; its script runs only if you say - once, or for every page of this chat. */}
      {/* B-168: once you said Run once or Don't run, a line says so and lets you change your mind. */}
      {!showsCode && kind === 'html' && !view?.too_large && !always && (live || declined) && (
        <div className="view-where" role="group" aria-label="Its script">
          <p className="muted">{live ? 'Script ran once.' : 'Script not run.'}</p>
          <button
            type="button"
            className="view-run"
            onClick={() => {
              setDeclined(false)
              onRun(!live)
            }}
          >
            {live ? 'Ask each time' : 'Run once'}
          </button>
        </div>
      )}
      {!showsCode && kind === 'html' && !view?.too_large && (always || (!live && !declined)) && (
        <div className="view-where" role="group" aria-label={always ? 'Its script' : 'Run its script?'}>
          <p className="muted" title="A page's script can reach outside KOLONİ: its first step out and a WebRTC connection are not stopped">
            {always ? 'Scripts run in this chat without asking.' : 'Its script runs only if you say.'}
          </p>
          {always ? (
            <button type="button" className="view-run" onClick={() => runAlways(false)}>
              Ask each time
            </button>
          ) : (
            <>
              <button type="button" className="view-run" onClick={() => onRun(true)}>
                Run once
              </button>
              <button type="button" className="view-run" onClick={() => runAlways(true)}>
                Always run in this chat
              </button>
              <button type="button" className="view-run" onClick={() => setDeclined(true)}>
                Don’t run
              </button>
            </>
          )}
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {diffed && (
        <div className="changes-info">
          {change && (
            <>
              <span className="mono" style={{ color: 'var(--ok)' }}>
                +{change.additions}
              </span>
              <span className="mono" style={{ color: 'var(--del)' }}>
                −{change.deletions}
              </span>
              {(change.status === 'proposed' || change.status === 'applied') && <span className={CHANGE_LABEL[change.status][1]}>{CHANGE_LABEL[change.status][0]}</span>}
              <ChangeActions change={change} onDecide={onDecide} />
            </>
          )}
          {showsCode && (
            <button
              type="button"
              className="icon-btn"
              aria-label="Side by side"
              aria-pressed={split}
              disabled={!wide}
              title={wide ? 'Before and after side by side, or in one column' : 'Too narrow for two columns: hide the files, or expand the window'}
              onClick={chooseSplit}
            >
              <Columns size={14} />
            </button>
          )}
        </div>
      )}
      {/* (Selected code here can be asked about, by its path and lines: slice 80.) */}
      <div ref={body.measure} className={showsCode ? 'changes-body' : 'view-body'} data-ask={showsCode ? path : undefined}>
        {showsCode ? (
          change ? (
            <DiffView diff={change.diff} path={path} split={split && wide} readWhole={() => api.get<{ diff: string }>(`/file-changes/${change.id}/diff`).then(read => read.diff)} />
          ) : asChanged && inGit ? (
            <GitDiff projectId={projectId} path={path} branch={branch} stamp={gitStamp} split={split && wide} />
          ) : (
            <Code projectId={projectId} path={path} branch={branch} />
          )
        ) : view?.too_large ? (
          <p className="view-empty muted">Too large to show: over {kind === 'model' ? 50 : 5} MB.</p>
        ) : !src ? (
          <p className="view-empty muted">Outside the project: not previewed here.</p>
        ) : kind === 'image' ? (
          <img className="view-image" src={src} alt={path} />
        ) : kind === 'md' ? (
          <Note src={src} />
        ) : kind === 'model' ? (
          <Suspense fallback={<p className="view-empty muted">Loading the 3D view…</p>}>
            <ModelView src={src} name={fileName(path)} />
          </Suspense>
        ) : kind === 'pdf' ? (
          <PdfView key={src} src={src} path={path} />
        ) : kind === 'docx' || kind === 'xlsx' || kind === 'pptx' ? (
          <OfficeView key={src} src={src} path={path} kind={kind} />
        ) : kind === 'drawio' ? (
          // (by its path: written again, its text is posted to the same frame)
          <DrawioView key={path} src={src} path={path} projectId={projectId} />
        ) : (
          // (A drawing's script never runs: there is nothing in it to ask for.)
          <Frame key={`${src} ${live}`} src={src} title={path} live={live && kind === 'html'} />
        )}
      </div>
    </>
  )
}

/**
 * The last agents on this file (K-devir-4), one quiet line: each a link to that agent - or, in another chat, to that chat -
 * with what it did and whether that is in the project. Nothing where KOLONİ has nothing on record; read once a stamp, as the
 * diff is.
 */
function LastOnIt({ projectId, path, stamp }: { projectId: string; path: string; stamp: string }) {
  const [told, setTold] = useState<FileHistory[] | null>(null)
  const chat = useApp(s => s.conv?.conversation.id)
  useEffect(() => {
    // (not before git answered the first time: the stamp is '' till then and comes once the window is open - else twice)
    if (!stamp) return
    let gone = false
    api.get<FileHistory[] | null>(`/projects/${projectId}/file-history?path=${encodeURIComponent(path)}`).then(
      found => !gone && setTold(Array.isArray(found) ? found : null),
      () => !gone && setTold(null),
    )
    return () => {
      gone = true
    }
  }, [projectId, path, stamp])
  if (!told) return null
  return (
    <div className="view-last-on">
      <p className="muted">
        Last on this file:{' '}
        {told.map((one, i) => (
          <span key={`${one.agent_id} ${one.at}`}>
            {i > 0 && ' · '}
            <button type="button" className="link-btn" onClick={() => (one.conversation_id === chat ? useApp.getState().select(`agent:${one.agent_id}`) : void useApp.getState().openConversation(one.conversation_id))}>
              {one.agent_name || one.agent_role} {at(one.at)}
            </button>
            {one.conversation_id !== chat && ` in chat ${one.conversation_title}`} ({LETTER[one.kind][2]}, {one.status})
          </span>
        ))}
      </p>
    </div>
  )
}

/** A file's diff against the project's git HEAD (K-degisenler), read whole: its folds open on a click. Why not, in a line. */
function GitDiff({ projectId, path, branch, stamp, split }: { projectId: string; path: string; branch: string | null; stamp: string; split: boolean }) {
  const [read, setRead] = useState<{ diff: string } | { failed: string } | null>(null)
  useEffect(() => {
    let gone = false
    api.get<{ diff: string }>(`/projects/${projectId}/changes/diff?path=${encodeURIComponent(path)}${onBranch(branch)}`).then(
      found => !gone && setRead(found),
      error => !gone && setRead({ failed: errorText(error) }),
    )
    return () => {
      gone = true
    }
  }, [projectId, path, branch, stamp])
  if (read === null) return null
  if ('failed' in read) return <p className="view-empty muted">{read.failed}</p>
  return <DiffView diff={read.diff} path={path} split={split} />
}

/** A file of the project as read-only code: numbered, coloured as its name says (42a's colours). */
function Code({ projectId, path, branch }: { projectId: string; path: string; branch: string | null }) {
  const [read, setRead] = useState<ProjectFile | 'failed' | null>(null)
  useEffect(() => {
    let gone = false
    api.get<ProjectFile>(`/projects/${projectId}/file?path=${encodeURIComponent(path)}${onBranch(branch)}`).then(
      file => !gone && setRead(file),
      () => !gone && setRead('failed'),
    )
    return () => {
      gone = true
    }
  }, [projectId, path, branch])
  if (read === null) return null
  // (a file outside the project is not read here: only a change to it is shown)
  if (read === 'failed') return <p className="view-empty muted">It could not be read.</p>
  if (read.binary) return <p className="view-empty muted">Not text: there is no code to show.</p>
  if (read.too_large || read.text === null) return <p className="view-empty muted">Too large to show: over 256 KB.</p>
  const lines = read.text.replace(/\n$/, '').split('\n')
  const language = lines.length <= MOST_COLOURED ? languageOf(path) : null
  // As one text, so a string over several lines is one (a line too long to colour stands in it empty).
  const coloured = language ? colourLines(lines.map(line => (line.length > LONGEST_COLOURED ? '' : line)).join('\n'), language) : null
  return (
    <div className="diff mono">
      {lines.map((line, n) => (
        <div key={n} className="diff-line diff-ctx">
          <span className="diff-no">{n + 1}</span>
          {/* (highlight.js's own output, which escapes the text: the only HTML set here) */}
          {coloured && line.length <= LONGEST_COLOURED ? <span className="diff-text" dangerouslySetInnerHTML={{ __html: coloured[n] }} /> : <span className="diff-text">{line}</span>}
        </div>
      ))}
    </div>
  )
}

/**
 * The frame a page or a drawing is drawn in. No allow-same-origin, ever: it runs in an origin of
 * its own, away from the app's. Scripts only where `live`. A frame that loads a second time at
 * the same address went elsewhere by itself (nothing here moved it): it is taken off, and the
 * user told. That stops what it would do next, not the first step out (the design's known limit).
 */
function Frame({ src, title, live }: { src: string; title: string; live: boolean }) {
  const loads = useRef(0)
  const [stopped, setStopped] = useState(false)
  if (stopped) return <p className="view-empty muted">The page tried to go elsewhere; it was stopped.</p>
  return (
    <iframe
      className="view-frame"
      title={title}
      sandbox={live ? 'allow-scripts' : ''}
      src={src}
      onLoad={() => {
        loads.current += 1
        if (loads.current > 1) setStopped(true)
      }}
    />
  )
}

/** Kinds whose diff is no text to read: a changed one opens on what it draws. */
const DRAWN: ReadonlySet<string> = new Set(['model', 'pdf', 'docx', 'xlsx', 'pptx'])

/**
 * K-belge-ciktilari: a PDF in the browser's own viewer, which draws nothing in a sandbox - so in KOLONİ's own origin, under
 * `views.PDF_HEADERS` (application/pdf, nosniff, no script of the page's). Loaded only once the user says, never by itself:
 * a flaw in the viewer would run there (security review, 3 Nov).
 */
function PdfView({ src, path }: { src: string; path: string }) {
  const [open, setOpen] = useState(false)
  const loads = useRef(0)
  const [stopped, setStopped] = useState(false)
  // (A link in it that the frame followed would leave a page of the web in KOLONİ's panel, unsandboxed: taken off.)
  if (stopped) return <p className="view-empty muted">The PDF tried to go elsewhere; it was stopped.</p>
  if (open)
    return (
      <iframe
        className="view-frame"
        title={path}
        src={src}
        referrerPolicy="no-referrer"
        onLoad={() => {
          loads.current += 1
          if (loads.current > 1) setStopped(true)
        }}
      />
    )
  return (
    <div className="view-empty muted">
      <p>A PDF is drawn by your browser’s own viewer, in KOLONİ’s page: it opens only when you say.</p>
      <button type="button" className="view-run" onClick={() => setOpen(true)}>
        Open the PDF preview
      </button>
    </div>
  )
}

function Note({ src }: { src: string }) {
  const [text, setText] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let gone = false
    fetch(src)
      .then(answer => (answer.ok ? answer.text() : Promise.reject(answer.status)))
      .then(
        read => !gone && (setText(read), setFailed(false)),
        () => !gone && setFailed(true),
      )
    return () => {
      gone = true
    }
  }, [src])
  if (failed) return <p className="view-empty muted">It could not be read.</p>
  return (
    <div className="view-md">
      <Markdown written>{text}</Markdown>
    </div>
  )
}
