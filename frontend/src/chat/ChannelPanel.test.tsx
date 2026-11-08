import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { agent, convState } from '../test-fixtures'
import { ChannelPanel } from './ChannelPanel'

test('an empty channel says what it is for', () => {
  render(<ChannelPanel state={convState()} />)
  expect(screen.getByText('What agents say to each other shows here.')).toBeInTheDocument()
})

test('hand-offs are listed in order with who wrote to whom', () => {
  const state = convState({
    agents: [
      agent('r', 'completed', { id: 'lead' }),
      agent('r', 'completed', { id: 'kid', parent_agent_id: 'lead', role_name: 'Reviewer', depth: 1 }),
    ],
    channelMessages: [
      { id: '1', run_id: 'r', from_agent_id: 'lead', to_agent_id: 'kid', kind: 'task', content: 'Review hello.py', created_at: '2026-10-05T10:00:00Z' },
      { id: '2', run_id: 'r', from_agent_id: 'kid', to_agent_id: 'lead', kind: 'report', content: 'Looks fine.', created_at: '2026-10-05T10:00:05Z' },
    ],
  })
  const { container } = render(<ChannelPanel state={state} />)
  expect(screen.getByText('Orchestrator → Reviewer · task')).toBeInTheDocument()
  expect(screen.getByText('Reviewer → Orchestrator · report')).toBeInTheDocument()
  const text = container.textContent ?? ''
  expect(text.indexOf('Review hello.py')).toBeLessThan(text.indexOf('Looks fine.'))
})
