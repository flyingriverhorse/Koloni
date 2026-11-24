import { render } from '@testing-library/react'
import { expect, test } from 'vitest'
import { LiveFacts } from './LiveFacts'
import { liveFactList, liveKind } from './liveLine'

const T = Date.parse('2026-10-05T10:00:00Z')
const iso = (ms: number) => new Date(ms).toISOString()

test('a live line says what is known - time, tokens written, tier or model - and leaves out what is not', () => {
  expect(liveFactList(T + 12_000, iso(T), 1234, 'Fast')).toEqual(['12s', '↓ 1.2k tokens', 'Fast'])
  expect(liveFactList(T + 12_000, iso(T), null, 'Fast')).toEqual(['12s', 'Fast'])
  expect(liveFactList(T + 62_000, iso(T), 980, null)).toEqual(['1m 02s', '↓ 980 tokens'])
  expect(liveFactList(T, null, null, null)).toEqual([])
  expect(liveFactList(T, iso(T + 3_000), null, null)).toEqual(['0s'])
  // Its tier's name, else its model's, else nothing.
  expect(liveKind({ tier: 'fast', model_id: 'qwen' })).toBe('Fast')
  expect(liveKind({ tier: null, model_id: 'qwen' })).toBe('qwen')
  expect(liveKind({ tier: null, model_id: null }, 'qwen-plus')).toBe('qwen-plus')
  expect(liveKind({ tier: null, model_id: null })).toBeNull()
  // (Not known is not a name: a CLI's own default model is not said.)
  expect(liveKind({ tier: null, model_id: 'claude default' })).toBeNull()
})

test('its facts follow what it does, after a dot, each its own piece - time, tokens, tier - so the last gives way first; with none known, nothing', () => {
  const { container, rerender } = render(<LiveFacts since={iso(Date.now() - 5_000)} wrote={1234} kind="Fast" />)
  expect(container.querySelector('.live-facts')).toHaveTextContent(/^· \d+s · ↓ 1\.2k tokens · Fast$/)
  expect(Array.from(container.querySelectorAll('.live-facts > span'), piece => piece.textContent)).toEqual([
    expect.stringMatching(/^ · \d+s$/),
    ' · ↓ 1.2k tokens',
    ' · Fast',
  ])
  rerender(<LiveFacts since={null} wrote={null} kind={null} />)
  expect(container.querySelector('.live-facts')).toBeNull()
})
