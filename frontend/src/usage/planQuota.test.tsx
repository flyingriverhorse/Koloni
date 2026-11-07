import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { dayAndTime } from '../agents/failure'
import type { Limits, Provider } from '../api/types'
import { readingOf } from '../models/cards'
import { ModelsPage } from '../models/ModelsPage'
import { PlanLimits } from './PlanLimits'
import { PlanUse } from './PlanUse'

// K-agy-kota: agy's /quota and Copilot's getQuota, read without a turn, on the plan meter, the Models card and Usage.

const provider = (id: string, name: string, kind: Provider['kind']): Provider => ({
  id,
  name,
  kind,
  base_url: null,
  default_model: null,
  executable: null,
  mode: null,
  options: null,
  for_agents: false,
  note: null,
  models: [],
  only_listed: false,
  max_running: null,
  plan: false,
  step_down_at: null,
  day_limit: null,
  month_limit: null,
  has_key: kind === 'copilot_cli',
  position: 0,
  created_at: 't',
  updated_at: 't',
})
const RESETS = '2026-10-31T15:03:17Z'
const reading = (windows: Limits['windows']): Limits => ({ unknown: null, read_at: null, source: null, plan: null, windows, credits: null })
// As the backend shows what was measured: agy's two groups a week each, Copilot's premium requests with no length.
const agyRead = reading([
  { name: 'Gemini Models', minutes: 10080, used_percent: 7.84, resets_at: '2026-10-31T08:44:11Z', stale: false },
  { name: 'Claude and GPT models', minutes: 10080, used_percent: 0, resets_at: RESETS, stale: false },
])
const copilotRead = reading([{ name: 'premium requests', minutes: null, used_percent: 90.2, resets_at: '2026-11-01T00:00:00Z', stale: false }])
const agy = provider('a', 'agy', 'agy_cli')
const copilot = provider('g', 'Copilot', 'copilot_cli')
const told: Record<string, Limits> = { a: agyRead, g: copilotRead }

test('the plan meter shows agy and Copilot by their short names, each window named', async () => {
  render(<PlanUse providers={[agy, copilot]} onLimits={id => Promise.resolve(told[id])} every={60000} onOpen={() => {}} />)
  const button = await screen.findByRole('button', { name: 'Plan use: agy 8% of Gemini Models this week, Copilot 90% of premium requests; open Usage' })
  expect(button).toHaveTextContent('agy8%Copilot90%')
  expect(button).toHaveAttribute('title', 'agy: 8% of Gemini Models this week used\nCopilot: 90% of premium requests used')
})

test('their cards say what is left of each window, by the name its CLI gives it', () => {
  expect(readingOf(agy, { limits: agyRead })).toEqual({
    share: 0.92,
    value: '92%',
    label: 'left of Gemini Models this week',
    more: `Claude and GPT models this week 100% left · resets ${dayAndTime(RESETS)}`,
  })
  expect(readingOf(copilot, { limits: copilotRead })).toEqual({ share: 0.1, value: '10%', label: 'left of premium requests', more: undefined })
})

test('their cards and Usage’s Check now read them afresh: neither costs a turn', async () => {
  const onLimits = vi.fn((id: string, afresh: boolean) => Promise.resolve(afresh ? told[id] : { ...reading([]), unknown: 'not read yet' }))
  const { unmount } = render(<ModelsPage providers={[agy, copilot]} onCreate={vi.fn()} onSave={vi.fn()} onDelete={vi.fn()} onTest={vi.fn()} onLimits={onLimits} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Read agy’s plan now' }))
  await userEvent.click(screen.getByRole('button', { name: 'Read Copilot’s plan now' }))
  await waitFor(() => expect(screen.getByRole('button', { name: /^Copilot.*10%\s*left of premium requests/ })).toBeInTheDocument())
  expect(screen.queryByText('one short request')).not.toBeInTheDocument()
  unmount()
  onLimits.mockClear()
  render(<PlanLimits providers={[agy, copilot]} onLimits={onLimits} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Check now' }))
  await waitFor(() => expect(onLimits).toHaveBeenCalledTimes(4))
  expect(onLimits.mock.calls.slice(2)).toEqual([
    ['a', true],
    ['g', true],
  ])
  await waitFor(() =>
    expect(screen.getByRole('table', { name: 'Plan limits by provider' })).toHaveTextContent(
      /7.84% of Gemini Models this week used, resets .+ · 0% of Claude and GPT models this week used.+90.2% of premium requests used/,
    ),
  )
})
