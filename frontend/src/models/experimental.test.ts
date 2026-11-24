import { expect, test } from 'vitest'
import { isExperimental, kindsShown, modesShown } from './experimental'

test('0.1.8: agy, and Codex run one step at a time, are experimental; nothing else is', () => {
  expect(isExperimental('agy_cli')).toBe(true)
  expect(isExperimental('codex_cli', 'step')).toBe(true)
  expect(isExperimental('codex_cli', 'session')).toBe(false)
  expect(isExperimental('claude_cli', 'step')).toBe(false)
  expect(isExperimental('copilot_cli', 'native')).toBe(false)
})

test('an experimental kind or way is shown with experimental CLIs on, or where it is already chosen', () => {
  const kinds: ['claude_cli' | 'agy_cli', string][] = [
    ['claude_cli', 'Claude Code (CLI)'],
    ['agy_cli', 'agy (CLI)'],
  ]
  expect(kindsShown(kinds, 'claude_cli', false)).toEqual([[kinds[0]], []])
  expect(kindsShown(kinds, 'claude_cli', true)).toEqual([[kinds[0]], [kinds[1]]])
  expect(kindsShown(kinds, 'agy_cli', false)).toEqual([[kinds[0]], [kinds[1]]]) // (a saved agy)
  const codex = ['session', 'step', 'native'] as const
  expect(modesShown('codex_cli', [...codex], 'session', false)).toEqual([['session', 'native'], []])
  expect(modesShown('codex_cli', [...codex], 'session', true)).toEqual([['session', 'native'], ['step']])
  expect(modesShown('codex_cli', [...codex], 'step', false)).toEqual([['session', 'native'], ['step']]) // (in use)
  // Claude Code's step is no experiment, and agy's ways are its own: its kind says it.
  expect(modesShown('claude_cli', [...codex], null, false)).toEqual([[...codex], []])
  expect(modesShown('agy_cli', ['reads', 'native'], 'reads', false)).toEqual([['reads', 'native'], []])
})
