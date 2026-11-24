import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { expect, test } from 'vitest'
import type { BacklogTask, Story } from '../api/types'
import { useApp } from '../state/store'
import { convState } from '../test-fixtures'
import { ChatStoryStrip, StoryStrip } from './StoryStrip'
import { stripOf } from './strip'

const task = (over: Partial<BacklogTask>): BacklogTask => ({
  id: over.title ?? 't',
  title: 't',
  detail: null,
  criteria: null,
  priority: 'normal',
  status: 'todo',
  position: 0,
  conversation_id: null,
  created_by: 'user',
  pending: null,
  assessment: null,
  not_in: false,
  after: [],
  stuck: null,
  waiting: false,
  kind: 'task',
  created_at: '2026-11-24T10:00:00Z',
  ...over,
})

const CHAT = { ...convState().conversation, id: 'c1' }

const note = (text: string) => ({ kind: 'decision', text, by: 'Orchestrator', at: '2026-11-24T10:00:00Z' })

const STORY: Story = {
  id: 's1',
  goal_id: null,
  title: 'İki adımlı giriş',
  position: 0,
  state: 'running',
  notes: [note('TOTP, not SMS')],
  created_by: 'user',
  closed_at: null,
}

/** A story of two tasks in chat c1 - the first at work, the second waiting there - and a task of no story. */
const BACKLOG = [
  task({ id: 'a', title: 'Kodu üret ve doğrula', story_id: 's1', status: 'doing', conversation_id: 'c1' }),
  task({ id: 'b', title: 'Ayarlarda aç / kapat', story_id: 's1', position: 1, conversation_id: 'c1', place: 1 }),
  task({ id: 'p', title: 'proposed', story_id: 's1', status: 'proposed', position: 2 }),
  task({ id: 'l', title: 'lone', status: 'doing', conversation_id: 'c2' }),
]

test('the strip says the story, the place of its task at work, the next one and its notes, on one line', async () => {
  const strip = stripOf(BACKLOG, [STORY], 'c1')
  expect(strip).toEqual({ story: STORY, at: 1, of: 2, next: BACKLOG[1] })
  render(<StoryStrip strip={strip!} />)
  const region = screen.getByRole('region', { name: 'Story' })
  expect(region).toHaveTextContent('Story · İki adımlı giriş · 1 / 2 · next: Ayarlarda aç / kapat · 📓 notes')
  // narrow, only its title and place: the rest is what the container rule hides
  expect(within(region).getByText(/next:/)).toHaveClass('story-strip-wide')
  const notes = within(region).getByRole('button', { name: 'notes' })
  expect(notes.closest('.story-strip-wide')).not.toBeNull()
  // closed until 📓 is pressed: then the notebook
  expect(notes).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(notes)
  expect(screen.getByRole('dialog', { name: 'Notebook of İki adımlı giriş' })).toHaveTextContent('TOTP, not SMS')
})

test('between its tasks the first waiting is the one shown; no next or notes part where there is none', () => {
  const between = BACKLOG.map(one => (one.id === 'a' ? { ...one, status: 'review' as const } : one))
  const strip = stripOf(between, [{ ...STORY, notes: [] }], 'c1')!
  expect([strip.at, strip.of, strip.next]).toEqual([2, 2, null])
  render(<StoryStrip strip={strip} />)
  expect(screen.getByRole('region', { name: 'Story' })).toHaveTextContent(/^Story · İki adımlı giriş · 2 \/ 2$/)
  expect(screen.queryByRole('button')).toBeNull()
})

test('no strip where no story works in the chat: a task of no story, another chat, a closed story, none read yet', () => {
  expect(stripOf(BACKLOG, [STORY], 'c2')).toBeNull()
  expect(stripOf(BACKLOG, [STORY], 'c3')).toBeNull()
  expect(stripOf(BACKLOG, [{ ...STORY, state: 'done' }], 'c1')).toBeNull()
  useApp.setState({ backlog: null, stories: null })
  const { container } = render(<ChatStoryStrip conv={convState({ conversation: CHAT })} tab="Chat" />)
  expect(container).toBeEmptyDOMElement()
})

test('the chat shows it from the To-do list as read, over its messages only', () => {
  useApp.setState({ backlog: BACKLOG, stories: [STORY] })
  const { rerender } = render(<ChatStoryStrip conv={convState({ conversation: CHAT })} tab="Chat" />)
  expect(screen.getByRole('region', { name: 'Story' })).toHaveTextContent('1 / 2')
  rerender(<ChatStoryStrip conv={convState({ conversation: CHAT })} tab="Talk" />)
  expect(screen.queryByRole('region', { name: 'Story' })).toBeNull()
  rerender(<ChatStoryStrip conv={null} tab="Chat" />)
  expect(screen.queryByRole('region', { name: 'Story' })).toBeNull()
})

test('a narrow chat keeps only its title and place: the container rule', () => {
  const css = readFileSync('src/theme/base.css', 'utf8')
  expect(css).toMatch(/\.story-strip \{\s*container: story-strip \/ inline-size;/)
  expect(css).toMatch(/@container story-strip \(max-width: 360px\) \{\s*\.story-strip-wide \{\s*display: none;/)
})
