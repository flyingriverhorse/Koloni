// Kept copies have no cap and KOLONİ deletes none unasked: Settings › The app › Your data says how many there are and
// what they take, warns above KEPT_WARN_MB, and offers each one's Discard - its card's own, asked first.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Storage } from '../api/types'
import { when } from '../canvas/turns'
import { KEPT_WARN_MB, KeptCopies } from './KeptCopies'

afterEach(() => vi.restoreAllMocks())

const sizes = { db_mb: 1, backups_mb: 0, copies_mb: 30, logs_mb: 0 }
const kept = (n: number, mb: number | null): Storage => ({
  ...sizes,
  kept: Array.from({ length: n }, (_, i) => ({
    merge_id: `m${i}`,
    conversation_id: 'c1',
    title: 'Fix the login',
    agent: `Coder ${i + 1}`,
    kept_at: `2026-11-2${i}T10:00:00Z`,
  })),
  kept_mb: mb,
})

test('none kept: nothing is said', () => {
  const { container } = render(<KeptCopies storage={kept(0, 0)} onChanged={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
})

test('how many are kept and what they take; a warning only above the line', () => {
  const { rerender } = render(<KeptCopies storage={kept(2, 12.5)} onChanged={vi.fn()} />)
  const region = screen.getByRole('region', { name: 'Kept copies' })
  expect(region).toHaveTextContent('2 copies are kept for your word (12.5 MB)')
  // Two of one chat told apart: by the agent, and when each was kept.
  const [first, second] = screen.getAllByRole('listitem')
  expect(first).toHaveTextContent(`Fix the login - Coder 1, kept ${when('2026-11-20T10:00:00Z')}`)
  expect(second).toHaveTextContent(`Fix the login - Coder 2, kept ${when('2026-11-21T10:00:00Z')}`)
  expect(screen.queryByRole('alert')).toBeNull()
  rerender(<KeptCopies storage={kept(1, KEPT_WARN_MB + 1)} onChanged={vi.fn()} />)
  expect(region).toHaveTextContent('1 copy is kept for your word')
  expect(screen.getByRole('alert')).toHaveTextContent('Kept copies take over 1 GB')
  rerender(<KeptCopies storage={kept(1, null)} onChanged={vi.fn()} />)
  expect(region).toHaveTextContent('(size not counted)')
})

test('Discard asks first, then discards that copy as its card does and counts again; Keep it does nothing', async () => {
  const discarded = vi.spyOn(api, 'post').mockResolvedValue({})
  const onChanged = vi.fn()
  render(<KeptCopies storage={kept(2, 3)} onChanged={onChanged} />)
  const discards = screen.getAllByRole('button', { name: 'Discard' })
  await userEvent.click(discards[1])
  expect(screen.getByRole('alertdialog')).toHaveTextContent("Delete Coder 2's copy kept from “Fix the login”?")
  await userEvent.click(screen.getByRole('button', { name: 'Keep it' }))
  expect(discarded).not.toHaveBeenCalled()
  await userEvent.click(discards[1])
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard' }))
  await waitFor(() => expect(onChanged).toHaveBeenCalled())
  expect(discarded).toHaveBeenCalledWith('/merges/m1/reject')
})

test('a Discard that fails says why', async () => {
  vi.spyOn(api, 'post').mockRejectedValue(new Error('nothing of these changes can be decided like this'))
  render(<KeptCopies storage={kept(1, 3)} onChanged={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Discard' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('nothing of these changes can be decided')
})
