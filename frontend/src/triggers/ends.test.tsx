// A trigger's end (K-tetik-bitis), its skip when nothing changed (K-tetik-degismedi) and an agent's proposed trigger (slice 69).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Trigger, TriggerProposal } from '../api/types'
import { conversation } from '../test-fixtures'
import { newTrigger, trigger, triggerRun } from './fixtures'
import { TriggerProposalCard } from './TriggerProposalCard'
import { TriggersPage } from './TriggersPage'
import { endLine, offLine, outcomeOf } from './triggerText'

const proposal = (over: Partial<TriggerProposal> = {}): TriggerProposal => ({
  id: 'p1',
  conversation_id: 'c',
  run_id: 'r1',
  name: 'Dependencies',
  kind: 'schedule',
  config: { at: '17:00', days: ['fri'] },
  message: 'Look over the dependencies. Change nothing.',
  ends: { runs: 10 },
  status: 'proposed',
  trigger_id: null,
  created_at: 't',
  ...over,
})

function page(over: object = {}) {
  const h = {
    onCreate: vi.fn(async (values: object) => ({ ...trigger(values as Partial<Trigger>), id: 'new', key: null as string | null })),
    onSave: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn(),
    onRun: vi.fn(),
    onShowTurn: vi.fn(),
    onDraftTaken: vi.fn(),
    onRules: vi.fn(async () => []),
    onAddRule: vi.fn(),
  }
  render(<TriggersPage triggers={[]} conversations={[conversation]} draft={null} origin="http://127.0.0.1:8790" {...h} {...over} />)
  return h
}
const form = () => within(screen.getByRole('form', { name: /trigger/i }))

test('with no end the form warns, and says what it may cost from the budget as typed; an end clears the warning', async () => {
  page()
  await newTrigger()
  const f = form()
  expect(f.getByRole('radio', { name: 'No end' })).toBeChecked()
  const warning = f.getByRole('note', { name: 'No end' })
  expect(warning).toHaveTextContent('No end: it runs until you switch it off. Up to 24 runs a day, each up to 15 model steps and 10 minutes')
  await userEvent.clear(f.getByLabelText('Runs a day'))
  await userEvent.type(f.getByLabelText('Runs a day'), '3')
  expect(warning).toHaveTextContent('Up to 3 runs a day')
  await userEvent.click(f.getByRole('radio', { name: 'After so many runs' }))
  expect(f.queryByRole('note', { name: 'No end' })).not.toBeInTheDocument()
  expect(f.getByLabelText('Runs, then it switches itself off')).toHaveValue(10)
})

test('an end after so many runs, or after a day, is sent as the server takes it; a count out of bounds is not sent', async () => {
  const h = page()
  await newTrigger()
  const f = form()
  await userEvent.type(f.getByLabelText('Name'), 'Hourly look')
  await userEvent.type(f.getByLabelText('Message'), 'Look the project over.')
  await userEvent.click(f.getByRole('radio', { name: 'After so many runs' }))
  await userEvent.clear(f.getByLabelText('Runs, then it switches itself off'))
  await userEvent.type(f.getByLabelText('Runs, then it switches itself off'), '0')
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate).not.toHaveBeenCalled()
  expect(f.getByLabelText('Runs, then it switches itself off')).toHaveAccessibleDescription('From 1 to 1000.')
  await userEvent.clear(f.getByLabelText('Runs, then it switches itself off'))
  await userEvent.type(f.getByLabelText('Runs, then it switches itself off'), '7')
  // A clock trigger may be told to run even when nothing changed.
  await userEvent.click(f.getByLabelText('Run even if nothing changed'))
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate).toHaveBeenCalledWith(expect.objectContaining({ ends: { runs: 7 }, run_unchanged: true, proposal_id: null }))
})

test('an end after a day starts at today and is sent as that day', async () => {
  const h = page()
  await newTrigger()
  const f = form()
  await userEvent.type(f.getByLabelText('Name'), 'Until Friday')
  await userEvent.type(f.getByLabelText('Message'), 'Look.')
  await userEvent.click(f.getByRole('radio', { name: 'After a day' }))
  const day = f.getByLabelText('Its last day') as HTMLInputElement
  expect(day.value).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate).toHaveBeenCalledWith(expect.objectContaining({ ends: { until: day.value } }))
})

test('a card says its end and the runs done toward it; one that ended says why, not as a failure', () => {
  expect(endLine(trigger())).toBe('no end: it runs until you switch it off')
  expect(endLine(trigger({ ends: { runs: 10 }, ran: 3 }))).toBe('after 10 runs · 3 done')
  expect(endLine(trigger({ ends: { until: '2026-11-01' } }))).toBe('after 2026-11-01')
  expect(offLine(trigger({ enabled: false, failures: 1, off_because: 'ended: 10 runs done' }))).toBe('ended: 10 runs done')
  expect(outcomeOf(triggerRun('1', 'skipped_same'))).toBe('skipped: nothing changed since the last run')
})

test('a proposed trigger says when, its end, what it does and that it reads only; each button does its one thing', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const onEdit = vi.fn()
  render(<TriggerProposalCard proposal={proposal()} onDecide={onDecide} onEdit={onEdit} />)
  const card = screen.getByRole('region', { name: 'Proposed trigger: Dependencies' })
  expect(card).toHaveTextContent('Fridays at 17:00 · ends after 10 runs')
  // The agent's words for each run, whole and said to be the agent's.
  expect(card).toHaveTextContent('Each run is told (written by the agent):Look over the dependencies. Change nothing.')
  expect(card).toHaveTextContent('reads only · no sub-agents · 15 model steps and 10 minutes a run · 24 runs a day')
  await userEvent.click(within(card).getByRole('button', { name: 'Edit' }))
  expect(onEdit).toHaveBeenCalled()
  await userEvent.click(within(card).getByRole('button', { name: 'Approve' }))
  expect(onDecide).toHaveBeenLastCalledWith('approve')
  await userEvent.click(within(card).getByRole('button', { name: 'Reject' }))
  expect(onDecide).toHaveBeenLastCalledWith('reject')
})

test('a refused Approve is said on the card; a decided one is one line', async () => {
  const onDecide = vi.fn().mockRejectedValue(new Error('this proposal was rejected already'))
  const { rerender } = render(<TriggerProposalCard proposal={proposal()} onDecide={onDecide} onEdit={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: 'Approve' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('this proposal was rejected already')
  rerender(<TriggerProposalCard proposal={proposal({ status: 'approved', trigger_id: 't9' })} onDecide={onDecide} onEdit={vi.fn()} />)
  expect(screen.getByRole('note')).toHaveTextContent('The trigger “Dependencies” was made: it is on the Triggers page.')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test('Edit on a proposal opens a new trigger’s form filled in, allowed nothing; saved, it names the proposal', async () => {
  const h = page({ draft: { proposal: proposal({ ends: { runs: 4 } }) } })
  const f = form()
  expect(f.getByLabelText('Name')).toHaveValue('Dependencies')
  expect(f.getByRole('radio', { name: 'After so many runs' })).toBeChecked()
  expect(f.getByLabelText('Runs, then it switches itself off')).toHaveValue(4)
  expect(f.getByLabelText('May change files')).not.toBeChecked()
  expect(h.onDraftTaken).toHaveBeenCalled()
  await userEvent.click(f.getByRole('button', { name: 'Add trigger' }))
  expect(h.onCreate).toHaveBeenCalledWith(
    expect.objectContaining({ name: 'Dependencies', config: { at: '17:00', days: ['fri'] }, ends: { runs: 4 }, proposal_id: 'p1', permissions: { write: false, commands: [], agents: 0 } }),
  )
  await waitFor(() => expect(screen.queryByRole('form')).not.toBeInTheDocument())
})

test('a trigger past its last day says to change the day before it is switched on again', () => {
  page({ triggers: [trigger({ enabled: false, ends: { until: '2026-10-01' }, off_because: 'ended: its last day, 2026-10-01, is over' })] })
  expect(screen.getByRole('alert')).toHaveTextContent('ended: its last day, 2026-10-01, is over To run it more, change its last day (Edit), then switch it on again.')
})
