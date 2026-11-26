import { expect, test } from 'vitest'
import { isExperimental, kindsShown, modesShown } from './experimental'

test('agy (0.1.8) and any CLI run Native (0.1.10) are experimental; nothing else is', () => {
  expect(isExperimental('agy_cli')).toBe(true)
  expect(isExperimental('codex_cli')).toBe(false)
  expect(isExperimental('codex_cli', 'session')).toBe(false)
  expect(isExperimental('claude_cli', 'step')).toBe(false)
  expect(isExperimental('copilot_cli', 'native')).toBe(true)
  expect(isExperimental('claude_cli', 'native')).toBe(true)
})

test('an experimental kind or way is shown with experimental features on, or where it is saved', () => {
  const kinds: ['claude_cli' | 'agy_cli', string][] = [
    ['claude_cli', 'Claude Code (CLI)'],
    ['agy_cli', 'agy (CLI)'],
  ]
  expect(kindsShown(kinds, 'claude_cli', false)).toEqual([[kinds[0]], []])
  expect(kindsShown(kinds, 'claude_cli', true)).toEqual([[kinds[0]], [kinds[1]]])
  expect(kindsShown(kinds, 'agy_cli', false)).toEqual([[kinds[0]], [kinds[1]]]) // (a saved agy)
  const claude = ['session', 'step', 'native'] as const
  expect(modesShown('claude_cli', [...claude], null, false)).toEqual([['session', 'step'], []])
  expect(modesShown('claude_cli', [...claude], null, true)).toEqual([['session', 'step'], ['native']])
  // A provider saved Native keeps its way under Experimental - while it is edited to another, too.
  expect(modesShown('claude_cli', [...claude], 'native', false)).toEqual([['session', 'step'], ['native']])
  expect(modesShown('codex_cli', ['session', 'native'], null, false)).toEqual([['session'], []])
  // agy's ways are its own: its kind says it.
  expect(modesShown('agy_cli', ['reads', 'native'], 'reads', false)).toEqual([['reads', 'native'], []])
})
