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

test('suggest_preference: a card in its chat - Add puts the line in Your preferences, Not now leaves them', async () => {
  const conv = convState()
  const own = memoryRecord('p1', {
    tier: 'preference',
    status: 'proposed',
    origin: 'agent',
    conversation_id: conv.conversation.id,
    text: 'Write commit messages in Turkish',
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
  const card = screen.getByRole('region', { name: 'Your preferences' })
  expect(card).toHaveTextContent('Add this to your preferences: Write commit messages in Turkish?')
  expect(screen.queryByText(/Not this chat|The summariser’s/)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(addPreference).toHaveBeenCalledWith('p1')
  await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
  expect(rejectMemory).toHaveBeenCalledWith('p1')
  rerender(<PreferenceAsk conv={conv} open={false} />)
  expect(screen.queryByRole('region', { name: 'Your preferences' })).toBeNull()
})
