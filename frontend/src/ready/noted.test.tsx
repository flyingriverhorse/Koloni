import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Decision } from '../api/types'
import { useApp } from '../state/store'
import { Decisions } from './Decisions'

afterEach(() => {
  vi.unstubAllGlobals()
  useApp.setState({ loadBoard: useApp.getInitialState().loadBoard })
})

/** A decision the Orchestrator noted itself (note_decision, 0.1.11). */
const noted: Decision = {
  id: 'noted:n1',
  at: new Date().toISOString(),
  kind: 'noted',
  who: 'orchestrator',
  what: 'Decided',
  quote: 'Use SQLite for the cart',
  answer: null,
  why: 'One user, no server to run',
  conversation_id: 'c1',
  chat: 'Shop',
  link: { kind: 'noted', id: 'n1' },
  undo: 'change',
  undo_reason: null,
  seen: false,
}

test('a noted decision says the Orchestrator decided, why, and takes your OK and your own Change', async () => {
  const asked = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', asked)
  useApp.setState({ loadBoard: vi.fn().mockResolvedValue(undefined) })
  const onLoad = vi.fn().mockResolvedValue({ rows: [noted], judge_fine: 0, more: false })
  render(<Decisions onLoad={onLoad} leftAt={null} />)
  const row = (await screen.findByText('Use SQLite for the cart')).closest('li') as HTMLElement
  expect(row).toHaveTextContent('Orchestrator')
  expect(row).toHaveTextContent('Decided: Use SQLite for the cart')
  expect(within(row).getByText('One user, no server to run')).toBeInTheDocument()
  await userEvent.click(within(row).getByRole('button', { name: 'Change' }))
  await userEvent.type(within(row).getByLabelText('What you decide instead'), 'Use Postgres')
  await userEvent.click(within(row).getByRole('button', { name: 'Send' }))
  await waitFor(() =>
    expect(asked).toHaveBeenCalledWith(
      '/api/decisions/n1/change',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ words: 'Use Postgres' }) }),
    ),
  )
  expect(await screen.findByText('Sent to the Orchestrator')).toBeInTheDocument()
  await userEvent.click(within(row).getByRole('button', { name: 'OK' }))
  await waitFor(() =>
    expect(asked).toHaveBeenCalledWith('/api/decisions/n1/ok', expect.objectContaining({ method: 'POST' })),
  )
})
