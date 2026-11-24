import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { useApp } from '../state/store'
import { agent, convState, run } from '../test-fixtures'
import { namedOf } from './levels'
import { ModelPicker } from './ModelPicker'
import { ModelsPage } from './ModelsPage'
import { withRouting } from './routing'

const github = (over: Partial<Provider> = {}): Provider => ({
  id: 'gh',
  name: 'Copilot',
  kind: 'copilot_cli',
  base_url: null,
  default_model: null,
  executable: null,
  mode: 'native',
  options: null,
  for_agents: true,
  note: null,
  models: [
    { name: 'auto', note: null, tier: 'fast', agents: true },
    { name: 'fusion', note: null, tier: null, agents: true, routing: 'high' },
    { name: 'gpt-x', note: null, tier: 'strongest', agents: true },
  ],
  only_listed: false,
  max_running: null,
  plan: false,
  step_down_at: null,
  day_limit: null,
  month_limit: null,
  has_key: false,
  position: 0,
  created_at: '2026-11-21T10:00:00Z',
  updated_at: '2026-11-21T10:00:00Z',
  ...over,
})

const handlers = {
  onCreate: vi.fn(async () => {}),
  onDelete: vi.fn(async () => {}),
  onTest: vi.fn(async () => ({ ok: true, model_id: 'x', tools_supported: true, error: null, reply: null })),
}

const options = (select: HTMLElement) =>
  within(select)
    .getAllByRole('option')
    .map(option => option.textContent)

test('Copilot’s auto and fusion on your GitHub account take a routing on their row, saved at once', async () => {
  const onSave = vi.fn(async () => {})
  render(<ModelsPage providers={[github()]} {...handlers} onSave={onSave} />)
  await userEvent.click(screen.getByRole('button', { name: /^Copilot/ }))
  const dialog = screen.getByRole('dialog', { name: 'Copilot' })
  const auto = within(dialog).getByLabelText('Routing of auto')
  // (Before its account was asked: every routing the package knows.)
  expect(options(auto)).toEqual(['Default', 'Efficiency', 'Balance', 'Intelligence', 'Fast'])
  expect(auto).toHaveValue('')
  const fusion = within(dialog).getByLabelText('Routing of fusion')
  expect(options(fusion)).toEqual(['Default', 'Standard', 'High', 'Max'])
  expect(fusion).toHaveValue('high')
  expect(fusion).toHaveAttribute('title', expect.stringMatching(/cost more than auto/))
  expect(within(dialog).queryByLabelText('Routing of gpt-x')).not.toBeInTheDocument()
  await userEvent.selectOptions(auto, 'balance')
  expect(onSave).toHaveBeenLastCalledWith('gh', {
    models: [
      { name: 'auto', note: null, tier: 'fast', agents: true, routing: 'balance' },
      { name: 'fusion', note: null, tier: null, agents: true, routing: 'high' },
      { name: 'gpt-x', note: null, tier: 'strongest', agents: true },
    ],
  })
  expect(await within(dialog).findByText('auto: balance routing.')).toBeInTheDocument()
})

test('a Copilot on a model server of your own has no routing', async () => {
  render(
    <ModelsPage
      providers={[github({ base_url: 'http://localhost:8080/v1' })]}
      {...handlers}
      onSave={vi.fn(async () => {})}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: /^Copilot/ }))
  expect(screen.getByText('auto')).toBeInTheDocument()
  expect(screen.queryByLabelText('Routing of auto')).not.toBeInTheDocument()
})

test('the chat’s model panel shows Copilot’s routing and saves it on its Models row; none for another model', async () => {
  const onRouting = vi.fn(async () => {})
  const { unmount } = render(
    <ModelPicker providers={[github()]} providerId="gh" modelId="auto" onSave={async () => {}} onRouting={onRouting} />,
  )
  await userEvent.click(screen.getByRole('button', { name: /^Model:/ }))
  const routing = screen.getByLabelText('Routing')
  expect(
    screen.getByText('Saved on its Models row: every chat and agent on Copilot · auto uses it.'),
  ).toBeInTheDocument()
  await userEvent.selectOptions(routing, 'balance')
  expect(onRouting).toHaveBeenLastCalledWith('gh', [
    { name: 'auto', note: null, tier: 'fast', agents: true, routing: 'balance' },
    { name: 'fusion', note: null, tier: null, agents: true },
    { name: 'gpt-x', note: null, tier: 'strongest', agents: true },
  ])
  unmount()
  render(
    <ModelPicker
      providers={[github()]}
      providerId="gh"
      modelId="gpt-x"
      onSave={async () => {}}
      onRouting={onRouting}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: /^Model:/ }))
  expect(screen.queryByLabelText('Routing')).not.toBeInTheDocument()
})

// As Copilot 1.0.114's models.list said the user's account on 24 Nov 2026 (app/copilot_offers.py keeps it so).
const NOT_ON_PLAN = "This tier is not available for the user's Copilot plan."
const offers: NonNullable<Provider['offers']> = {
  models: [],
  tiers: [
    { id: 'balance', name: 'Standard', type: 'auto', fusion: 'standard', enabled: true, why: null },
    { id: 'hydrafusion', name: 'High', type: 'fusion', fusion: 'high', enabled: false, why: NOT_ON_PLAN },
    { id: 'hydrafusion-max', name: 'Max', type: 'fusion', fusion: 'max', enabled: false, why: NOT_ON_PLAN },
    { id: 'fast', name: 'Fast', type: 'auto', fusion: null, enabled: true, why: null },
  ],
}

test('once its account was asked, a routing offers only its tiers, by its names; one it lacks is dimmed with why', async () => {
  const onOffers = vi.fn(async () => {})
  const rows: Provider['models'] = [
    { name: 'auto', note: null, tier: 'fast', agents: true, routing: 'efficiency' },
    { name: 'fusion', note: null, tier: null, agents: true, routing: 'high' },
  ]
  render(
    <ModelsPage
      providers={[github({ offers, models: rows })]}
      {...handlers}
      onSave={vi.fn(async () => {})}
      onOffers={onOffers}
    />,
  )
  // Asked as the page opens: the server asks the account at most once in 10 minutes.
  expect(onOffers).toHaveBeenCalledWith('gh')
  await userEvent.click(screen.getByRole('button', { name: /^Copilot/ }))
  const dialog = screen.getByRole('dialog', { name: 'Copilot' })
  const auto = within(dialog).getByLabelText('Routing of auto')
  // Its own `fast` is offered (not in Copilot's picker, on in the account); a routing it does not list stays, dimmed.
  expect(options(auto)).toEqual(['Default', 'Standard', 'Fast', 'Efficiency — not on your plan'])
  expect(within(auto).getByRole('option', { name: 'Efficiency — not on your plan' })).toBeDisabled()
  expect(auto).toHaveValue('efficiency')
  const fusion = within(dialog).getByLabelText('Routing of fusion')
  expect(options(fusion)).toEqual(['Default', 'Standard', 'High — not on your plan', 'Max — not on your plan'])
  const high = within(fusion).getByRole('option', { name: 'High — not on your plan' })
  expect(high).toBeDisabled()
  expect(high).toHaveAttribute('title', NOT_ON_PLAN)
  expect(within(fusion).getByRole('option', { name: 'Standard' })).toBeEnabled()
})

test('the chat’s model panel asks Copilot’s account as it opens on it, and offers only its tiers', async () => {
  const onOffers = vi.fn(async () => {})
  render(
    <ModelPicker
      providers={[github({ offers })]}
      providerId="gh"
      modelId="auto"
      onSave={async () => {}}
      onRouting={async () => {}}
      onOffers={onOffers}
    />,
  )
  expect(onOffers).not.toHaveBeenCalled() // (not before it is opened)
  await userEvent.click(screen.getByRole('button', { name: /^Model:/ }))
  expect(onOffers).toHaveBeenCalledWith('gh')
  expect(options(screen.getByLabelText('Routing'))).toEqual(['Default', 'Standard', 'Fast'])
})

test('a fill of a Copilot account that lists no models proposes only what it offers, and says why', async () => {
  const note =
    'Your Copilot account lists no models by name now: only what it offers is proposed, and each other model is ' +
    'switched off until Copilot lists it again.'
  const onFill = vi.fn(async () => ({
    models: [{ name: 'auto', note: null, tier: 'fast' as const }],
    left_out: 0,
    note,
  }))
  render(
    <ModelsPage
      providers={[github({ offers, models: [] })]}
      picked="gh"
      {...handlers}
      onSave={vi.fn(async () => {})}
      onFill={onFill}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Fill from the catalogue' }))
  expect(onFill).toHaveBeenCalledWith('gh')
  expect(screen.getByText(note)).toHaveAttribute('role', 'note')
  expect(screen.getByText(/not saved yet/)).toBeInTheDocument()
  expect(screen.getByLabelText('Routing of auto')).toBeInTheDocument()
})

test('fusion picks its own level, as auto does', () => {
  expect(namedOf(true, 'fusion')).toBe('auto')
  expect(namedOf(true, 'auto')).toBe('auto')
  expect(namedOf(true, 'gemini-3-high')).toBe('name')
})

test('a routing saved from the chat sends each row’s agents as the Models tab does', () => {
  // (A provider agents may not choose: its rows say no, as the Models tab's own save says it.)
  const off = github({ for_agents: false })
  expect(withRouting(off, 'auto', 'balance').map(row => [row.name, row.agents, row.routing])).toEqual([
    ['auto', false, 'balance'],
    ['fusion', false, undefined],
    ['gpt-x', false, undefined],
  ])
})

test('the chat’s model button says the model fusion picked for the chat’s latest turn, and Copilot’s reason in its tooltip', () => {
  const why = 'Copilot Fusion selected GPT-6 Luna since the task has low complexity.'
  const picker = (modelId: string) => (
    <ModelPicker providers={[github()]} providerId="gh" modelId={modelId} onSave={async () => {}} />
  )
  const { rerender } = render(picker('fusion'))
  const button = screen.getByRole('button', { name: /^Model:/ })
  // Before a turn ran on it: what was chosen.
  expect(button).toHaveTextContent(/^fusion · Copilot$/)
  const lead = (id: string, model_id: string, model_from: string, note: string) =>
    agent(id, 'completed', {
      provider_name: 'Copilot',
      model_id,
      model_from,
      effort_note: `Copilot's ${model_from} picked ${model_id}: “${note}”`,
    })
  const turns = (agents: ReturnType<typeof agent>[]) =>
    act(() => useApp.setState({ conv: convState({ runs: [run('r1', 'completed'), run('r2', 'completed')], agents }) }))
  // (The latest turn's Lead: of its run - a comparison's other side, whose Lead started after it, is not it.)
  turns([lead('r2', 'gpt-6-luna', 'fusion', why), lead('r1', 'gpt-7', 'fusion', 'Hard.')])
  expect(button).toHaveTextContent(/^fusion → gpt-6-luna · Copilot$/)
  // Its name and tooltip say what the chat uses, and what its last turn ran on - not that agents use that.
  expect(button).toHaveAccessibleName('Model: Copilot · fusion, last picked gpt-6-luna')
  expect(button).toHaveAttribute(
    'title',
    `Copilot · fusion: the model this conversation's agents use. Its last turn ran on gpt-6-luna: ${why}`,
  )
  // (The latest turn's Lead ran elsewhere - its role's own model, say: no pick of an older turn's is shown for it.)
  turns([lead('r1', 'gpt-6-luna', 'fusion', why), agent('r2', 'completed', { provider_name: 'Local' })])
  expect(button).toHaveTextContent(/^fusion · Copilot$/)
  expect(button).toHaveAccessibleName('Model: Copilot · fusion')
  expect(button.title).not.toContain(why)
  // (A later model said with no reason: no reason of the model before under it.)
  turns([{ ...lead('r2', 'gpt-6-luna', 'fusion', why), model_id: 'gpt-7' }])
  expect(button).toHaveTextContent(/^fusion → gpt-7 · Copilot$/)
  expect(button).toHaveAttribute(
    'title',
    "Copilot · fusion: the model this conversation's agents use. Its last turn ran on gpt-7.",
  )
  // (A pick of auto's is not fusion's: the chat moved on from it.)
  turns([lead('r2', 'gpt-6-luna', 'fusion', why)])
  rerender(picker('auto'))
  expect(button).toHaveTextContent(/^auto · Copilot$/)
  expect(button.title).not.toContain(why)
  act(() => useApp.setState({ conv: null }))
})
