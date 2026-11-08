import type { Agent, FileChange, GitChange, Merge, Message } from '../api/types'
import { copyStands, inScratch } from '../changes/copies'
import type { TreeFile } from './TwoPane'
import { fileName, keyOf } from './views'

/**
 * The Workspace's Changes tab (sample A, 7 Nov): what changed, by what you have to do about it, top to bottom. Inside a
 * group, by the agent and your message it came from; each state in words, not git's letters.
 */
export const GROUPS = ['Waits for you', 'At work', 'Kept', 'In the project', 'Not by an agent', 'Needs a look', 'Closed'] as const
/** The group that starts shut: what is over. */
export const CLOSED = 'Closed'

type Status = Exclude<FileChange['status'], 'in_copy'>
/** Where a change of this chat's record lands, and how it stands in a few words (none where its group says it all). */
export const PLACE: Record<Status, [group: string, words: string]> = {
  proposed: ['Waits for you', ''],
  approved: ['In the project', 'yes given, not made yet'],
  applied: ['In the project', ''],
  merged: ['In the project', 'put together with yours'],
  conflict: ['Needs a look', 'changed on disk since'],
  failed: ['Needs a look', 'not written: the disk refused'],
  rejected: ['Closed', 'you said no'],
  reverted: ['Closed', 'reverted'],
  discarded: ['Closed', 'never made'],
}
/** What a change did, and what git says of a file: in words. */
export const DID: Record<FileChange['kind'], string> = { create: 'new', modify: 'changed', delete: 'deleted' }
export const GIT_SAYS: Record<GitChange['status'], string> = { M: 'changed', A: 'new', D: 'deleted', R: 'renamed', '?': 'new, not in git' }
const COPY_GROUP = { waits: 'Waits for you', kept: 'Kept', 'at work': 'At work' } as const

/** A change that changed its file, or will: the others left it as it was. */
export const LIVE: FileChange['status'][] = ['proposed', 'approved', 'applied', 'merged']

/**
 * Each file once, by the change it stands on - the one the Workspace marks it by and opens it on, in Files and Changes
 * alike: its latest live change (`LIVE`; with `inCopy`, one still in a working copy too), else its latest other one.
 * B-342: one done with that changes nothing (+0 −0, no delete) is no diff to stand on. Without `inCopy` a copy's changes
 * are left out: in Changes a copy is one row.
 */
export function standsOn(changes: FileChange[], inCopy = false): Map<string, FileChange> {
  const live = (change: FileChange) => Number(LIVE.includes(change.status) || (inCopy && change.status === 'in_copy'))
  const on = new Map<string, FileChange>()
  for (const change of changes) {
    if ((change.status === 'in_copy' && !inCopy) || (!live(change) && !change.diff && change.kind !== 'delete')) continue
    const was = on.get(keyOf(change.path))
    if (!was || live(change) > live(was) || (live(change) === live(was) && Date.parse(change.created_at) >= Date.parse(was.created_at))) on.set(keyOf(change.path), change)
  }
  return on
}

export interface ChangeRow {
  /** The file's key (`keyOf`), or `copy:` and its agent's id: what opens on a click. */
  key: string
  path: string
  group: string
  /** The line it is listed under: its agent and your message; null for one no agent of this chat made. */
  who: string | null
  /** When that message was sent (else the change made), in ms: the lines of a group go in this order. */
  at: number
  words: string
}

interface Sources {
  /** This chat's changes, in the project or meant for it. */
  changes: FileChange[]
  /** What git says changed; null or undefined where it said nothing (no git, no answer, not yet). */
  git?: GitChange[] | null
  /** The chat's agents and merges: their working copies, one row each (none on a branch). */
  agents: Agent[]
  merges: Merge[]
  messages: Message[]
  name(agentId: string): string
  /** K-dallar: a branch looked at - what git says is what that branch changed. */
  branch?: string | null
}

const outside = (path: string) => /^([a-z]:)?[\\/]/i.test(path)
/** A group's or a line's name as one folder of the tree: a '/' in it would split it. */
const part = (name: string) => name.replaceAll('/', '∕')
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
/** The message of yours a change's turn answered, if there is one. */
const askedBy = (change: FileChange, messages: Message[]) => messages.find(m => m.run_id === change.run_id && m.role === 'user')

/** "10:42 · Coder · “The login fails after…”": the agent, and the message of yours its turn answered (where there is one). */
export function heading(change: FileChange, name: string, messages: Message[]): string {
  const asked = askedBy(change, messages)
  const said = asked?.content.replace(/\s+/g, ' ').trim() ?? ''
  const quote = said && ` · “${said.length > 40 ? `${said.slice(0, 40)}…` : said}”`
  return `${clock(asked?.created_at ?? change.created_at)} · ${name}${quote}`
}

/** What a change did and how it stands, in words: "changed, you said no", "new, outside the project". */
const saidOf = (change: FileChange, words: string) => [DID[change.kind], words, outside(change.path) && 'outside the project'].filter(Boolean).join(', ')

/** The rows of the Changes tab, group by group in `GROUPS`' order. */
export function changeRows({ changes, git, agents, merges, messages, name, branch }: Sources): ChangeRow[] {
  const seen = new Map((git ?? []).map(c => [keyOf(c.path), c]))
  const rows: ChangeRow[] = []
  for (const [key, change] of standsOn(changes)) {
    const [group, words] = change.gone ? ['Needs a look', 'not on disk now'] : PLACE[change.status as Status]
    // (no change of this chat's to it stands, yet git sees it changed: someone else changed it since)
    if (inScratch(change.path) || (group === CLOSED && seen.has(key))) continue
    const at = Date.parse((askedBy(change, messages) ?? change).created_at)
    rows.push({ key, path: change.path, group, who: heading(change, name(change.agent_id), messages), at, words: saidOf(change, words) })
  }
  const others = branch ? `Changed on ${branch.replace(/^refs\/(heads|remotes)\//, '')}` : 'Not by an agent'
  for (const [key, c] of seen) if (!rows.some(row => row.key === key)) rows.push({ key, path: c.path, group: others, who: null, at: 0, words: GIT_SAYS[c.status] })
  const order = (group: string) => (GROUPS as readonly string[]).indexOf(group)
  return [...rows, ...(branch ? [] : copyRows(agents, merges, name))].sort((a, b) => order(a.group) - order(b.group))
}

/** Each agent's own working copy, one row in the group of how it stands (`copyStands`): it opens on what the copy holds. */
function copyRows(agents: Agent[], merges: Merge[], name: (agentId: string) => string): ChangeRow[] {
  return agents.flatMap(agent => {
    const stands = copyStands({ merges }, agent)
    return stands ? [{ key: `copy:${agent.id}`, path: `${name(agent.id)}'s copy`, group: COPY_GROUP[stands], who: null, at: 0, words: 'its working copy' }] : []
  })
}

/** "Changes · N": with git, what git lists - as the top bar counts it; without, this chat's changes that are not closed. */
export const changesCount = (rows: ChangeRow[], git: GitChange[] | null) => git?.length ?? rows.filter(row => row.group !== CLOSED).length

/**
 * The rows as the tree draws them: each group a folder that says its count, its lines folders in it in the order they
 * came, and the files in them - by name with their folder after it, or (`asTree`) in their own folders.
 */
export function changeTree(rows: ChangeRow[], asTree: boolean): TreeFile[] {
  const groups = [...new Set(rows.map(row => row.group))]
  const heads: TreeFile[] = groups.map(group => ({ id: `/${part(group)}`, path: part(group), folder: true, title: group, meta: String(rows.filter(row => row.group === group).length) }))
  const lines = new Map<string, TreeFile>()
  for (const { group, who, at } of rows) {
    const path = who && `${part(group)}/${part(who)}`
    if (path && !lines.has(path)) lines.set(path, { id: `/${path}`, path, folder: true, title: who, meta: '', order: at })
  }
  const files = rows.map(({ key, path, group, who, words }) => {
    const shown = key.startsWith('copy:') ? part(path) : path.replaceAll('\\', '/')
    const folder = shown.includes('/') ? shown.slice(0, shown.lastIndexOf('/')) : undefined
    return {
      id: key,
      path: [part(group), who && part(who), asTree || !folder ? shown : fileName(shown)].filter(Boolean).join('/'),
      where: asTree ? undefined : folder,
      title: [shown, words].join(' · '),
      meta: words,
    }
  })
  return [...heads, ...lines.values(), ...files]
}

/**
 * What the Changes tab shows, in plain words: what the list is, with git or without - not what the tool is doing. `git`
 * undefined: not read yet. On a branch looked at, its banner says it.
 */
export function changesSaid(git: { list: unknown[] | null; failed?: boolean } | undefined, rows: number, root: string, branch: string | null): string {
  if (!git) return 'Looking for changes…'
  if (git.failed) return `The changes could not be read${rows ? ": this is what this chat's agents changed" : ''}.`
  if (rows === 0) return 'Nothing changed.'
  if (branch) return ''
  return git.list ? `This chat's work, and what git sees changed in ${root} since the last commit.` : "No git here, or it did not answer in time: this is what this chat's agents changed."
}
