import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { ProjectMemory } from '../api/types'
import { useApp } from '../state/store'
import { convState, memoryRecord } from '../test-fixtures'
import { PreferenceAsk } from './PreferenceAsk'

afterEach(() => {
  cleanup()
  useApp.setState(useApp.getInitialState(), true)
})

test('suggest_preference at Ask me first: a card in its chat with your words - Add puts the line in, Not now leaves them', async () => {
  const conv = convState()
  const own = memoryRecord('p1', {
    tier: 'preference',
    status: 'proposed',
    origin: 'agent',
    conversation_id: conv.conversation.id,
    text: 'Write commit messages in Turkish',
    noted_by: { provider_name: 'Local', model_id: 'q', quote: 'write commits in Turkish' },
  })
  const elsewhere = { ...own, id: 'p2', conversation_id: 'other', text: 'Not this chat' }
  const summarisers = { ...own, id: 'p3', origin: 'auto' as const, text: 'The summariser’s' }
  const addPreference = vi.fn().mockResolvedValue(undefined)
  const rejectMemory = vi.fn().mockResolvedValue(undefined)
  useApp.setState({
    memory: { suggestions: [own, elsewhere, summarisers] } as unknown as ProjectMemory,
    addPreference,
    rejectMemory,
  })
  const { rerender } = render(<PreferenceAsk conv={conv} open />)
  const card = screen.getByRole('region', { name: 'Suggested by the Orchestrator' })
  expect(card).toHaveTextContent('The Orchestrator suggests, from your words write commits in Turkish:')
  expect(card).toHaveTextContent('Add this to your preferences: Write commit messages in Turkish?')
  expect(screen.queryByText(/Not this chat|The summariser’s/)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(addPreference).toHaveBeenCalledWith('p1')
  await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
  expect(rejectMemory).toHaveBeenCalledWith('p1')
  rerender(<PreferenceAsk conv={conv} open={false} />)
  expect(screen.queryByRole('region', { name: 'Suggested by the Orchestrator' })).toBeNull()
})
