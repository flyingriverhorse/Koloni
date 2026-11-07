import type { GitStatus } from '../api/types'
import { since } from '../board/columns'
import { copyFiles, copyLine, copyStands } from '../changes/copies'
import type { ConvState } from '../state/applyEvent'

/** Where the work is (slice 70; sample A, 7 Nov): below your branch, the open chat's copies, the other branches, and what was said. */
export type Section = 'copies' | 'branches' | 'said'
export const SECTIONS: [Section, string][] = [
  ['copies', 'Agents’ copies · this chat'],
  ['branches', 'Other branches'],
  ['said', 'Said, not seen in git'],
]

/** One piece of work: what it is, how it stands in words, a line under it, and its one button. */
export interface Row {
  key: string
  section: Section
  what: string
  state: string
  /** The colour of `state`, over its words: waits for you, on its way in, or out of KOLONİ's hands. */
  tone: 'wait' | 'ok' | 'q'
  small: string
  /** See changes: the copy's diff in the Workspace; Take in… and Look: the agent's window, where its card is. */
  act?: { label: 'See changes' | 'Take in…' | 'Look'; agentId: string; copy: boolean }
  /** K-dallar: a branch's row - Look, and Switch to for a local one. */
  branch?: GitStatus['branches'][number]
}

const many = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`
const line = (...parts: (string | number | null | false | undefined)[]) => parts.filter(Boolean).join(' · ')
/** K-dallar: a branch's last commit, "a1b2c3d fix the login · 2 h ago" - the subject is the repository's words. */
export const lastCommit = (b: { sha: string | null; subject: string | null; last_at: string | null }) =>
  line([b.sha, b.subject].filter(Boolean).join(' '), b.last_at && `${since(b.last_at)} ago`)
/** The top bar's words: "⑂ main · 4 changed · 1 worktree". */
export function gitLabel(git: GitStatus): string {
  const others = git.worktrees.filter(w => !w.here).length
  return line('⑂ ' + (git.branch || 'no branch'), git.changed > 0 && `${git.changed} changed`, others > 0 && many(others, 'worktree'))
}

/**
 * K-dal-takim D2: the team working on a `koloni/` branch - the agent whose copy is its worktree, and the agents below it -
 * by name; null where no agent of the open chat is on it.
 * shortcut: only the open chat's agents, as the copies above; read it from the server if a branch of another chat is missed.
 */
export function team(state: ConvState | null, branch: string): string | null {
  const owner = state?.agents.find(a => a.copy?.on_branch === branch)
  if (!state || !owner) return null
  const crew = new Set([owner.id])
  // (Opened after the agent that opened them: one pass in their order finds the whole line.)
  for (const a of state.agents) if (a.parent_agent_id && crew.has(a.parent_agent_id)) crew.add(a.id)
  return state.agents.filter(a => crew.has(a.id)).map(a => a.name || a.role_name).join(', ')
}

/** A folder as two names of it compare: one slash, one case (Windows). */
const folder = (path: string) => path.replaceAll('\\', '/').replace(/\/+$/, '').toLowerCase()

/**
 * The open chat's working copies (`state`, of this project), each by how it stands (`copyStands`). A copy goes into the
 * project's branch when you take it in, or when it finishes where the chat does not ask (`permission_mode`).
 * shortcut: only the open chat's copies; the project's other chats' are on the Board. Read them from the server if
 * users miss them here. A check command can still hold a copy that goes in "when it finishes".
 */
function copyRows(git: GitStatus, state: ConvState): Row[] {
  const trunk = git.branch || 'the project'
  const commit = git.commit ? ` · then offered for a commit on ${trunk}` : ''
  const asks = state.conversation.permission_mode === 'ask'
  const rows: Row[] = []
  for (const agent of state.agents) {
    const [key, what, stands] = [agent.id, agent.name || agent.role_name, copyStands(state, agent)]
    const where = copyLine(state, agent) ?? 'works in its own copy'
    if (stands === 'waits')
      rows.push({ key, section: 'copies', what, state: 'finished, waits for you', tone: 'wait', small: line(where, `goes into ${trunk} when you take it in${commit}`), act: { label: 'Take in…', agentId: key, copy: false } })
    else if (stands === 'kept')
      rows.push({ key, section: 'copies', what, state: 'kept', tone: 'wait', small: 'in its copy · nothing was taken · goes in only if you take it in', act: { label: 'Look', agentId: key, copy: false } })
    else if (stands === 'at work') {
      const n = copyFiles(state, agent)
      const how = `${where}${agent.provider_name ? ` (${agent.provider_name})` : ''}`
      const small = line(n && `${many(n, 'file')} so far`, how, `goes into ${trunk} when ${asks ? 'you take it in' : 'it finishes'}${commit}`)
      rows.push({ key, section: 'copies', what, state: 'working', tone: 'ok', small, act: { label: 'See changes', agentId: key, copy: true } })
    }
  }
  return rows
}

/** The repository's other branches and worktrees, each held against what an agent said of it. */
function branchRows(git: GitStatus, state: ConvState | null): Row[] {
  const trunk = git.branch || 'the project'
  const said = (branch: string, worktree: string | null) =>
    git.reports.find(r => r.branch === branch || (!!worktree && !!r.worktree && folder(r.worktree) === folder(worktree)))
  const rows = git.branches.map((b): Row => {
    const report = b.remote ? undefined : said(b.name, b.worktree)
    const crew = b.remote ? null : team(state, b.name)
    // shortcut: a branch's worktree folder has no Open - it is the repository's word (an agent may have written it)
    // and is not handed to the system to open; and "joined" has no date (git keeps none of a merge that moved no
    // commit). Add an Open that the server checks, and the merge's date from its commit, if missed.
    const what = report ? `${report.agent} said it made the branch ${b.name}` : `${b.remote ? 'Remote branch' : 'Branch'} ${b.name}${crew ? ` · team ${crew}` : ''}`
    if (b.joined) return { key: `b:${b.ref}`, section: 'branches', what, state: 'joined ✓', tone: 'ok', small: line(`already in ${trunk}`, lastCommit(b)), branch: b }
    const goes = report?.merge_into ? `said by ${report.agent}: goes into ${report.merge_into}` : 'nobody said where it goes'
    const small = line(b.worktree && `in its own folder ${b.worktree}`, b.ahead != null && `${many(b.ahead, 'commit')} ahead of ${trunk}`, b.behind && `${b.behind} behind`, lastCommit(b), goes)
    return { key: `b:${b.ref}`, section: 'branches', what, state: 'not joined', tone: 'q', small, branch: b }
  })
  for (const w of git.worktrees.filter(w => !w.here && !w.branch))
    rows.push({ key: `w:${w.path}`, section: 'branches', what: `A worktree at ${w.path}`, state: 'not joined', tone: 'q', small: 'on no branch · nobody said where it goes' })
  return rows
}

/**
 * Where the work is, below your branch: the open chat's working copies, then the repository's other branches and
 * worktrees, then what an agent said and git does not show.
 */
export function gitRows(git: GitStatus, state: ConvState | null): Row[] {
  const reports = git.reports
    .filter(r => !r.seen)
    .map((r): Row => ({ key: `r:${r.branch ?? ''}:${r.worktree ?? ''}`, section: 'said', what: `${r.agent} said it made ${r.branch ? `the branch ${r.branch}` : `a worktree at ${r.worktree}`}`, state: 'not seen in git', tone: 'wait', small: r.why ?? '' }))
  return [...(state ? copyRows(git, state) : []), ...branchRows(git, state), ...reports]
}
