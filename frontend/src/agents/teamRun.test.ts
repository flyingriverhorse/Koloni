import { expect, test } from 'vitest'
import type { ChatTeam, ChatTeamState } from '../api/types'
import { agent, conversation, fileChange } from '../test-fixtures'
import { readyLine } from './teamRun'

const row = (team_id: string, state: Partial<ChatTeamState>): ChatTeam => ({
  team_id,
  recipe_id: null,
  no_recipe: false,
  picked_by: 'user',
  why: null,
  state: {
    run_id: 'r',
    team: team_id,
    recipe: 'Feature',
    status: 'ready',
    why: null,
    steps: [],
    agents: [],
    ended_ready: null,
    passes: [],
    ...state,
  },
})
const LONG = 'waits for the review of the first of its three steps, which is not over yet'

function state(teams: ChatTeam[], agents: Parameters<typeof agent>[2][] = []) {
  return {
    conversation: { ...conversation, teams },
    runs: [],
    agents: agents.map(over => agent('r', 'completed', over)),
    fileChanges: [
      fileChange('1', 'r', { agent_id: 'a', path: 'web/x.ts' }),
      fileChange('2', 'r', { agent_id: 'a', path: 'web/y.ts', created_at: '2026-10-05T10:05:00Z' }),
      fileChange('3', 'r', { agent_id: 'b', path: 'docs/z.md', status: 'in_copy' }),
    ],
  }
}

test('the Ready for you card in one line: each team its files, a team kept apart, one not at its end and why', () => {
  const teams = [
    row('Web app', { agents: ['a'] }),
    row('Docs', { agents: ['b'], recipe: '', status: 'done' }),
    row('Notes', { agents: ['n'], recipe: '', status: 'in' }),
    row('Backend', { agents: ['c'], status: 'running', why: LONG }),
    row('Ready, why', { agents: [], why: 'two findings left' }),
    row('Later', { status: 'waiting' }),
    row('Other turn', { run_id: 'q' }),
  ]
  expect(readyLine(state(teams), 'r')).toBe(
    `Teams' work is ready · Web app 2 files · Docs 1 file, kept apart · Notes nothing to take in · Backend running: ${LONG.slice(0, 59)}… · 0 files · Ready, why ready: two findings left · 0 files`,
  )
  // Answered: no row's state, and counted as the card was asked.
  expect(readyLine(state(teams), 'r', { at: '2026-10-05T10:01:00Z', open: false })).toBe(
    "Teams' work is ready · Web app 1 file · Docs 1 file, kept apart · Notes nothing to take in · Backend 0 files · Ready, why 0 files",
  )
  expect(readyLine(state(teams), 'r', { at: '2026-10-05T10:01:00Z', open: true })).toContain('Web app 1 file · Docs')
  expect(readyLine(state([]), 'r')).toBe("Teams' work is ready")
})

test('with a team that ended badly each team says its own state, and what Take in takes of a team that stopped early', () => {
  const teams = [
    row('Docs', { agents: ['b'], status: 'failed', why: 'rule broken: Test it was not done', ended_ready: false }),
    row('Web app', { agents: ['a'], status: 'done' }),
    row('Backend', { agents: ['c', 'd'], status: 'running', why: LONG }),
    row('Lead only', { agents: ['e'], recipe: '', status: 'running' }),
    row('Stopped', { agents: [], status: 'stopped' }),
  ]
  const agents = [
    { id: 'c', status: 'failed' as const },
    { id: 'd', status: 'cancelled' as const },
    { id: 'e', status: 'running' as const },
  ]
  expect(readyLine(state(teams, agents), 'r')).toBe(
    `Docs failed: rule broken: Test it was not done (1 file) · Web app is ready (2 files) · Backend failed: ${LONG.slice(0, 59)}… (0 files) · Lead only running (nothing to take in) · Stopped stopped (0 files) · Take in also takes in what Docs left before it stopped.`,
  )
  expect(readyLine(state(teams, agents), 'r', { at: '2026-10-05T10:01:00Z', open: false })).toBe(
    'Docs failed (1 file) · Web app is ready (1 file) · Backend failed (0 files) · Lead only running (nothing to take in) · Stopped stopped (0 files)',
  )
})
