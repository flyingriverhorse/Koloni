import type { MemoryRecord, ProjectMemory, SaidInTurn, ToolCall } from '../api/types'

/**
 * How a record's source stands, in the server's own words. "Unchanged" says only that the
 * file lines read as they did when the note was written - never that the note is right.
 */
const SOURCE_SAYS: Record<MemoryRecord['source_state'], string> = {
  unchanged: 'source unchanged since noted',
  changed: 'source changed since noted: check again',
  moved: 'source moved since noted: check again',
  none: 'no source',
  elsewhere: 'not checked here: the file is in another project',
}

export function sourceOf(record: Pick<MemoryRecord, 'source_state'>): string {
  return SOURCE_SAYS[record.source_state]
}

/** The file lines a record rests on, as `file:start-end`; null when no file is behind it. */
export function whereOf(record: Pick<MemoryRecord, 'source'>): string | null {
  const source = record.source
  if (!source) return null
  return source.start === null || source.end === null ? source.path : `${source.path}:${source.start}-${source.end}`
}

/** The place a block that moved was found at, as `file:start-end`; null when it has not moved. */
export function foundAt(record: Pick<MemoryRecord, 'source' | 'found_at'>): string | null {
  return record.source && record.found_at ? `${record.source.path}:${record.found_at.start}-${record.found_at.end}` : null
}

/** A moment as a date and a time of day. */
export function moment(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/**
 * Under something a search found, as `earlier.told` says it: who said it (a backlog task, as you
 * closed it), in which chat if any, when (or that the day is not on record), and that it was a
 * trigger's turn. Never an empty part between the dots (B-329).
 */
export function saidWhere(said: SaidInTurn): string {
  const who = said.kind === 'task' ? 'a backlog task closed by you' : said.who
  const when = said.at ? moment(said.at) : 'a day not on record'
  return [who, said.conversation_title, when, said.trigger ? 'in a trigger’s turn' : ''].filter(Boolean).join(' · ')
}

export function day(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** The model that made a note by itself, as it was asked for: provider · model. */
export function summariser(record: Pick<MemoryRecord, 'noted_by'>): string {
  const by = record.noted_by
  return [by?.provider_name, by?.model_id].filter(Boolean).join(' · ') || 'not on record'
}

/** Whose words these are, and from when. */
export function whoWhen(record: MemoryRecord): string {
  const who =
    record.origin === 'user'
      ? record.decided_how === 'feedback'
        ? 'said by you at a card, asking for changes'
        : 'written by you'
      : record.origin === 'auto'
        ? `noted by KOLONİ’s summariser (${summariser(record)}) from what was said on a message`
        : `noted by ${record.agent_name || 'an agent'}`
  return `${who} · ${day(record.observed_at)}`
}

/** How noting by itself went after the last turn it was tried for (`turn`: which one, in words); null when for none yet. */
export function lastAutoText(last: ProjectMemory['last_auto'], turn: string): string | null {
  if (!last) return null
  const after = `After the last work noted by itself (${turn})`
  if (last.noted === 0) return `${after} nothing was noted: ${last.note ?? 'no reason on record'}.`
  const skipped = last.skipped ? `, ${last.skipped} skipped` : ''
  return `${after}: ${last.noted} noted${skipped}.`
}

/** 1240 -> "1 240": thousands apart, whatever the browser's own way of writing numbers. */
export function spaced(n: number): string {
  return String(n).replace(/\B(?=(\d{3})+$)/g, ' ')
}

export function meter(chars: number, limit: number): string {
  return `${spaced(chars)} / ${spaced(limit)} characters`
}

/** A record of the project's memory by its id, wherever it stands now; undefined when it is not there. */
export function findRecord(memory: ProjectMemory, id: string): MemoryRecord | undefined {
  for (const list of [memory.core, memory.proposals, memory.journal, memory.past]) {
    const found = list.find(record => record.id === id)
    if (found) return found
  }
  return undefined
}

/** A subject as compared: case and spacing aside; '' for none. */
export const subject = (about: string | null) => (about ?? '').trim().replace(/\s+/g, ' ').toLowerCase()

/**
 * The fact of the core a waiting note would take the place of if approved: the one it was
 * written against, or the one the core has on the same subject now.
 */
export function wouldReplace(memory: ProjectMemory, note: MemoryRecord): MemoryRecord | undefined {
  return (
    memory.core.find(fact => fact.id === note.supersedes_id) ??
    (subject(note.about) ? memory.core.find(fact => subject(fact.about) === subject(note.about)) : undefined)
  )
}

/** Whether a record has every word of what was typed, in its text, subject, file or writer. */
export function matches(record: MemoryRecord, query: string): boolean {
  return hasWords([record.text, record.about, record.source?.path, record.agent_name].join(' '), query)
}

/** Whether a text has every word of what was typed. */
export function hasWords(text: string, query: string): boolean {
  const hay = text.toLowerCase()
  return query.toLowerCase().split(/\s+/).filter(Boolean).every(word => hay.includes(word))
}

/** The page's tabs, by how a record reaches an agent. */
export const TABS = [
  ['told', 'Told'],
  ['facts', 'Facts'],
  ['notes', 'Notes'],
  ['history', 'History'],
] as const
export type Tab = (typeof TABS)[number][0]

/** The lines of your preferences or rules that say something. */
export const linesOf = (text: string | null | undefined) => (text ?? '').split('\n').filter(line => line.trim())

/** A record's row on the page, for a search hit to go to. */
export const rowId = (id: string) => `mem-${id}`
/** A note that waits, on the waiting line (the journal has the same note: another id). */
export const waitId = (id: string) => `wait-${id}`

/** A decision's line in History, for a search hit to go to. */
export const decisionId = (decision: ProjectMemory['decisions'][number]) => `decision-${decision.kind}-${decision.memory_id ?? ''}`

/** Who wrote a note, in a word: the Notes tab's filter. */
export const writerOf = (record: MemoryRecord) =>
  record.origin === 'auto' ? 'fast model' : record.origin === 'user' ? 'you' : record.agent_name || 'an agent'

export interface Topic {
  /** The subject as first written; null for the records without one. */
  about: string | null
  records: MemoryRecord[]
  /** When the newest of them was noted. */
  last: string
}

/**
 * Records by their subject (case and spacing aside), the group noted most recently first and
 * the records without a subject last. No summary per group: the heading is somebody's own word.
 */
export function byTopic(records: MemoryRecord[]): Topic[] {
  const topics = new Map<string, Topic>()
  for (const record of records) {
    const key = subject(record.about)
    const topic = topics.get(key) ?? { about: key ? record.about : null, records: [], last: record.observed_at }
    topic.records.push(record)
    if (record.observed_at > topic.last) topic.last = record.observed_at
    topics.set(key, topic)
  }
  return [...topics.values()].sort((a, b) => (a.about === null ? 1 : b.about === null ? -1 : b.last.localeCompare(a.last)))
}

/** How a record that is no longer in effect left, as far as on record. */
export function leftHow(record: MemoryRecord): string {
  const when = record.decided_at ? ` · ${day(record.decided_at)}` : ''
  if (record.status === 'rejected') return `removed by ${record.decided_by === 'user' ? 'you' : 'an agent'}${when}`
  if (record.decided_by === 'agent') return `replaced by an agent’s newer note${when}`
  if (record.decided_by === 'auto') return `replaced by a newer note of KOLONİ’s summariser${when}`
  return `replaced${record.decided_by === 'user' ? ' by you' : ''}${when}`
}

/**
 * What a decision was, in words. Nobody is named: the request said it came from the app's
 * own page, which is all that is on record and which any program on this machine can say -
 * the list is there so that one that was not yours shows.
 */
const DECIDED: Record<ProjectMemory['decisions'][number]['kind'], string> = {
  written: 'Written into the core',
  feedback: 'Said at a card, into the core',
  approved: 'Approved into the core',
  corrected: 'Corrected',
  confirmed: 'Lines confirmed as the same',
  restored: 'Restored',
  rejected: 'Rejected',
  removed: 'Removed',
  added: 'Added to your preferences',
  rules: 'Standing rules changed',
}

export function decisionOf(decision: ProjectMemory['decisions'][number]): string {
  return DECIDED[decision.kind]
}

/** What a fact rests on, as far as it can be said of something handed over earlier. */
export function restsOn(record: MemoryRecord): string {
  const where = whereOf(record)
  if (where) return where
  if (record.origin !== 'user') return 'no source'
  return record.decided_how === 'feedback' ? 'said by you at a card, no file behind it' : 'written by you, no file behind it'
}

/** What a `recall` call asked for. */
export function queryOf(call: ToolCall): string {
  try {
    const args: unknown = JSON.parse(call.arguments || '{}')
    const query = (args as { query?: unknown } | null)?.query
    return typeof query === 'string' ? query : ''
  } catch {
    return ''
  }
}

