import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Snapshot } from '../api/types'
import { Earlier } from '../chat/Earlier'
import { assistantMessage, convState, fileChange, run } from '../test-fixtures'
import { TURNS_PAGE, turnsOf, withEarlier } from './earlier'
import { useApp } from './store'

const at = (minute: number) => `2026-11-26T10:${String(minute).padStart(2, '0')}:00Z`
const turn = (n: number) => run(`r${n}`, 'completed', { created_at: at(n) })
const said = (n: number) => assistantMessage(`m${n}`, `r${n}`, `turn ${n}`)

afterEach(() => vi.unstubAllGlobals())

/** An older page as the server sends it: every list of a chat's turns, `over` given. */
const page = (over: object) =>
  ({
    conversation: convState().conversation,
    ...Object.fromEntries(
      ['messages', 'runs', 'tool_calls', 'file_changes', 'commands', 'web_requests', 'agents', 'channel_messages']
        .concat(['questions', 'discussions', 'discussion_posts', 'board_posts', 'merges', 'topics'])
        .map(key => [key, []]),
    ),
    last_event_id: 0,
    ...over,
  }) as unknown as Snapshot

test('an older page goes before the turns shown, each row once, and a turn that waited goes back to its place', () => {
  // The first page: turns 7-9, and turn 2 that still waited (a change asked about).
  const shown = convState({
    runs: [turn(2), turn(7), turn(8), turn(9)],
    messages: [said(2), said(7), said(8), said(9)],
    fileChanges: [fileChange('k', 'r2')],
    older: 7,
    olderFrom: 'r7',
  })
  const older = page({
    runs: [1, 2, 3, 4, 5, 6].map(turn),
    messages: [1, 2, 3, 4, 5, 6].map(said),
    file_changes: [fileChange('k', 'r2')],
    older: 1,
    older_from: 'r1',
  })
  const next = withEarlier(shown, older)
  expect(next.runs.map(r => r.id)).toEqual(['r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'r8', 'r9'])
  expect(next.messages.map(m => m.id)).toEqual(['m1', 'm2', 'm3', 'm4', 'm5', 'm6', 'm7', 'm8', 'm9'])
  expect(next.fileChanges.map(c => c.id)).toEqual(['k'])
  expect([next.older, next.olderFrom]).toEqual([1, 'r1'])
})

test('a row the events changed while the older page was read keeps the copy shown, not the page’s older one', () => {
  // Turn 2 still waited (a change asked about) and came with the first page; it was answered while the page was read.
  const shown = convState({
    runs: [turn(2), turn(7)],
    fileChanges: [fileChange('k', 'r2', { status: 'applied' })],
    older: 5,
    olderFrom: 'r7',
  })
  const older = page({
    runs: [1, 2, 3].map(turn),
    file_changes: [fileChange('k', 'r2', { status: 'proposed' })],
    older: 0,
    older_from: null,
  })
  const next = withEarlier(shown, older)
  expect(next.fileChanges.map(c => [c.id, c.status])).toEqual([['k', 'applied']])
  expect(next.runs.map(r => r.id)).toEqual(['r1', 'r2', 'r3', 'r7'])
})

test('a chat is read with its newest page - again with as many turns as are shown', () => {
  const many = convState({ runs: Array.from({ length: TURNS_PAGE + 5 }, (_, n) => turn(n % 60)) })
  expect(turnsOf(null, false)).toBe(TURNS_PAGE)
  expect(turnsOf(many, false)).toBe(TURNS_PAGE)
  expect(turnsOf(many, true)).toBe(TURNS_PAGE + 5)
  // (never more than the server reads at once: a reconnect asking more would be refused for ever)
  expect(turnsOf(convState({ runs: Array.from({ length: 1200 }, (_, n) => turn(n % 60)) }), true)).toBe(1000)
})

test('a turn asked for by its id, older than the page, is read until it is there', async () => {
  const shown = convState({ runs: [turn(9)], older: 2, olderFrom: 'r9' })
  const pages = [
    page({ runs: [turn(8)], older: 1, older_from: 'r8' }),
    page({ runs: [turn(5)], older: 0, older_from: null }),
  ]
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(pages.shift()), { status: 200 })),
  )
  useApp.setState({ conv: shown })
  await useApp.getState().openTurn(shown.conversation.id, 'r5')
  expect(useApp.getState().conv?.runs.map(r => r.id)).toEqual(['r5', 'r8', 'r9'])
  expect(useApp.getState().turnId).toBe('r5')
})

test('Show earlier turns reads the page before the oldest shown, and is not there once every turn is', async () => {
  const shown = convState({ runs: [turn(7)], messages: [said(7)], older: 3, olderFrom: 'r7' })
  const before = page({ runs: [turn(5), turn(6)], messages: [said(5), said(6)], older: 0, older_from: null })
  const read = vi.fn(async () => new Response(JSON.stringify(before), { status: 200 }))
  vi.stubGlobal('fetch', read)
  useApp.setState({ conv: shown })
  const { rerender } = render(<Earlier conv={shown} />)
  expect(screen.getByText('3 older turns are not shown')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show 3 earlier turns' }))
  await vi.waitFor(() => expect(useApp.getState().conv?.runs.map(r => r.id)).toEqual(['r5', 'r6', 'r7']))
  expect(String((read.mock.calls[0] as unknown[])[0])).toBe(
    `/api/conversations/${shown.conversation.id}?turns=${TURNS_PAGE}&before=r7`,
  )
  rerender(<Earlier conv={useApp.getState().conv!} />)
  expect(screen.queryByRole('button', { name: /earlier/ })).toBeNull()
})
