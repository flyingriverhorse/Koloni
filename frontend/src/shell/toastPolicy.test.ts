import { expect, test } from 'vitest'
import { PER_SOURCE, type Said, WINDOW_MS, admit, fresh, settle } from './toastPolicy'

const note = (text: string, at: number, more: Partial<Said> = {}): Said => ({ key: `${text} ${at}`, source: 'a', text, at, ...more })

/** Each note in turn; what was shown for each (null: nothing), and the policy after. */
function run(notes: Said[]) {
  let policy = fresh()
  const shown = notes.map(one => {
    const [next, show] = admit(policy, one)
    policy = next
    return show
  })
  return { policy, shown }
}

test('the same note of the same source is shown once a minute; of another source, or a minute later, again', () => {
  const { shown } = run([note('Done · Docs', 0), note('Done · Docs', 1000), note('Done · Docs', 2000, { source: 'b' }), note('Done · Docs', WINDOW_MS)])
  expect(shown.map(one => one?.at ?? null)).toEqual([0, null, 2000, WINDOW_MS])
})

test('a source shows at most four a minute; the fifth is not shown until the first is a minute old', () => {
  const five = Array.from({ length: PER_SOURCE + 1 }, (_, n) => note(`n${n}`, n * 1000))
  expect(run(five).shown.map(Boolean)).toEqual([true, true, true, true, false])
  const later = [...five.slice(0, PER_SOURCE), note('n4', WINDOW_MS)]
  expect(run(later).shown.map(Boolean)).toEqual([true, true, true, true, true])
  // another source is not held by this one's
  expect(run([...five.slice(0, PER_SOURCE), note('x', 5000, { source: 'b' })]).shown[PER_SOURCE]).not.toBeNull()
})

test('an error said again is counted on the one shown: ×N, its key, said now', () => {
  const { shown } = run([note('Failed · Docs', 0, { error: true }), note('Failed · Docs', 500, { error: true }), note('Failed · Docs', 900, { error: true })])
  expect(shown[2]).toMatchObject({ key: 'Failed · Docs 0', count: 3, at: 900 })
})

test('an error over the limit is owed, never dropped, and said once its source has room again', () => {
  const full = Array.from({ length: PER_SOURCE }, (_, n) => note(`n${n}`, n * 1000))
  const { policy, shown } = run([...full, note('Failed · A', 5000, { error: true }), note('Failed · B', 6000, { error: true }), note('plain', 7000)])
  expect(shown.slice(PER_SOURCE)).toEqual([null, null, null])
  expect(policy.owed.a.count).toBe(2)
  // before the oldest is a minute old: nothing yet, and when to look again
  const [still, none, next] = settle(policy, 30_000)
  expect(none).toEqual([])
  expect(next).toBe(WINDOW_MS)
  const [after, said, again] = settle(still, WINDOW_MS)
  expect(said.map(one => [one.text, one.error])).toEqual([['2 errors not shown · last: Failed · B', true]])
  expect([after.owed, again]).toEqual([{}, null])
  // the note said counts against its source's limit like any other
  expect(after.shown.filter(one => one.source === 'a')).toHaveLength(PER_SOURCE)
})
