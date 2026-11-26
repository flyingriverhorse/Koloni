import { expect, test } from 'vitest'
import { isExperimental, kindsShown } from './experimental'

test('0.1.8: agy is experimental; nothing else is (0.1.10: Codex run one step at a time is cut)', () => {
  expect(isExperimental('agy_cli')).toBe(true)
  expect(isExperimental('codex_cli')).toBe(false)
  expect(isExperimental('claude_cli')).toBe(false)
  expect(isExperimental('copilot_cli')).toBe(false)
})

test('an experimental kind is shown with experimental CLIs on, or where it is already chosen', () => {
  const kinds: ['claude_cli' | 'agy_cli', string][] = [
    ['claude_cli', 'Claude Code (CLI)'],
    ['agy_cli', 'agy (CLI)'],
  ]
  expect(kindsShown(kinds, 'claude_cli', false)).toEqual([[kinds[0]], []])
  expect(kindsShown(kinds, 'claude_cli', true)).toEqual([[kinds[0]], [kinds[1]]])
  expect(kindsShown(kinds, 'agy_cli', false)).toEqual([[kinds[0]], [kinds[1]]]) // (a saved agy)
})
