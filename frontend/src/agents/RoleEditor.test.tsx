import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { RecordRow, Role, RoleModel } from '../api/types'
import { AgentsPage } from './AgentsPage'
import { levelsKnown, namedLevel } from '../models/levels'
import { recordLine } from './record'

const role = (over: Partial<Role>): Role => ({
  id: 'r1',
  name: 'Reviewer',
  description: 'Reviews changes',
  instructions: 'Be strict.',
  tools: ['list_dir', 'read_file', 'search'],
  builtin: true,
  created_by_agent: false, models: null,
  provider_id: null,
  model_id: null,
  tier: null,
  tier_min: null,
  tier_max: null,
  kind: 'build',
  enabled: true,
  teams: [],
  pick_from: null,
  max_steps: null,
  max_tokens: null,
  effort: null,
  max_effort: null,
  context_window: null,
  mcp: [],
  skills: [],
  inside_cli: false,
  knows: [],
  created_at: 't',
  updated_at: 't',
  ...over,
})
const documenter = role({ id: 'r2', name: 'Documenter', builtin: false, tools: ['read_file', 'write_file'] })
const handlers = () => ({
  onSave: vi.fn().mockResolvedValue(undefined),
  onCreate: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onReset: vi.fn().mockResolvedValue(undefined),
})

// Slice 81b: a role opens from its card, read first; its form opens at the part of its own Edit (0.1.0-ui: one form).
const seg = (name: string) => screen.getByRole('radio', { name })
const card = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) })
/** Open a role's card, then one part of its form: from a tab's Edit, or from an Overview row's ("Edit model")
 * (slice 81d: its tools are the Tools tab's own tiles; K-skill-uyum: its skills too). */
async function edit(name: string, where: 'Instructions' | 'Edit model') {
  await userEvent.click(card(name))
  if (where === 'Edit model') return userEvent.click(screen.getByRole('button', { name: where }))
  await userEvent.click(screen.getByRole('tab', { name: where }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
}

test('a role opens read first: its instructions as words, its form behind Edit; its tools as tiles', async () => {
  render(<AgentsPage roles={[role({}), documenter]} {...handlers()} />)
  await userEvent.click(card('Reviewer'))
  await userEvent.click(screen.getByRole('tab', { name: 'Instructions' }))
  expect(screen.getByText('Be strict.')).toBeInTheDocument()
  expect(screen.queryByRole('textbox', { name: 'Instructions' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
  expect(screen.getByLabelText('Name')).toHaveValue('Reviewer')
  expect(screen.getByRole('textbox', { name: 'Instructions' })).toHaveValue('Be strict.')
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  expect(screen.getByRole('button', { name: 'Read files' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: 'Write files' })).toHaveAttribute('aria-pressed', 'false')
  // the tiles are the tools' form: no Edit for them
  expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
})

test('a role names the MCP servers it may use; "on Tools →" goes there', async () => {
  const h = handlers()
  const onOpenTools = vi.fn()
  render(<AgentsPage roles={[role({ mcp: ['rea', 'docs'] }), documenter]} onOpenTools={onOpenTools} {...h} />)
  await userEvent.click(card('Reviewer'))
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  expect(screen.getByText('rea')).toHaveClass('chip')
  expect(screen.getByText('docs')).toHaveClass('chip')
  await userEvent.click(screen.getByRole('button', { name: 'on Tools →' }))
  expect(onOpenTools).toHaveBeenCalled()
  // saving the role says nothing of them: they stay as the Tools page has them
  await userEvent.click(screen.getByRole('tab', { name: 'Instructions' }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).not.toHaveProperty('mcp')
  await userEvent.click(card('Documenter'))
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  expect(screen.getByText(/^May use/)).toHaveTextContent('May use 2 of 36 tools · 0 MCP servers · 0 skills')
})

test('a built-in role keeps its name, can be reset and cannot be deleted', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({})]} {...h} />)
  await edit('Reviewer', 'Instructions')
  expect(screen.getByLabelText('Name')).toHaveAttribute('readonly')
  expect(screen.queryByRole('button', { name: 'Delete role' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Reset to default' }))
  expect(h.onReset).toHaveBeenCalledWith('r1')
})

test('edits are saved with the role’s tools as they are', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({})]} {...h} />)
  await edit('Reviewer', 'Instructions')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('r1', {
    name: 'Reviewer',
    description: 'Reviews changes',
    instructions: 'Be strict.',
    tools: ['list_dir', 'read_file', 'search'],
    provider_id: null,
    model_id: null,
    models: null,
    tier: null,
    tier_min: null,
    tier_max: null,
    kind: 'build',
    pick_from: null,
    max_steps: null,
    max_tokens: null,
    effort: null,
    max_effort: null,
    context_window: null,
    skills: [],
    inside_cli: false,
  })
  // saved, the form is put away: the tab reads again
  expect(await screen.findByRole('button', { name: 'Edit' })).toBeInTheDocument()
})

/** The thinking card (K-ladder): Auto or one fixed level, then one ladder of the levels, Off to Max, as radios. */
const mode = (name: 'Auto' | 'One fixed level') => within(screen.getByRole('radiogroup', { name: 'Thinking' })).getByRole('radio', { name })
const ladder = () => screen.getByRole('radiogroup', { name: /^(Fixed level|Most the Orchestrator may pick)$/ })
const rung = (name: string) => within(ladder()).getByRole('radio', { name })
const checked = () =>
  within(ladder())
    .queryAllByRole('radio', { checked: true })
    .map(radio => radio.closest('label')?.textContent)

test('K-ladder: in Auto the ladder picks the most; one fixed level is any level its model takes, the top one too', async () => {
  const h = handlers()
  const onRoleModels = vi.fn().mockResolvedValue([
    { role: 'Reviewer', efforts: ['off', 'low', 'medium', 'high', 'xhigh'] },
    { role: 'Documenter', efforts: [] },
  ])
  render(<AgentsPage roles={[role({}), documenter]} {...h} onRoleModels={onRoleModels} />)
  await edit('Reviewer', 'Edit model')
  expect(await screen.findByText(/Its model takes: Off, Low, Medium, High, XHigh\./)).toBeInTheDocument()
  // Auto by default: up to High; it never picks Off; Max is struck, and the note says why.
  expect(mode('Auto')).toBeChecked()
  expect(ladder()).toHaveAccessibleName('Most the Orchestrator may pick')
  expect(ladder()).toHaveAccessibleDescription('Auto picks a level for each task, from Low up to High. Click a level to move “most”.')
  expect(checked()).toEqual(['Highmost'])
  expect(rung('Off')).toBeDisabled()
  expect(rung('Max')).toBeDisabled()
  expect(screen.getByText(/Max: not taken by this model\./)).toBeInTheDocument()
  await userEvent.click(rung('Medium'))
  expect(checked()).toEqual(['Mediummost'])
  // One fixed level: Medium; a click picks another - one checked, the most left as it was
  await userEvent.click(mode('One fixed level'))
  expect(ladder()).toHaveAccessibleName('Fixed level')
  expect(checked()).toEqual(['Medium'])
  expect(ladder()).toHaveAccessibleDescription('Every task gets Medium. The Orchestrator doesn’t change it. Click another level to change it.')
  await userEvent.click(rung('XHigh'))
  expect(checked()).toEqual(['XHigh'])
  await userEvent.click(rung('Off'))
  expect(checked()).toEqual(['Off'])
  await userEvent.click(rung('XHigh'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ effort: 'xhigh', max_effort: null })
  // (as kept here: Auto) the read view answers how hard it thinks, in one line
  expect(screen.getByRole('complementary', { name: 'Role Reviewer' })).toHaveTextContent('How hard it thinksAuto · up to HighHow much')
  // a model that takes none: nothing to choose, and nothing is sent
  await edit('Documenter', 'Edit model')
  expect(screen.getByText(/The model’s levels are not known: nothing is sent\./)).toBeInTheDocument()
  expect(rung('Low')).toBeDisabled()
  expect(mode('Auto')).toBeEnabled()
  expect(mode('One fixed level')).toBeDisabled()
})

test('K-ladder: a most set earlier above a fixed level is said under the ladder, and Remove takes it away', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({ effort: 'low', max_effort: 'medium' })]} {...h} onRoleModels={vi.fn().mockResolvedValue([{ role: 'Reviewer', efforts: ['off', 'low', 'medium', 'high'] }])} />)
  await edit('Reviewer', 'Edit model')
  await screen.findByText(/Its model takes: Off, Low, Medium, High\./)
  expect(screen.getByRole('complementary', { name: 'Role Reviewer' })).toHaveTextContent('How hard it thinksLow, up to Medium')
  expect(checked()).toEqual(['Low'])
  expect(screen.getByText(/The Orchestrator may also go up to Medium \(set earlier\)\./)).toBeInTheDocument()
  // another level leaves it as it was
  await userEvent.click(rung('Off'))
  expect(screen.getByText(/may also go up to Medium/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Remove the most of Medium' }))
  expect(screen.queryByText(/may also go up to/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ effort: 'off', max_effort: null })
})

test('nothing is said of the levels before they are known', async () => {
  let answer: (rows: RoleModel[]) => void = () => {}
  render(<AgentsPage roles={[role({})]} {...handlers()} onRoleModels={() => new Promise(done => (answer = done))} />)
  await edit('Reviewer', 'Edit model')
  expect(screen.getByText(/Looking up the model’s levels…/)).toBeInTheDocument()
  answer([{ role: 'Reviewer', efforts: ['low'] } as RoleModel])
  expect(await screen.findByText(/Its model takes: Low\./)).toBeInTheDocument()
})

test('a saved level the model does not take is shown struck, and can be taken back to Auto', async () => {
  const h = handlers()
  const onRoleModels = vi.fn().mockResolvedValue([{ role: 'Reviewer', efforts: ['low', 'medium'] }])
  render(<AgentsPage roles={[role({ effort: 'max', max_effort: 'max' })]} {...h} onRoleModels={onRoleModels} />)
  await edit('Reviewer', 'Edit model')
  await screen.findByText(/Its model takes: Low, Medium\./)
  expect(mode('One fixed level')).toBeChecked()
  expect(checked()).toEqual(['Max'])
  expect(rung('Max')).toBeDisabled()
  expect(screen.getByText(/Off, High, XHigh, Max: not taken by this model\. Max as saved: the nearest lower level it takes is sent, or none\./)).toBeInTheDocument()
  // back to Auto, a most its model does not take goes too
  await userEvent.click(mode('Auto'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ effort: null, max_effort: null })
})

test('K-ladder: on a model without High, Auto’s most is shown at the nearest lower level it takes - and not saved', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({})]} {...h} onRoleModels={vi.fn().mockResolvedValue([{ role: 'Reviewer', efforts: ['low', 'medium'] }])} />)
  await edit('Reviewer', 'Edit model')
  await screen.findByText(/Its model takes: Low, Medium\./)
  expect(checked()).toEqual(['Mediummost'])
  expect(screen.getByText('Auto picks a level for each task, from Low up to Medium. Click a level to move “most”.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ effort: null, max_effort: null })
})

test('K-ladder: Auto with a most of Off set earlier marks the lowest level it takes, says so, and Remove takes it away', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({ max_effort: 'off' })]} {...h} onRoleModels={vi.fn().mockResolvedValue([{ role: 'Reviewer', efforts: ['off', 'low', 'high'] }])} />)
  await edit('Reviewer', 'Edit model')
  await screen.findByText(/Its model takes: Off, Low, High\./)
  expect(checked()).toEqual(['Lowmost'])
  expect(rung('Off')).toBeDisabled()
  expect(screen.getByText(/Up to Off \(set earlier\)\./)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Remove the most of Off' }))
  expect(checked()).toEqual(['Highmost'])
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ effort: null, max_effort: null })
})

test('K-ladder: with its levels not known, going back to Auto keeps a most set earlier', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({ effort: 'high', max_effort: 'xhigh' })]} {...h} onRoleModels={vi.fn().mockResolvedValue([{ role: 'Reviewer', efforts: [] }])} />)
  await edit('Reviewer', 'Edit model')
  await screen.findByText(/The model’s levels are not known/)
  await userEvent.click(mode('Auto'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ effort: null, max_effort: 'xhigh' })
})

test('where the levels could not be looked up, that is said and no level can be chosen', async () => {
  render(<AgentsPage roles={[role({})]} {...handlers()} onRoleModels={vi.fn().mockRejectedValue(new Error('down'))} />)
  await edit('Reviewer', 'Edit model')
  expect(await screen.findByText(/Could not look up the model’s levels\./)).toBeInTheDocument()
  expect(rung('High')).toBeDisabled()
})

test('choosing another role shows it; a role of your own can be deleted', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({}), documenter]} {...h} />)
  await edit('Documenter', 'Instructions')
  expect(screen.getByLabelText('Name')).toHaveValue('Documenter')
  expect(screen.getByLabelText('Name')).not.toHaveAttribute('readonly')
  await userEvent.click(screen.getByRole('button', { name: 'Delete role' }))
  expect(h.onDelete).toHaveBeenCalledWith('r2')
})

test('a new role starts empty and is created', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({})]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  expect(screen.getByLabelText('Name')).toHaveValue('')
  expect(screen.getByRole('button', { name: 'Create role' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Name'), 'Translator')
  await userEvent.click(screen.getByLabelText('read_file'))
  await userEvent.click(screen.getByRole('button', { name: 'Create role' }))
  expect(h.onCreate).toHaveBeenCalledWith({
    name: 'Translator',
    description: '',
    instructions: '',
    tools: ['read_file'],
    provider_id: null,
    model_id: null,
    models: null,
    tier: null,
    tier_min: null,
    tier_max: null,
    kind: 'build',
    pick_from: null,
    max_steps: null,
    max_tokens: null,
    effort: null,
    max_effort: null,
    context_window: null,
    skills: [],
    inside_cli: false,
  })
})

test('a new role is put in one of the categories, Build to begin with', async () => {
  const categories = [
    { key: 'build', name: 'Build', colour: 'amber' as const },
    { key: 'k1', name: 'Research', colour: 'rose' as const },
  ]
  render(<AgentsPage roles={[role({})]} categories={categories} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  const category = screen.getByLabelText('Category')
  expect(within(category).getAllByRole('option').map(o => o.textContent)).toEqual(['Build', 'Research'])
  expect(category).toHaveValue('build')
  // with Build deleted, the first category: the one sent is the one shown
  cleanup()
  render(<AgentsPage roles={[role({})]} categories={categories.slice(1)} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  expect(screen.getByLabelText('Category')).toHaveValue('k1')
})

test('which model a role uses is one choice: the Lead picks in a range, always a tier, always a model, or the conversation’s', async () => {
  const h = handlers()
  const providers = [provider('p1', 'Local', true), provider('p2', 'Claude Code', true)]
  render(<AgentsPage roles={[role({}), role({ id: 'r3', name: 'Debugger', tier: 'strongest' })]} providers={providers} {...h} />)
  await userEvent.click(card('Debugger'))
  expect(screen.getByRole('complementary', { name: 'Role Debugger' })).toHaveTextContent('Which modelAlways strongest')
  await edit('Reviewer', 'Edit model')
  const uses = screen.getByRole('radiogroup', { name: 'Who picks it?' })
  // mockup B: who picks it, then only what that choice needs
  expect(seg('Orchestrator')).toBeChecked()
  expect(within(uses).getAllByRole('radio').map(o => o.closest('label')?.textContent)).toEqual(['Orchestrator', 'As the chat', 'One tier', 'One model'])
  expect(uses).toHaveAccessibleDescription('It picks a tier for each job, inside this range, and says why.')
  expect(screen.queryByRole('radiogroup', { name: 'Tier' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument()
  expect(screen.getByLabelText('From')).toHaveValue('fast')
  expect(screen.getByLabelText('To')).toHaveValue('strongest')
  await userEvent.selectOptions(screen.getByLabelText('From'), 'balanced')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  // an end left where it is, is no bound: sent as null
  expect(h.onSave).toHaveBeenLastCalledWith('r1', expect.objectContaining({ tier: null, tier_min: 'balanced', tier_max: null, provider_id: null }))

  await edit('Debugger', 'Edit model')
  expect(seg('One tier')).toBeChecked()
  expect(seg('Strongest')).toBeChecked()
  expect(screen.getByText('Always this tier. The Orchestrator can’t change it.')).toBeInTheDocument()
  expect(screen.queryByLabelText('From')).not.toBeInTheDocument()
  // each choice clears the others' fields: no leftover decides
  await userEvent.click(seg('Fast'))
  expect(seg('Fast')).toBeChecked()
  await userEvent.click(seg('One model'))
  expect(screen.queryByRole('radiogroup', { name: 'Tier' })).not.toBeInTheDocument()
  expect(screen.getByText('Always this model, whatever the job.')).toBeInTheDocument()
  expect(screen.getByLabelText('Provider')).toHaveValue('p1')
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'p2')
  await userEvent.type(screen.getByLabelText('Model name'), 'opus')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('r3', expect.objectContaining({ provider_id: 'p2', model_id: 'opus', tier: null, tier_min: null, tier_max: null }))
  await edit('Debugger', 'Edit model')
  await userEvent.click(seg('As the chat'))
  expect(screen.queryByLabelText('Provider')).not.toBeInTheDocument()
  expect(screen.getByText('Whatever the chat’s model picker says.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('r3', expect.objectContaining({ tier: 'conversation', provider_id: null, model_id: null }))
})

test('one tier clears what another choice left: no range or model of its own stays', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({ tier: 'strongest', tier_min: 'balanced', model_id: 'left' })]} {...h} />)
  await edit('Reviewer', 'Edit model')
  await userEvent.click(seg('Fast'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('r1', expect.objectContaining({ tier: 'fast', tier_min: null, tier_max: null, provider_id: null, model_id: null }))
})

test('K-rol-model-sirasi: a role’s preferred models are added, reordered and removed, and saved in that order', async () => {
  const h = handlers()
  const providers = [provider('p1', 'Local', true), provider('p2', 'Claude Code', true), provider('p3', 'Paid Api', false)]
  render(<AgentsPage roles={[role({ models: [{ provider_id: 'p1', model_id: 'big' }] })]} providers={providers} {...h} />)
  await userEvent.click(card('Reviewer'))
  expect(screen.getByRole('complementary', { name: 'Role Reviewer' })).toHaveTextContent('Which modelFirst big — then Orchestrator · fast–strongest')
  await edit('Reviewer', 'Edit model')
  // the list is its own field: the one choice above it stays as it was
  expect(seg('Orchestrator')).toBeChecked()
  expect(screen.getByText('Up to 5 from the team guide, tried in order before the choice above.')).toBeInTheDocument()
  // only providers in the team guide can be added
  await userEvent.click(screen.getByRole('button', { name: '+ Add a model' }))
  // Cancel folds the row away; the button is back
  await userEvent.click(screen.getByRole('button', { name: 'Cancel adding a model' }))
  expect(screen.queryByLabelText('Preferred model name')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '+ Add a model' }))
  expect(within(screen.getByLabelText('Preferred models')).getAllByRole('option').map(o => o.textContent)).toEqual(['Local', 'Claude Code'])
  await userEvent.selectOptions(screen.getByLabelText('Preferred models'), 'p2')
  await userEvent.type(screen.getByLabelText('Preferred model name'), 'opus')
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  const order = () => within(screen.getByRole('list', { name: 'Preferred models, in order' })).getAllByRole('listitem').map(li => li.textContent?.split(' ↑')[0])
  expect(order()).toEqual(['1. Local · big', '2. Claude Code · opus'])
  expect(screen.getByLabelText('Preferred model name')).toHaveValue('')
  await userEvent.click(screen.getByRole('button', { name: 'Move opus up' }))
  expect(order()).toEqual(['1. Claude Code · opus', '2. Local · big'])
  await userEvent.click(screen.getByRole('button', { name: 'Remove big' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('r1', expect.objectContaining({ models: [{ provider_id: 'p2', model_id: 'opus' }], provider_id: null, tier: null }))
})

test('a refused save shows the reason', async () => {
  const h = handlers()
  h.onSave.mockRejectedValue({ detail: 'unknown skill' })
  render(<AgentsPage roles={[role({})]} {...h} />)
  await edit('Reviewer', 'Instructions')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('unknown skill')
})

test('a role an agent created says so', async () => {
  render(<AgentsPage roles={[role({ id: 'r3', name: 'Scout', builtin: false, created_by_agent: true })]} {...handlers()} />)
  await edit('Scout', 'Instructions')
  expect(screen.getAllByText('Created by an agent').length).toBeGreaterThan(0)
})

test('a role with a model of its own shows it as that choice, and with no provider there is none to choose', async () => {
  const providers = [provider('p2', 'Claude Code', false)]
  render(<AgentsPage roles={[role({ provider_id: 'p2', model_id: 'opus' }), role({ id: 'r4', name: 'Scout' })]} providers={providers} {...handlers()} />)
  await userEvent.click(card('Reviewer'))
  expect(screen.getByRole('complementary', { name: 'Role Reviewer' })).toHaveTextContent('Which modelClaude Code · opus')
  await edit('Reviewer', 'Edit model')
  expect(seg('One model')).toBeChecked()
  expect(screen.getByLabelText('Provider')).toHaveValue('p2')
  expect(screen.getByLabelText('Model name')).toHaveValue('opus')
  cleanup()
  render(<AgentsPage roles={[role({})]} {...handlers()} />)
  await edit('Reviewer', 'Edit model')
  expect(seg('One model')).toBeDisabled()
})

const provider = (id: string, name: string, forAgents: boolean) => ({
  id, name, kind: 'openai_compat' as const, base_url: 'http://x/v1', default_model: null, executable: null, mode: null, options: null,
  for_agents: forAgents, note: null, models: [], only_listed: false, max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null, has_key: false, position: 0, created_at: 't', updated_at: 't',
})

test('what may be picked for a role: all in the team guide, none, or only the guide’s providers that are ticked', async () => {
  const h = handlers()
  const providers = [provider('p1', 'Local', true), provider('p2', 'Fast', true), provider('p3', 'Paid Api', false)]
  render(<AgentsPage roles={[role({})]} providers={providers} {...h} />)
  const pick = async (name: string | RegExp) => {
    await edit('Reviewer', 'Edit model')
    return within(screen.getByRole('radiogroup', { name: 'May be picked for this role' })).getByRole('radio', { name })
  }
  expect(await pick('Any provider in the team guide')).toBeChecked()
  expect(screen.queryByRole('checkbox', { name: 'Fast' })).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('radio', { name: /^No one/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('r1', expect.objectContaining({ pick_from: [] }))

  await userEvent.click(await pick('Only these'))
  // only what is in the team guide can be ticked
  expect(screen.queryByLabelText('Paid Api')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('checkbox', { name: 'Fast' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('r1', expect.objectContaining({ pick_from: ['p2'] }))

  await userEvent.click(await pick('Any provider in the team guide'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenLastCalledWith('r1', expect.objectContaining({ pick_from: null }))
  // saved (as kept here: all), the read view answers its question
  expect(screen.getByRole('complementary', { name: 'Role Reviewer' })).toHaveTextContent('Who may move itAny providerin the team guide, with a reason')
})

test('a role’s list is shown as it is kept: a provider no longer in the guide stays ticked, and says so', async () => {
  const providers = [provider('p1', 'Local', true), provider('p3', 'Paid Api', false)]
  render(<AgentsPage roles={[role({ pick_from: ['p3'] })]} providers={providers} {...handlers()} />)
  await edit('Reviewer', 'Edit model')
  expect(screen.getByRole('radio', { name: 'Only these' })).toBeChecked()
  expect(screen.getByLabelText(/Paid Api/)).toBeChecked()
  expect(screen.getByText(/not in the team guide now/)).toBeInTheDocument()
  expect(screen.getByLabelText('Local')).not.toBeChecked()
})

test('a role’s limits on steps and tokens are whole numbers above zero, or empty for none - and say whom they do not hold', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({ max_steps: 8 })]} {...h} />)
  await edit('Reviewer', 'Edit model')
  // Folded, closed, at the end: one short line under its title, the rest behind ⓘ.
  const fold = screen.getByText('Safety stops for one agent')
  expect(fold.closest('details')).not.toHaveAttribute('open')
  await userEvent.click(fold)
  expect(screen.getByText('Stops one runaway agent of this role. Empty: KOLONİ’s own step limit.')).toBeVisible()
  expect(screen.getByLabelText('At most this many steps')).toHaveAccessibleDescription(/added up over its task and each time it is told to go on.*reaches an agent already open the next time it is told to go on/)
  const steps = screen.getByLabelText('At most this many steps')
  const tokens = screen.getByLabelText('At most this many tokens')
  expect(steps).toHaveValue('8')
  expect(tokens).toHaveValue('')
  // a session's messages are counted; only a CLI at work with its own tools is not held - and that is said in sight
  const unheld = screen.getByText(/A CLI working with its own tools \(native\) takes no steps KOLONİ can count: this limit does not hold it/)
  expect(unheld.closest('.hint')).toBeNull()
  expect(screen.getByText(/A change to the limit reaches an agent already open the next time it is told to go on\..*With nobody watching \(a trigger’s message\), what a sub-agent\s+stopped there had changed is not kept.*For a CLI session each message it\s+writes is a step\./s)).toBeInTheDocument()
  expect(screen.getByText(/an agent carried on for a later\s+message starts again from zero/)).toBeInTheDocument()
  const tokenNote = screen.getByText(/A model that reports nothing is not held by this\. A CLI \(a session, or its own tools\)\s+reports when it ends/)
  expect(tokenNote.closest('.hint')).toBeNull()

  await userEvent.type(tokens, '0')
  expect(tokens).toHaveAttribute('aria-invalid', 'true')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.clear(tokens)
  await userEvent.type(tokens, '50000')
  await userEvent.clear(steps)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('r1', expect.objectContaining({ max_steps: null, max_tokens: 50000 }))
})

test('changing one tool keeps the memory tools a role already has, and the backlog’s no tile shows', async () => {
  const onPatch = vi.fn().mockResolvedValue(undefined)
  render(<AgentsPage roles={[role({ tools: ['read_file', 'read_backlog', 'remember', 'recall'] })]} onPatch={onPatch} {...handlers()} />)
  await userEvent.click(card('Reviewer'))
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  expect(screen.getByRole('button', { name: 'Remember' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: 'Recall' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  expect(onPatch).toHaveBeenCalledWith('r1', { tools: ['read_file', 'read_backlog', 'remember', 'recall', 'search'] })
})

// Slice 38c: the record of a role is a table, a row for each model (its History, slice 81b).
const ran: RecordRow = {
  role_name: 'Reviewer',
  provider_name: 'Local',
  model_id: 'qwen',
  agents: 7,
  ended: { done: 3, failed: 1, stopped_by_koloni: 1, stopped_by_user: 2, interrupted: 1 },
  steps: 4.5,
  seconds: 130,
  input_tokens: 1200,
  output_tokens: 36,
  changes: { taken: 2, rejected: 1 },
  compared: { chosen: 1, not_chosen: 2 },
  rediscovery: { mean: 6.2, agents: 4 },
  taken_in: 2, turned_down: 1, cost: { amount: 0.0375, currency: 'USD' },
}
/** A cell as it is drawn: what is there only for a screen reader left out. */
const drawn = (cell: HTMLElement) => {
  const copy = cell.cloneNode(true) as HTMLElement
  copy.querySelectorAll('.visually-hidden').forEach(hidden => hidden.remove())
  return copy.textContent
}
const history = { days: 30, lead_turns: 0, jobs_limit: 200, roles: [{ name: 'Reviewer', done: 1, failed: 0, running: 0 }], teams: [], recipes: [], jobs: [] }
/** 0.1.0-ui: a role's record is on the page's History tab, under its jobs, once the list is of that role. */
const historyOf = async (onRecord: () => Promise<RecordRow[]>) => {
  render(<AgentsPage roles={[role({})]} onRecord={onRecord} onHistory={vi.fn().mockResolvedValue(history)} {...handlers()} />)
  await vi.waitFor(() => expect(onRecord).toHaveBeenCalled())
  await userEvent.click(screen.getByRole('tab', { name: 'History' }))
  await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Role' }), 'Reviewer')
}
const tableOf = async (rows: RecordRow[]) => {
  await historyOf(vi.fn().mockResolvedValue(rows))
  return screen.findByRole('table', { name: 'Record of the last 30 days' })
}

test("a role's record is a table with its columns in order, its numbers those of the record's line", async () => {
  const table = await tableOf([ran])
  expect(within(table).getAllByRole('columnheader').map(th => th.textContent)).toEqual([
    'Provider · model', 'Ran', 'Done', 'Failed', 'Stopped', 'Interrupted', 'Steps', 'Time', 'Sent', 'Written', 'Changes taken / rejected',
    'Chosen in comparisons', 'Taken in', 'Turned down', 'Cost',
  ])
  // named once: by its own name, with no caption beside it (its fold's line says the rest)
  expect(table).toHaveAttribute('aria-label', 'Record of the last 30 days')
  expect(table.querySelector('caption')).toBeNull()
  const row = within(table).getAllByRole('row')[1]
  expect(within(row).getByRole('rowheader')).toHaveTextContent('Local · qwen')
  const cells = within(row).getAllByRole('cell')
  const [runs, done, failed, stopped, interrupted, steps, time, sent, written, changes, compared, tookIn, turnedDown, cost] = cells.map(drawn)
  expect([runs, done, failed, stopped, interrupted, steps, time, sent, written, changes, compared]).toEqual(['7', '3', '1', '3', '1', '4.5', '2 min', '1200', '36', '2 / 1', '1 of 3'])
  // K-model-puan: jobs taken in and turned down, and the middle cost as the Usage page writes one
  expect([tookIn, turnedDown, cost]).toEqual(['2', '1', '≈ 0.0375 USD'])
  // the same numbers as the record's line of words
  const line = recordLine(ran)
  const [taken, rejected] = changes!.split(' / ')
  for (const said of [`${runs} ran`, `${done} done`, `${failed} failed`, `${interrupted} interrupted`, `${steps} steps`, time, `sent ${sent}`, `written ${written}`, `${taken} taken`, `${rejected} rejected`, `chosen ${compared}`]) expect(line).toContain(said)
  // stopped by KOLONİ and by you together; apart under the pointer and to a screen reader, as the line says
  expect(cells[3]).toHaveAttribute('title', '1 by KOLONİ, 2 by you')
  expect(cells[3]).toHaveTextContent('1 by KOLONİ, 2 by you')
  expect(line).toContain('1 stopped by KOLONİ, 2 stopped by you')
  expect(Number(stopped)).toBe(ran.ended.stopped_by_koloni + ran.ended.stopped_by_user)
  // no bullet lines left in the record
  expect(within(table.closest('details')!).queryByRole('list')).not.toBeInTheDocument()
  expect(screen.getByText('Middle values: half the agents took more, half less.')).toBeInTheDocument()
})

test('a middle value not every agent reported is "–", said so under the pointer and to a screen reader - never a zero', async () => {
  const table = await tableOf([{ ...ran, steps: null, seconds: null, output_tokens: null }])
  const unknown = within(table).getAllByRole('cell', { name: 'not every agent reported it' })
  expect(unknown).toHaveLength(3)
  for (const cell of unknown) {
    expect(drawn(cell)).toBe('–')
    expect(cell).toHaveAttribute('title', 'not every agent reported it')
  }
  expect(within(table).queryByRole('cell', { name: '0' })).not.toBeInTheDocument()
})

test('a middle value of zero is a zero, never "–"', async () => {
  const table = await tableOf([{ ...ran, steps: 0, seconds: 0, input_tokens: 0, output_tokens: 0 }])
  const cells = within(within(table).getAllByRole('row')[1]).getAllByRole('cell').map(drawn)
  expect(cells.slice(5, 9)).toEqual(['0', '0 s', '0', '0'])
  expect(within(table).queryByRole('cell', { name: 'not every agent reported it' })).not.toBeInTheDocument()
})

test('a long role name is whole in the library: never cut', () => {
  const name = 'A reviewer of everything the other agents wrote in the last turn and the one before'
  render(<AgentsPage roles={[role({ name })]} {...handlers()} />)
  expect(card(name).querySelector('.lib-row-name')).toHaveTextContent(name)
})

test("a role's record is folded, closed: its line says the gist, and opening it shows the table and its note; with no record there is none", async () => {
  const table = await tableOf([ran, { ...ran, model_id: 'other', agents: 2, ended: { done: 2, failed: 0, stopped_by_koloni: 0, stopped_by_user: 0, interrupted: 0 } }])
  const fold = table.closest('details')!
  expect(fold).not.toHaveAttribute('open')
  const line = within(fold).getByText(/^Record of the last 30 days: /)
  expect(line.tagName).toBe('SUMMARY')
  expect(line).toHaveTextContent('Record of the last 30 days: 9 ran on 2 models · 5 done · 1 failed · 1 stopped by KOLONİ · 2 stopped by you · 1 interrupted')
  await userEvent.click(line)
  expect(fold).toHaveAttribute('open')
  expect(within(fold).getByText('Middle values: half the agents took more, half less.')).toBeInTheDocument()
})

test('a role that has not run has no record, folded or not', async () => {
  await historyOf(vi.fn().mockResolvedValue([]))
  expect(screen.queryByText(/Record of the last 30 days:/)).not.toBeInTheDocument()
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  expect(screen.getByText('No agent of this role ended in the last 30 days.')).toBeInTheDocument()
})

test('the Observer has no tools to tick, and is saved with none', async () => {
  const h = handlers()
  const observer = role({ id: 'r3', name: 'Observer', tools: [], tier: 'balanced' })
  render(<AgentsPage roles={[observer]} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: /^Observer/ }))
  expect(screen.queryByRole('switch', { name: 'Observer on' })).not.toBeInTheDocument() // KOLONİ asks it: never off
  await userEvent.click(screen.getByRole('tab', { name: 'Tools' }))
  expect(screen.getByText(/Tools: none\. Where a project has it on/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Read files' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('tab', { name: 'Instructions' }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ tools: [], tier: 'balanced' })
  await userEvent.click(screen.getByRole('tab', { name: 'Overview' }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  expect(screen.queryByRole('radiogroup', { name: 'Thinking starts at' })).not.toBeInTheDocument() // its one question goes with no level
  expect(screen.queryByRole('checkbox', { name: /Run inside the CLI/ })).not.toBeInTheDocument()
})

test('a role shows its model’s window as found and where from, takes one set by you, and goes back to the found one', async () => {
  const h = handlers()
  const onRoleModels = vi.fn().mockResolvedValue([{ role: 'Reviewer', provider_name: 'Local', efforts: [], context_window: 80128 }])
  const compaction = vi.spyOn(api, 'get').mockResolvedValue({ compact_at: 80 })
  render(<AgentsPage roles={[role({})]} {...h} onRoleModels={onRoleModels} />)
  await edit('Reviewer', 'Edit model')
  const field = () => screen.getByLabelText('Context window')
  expect(await screen.findByText('Found automatically: 80,128 tokens (from the server).')).toBeInTheDocument()
  // the bar under it marks the app's "Summarise a long context at (%)", as read
  const mark = await screen.findByText('summarized past 80%')
  expect(mark.parentElement).toHaveStyle({ '--at': '80%' })
  expect(compaction).toHaveBeenCalledWith('/compaction')
  compaction.mockRestore()
  expect(screen.getByText(/Past the % in Settings › The app \(“Summarise a long context at \(%\)”\)/)).toBeInTheDocument()
  expect(screen.getByText('Set by hand').closest('details')).not.toHaveAttribute('open')
  expect(field()).toHaveAttribute('placeholder', '80128')
  await userEvent.type(field(), '0')
  expect(field()).toHaveAttribute('aria-invalid', 'true')
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  await userEvent.clear(field())
  await userEvent.type(field(), '32000')
  expect(screen.getByText(/Set by you; empty it to use the one found\./)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ context_window: 32000 })
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  await userEvent.clear(field())
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[1][1]).toMatchObject({ context_window: null })
})

test('a model whose window is not said shows it as unknown', async () => {
  render(<AgentsPage roles={[role({ context_window: 4096 })]} {...handlers()} onRoleModels={vi.fn().mockResolvedValue([{ role: 'Reviewer', efforts: [], context_window: null }])} />)
  await edit('Reviewer', 'Edit model')
  expect(await screen.findByText('Found automatically: unknown.')).toBeInTheDocument()
  // one set by hand: its fold is open, and the meter is known from it
  expect(screen.getByText('Set by hand').closest('details')).toHaveAttribute('open')
  expect(screen.getByLabelText('Context window')).toHaveValue('4096')
  expect(screen.getByText(/Set by you/)).toBeInTheDocument()
})

test('in the form, a tool switched off on the Tools page says so beside its switch (slice 61)', async () => {
  render(<AgentsPage roles={[role({})]} off={['web_search']} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: 'New role' }))
  expect(screen.getByLabelText('web_search').closest('label')).toHaveTextContent('search the web · off on the Tools page')
  expect(screen.getByLabelText('http_request').closest('label')).not.toHaveTextContent('off on the Tools page')
})

test('89g: a role may also run inside a Claude Code Lead - off until ticked, and it says what that costs', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({ builtin: false })]} {...h} />)
  await edit('Reviewer', 'Edit model')
  const inside = screen.getByRole('checkbox', { name: /Run inside the CLI/ })
  expect(inside).not.toBeChecked()
  // It depends on the agent that opens it running in Claude Code, not on the role's own provider.
  expect(screen.getByText('Only when the agent opening it runs in Claude Code.')).toBeInTheDocument()
  expect(screen.getByText(/the instructions hold any of % & \| < > !/)).toBeInTheDocument()
  await userEvent.click(inside)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave).toHaveBeenCalledWith('r1', expect.objectContaining({ inside_cli: true }))
})

test('K-rol-model: the Lead, whom nobody opens, has no most; its Auto sends no level of its own, and a click sets one', async () => {
  const h = handlers()
  const onRoleModels = vi.fn().mockResolvedValue([{ role: 'Lead', efforts: ['low', 'medium', 'high'] }])
  render(<AgentsPage roles={[role({ id: 'lead', name: 'Lead', kind: 'plan' })]} {...h} onRoleModels={onRoleModels} />)
  await userEvent.click(screen.getByRole('button', { name: 'Open the Lead' }))
  expect(screen.getByRole('complementary', { name: 'Role Lead' })).toHaveTextContent('How hard it thinksAutothe chat’s level, or the model’s own')
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  await screen.findByText(/Its model takes: Low, Medium, High\./)
  expect(checked()).toEqual([])
  expect(screen.getByText('Auto: no level is sent; the chat’s level, or the model’s own, applies.')).toBeInTheDocument()
  expect(screen.queryByText(/It picks Low for reading/)).not.toBeInTheDocument()
  await userEvent.click(rung('Medium'))
  await userEvent.click(rung('High'))
  // a higher level is its level, not a most
  expect(checked()).toEqual(['High'])
  expect(screen.getByText('It runs at High, unless the chat’s model picker sets a level.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ effort: 'high', max_effort: null })
})

test('back to Auto, a most of Off is taken away: Auto never runs "from Low up to Off"', async () => {
  const h = handlers()
  render(<AgentsPage roles={[role({ effort: 'off', max_effort: 'off' })]} {...h} onRoleModels={vi.fn().mockResolvedValue([{ role: 'Reviewer', efforts: ['off', 'low', 'high'] }])} />)
  await edit('Reviewer', 'Edit model')
  await screen.findByText(/Its model takes: Off, Low, High\./)
  await userEvent.click(mode('Auto'))
  expect(checked()).toEqual(['Highmost'])
  expect(screen.getByText('Auto picks a level for each task, from Low up to High. Click a level to move “most”.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ effort: null, max_effort: null })
})

test('a model whose name sets its level says so where its levels are told (B-404)', () => {
  const facts = { efforts: [], sources: { efforts: 'its name says its level' } } as never
  expect(levelsKnown([], namedLevel(facts))).toBe('Its name sets its level: nothing is sent.')
  expect(levelsKnown([], namedLevel({ efforts: [], sources: {} } as never))).toBe('The model’s levels are not known: nothing is sent.')
})

test('a role whose model’s name sets its level says so on its card and in its form (B-404)', async () => {
  render(<AgentsPage roles={[documenter]} {...handlers()} onRoleModels={vi.fn().mockResolvedValue([{ role: 'Documenter', efforts: [], level_named: true }])} />)
  await userEvent.click(card('Documenter'))
  const panel = screen.getByRole('complementary', { name: 'Role Documenter' })
  expect(await within(panel).findByText('its name sets its level: none is sent')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  expect(screen.getByText(/Its name sets its level: nothing is sent\./)).toBeInTheDocument()
})

test('a role on Copilot’s auto says Copilot picks the model and its level: none is sent', async () => {
  const runs = { role: 'Documenter', provider_name: 'Copilot', model_id: 'auto', efforts: [], level_named: true }
  render(<AgentsPage roles={[documenter]} {...handlers()} onRoleModels={vi.fn().mockResolvedValue([runs])} />)
  await userEvent.click(card('Documenter'))
  const panel = screen.getByRole('complementary', { name: 'Role Documenter' })
  expect(await within(panel).findByText('The model’s own')).toBeInTheDocument()
  expect(within(panel).getByText('Copilot picks the model and its level: none is sent')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Edit model' }))
  expect(screen.getByText(/Copilot picks the model and its level: nothing is sent\./)).toBeInTheDocument()
  const facts = { efforts: [], sources: { efforts: 'Copilot picks it (auto)' } } as never
  expect(levelsKnown([], namedLevel(facts))).toBe('Copilot picks the model and its level: nothing is sent.')
})
