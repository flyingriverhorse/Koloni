import { expect, test } from 'vitest'
import type { Provider, Role } from '../api/types'
import { agent, conversation, convState, run, topic } from '../test-fixtures'
import { staysOn } from './staysOn'

const provider = (id: string, name: string, default_model: string | null = null) => ({ id, name, default_model }) as Provider
const role = (name: string, over: Partial<Role> = {}) => ({ id: name, name, provider_id: null, model_id: null, ...over }) as Role

const providers = [provider('p-local', 'Local', 'qwen'), provider('p-fast', 'Fast', 'quick'), provider('p-cli', 'Claude Code')]

/** A topic of two turns: the Coder of the first ran on Local · qwen, and the one waiting to be opened goes on from it. */
const state = (over: { coder2?: object; conversation?: object } = {}) =>
  convState({
    conversation: { ...conversation, ...over.conversation },
    topics: [topic('ta', 'Fix the greeting')],
    runs: [run('a1', 'completed', { topic_id: 'ta' }), run('a2', 'running', { topic_id: 'ta' })],
    agents: [
      agent('a1', 'completed'),
      agent('a1', 'completed', { id: 'coder1', parent_agent_id: 'a1', role_name: 'Coder', depth: 1 }),
      agent('a2', 'running', { continues_id: 'a1' }),
      agent('a2', 'proposed', { id: 'coder2', parent_agent_id: 'a2', role_name: 'Coder', depth: 1, continues_id: 'coder1', ...over.coder2 }),
    ],
  })
const of = (s: ReturnType<typeof state>, roles: Role[], known = providers) => staysOn(s, s.agents.find(a => a.id === 'coder2')!, roles, known)

test('an agent that goes on where it ran before, while its role would now run elsewhere, is said to stay there', () => {
  // the role has a provider and a model of its own now
  expect(of(state(), [role('Coder', { provider_id: 'p-fast', model_id: 'deep' })])).toEqual({ on: 'Local · qwen', role: 'Fast · deep' })
  // the role names a provider only: that provider's own model
  expect(of(state(), [role('Coder', { provider_id: 'p-fast' })])).toEqual({ on: 'Local · qwen', role: 'Fast · quick' })
  // a provider with no model of its own is named alone
  expect(of(state(), [role('Coder', { provider_id: 'p-cli' })])).toEqual({ on: 'Local · qwen', role: 'Claude Code' })
  // the same provider, another model
  expect(of(state(), [role('Coder', { provider_id: 'p-local', model_id: 'big' })])).toEqual({ on: 'Local · qwen', role: 'Local · big' })
})

test('a role with no choice of its own would get the conversation’s, and with none there the first provider', () => {
  const chose = state({ conversation: { provider_id: 'p-fast', model_id: null } })
  expect(of(chose, [role('Coder')])).toEqual({ on: 'Local · qwen', role: 'Fast · quick' })
  // the role's own choice comes before the conversation's
  expect(of(chose, [role('Coder', { provider_id: 'p-cli' })])).toEqual({ on: 'Local · qwen', role: 'Claude Code' })
  // a choice whose provider is gone counts as no choice
  expect(of(chose, [role('Coder', { provider_id: 'gone', model_id: 'deep' })])).toEqual({ on: 'Local · qwen', role: 'Fast · quick' })
  // nobody chose: the first provider
  expect(of(state(), [role('Coder')], [providers[1], providers[0]])).toEqual({ on: 'Local · qwen', role: 'Fast · quick' })
})

test('nothing is said when it runs where its role would run today, or when it does not stay where it ran before', () => {
  // the same place: the role's choice, the conversation's, the first provider
  expect(of(state(), [role('Coder', { provider_id: 'p-local', model_id: 'qwen' })])).toBeNull()
  expect(of(state(), [role('Coder', { provider_id: 'p-local' })])).toBeNull()
  expect(of(state(), [role('Coder')])).toBeNull()
  // it was moved to its role's choice of today: it does not stay anywhere
  const moved = state({ coder2: { provider_name: 'Fast', model_id: 'quick' } })
  expect(of(moved, [role('Coder', { provider_id: 'p-fast' })])).toBeNull()
  expect(of(moved, [role('Coder', { provider_id: 'p-cli' })])).toBeNull()
  // an agent that started clean, and a lead, are not said to stay
  const s = state()
  expect(staysOn(s, s.agents[1], [role('Coder', { provider_id: 'p-fast' })], providers)).toBeNull()
  expect(staysOn(s, s.agents[2], [role('Lead', { provider_id: 'p-fast' })], providers)).toBeNull()
  // where it runs is not on record
  expect(of(state({ coder2: { provider_name: null, model_id: null } }), [role('Coder', { provider_id: 'p-fast' })])).toBeNull()
})

test('when what its role would get is not known here, only where it stays is said', () => {
  // the roles have not been read, the role is not among them, or there is no provider to name
  expect(of(state(), [])).toEqual({ on: 'Local · qwen', role: null })
  expect(of(state(), [role('Reviewer', { provider_id: 'p-fast' })])).toEqual({ on: 'Local · qwen', role: null })
  expect(of(state(), [role('Coder', { provider_id: 'p-fast' })], [])).toEqual({ on: 'Local · qwen', role: null })
})
