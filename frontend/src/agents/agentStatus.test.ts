import { expect, test } from 'vitest'
import { titleOf } from './agentStatus'

test('K-isimler: the Lead reads as the Orchestrator, a team’s lead as its team’s coordinator; names stay as records have them', () => {
  const teams = [{ name: 'Docs', lead: { name: 'Docs lead' } }] as Parameters<typeof titleOf>[1]
  expect(titleOf('Lead')).toBe('Orchestrator')
  expect(titleOf('Docs lead', teams)).toBe('Docs coordinator')
  expect(titleOf('Docs lead')).toBe('Docs lead')
  expect(titleOf('Coder 2', teams)).toBe('Coder 2')
})
