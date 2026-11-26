import { expect, test } from 'vitest'
import type { AwayJob } from '../api/types'
import { doneSaid } from './awayText'

const done = (over: Partial<AwayJob>) => ({ kept: ['m1'], files: ['a.py', 'b.py'], taken: [], ...over }) as AwayJob

test('a job done on its own branch says its files wait on its branch, not in a copy (D3)', () => {
  expect(doneSaid(done({}))).toBe('2 files in its copy, waits for you')
  const branch = { name: 'koloni/one-3f2a' } as AwayJob['branch']
  expect(doneSaid(done({ branch }))).toBe('2 files on its branch, waits for you')
})
