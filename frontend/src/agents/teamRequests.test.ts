import { expect, test } from 'vitest'
import { agent, toolCall } from '../test-fixtures'
import { standsLine, type TeamRequest } from './teamRequests'

const lead = agent('r', 'running', { id: 'bl', role_name: 'Backend / API lead', name: 'Backend / API lead 2' })
const asker = agent('r', 'waiting', { id: 'wc', role_name: 'Coder', name: 'Coder' })

function request(stands: TeamRequest['stands'], over: Partial<TeamRequest> = {}): TeamRequest {
  return { call: toolCall('5', 'r', 'request_work', 'running'), from: asker, fromTeam: 'Web app', to: 'Backend / API', what: 'GET /api/items', contract: false, lead, stands, ...over }
}

test('how a request stands, each way it can: who has it, who waits, how it ended', () => {
  expect(standsLine(request('answered'))).toBe('Backend / API lead 2 answered ✓')
  expect(standsLine(request('declined', { lead: { ...lead, report: ' Declined: the page reads a file\nmore' } }))).toBe('Backend / API lead 2 declined: the page reads a file')
  expect(standsLine(request('declined'))).toBe('Backend / API lead 2 declined: ')
  expect(standsLine(request('failed', { lead: { ...lead, status: 'cancelled' } }))).toBe('Backend / API lead 2 cancelled')
  expect(standsLine(request('failed', { lead: undefined }))).toBe("Backend / API's lead failed")
  expect(standsLine(request('not delivered', { lead: undefined }))).toBe('not delivered: the Orchestrator has it')
  expect(standsLine(request('refused', { lead: undefined }))).toBe('refused')
  expect(standsLine(request('waits', { lead: { ...lead, status: 'proposed' } }))).toBe('Backend / API lead 2 waits for your approval')
  expect(standsLine(request('waits'), asker)).toBe("Backend / API lead 2 gave it to its Coder · at work · Web app's Coder waits")
  expect(standsLine(request('at work'), asker)).toBe('Backend / API lead 2 gave it to its Coder · at work')
  expect(standsLine(request('waits', { fromTeam: null, from: undefined }))).toBe('Backend / API lead 2 has it · at work · an agent waits')
  // (A lead with no name of its own goes by its role; none yet, by its team.)
  expect(standsLine(request('at work', { lead: { ...lead, name: '' } }))).toBe('Backend / API lead has it · at work')
  expect(standsLine(request('waits', { lead: undefined }))).toBe("Backend / API's lead has it · at work · Web app's Coder waits")
})
