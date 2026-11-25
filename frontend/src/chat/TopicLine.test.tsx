import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Story } from '../api/types'
import { useApp } from '../state/store'
import { convState, run, topic, userMessage } from '../test-fixtures'
import { MessageList } from './MessageList'
import { storyDivider } from './todo'
import { TopicLine } from './TopicLine'

const STORY: Story = {
  id: 's1',
  goal_id: null,
  title: 'İki adımlı giriş',
  position: 0,
  state: 'running',
  notes: [{ kind: 'decision', text: 'TOTP, not SMS', by: 'Orchestrator', at: '2026-11-24T10:00:00Z' }],
  created_by: 'user',
  closed_at: null,
}

test("a story's topic line: its 📓 opens the story's notebook, closed until pressed", async () => {
  render(<TopicLine text={storyDivider(STORY)} story={STORY} />)
  const notes = screen.getByRole('button', { name: 'notes' })
  expect(notes.parentElement).toHaveTextContent('Topic · Story · İki adımlı giriş · 📓 notes')
  expect(notes).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(notes)
  expect(screen.getByRole('dialog', { name: 'Notebook of İki adımlı giriş' })).toHaveTextContent('TOTP, not SMS')
})

test('the words alone for a story with no note yet, and for any other topic', () => {
  const { rerender } = render(<TopicLine text={storyDivider(STORY)} story={{ ...STORY, notes: [] }} />)
  expect(screen.getByText('Topic · Story · İki adımlı giriş · 📓 notes')).toBeVisible()
  expect(screen.queryByRole('button')).toBeNull()
  rerender(<TopicLine text="New topic: Fix the greeting" story={null} />)
  expect(screen.getByText('New topic: Fix the greeting')).toBeVisible()
})

test("the chat's line over a story's topic has the notebook's button", async () => {
  useApp.setState({ stories: [STORY] })
  const state = convState({
    topics: [topic('t1', 'İki adımlı giriş', { story_id: 's1' })],
    runs: [run('r1', 'completed', { topic_id: 't1' })],
    messages: [userMessage('r1', 'Kodu üret ve doğrula')],
  })
  const on = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn() }
  render(<MessageList {...on} state={state} />)
  const line = screen.getByRole('separator')
  expect(line).toHaveTextContent('Topic · Story · İki adımlı giriş · 📓 notes')
  await userEvent.click(within(line).getByRole('button', { name: 'notes' }))
  expect(screen.getByRole('dialog', { name: 'Notebook of İki adımlı giriş' })).toBeVisible()
})
