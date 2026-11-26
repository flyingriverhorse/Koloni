import { expect, test } from 'vitest'
import { isExperimental, kindsShown, modesShown } from './experimental'

test('agy, Codex run one step at a time (0.1.8) and any CLI run Native (0.1.10) are experimental; nothing else is', () => {
  expect(isExperimental('agy_cli')).toBe(true)
  expect(isExperimental('codex_cli', 'step')).toBe(true)
  expect(isExperimental('codex_cli', 'session')).toBe(false)
  expect(isExperimental('claude_cli', 'step')).toBe(false)
  expect(isExperimental('claude_cli', 'session')).toBe(false)
  expect(isExperimental('copilot_cli', 'native')).toBe(true)
  expect(isExperimental('claude_cli', 'native')).toBe(true)
})

test('an experimental kind or way is shown with experimental features on, or where it is already chosen', () => {
  const kinds: ['claude_cli' | 'agy_cli', string][] = [
    ['claude_cli', 'Claude Code (CLI)'],
    ['agy_cli', 'agy (CLI)'],
  ]
  expect(kindsShown(kinds, 'claude_cli', false)).toEqual([[kinds[0]], []])
  expect(kindsShown(kinds, 'claude_cli', true)).toEqual([[kinds[0]], [kinds[1]]])
  expect(kindsShown(kinds, 'agy_cli', false)).toEqual([[kinds[0]], [kinds[1]]]) // (a saved agy)
  const codex = ['session', 'step', 'native'] as const
  expect(modesShown('codex_cli', [...codex], 'session', false)).toEqual([['session'], []])
  expect(modesShown('codex_cli', [...codex], 'session', true)).toEqual([['session'], ['step', 'native']])
  expect(modesShown('codex_cli', [...codex], 'step', false)).toEqual([['session'], ['step']]) // (in use)
  // A provider already run Native keeps its way, under Experimental (0.1.10).
  expect(modesShown('claude_cli', [...codex], 'native', false)).toEqual([['session', 'step'], ['native']])
  // Claude Code's step is no experiment, and agy's ways are its own: its kind says it.
  expect(modesShown('claude_cli', [...codex], null, false)).toEqual([['session', 'step'], []])
  expect(modesShown('agy_cli', ['reads', 'native'], 'reads', false)).toEqual([['reads', 'native'], []])
})
