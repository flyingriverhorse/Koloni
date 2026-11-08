/**
 * Which notes the toasts show (K-bildirim-duzeni): the same note of the same source is shown once a minute, and a
 * source shows at most four a minute. An error is never lost: said again, the one shown counts it (×N); over the
 * limit, it is owed, and one note says what was owed once its source has room again (`settle`). Pure: the toasts
 * keep the policy and hand it the time. What is not shown stays in their Recent notifications list.
 */
export const WINDOW_MS = 60_000
export const PER_SOURCE = 4

export interface Said {
  key: string
  /** Whose: a conversation's id, or what it is of (`budget`, `near`). */
  source: string
  text: string
  error?: boolean
  at: number
  /** How many times an error was said that this note stands for. */
  count?: number
}

export interface Policy<T extends Said = Said> {
  /** What was shown in the last minute, oldest first. */
  shown: T[]
  /** Errors over a source's limit, not shown yet: how many, and the last of them. */
  owed: Record<string, { count: number; last: T }>
}

export const fresh = <T extends Said>(): Policy<T> => ({ shown: [], owed: {} })

/** The policy after `note`, and the note to show for it - itself, or the one it was the same as, counted - or null. */
export function admit<T extends Said>(policy: Policy<T>, note: T): [Policy<T>, T | null] {
  const shown = policy.shown.filter(one => note.at - one.at < WINDOW_MS)
  const mine = shown.filter(one => one.source === note.source)
  const same = mine.find(one => one.text === note.text)
  if (same) {
    if (!note.error) return [{ ...policy, shown }, null]
    const counted = { ...same, count: (same.count ?? 1) + 1 }
    return [{ ...policy, shown: shown.map(one => (one === same ? counted : one)) }, { ...counted, at: note.at }]
  }
  if (mine.length >= PER_SOURCE) {
    if (!note.error) return [{ ...policy, shown }, null]
    const count = (policy.owed[note.source]?.count ?? 0) + 1
    return [{ shown, owed: { ...policy.owed, [note.source]: { count, last: note } } }, null]
  }
  return [{ ...policy, shown: [...shown, note] }, note]
}

/** At `at`: the owed errors whose source has room again, each said in one note; and when to look again (null: none owed). */
export function settle<T extends Said>(policy: Policy<T>, at: number): [Policy<T>, T[], number | null] {
  const shown = policy.shown.filter(one => at - one.at < WINDOW_MS)
  const owed = { ...policy.owed }
  const notes: T[] = []
  let next: number | null = null
  for (const [source, { count, last }] of Object.entries(policy.owed)) {
    const mine = shown.filter(one => one.source === source)
    if (mine.length >= PER_SOURCE) {
      // Room comes when enough of its notes are a minute old.
      const frees = mine[mine.length - PER_SOURCE].at + WINDOW_MS
      next = next === null ? frees : Math.min(next, frees)
      continue
    }
    const note = { ...last, key: `owed ${source} ${at}`, text: `${count} ${count === 1 ? 'error' : 'errors'} not shown · last: ${last.text}`, at, count: undefined }
    notes.push(note)
    shown.push(note)
    delete owed[source]
  }
  return [{ shown, owed }, notes, next]
}
