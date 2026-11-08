import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { PendingRole } from '../api/types'
import { agent } from '../test-fixtures'
import { RoleApproval } from './RoleApproval'
import { SpawnApproval } from './SpawnApproval'
import { SpawnRow } from './SpawnRow'

const coder = agent('r', 'proposed', {
  id: 'kid',
  parent_agent_id: 'r',
  role_name: 'Coder',
  task: 'Fix the greeting in hello.py\nThen run the tests.',
  tools: ['read_file', 'edit_file', 'run_command'],
  depth: 1,
  started_at: null,
})

test('a spawn row names the role, the first line of the task and the status', async () => {
  const onSelect = vi.fn()
  render(<SpawnRow agent={{ ...coder, status: 'running' }} onSelect={onSelect} />)
  const row = screen.getByRole('button', { name: /Coder/ })
  expect(row).toHaveTextContent('Fix the greeting in hello.py')
  expect(row).not.toHaveTextContent('Then run the tests.')
  expect(row).toHaveTextContent('working')
  // (said by the one label a state has everywhere: its word, in its colour)
  expect(within(row).getByText('working')).toHaveClass('status')
  expect(within(row).getByText('working').style.color).toBe('var(--accent)')
  await userEvent.click(row)
  expect(onSelect).toHaveBeenCalledWith('kid')
})

test('a spawn row says how the sub-agent ended', () => {
  const { rerender } = render(<SpawnRow agent={{ ...coder, status: 'completed' }} onSelect={() => {}} />)
  expect(screen.getByRole('button')).toHaveTextContent('done')
  rerender(<SpawnRow agent={{ ...coder, status: 'rejected' }} onSelect={() => {}} />)
  expect(screen.getByRole('button')).toHaveTextContent('rejected')
})

test('the spawn card shows role, whole task, tools and depth, and reports the decision', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<SpawnApproval agent={coder} onDecide={onDecide} />)
  expect(screen.getByText('Open this sub-agent?')).toBeInTheDocument()
  expect(screen.getByText('Coder')).toBeInTheDocument()
  expect(screen.getByText(/Then run the tests\./)).toBeInTheDocument()
  for (const tool of ['read_file', 'edit_file', 'run_command']) {
    expect(screen.getByText(tool)).toBeInTheDocument()
  }
  expect(screen.getByText('depth 1')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open agent' }))
  expect(onDecide).toHaveBeenCalledWith('approve')
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide).toHaveBeenLastCalledWith('reject')
})

test('the spawn card says where the sub-agent would run, and who picked that', () => {
  const { rerender } = render(
    <SpawnApproval
      agent={{ ...coder, provider_name: 'Fast', model_id: 'deep', chosen: true }}
      openedBy="Lead"
      onDecide={async () => {}}
    />,
  )
  expect(screen.getByText('Fast · deep')).toBeInTheDocument()
  expect(screen.getByText('chosen by Orchestrator')).toBeInTheDocument()
  expect(screen.getByText(/not its role's own model/)).toBeInTheDocument()
  // its role's own model: said, but nobody chose it
  rerender(
    <SpawnApproval
      agent={{ ...coder, provider_name: 'Local', model_id: null, chosen: false }}
      openedBy="Lead"
      onDecide={async () => {}}
    />,
  )
  expect(screen.getByText('Local')).toBeInTheDocument()
  expect(screen.queryByText(/chosen by/)).not.toBeInTheDocument()
})

test('the card of an agent that goes on from an earlier turn says when it stays where it ran before, and not where its role would run now', () => {
  const going = { ...coder, provider_name: 'Local', model_id: 'qwen' }
  const { rerender } = render(<SpawnApproval agent={going} continuesTurn="10:01" stays={{ on: 'Local · qwen', role: 'Fast · deep' }} onDecide={async () => {}} />)
  expect(screen.getByText('continues Coder from the 10:01 message')).toBeInTheDocument()
  expect(screen.getByText('It stays on Local · qwen, where it ran before. Its role would now run on Fast · deep.')).toBeInTheDocument()
  // what its role would get is not known: only the first sentence
  rerender(<SpawnApproval agent={going} continuesTurn="10:01" stays={{ on: 'Local · qwen', role: null }} onDecide={async () => {}} />)
  expect(screen.getByText('It stays on Local · qwen, where it ran before.')).toBeInTheDocument()
  expect(screen.queryByText(/Its role would now run/)).not.toBeInTheDocument()
  // the same place, or an agent that started clean: nothing is said
  rerender(<SpawnApproval agent={going} continuesTurn="10:01" stays={null} onDecide={async () => {}} />)
  expect(screen.queryByText(/It stays on/)).not.toBeInTheDocument()
  rerender(<SpawnApproval agent={going} onDecide={async () => {}} />)
  expect(screen.queryByText(/It stays on/)).not.toBeInTheDocument()
})

test('the spawn card locks while deciding and shows why a decision failed', async () => {
  let fail: (err: unknown) => void = () => {}
  const onDecide = vi.fn(() => new Promise<void>((_, reject) => (fail = reject)))
  render(<SpawnApproval agent={coder} onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('button', { name: 'Open agent' }))
  expect(screen.getByRole('button', { name: 'Open agent' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
  fail(new ApiError(409, 'this agent is no longer waiting for a decision'))
  expect(await screen.findByRole('alert')).toHaveTextContent('no longer waiting')
  expect(screen.getByRole('button', { name: 'Open agent' })).toBeEnabled()
})

const documenter: PendingRole = {
  tool_call_id: 't1',
  run_id: 'r',
  agent_id: 'r',
  name: 'Documenter',
  description: 'Writes the docs.',
  instructions: 'Keep it short.',
  tools: ['read_file', 'write_file'],
}

test('the role card shows what would be created and reports the decision', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<RoleApproval role={documenter} onDecide={onDecide} />)
  expect(screen.getByText('Create this role?')).toBeInTheDocument()
  expect(screen.getByText('Documenter')).toBeInTheDocument()
  expect(screen.getByText('Writes the docs.')).toBeInTheDocument()
  expect(screen.getByText('Keep it short.')).toBeInTheDocument()
  expect(screen.getByText('write_file')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Create role' }))
  expect(onDecide).toHaveBeenCalledWith('approve')
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide).toHaveBeenLastCalledWith('reject')
})

test('B-363: a spawn row shows the task’s own words, not the folder line it opens with, nor KOLONİ’s opening', () => {
  const brief = 'Project folder: ./ (git repo, branch main; do not switch)\n\nWrite docs/setup.md for new users.'
  const { rerender } = render(<SpawnRow agent={{ ...coder, task: brief }} onSelect={() => {}} />)
  expect(screen.getByRole('button')).toHaveTextContent('Write docs/setup.md for new users.')
  expect(screen.getByRole('button')).not.toHaveTextContent('Project folder')
  rerender(<SpawnRow agent={{ ...coder, task: 'Project folder: ./ (git repo). Write docs/setup.md.' }} onSelect={() => {}} />)
  expect(screen.getByRole('button')).toHaveTextContent('Write docs/setup.md.')
  expect(screen.getByRole('button')).not.toHaveTextContent('Project folder')
  rerender(<SpawnRow agent={{ ...coder, task: 'KOLONİ opened you at the same time as Docs lead, beside your team’s, for …' }} onSelect={() => {}} />)
  expect(screen.getByRole('button')).not.toHaveTextContent('KOLONİ opened you')
  expect(screen.getByRole('button')).toHaveTextContent(/^Coder/)
})
