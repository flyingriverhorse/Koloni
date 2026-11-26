import { expect, test } from 'vitest'
import { count, since } from './columns'

// Noon, local time.
const NOW = new Date(2026, 9, 21, 12, 0)
const at = (day: number, hour: number) => new Date(2026, 9, day, hour, 0).toISOString()

test('how long ago, in the largest whole unit; and how many of a thing', () => {
  expect([at(21, 12), at(21, 11), at(21, 7), at(19, 12)].map(iso => since(iso, NOW.getTime()))).toEqual([
    '<1 min',
    '1 h',
    '5 h',
    '2 d',
  ])
  expect([count(1, 'agent'), count(3, 'agent'), count(2, 'copy', 'copies')]).toEqual([
    '1 agent',
    '3 agents',
    '2 copies',
  ])
})
