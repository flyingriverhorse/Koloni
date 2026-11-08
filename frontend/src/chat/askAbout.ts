import { api } from '../api/client'
import type { Agent, FileHistory } from '../api/types'
import { titleOf } from '../agents/agentStatus'
import { useApp } from '../state/store'

/** Text selected for "Ask about this" (slice 80): the file and lines where known (a file view, a diff), else none (a message). */
export interface Picked {
  path: string | null
  from: number | null
  to: number | null
  text: string
}

/** The agent whose change to the file is the last on record, as the screen names it, and whether it is at work still. */
export interface Writer {
  name: string
  atWork: boolean
}

/** A longer quote is cut, its line range kept: the Orchestrator reads the file for the rest. */
export const MOST_LINES = 60
/** An agent at work, for "and is still working". */
export const AT_WORK: ReadonlySet<Agent['status']> = new Set(['queued', 'running', 'waiting', 'blocked'])
/** `FileHistory.status` of a change that is (or may become) what the file holds (`handoff._STATUS`). */
export const WROTE: ReadonlySet<string> = new Set(['taken in', 'waiting'])

/** What "Ask about this" puts into the message box: where it is from and who wrote it, then the text fenced. */
export function quoteOf({ path, from, to, text }: Picked, writer: Writer | null, branch: string | null = null): string {
  const lines = text.replace(/\r\n?/g, '\n').replace(/\n+$/, '').split('\n')
  const kept = lines.slice(0, MOST_LINES)
  // (a fence longer than any run of backticks in the text, which would close it)
  const fence = '`'.repeat(Math.max(3, ...(text.match(/`+/g) ?? []).map(run => run.length + 1)))
  const range = from === null ? '' : to === null || to === from ? `:${from}` : `:${from}–${to}`
  const who = writer ? ` (${writer.name} wrote this${writer.atWork ? ' and is still working' : ''})` : ''
  // (R125: on which branch, where the project is in git - the Orchestrator may be on another)
  const head = path ? `${path}${range}${branch ? ` on ${branch}` : ''}${who}:\n` : ''
  const cut = lines.length > kept.length ? `\n(${lines.length - kept.length} more lines not quoted)` : ''
  return `${head}${fence}\n${kept.join('\n')}\n${fence}${cut}\n\n`
}

/** Whose change to `path` is the last on record (K-devir-4's file history), and whether that agent of this chat is at work. */
export async function writerOf(path: string): Promise<Writer | null> {
  const { projectId, conv, teams } = useApp.getState()
  if (!projectId) return null
  const found = await api.get<FileHistory[] | null>(`/projects/${projectId}/file-history?path=${encodeURIComponent(path)}`).catch(() => null)
  const last = Array.isArray(found) ? found[0] : undefined
  if (!last || !WROTE.has(last.status)) return null
  const agent = conv?.agents.find(one => one.id === last.agent_id)
  return { name: titleOf(last.agent_role, teams), atWork: agent !== undefined && AT_WORK.has(agent.status) }
}

const LINE = '.diff-line, .diff-half'

/** A line's number: the new side's where a diff has two, the old one's for a removed line. */
function numberOf(line: Element): number | null {
  const said = Array.from(line.querySelectorAll('.diff-no')).map(no => no.textContent ?? '').filter(Boolean)
  return said.length ? Number(said.at(-1)) : null
}

/**
 * The lines a selection covers in a file view or a diff under `root` (`.diff-line`, or a side's `.diff-half`), read from
 * their text alone - never the numbers or the +/- beside them. Outside such lines, the selection's own text.
 */
export function linesIn(root: Element, range: Range, said: string): Omit<Picked, 'path'> {
  const lineOf = (node: Node) => (node instanceof Element ? node : node.parentElement)?.closest(LINE) ?? null
  const first = lineOf(range.startContainer)
  let last = lineOf(range.endContainer)
  if (!first || !last || !root.contains(first) || !root.contains(last)) return { from: null, to: null, text: said }
  const side = first.matches('.diff-half') ? Array.from(first.parentElement?.children ?? []).indexOf(first) : -1
  const all = side < 0 ? Array.from(root.querySelectorAll('.diff-line')) : Array.from(root.querySelectorAll('.diff-row')).map(row => row.children[side])
  // (a selection that ends at the very start of a line - a triple click - is of the lines before it)
  if (last !== first) {
    const into = root.ownerDocument.createRange()
    into.setStart(last, 0)
    into.setEnd(range.endContainer, range.endOffset)
    if (!into.toString()) last = all[all.indexOf(last) - 1] ?? last
  }
  const lines = all.slice(all.indexOf(first), all.indexOf(last) + 1).filter(line => line?.querySelector('.diff-text'))
  const numbers = lines.map(numberOf).filter(n => n !== null)
  const inOne = first === last && first.querySelector('.diff-text')?.contains(range.commonAncestorContainer)
  return {
    from: numbers[0] ?? null,
    to: numbers.at(-1) ?? null,
    text: inOne ? said : lines.map(line => line.querySelector('.diff-text')?.textContent ?? '').join('\n'),
  }
}
