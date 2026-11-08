import { expect, test } from 'vitest'
import type { Conversation, Provider, Role, RoleModel, Team, Tiers } from '../api/types'
import { conversation } from '../test-fixtures'
import { type Known, inUseBy } from './inUse'

const providers = [
  { id: 'p-local', name: 'Local' },
  { id: 'p-copilot', name: 'Copilot' },
  { id: 'p-claude', name: 'Claude Code' },
] as Provider[]
const everyone = providers.map(one => one.name)
const role = (name: string, over: Partial<Role> = {}) => ({ name, builtin: false, enabled: true, teams: [], tier: 'balanced', provider_id: null, ...over }) as Role
const row = (name: string, provider_name: string, over: Partial<RoleModel> = {}) =>
  ({ role: name, provider_name, asks_how_hard: null, cannot_run: null, pick_from: everyone, ...over }) as RoleModel
const lead = role('Lead', { builtin: true, tier: null })
const chat = (over: Partial<Conversation> = {}) => ({ ...conversation, ...over })
const known = (roles: Role[], over: Partial<Known> = {}): Known => ({ roles, teams: [], providers, tiers: null, observes: false, ...over })
const ids = (c: Conversation, rows: RoleModel[], k: Known) => inUseBy(c, rows, k).ids

test("sample A's first situation: the chat follows the default (Local), its Orchestrator and roles run elsewhere - Local is not in use", () => {
  const rows = [row('Lead', 'Copilot'), row('Coder', 'Claude Code'), row('Reviewer', 'Claude Code')]
  expect(inUseBy(chat(), rows, known([lead, role('Coder'), role('Reviewer')]))).toEqual({ ids: ['p-copilot', 'p-claude'], cannot: [] })
})

test('a role that falls back to the default brings it in; a provider the user chose for the chat is in use whatever the roles run on', () => {
  expect(ids(chat(), [row('Lead', 'Copilot'), row('Coder', 'Local')], known([lead, role('Coder')]))).toEqual(['p-local', 'p-copilot'])
  expect(ids(chat({ provider_id: 'p-claude' }), [row('Lead', 'Copilot')], known([lead]))).toEqual(['p-claude', 'p-copilot'])
})

test("a role that is off, or in none of the chat's teams, is not opened: its provider is not in use", () => {
  const roles = [lead, role('Coder', { enabled: false }), role('Writer', { teams: ['t-docs'] }), role('Tester', { teams: ['t-web'] })]
  const rows = [row('Lead', 'Copilot'), row('Coder', 'Local'), row('Writer', 'Claude Code'), row('Tester', 'Local')]
  const teams = [{ id: 't-docs', lead: { name: 'Docs lead' }, lead_on: true }, { id: 't-web', lead: { name: 'Web lead' }, lead_on: true }] as Team[]
  const docs = chat({ teams_mode: 'manual', teams: [{ team_id: 't-docs' }] as Conversation['teams'] })
  expect(ids(docs, rows, known(roles, { teams }))).toEqual(['p-copilot', 'p-claude'])
})

test("a team's lead runs only beside another team, and only on: as the server opens one", () => {
  const roles = [lead, role('Web lead', { kind: 'lead' }), role('Docs lead', { kind: 'lead', enabled: false })]
  const rows = [row('Lead', 'Copilot'), row('Web lead', 'Local'), row('Docs lead', 'Claude Code')]
  const teams = [
    { id: 't-web', lead: { name: 'Web lead' }, lead_on: true },
    { id: 't-docs', lead: { name: 'Docs lead' }, lead_on: true },
    { id: 't-ops', lead: { name: 'Web lead' }, lead_on: false },
  ] as Team[]
  const of = (...picked: string[]) => chat({ teams_mode: 'manual', teams: picked.map(team_id => ({ team_id })) as Conversation['teams'] })
  // alone: the Orchestrator runs the team
  expect(ids(of('t-web'), rows, known(roles, { teams }))).toEqual(['p-copilot'])
  // beside another: its lead, where it is on and its role is on
  expect(ids(of('t-web', 't-docs'), rows, known(roles, { teams }))).toEqual(['p-local', 'p-copilot'])
  expect(ids(of('t-ops', 't-docs'), rows, known(roles, { teams }))).toEqual(['p-copilot'])
})

test("the Observer counts only where the chat's project looks over reports; the Planner, which the Lead may open any time, always", () => {
  const roles = [lead, role('Planner', { builtin: true }), role('Observer', { builtin: true })]
  const rows = [row('Lead', 'Copilot'), row('Planner', 'Claude Code'), row('Observer', 'Local')]
  expect(ids(chat(), rows, known(roles))).toEqual(['p-copilot', 'p-claude'])
  expect(ids(chat(), rows, known(roles, { observes: true }))).toEqual(['p-local', 'p-copilot', 'p-claude'])
})

test('the model a lead that follows the message asks how hard it is counts too', () => {
  const rows = [row('Lead', 'Copilot', { asks_how_hard: { provider_name: 'Local', model_id: 'qwen' } })]
  expect(ids(chat({ lead_auto: true }), rows, known([lead]))).toEqual(['p-local', 'p-copilot'])
})

test("each tier's first model a job may be given counts: any tier for a Lead that follows the message, a role's range where the Lead picks", () => {
  const model = (provider_name: string, agents = true) => ({ provider_id: '', provider_name, model: 'm', agents })
  const tiers = { fast: [model('Local', false), model('Claude Code')], balanced: [model('Copilot')], strongest: [model('Local')] } as Tiers
  const rows = [row('Lead', 'Copilot'), row('Coder', 'Copilot')]
  const coder = role('Coder', { tier: null, tier_min: 'fast', tier_max: 'balanced' })
  // without lead_auto the Lead runs where its row says; the Coder's range: fast (Local is off for agents: Claude Code) and balanced
  expect(ids(chat(), rows, known([lead, coder], { tiers }))).toEqual(['p-copilot', 'p-claude'])
  // the Lead may move to any tier's first
  expect(ids(chat({ lead_auto: true }), rows, known([lead, coder], { tiers }))).toEqual(['p-local', 'p-copilot', 'p-claude'])
  // ...of what may be picked for it
  expect(ids(chat({ lead_auto: true }), [row('Lead', 'Copilot', { pick_from: ['Copilot'] })], known([lead], { tiers }))).toEqual(['p-copilot'])
  // a role of one tier always, or with a model of its own, is never given another
  expect(ids(chat(), [row('Coder', 'Copilot')], known([role('Coder', { tier: null, provider_id: 'p-copilot' })], { tiers }))).toEqual(['p-copilot'])
})

test("a role in use that cannot run where it would is said, by what the screen calls it; one not in use is not", () => {
  const rows = [row('Lead', 'Copilot', { cannot_run: 'Copilot runs only the models listed for it' }), row('Coder', 'Local', { cannot_run: 'nope' })]
  expect(inUseBy(chat(), rows, known([lead, role('Coder', { enabled: false })])).cannot).toEqual([{ who: 'Orchestrator', why: 'Copilot runs only the models listed for it' }])
})
