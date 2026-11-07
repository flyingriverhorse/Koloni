import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Availability, FilledProvider, Provider } from '../api/types'
import { FillTiers } from './FillTiers'
import { dayOf } from './levels'
import { ModelsPage, stateOf } from './ModelsPage'

// Slice 60d: with no model given a tier, every role runs on the conversation's model; a box says so on
// Agents (on Models since 81a: a button) and opens one preview of every provider's tiers, saved only on Save.

const provider = (over: Partial<Provider>): Provider => ({
  id: 'p1',
  name: 'Local',
  kind: 'openai_compat',
  base_url: 'http://127.0.0.1:8080/v1',
  default_model: null,
  executable: null,
  mode: null,
  options: null,
  for_agents: true,
  note: null,
  models: [],
  only_listed: false,
  max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
  has_key: false,
  position: 0,
  created_at: 't',
  updated_at: 't',
  ...over,
})
const NOTES = { strongest: 'Among its strongest', balanced: 'Strength and speed balanced', fast: 'Fast and cheap' }
const proposal: FilledProvider[] = [
  { id: 'p1', name: 'Local', kind: 'openai_compat', catalogued: false, for_agents: false, models: [{ name: 'qwen', note: null, tier: null, agents: true }] },
  {
    id: 'p2',
    name: 'Claude Code',
    kind: 'claude_cli',
    catalogued: true,
    for_agents: true,
    models: [
      { name: 'opus', note: NOTES.strongest, tier: 'strongest', agents: true },
      { name: 'haiku', note: NOTES.fast, tier: 'fast', agents: true },
      { name: 'sonnet', note: 'mine', tier: 'balanced', agents: true },
    ],
  },
]

test('the box opens a preview; Save sends what is shown, as it was changed; Cancel sends nothing', async () => {
  const onFillAll = vi.fn().mockResolvedValue({ providers: proposal, notes: NOTES })
  const onSaveFillAll = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<FillTiers providers={[provider({})]} onFillAll={onFillAll} onSaveFillAll={onSaveFillAll} />)
  expect(screen.getByRole('region', { name: 'No model has a tier' })).toHaveTextContent(
    'No model has a tier yet, so the Orchestrator cannot pick one: every role runs on the conversation’s model. Fill the tiers',
  )
  await userEvent.click(screen.getByRole('button', { name: 'Fill the tiers' }))
  const preview = await screen.findByRole('region', { name: 'Tiers from the catalogue' })
  expect(screen.getByRole('heading', { name: 'Tiers from the catalogue' })).toHaveFocus()
  expect(within(preview).getByLabelText('Agents may choose this: Claude Code')).toBeChecked()
  expect(within(preview).getByLabelText('Tier of opus on Claude Code')).toHaveValue('strongest')
  // Cancel: nothing is sent, and the box is back, with the keyboard on its button.
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(onSaveFillAll).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Fill the tiers' })).toHaveFocus()
  await userEvent.click(screen.getByRole('button', { name: 'Fill the tiers' }))
  // A tier given to the server the catalogue does not know ticks it; the catalogue's note follows a
  // changed tier, the user's own does not.
  await userEvent.selectOptions(await screen.findByLabelText('Tier of qwen on Local'), 'balanced')
  expect(screen.getByLabelText('Agents may choose this: Local')).toBeChecked()
  await userEvent.selectOptions(screen.getByLabelText('Tier of haiku on Claude Code'), 'strongest')
  await userEvent.selectOptions(screen.getByLabelText('Tier of sonnet on Claude Code'), 'fast')
  await userEvent.click(screen.getByLabelText('Agents may choose this: Claude Code'))
  await userEvent.click(screen.getByRole('button', { name: 'Save these tiers' }))
  expect(onSaveFillAll).toHaveBeenCalledWith([
    { ...proposal[0], for_agents: true, models: [{ name: 'qwen', note: null, tier: 'balanced', agents: true }] },
    {
      ...proposal[1],
      for_agents: false,
      models: [
        proposal[1].models[0],
        { name: 'haiku', note: NOTES.strongest, tier: 'strongest', agents: true },
        { name: 'sonnet', note: 'mine', tier: 'fast', agents: true },
      ],
    },
  ])
  // Once a model has a tier the box is gone, and what Save did is said where it was.
  rerender(<FillTiers providers={[provider({ models: [{ name: 'qwen', note: null, tier: 'fast', agents: true }] })]} onFillAll={onFillAll} onSaveFillAll={onSaveFillAll} />)
  expect(screen.queryByRole('region', { name: 'No model has a tier' })).not.toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Tiers from the catalogue' })).not.toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(/^The tiers are saved/)
})

const avail = (over: Partial<Availability>): Availability => ({ installed: null, models: [], ...over }) as Availability

test('a provider’s dot says its state in words too', () => {
  const cli = provider({ kind: 'claude_cli', base_url: null })
  expect(stateOf(provider({ kind: 'anthropic', has_key: false }), undefined)).toEqual(['off', 'no key yet'])
  expect(stateOf(cli, avail({ installed: true, signed_in: true }))).toEqual(['ok', 'signed in'])
  expect(stateOf(cli, avail({ installed: true, signed_in: true, plan: 'max' }))).toEqual(['ok', 'signed in · max'])
  expect(stateOf(cli, avail({ installed: false }))).toEqual(['bad', 'not installed'])
  expect(stateOf(provider({}), avail({ models: [{ name: 'qwen', state: 'usable', why: null, retired: false }] }))).toEqual(['ok', 'running'])
  const refused = avail({ models: [{ name: 'm', state: 'unknown', why: 'HTTP 401 Unauthorized', retired: false }] })
  expect(stateOf(provider({ kind: 'anthropic', has_key: true }), refused)).toEqual(['bad', 'key refused · check it'])
  const down = avail({ models: [{ name: 'qwen', state: 'unknown', why: 'model server unreachable: refused', retired: false }] })
  expect(stateOf(provider({}), down)).toEqual(['bad', 'not answering'])
  expect(stateOf(provider({}), avail({ models: [] }))).toEqual(['off', 'not known'])
})

test('a server that does not answer is said once, not by each lookup that failed', async () => {
  const onFacts = vi.fn().mockResolvedValue({
    efforts: null, context_window: null, max_output: null, price: null, tier: null, deprecated: null, sources: {}, catalogue_date: null, failed: true,
  })
  const onModels = vi.fn().mockResolvedValue({ models: [], note: 'model server unreachable: connection refused' })
  render(
    <ModelsPage
      providers={[provider({ default_model: 'qwen' })]}
      picked="p1"
      onCreate={vi.fn()}
      onSave={vi.fn()}
      onDelete={vi.fn()}
      onTest={vi.fn()}
      onFacts={onFacts}
      onModels={onModels}
    />,
  )
  expect(await screen.findByText('Local isn’t answering: its models and levels show once it does.')).toBeInTheDocument()
  expect(screen.queryByText(/unreachable/)).not.toBeInTheDocument()
  expect(screen.queryByText(/Could not look up/)).not.toBeInTheDocument()
})

test('only the open provider and a server on this machine are read in full; the others’ dots from what costs nothing', async () => {
  const onAvailability = vi.fn().mockResolvedValue({ installed: true, models: [] })
  const claude = provider({ id: 'p2', name: 'Claude Code', kind: 'claude_cli', base_url: null })
  render(<ModelsPage providers={[provider({}), claude]} onCreate={vi.fn()} onSave={vi.fn()} onDelete={vi.fn()} onTest={vi.fn()} onAvailability={onAvailability} />)
  await waitFor(() => expect(onAvailability).toHaveBeenCalledTimes(2))
  expect(onAvailability.mock.calls).toEqual(expect.arrayContaining([['p1', false], ['p2', true]]))
  const card = screen.getByRole('button', { name: /^Claude Code/ })
  await waitFor(() => expect(card.querySelector('.state-dot')).toHaveClass('state-ok'))
  // opened, it is read in full
  await userEvent.click(card)
  await waitFor(() => expect(onAvailability).toHaveBeenLastCalledWith('p2'))
})

test('a catalogue read on a day is that day, wherever this machine is', () => {
  expect(dayOf('2026-10-21', false)).toBe('21 Oct')
  expect(dayOf('2026-10-21')).toBe('21 Oct')
})
