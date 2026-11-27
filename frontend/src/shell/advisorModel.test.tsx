import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { AdvisorOut } from '../api/types'
import { ADVISOR_WHY, useAdvisorModel } from './sections/AdvisorModel'

afterEach(() => vi.restoreAllMocks())

const READ: AdvisorOut = {
  provider_id: null,
  model_id: null,
  choices: [
    { provider_id: 'p1', provider_name: 'Local', model_id: 'quick', cli: false, measured: false, tier: 'fast' },
    { provider_id: 'p2', provider_name: 'Claude Code', model_id: 'haiku', cli: true, measured: false, tier: 'fast' },
  ],
}

function Advisor() {
  return useAdvisorModel()
}

test('The app › Agents: the Advisor model is another provider’s until one is chosen, kept as it is changed', async () => {
  vi.spyOn(api, 'get').mockResolvedValue(READ as never)
  const put = vi
    .spyOn(api, 'put')
    .mockImplementation(async (_path, body) => ({ ...READ, ...(body as object) }) as never)
  render(<Advisor />)
  const box = screen.getByLabelText('Advisor model')
  await waitFor(() => expect(box).toBeEnabled())
  expect(
    within(box)
      .getAllByRole('option')
      .map(one => one.textContent),
  ).toEqual(['Another provider’s than the Orchestrator’s', 'Local · quick (fast)', 'Claude Code · haiku (fast)'])
  expect(screen.getByText(ADVISOR_WHY)).toBeInTheDocument()
  await userEvent.selectOptions(box, 'Claude Code · haiku (fast)')
  expect(put).toHaveBeenLastCalledWith('/advisor', { provider_id: 'p2', model_id: 'haiku' })
  await waitFor(() => expect(box).toHaveDisplayValue('Claude Code · haiku (fast)'))
  await userEvent.selectOptions(box, 'Another provider’s than the Orchestrator’s')
  expect(put).toHaveBeenLastCalledWith('/advisor', { provider_id: null, model_id: null })
})

test('a chosen Advisor model that cannot be asked now stays chosen and says so', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ ...READ, provider_id: 'gone', model_id: 'old' } as never)
  render(<Advisor />)
  expect(await screen.findByText(/Your choice, old, cannot be asked now/)).toBeInTheDocument()
  expect(screen.getByLabelText('Advisor model')).toHaveDisplayValue('old (cannot be asked now)')
})
