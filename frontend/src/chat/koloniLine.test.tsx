import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Message } from '../api/types'
import { useApp } from '../state/store'
import { KoloniLine } from './KoloniLine'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useApp.setState(useApp.getInitialState(), true)
})

const line = (content: string) => ({ id: 'm1', role: 'koloni', content }) as Message

test('suggest_preference at Add them, tell me: the chat says what was added, and Undo takes it out', async () => {
  const asked = vi.fn(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', asked)
  const loadMemory = vi.fn().mockResolvedValue(undefined)
  useApp.setState({ loadMemory })
  const { rerender } = render(<KoloniLine message={line('Added to your preferences: "Never push without asking."')} />)
  expect(screen.getByRole('note')).toHaveTextContent('Added to your preferences: "Never push without asking." · Undo')
  await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
  await waitFor(() =>
    expect(asked).toHaveBeenCalledWith('/api/preference-lines/m1/undo', expect.objectContaining({ method: 'POST' })),
  )
  expect(loadMemory).toHaveBeenCalled()
  rerender(<KoloniLine message={line('Added to your preferences: "Never push without asking." · undone')} />)
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  rerender(<KoloniLine message={line('Coder was named but never opened.')} />)
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
})
