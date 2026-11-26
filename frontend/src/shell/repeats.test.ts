import { expect, test } from 'vitest'
import { foldRepeats, times } from './repeats'

const koloni = (line: { by: string; text: string }) => (line.by === 'koloni' ? line.text : null)

test('the same KOLONİ line in a row is one line with how many times it came; anybody’s own words never are', () => {
  const lines = [
    { by: 'agent', text: 'read_file farewell.py' },
    ...Array.from({ length: 8 }, () => ({ by: 'koloni', text: 'its older messages summarised' })),
    { by: 'agent', text: 'write_file farewell.py' },
    { by: 'agent', text: 'write_file farewell.py' }, // an agent's words, the same twice: both stay
    { by: 'koloni', text: 'its older messages summarised' }, // not in a row with the eight
    { by: 'koloni', text: 'something else' },
  ]
  expect(foldRepeats(lines, koloni).map(([line, n]) => `${line.text}${times(n)}`)).toEqual([
    'read_file farewell.py',
    'its older messages summarised ×8',
    'write_file farewell.py',
    'write_file farewell.py',
    'its older messages summarised',
    'something else',
  ])
  // the one kept is the first of them
  expect(foldRepeats(lines, koloni)[1][0]).toBe(lines[1])
  expect(foldRepeats([], koloni)).toEqual([])
})
