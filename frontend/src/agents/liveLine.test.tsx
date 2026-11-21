import { render } from '@testing-library/react'
import { expect, test } from 'vitest'
import { LiveFacts } from './LiveFacts'
import { liveFacts, liveKind } from './liveLine'

const T = Date.parse('2026-10-05T10:00:00Z')
const iso = (ms: number) => new Date(ms).toISOString()

test('a live line says what is known - time, tokens written, tier or model - and leaves out what is not', () => {
  expect(liveFacts(T + 12_000, iso(T), 1234, 'Fast')).toBe('12s · ↓ 1.2k tokens · Fast')
  expect(liveFacts(T + 12_000, iso(T), null, 'Fast')).toBe('12s · Fast')
  expect(liveFacts(T + 62_000, iso(T), 980, null)).toBe('1m 02s · ↓ 980 tokens')
  expect(liveFacts(T, null, null, null)).toBe('')
  expect(liveFacts(T, iso(T + 3_000), null, null)).toBe('0s')
  // Its tier's name, else its model's, else nothing.
  expect(liveKind({ tier: 'fast', model_id: 'qwen' })).toBe('Fast')
  expect(liveKind({ tier: null, model_id: 'qwen' })).toBe('qwen')
  expect(liveKind({ tier: null, model_id: null }, 'qwen-plus')).toBe('qwen-plus')
  expect(liveKind({ tier: null, model_id: null })).toBeNull()
  // (Not known is not a name: a CLI's own default model is not said.)
  expect(liveKind({ tier: null, model_id: 'claude default' })).toBeNull()
})

test('its facts follow what it does, after a dot; with none known, nothing', () => {
  const { container, rerender } = render(<LiveFacts since={iso(Date.now() - 5_000)} wrote={null} kind="Fast" />)
  expect(container.querySelector('.live-facts')).toHaveTextContent(/^· \d+s · Fast$/)
  rerender(<LiveFacts since={null} wrote={null} kind={null} />)
  expect(container.querySelector('.live-facts')).toBeNull()
})
