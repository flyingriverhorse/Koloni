import { expect, test } from 'vitest'
import type { Run } from '../api/types'
import { cached, spent, tokens } from './tokens'

const run = (input: number | null, output: number | null) =>
  ({ input_tokens: input, output_tokens: output }) as Run

test('reported counts are shown; missing ones say unknown, never zero', () => {
  expect(tokens(run(1204, 380))).toBe('in 1,204 · out 380')
  expect(tokens(run(null, null))).toBe('tokens unknown')
  expect(tokens(run(50, null))).toBe('in 50 · out unknown')
  expect(tokens(run(0, 0))).toBe('in 0 · out 0')
})

test('what was read from a cache and written to it is told where known, and nothing where not', () => {
  const told = (read: number | null, written: number | null) => cached({ cache_read_tokens: read, cache_write_tokens: written })
  expect(told(400000, 500000)).toBe('400,000 read again from the cache · 500,000 written to it')
  expect(told(64, null)).toBe('64 read again from the cache')
  expect(told(null, 30)).toBe('30 written to the cache')
  expect(told(0, 0)).toBe('0 read again from the cache · 0 written to it')
  expect(told(null, null)).toBeNull()
})

test("what Copilot spent is told in AI credits where it said them, else in premium requests, and nothing where it said neither", () => {
  const told = (nano: number | null, premium: number | null) => spent({ nano_aiu: nano, premium_requests: premium })
  expect(told(448558500, 2)).toBe('0.45 AI credits')
  expect(told(3_250_000_000, null)).toBe('3.25 AI credits')
  expect(told(5000, null)).toBe('< 0.01 AI credits')
  expect(told(null, 2)).toBe('2 premium requests')
  expect(told(null, 1)).toBe('1 premium request')
  expect(told(null, 0.33)).toBe('0.33 premium requests')
  expect(told(null, null)).toBeNull()
})

test('K-r152: a turn where some agents said no tokens says what was said, at least, and how many did not', async () => {
  const { agent, convState, run: aRun } = await import('../test-fixtures')
  const { partTokens } = await import('./tokens')
  const turn = aRun('r', 'completed')
  const said = (id: string, input: number | null, output: number | null) => agent('r', 'failed', { id, input_tokens: input, output_tokens: output })
  const conv = (...agents: ReturnType<typeof said>[]) => convState({ runs: [turn], agents })
  expect(partTokens(conv(said('a', 270000, 7000), said('b', null, null), said('c', null, null), said('d', null, null)), turn)).toBe('≥ 277k tokens · 3 unknown')
  expect(partTokens(conv(said('a', 900, 1), said('b', null, null)), turn)).toBe('≥ 901 tokens · 1 unknown')
  // All said, or none: said as before.
  expect(partTokens(conv(said('a', 1, 2)), turn)).toBeNull()
  expect(partTokens(conv(said('a', null, null)), turn)).toBeNull()
})
