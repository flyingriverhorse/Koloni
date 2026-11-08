import type { RecordRow } from '../api/types'
import { modelName } from '../shell/modelName'

const ENDED: [keyof RecordRow['ended'], string][] = [
  ['done', 'done'],
  ['failed', 'failed'],
  ['stopped_by_koloni', 'stopped by KOLONİ'],
  ['stopped_by_user', 'stopped by you'],
  ['interrupted', 'interrupted'],
]

// Shared with the role's record table (AgentsPage), so the table and the line say the same numbers.
export const round = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))
export const time = (seconds: number) => (seconds < 90 ? `${Math.round(seconds)} s` : `${Math.round(seconds / 60)} min`)
/** What nobody reported is said so: never a zero. */
const known = (value: number | null, say: (n: number) => string) => (value === null ? 'none recorded' : say(value))

/** A role's record in one short line, all its models together: how many ran and how they ended. Each place says its own beginning. */
export function recordSummary(rows: RecordRow[]): string {
  const ran = rows.reduce((sum, row) => sum + row.agents, 0)
  const ended = ENDED.map(([key, words]) => [rows.reduce((sum, row) => sum + row.ended[key], 0), words] as const)
    .filter(([count]) => count > 0)
    .map(([count, words]) => `${count} ${words}`)
  const models = rows.length > 1 ? ` on ${rows.length} models` : ''
  return `${ran} ran${models}${ended.length ? ` · ${ended.join(' · ')}` : ''}`
}

/** K-devir-0: a role's reads before the first write, on average over the agents that have it on record, all its models together; "" where none has. */
export function rediscoveryLine(rows: RecordRow[]): string {
  const known = rows.flatMap(row => (row.rediscovery ? [row.rediscovery] : []))
  const agents = known.reduce((sum, r) => sum + r.agents, 0)
  if (!agents) return ''
  const mean = known.reduce((sum, r) => sum + r.mean * r.agents, 0) / agents
  return `Reads before the first write: ${round(Math.round(mean * 10) / 10)} · ${agents} agent${agents === 1 ? '' : 's'}`
}

export const where = (row: RecordRow) =>
  `${row.provider_name ?? 'provider not on record'} · ${row.model_id ? modelName(row.model_id) : 'model not on record'}`

/**
 * One row of the record in words: who on what, how many ran and how they ended, the middle one of
 * their steps, time and tokens, and of their changes how many were taken. Measured; nothing judged.
 */
export function recordLine(row: RecordRow, withRole = false): string {
  const ended = ENDED.filter(([key]) => row.ended[key] > 0)
    .map(([key, words]) => `${row.ended[key]} ${words}`)
    .join(', ')
  return (
    `${withRole ? `${row.role_name} on ` : ''}${where(row)}: ${row.agents} ran - ${ended}. ` +
    `Middle one: ${known(row.steps, round)} steps, ${known(row.seconds, time)}, ` +
    `tokens sent ${known(row.input_tokens, round)}, written ${known(row.output_tokens, round)}. ` +
    `Changes: ${row.changes.taken} taken, ${row.changes.rejected} rejected.` +
    compared(row)
  )
}

/** How often its work was the one you chose in a comparison (slice 54); "" where it was in none. */
export function compared(row: RecordRow): string {
  const { chosen, not_chosen } = row.compared
  return chosen + not_chosen ? ` Compared: chosen ${chosen} of ${chosen + not_chosen}.` : ''
}
