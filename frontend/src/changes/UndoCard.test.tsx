import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Undo } from '../api/types'
import { UndoCard } from './UndoCard'

afterEach(() => vi.unstubAllGlobals())

const none: Undo = { turns: [], revert: [], skip: [], reject: [], copies: [], commands: [], stays: [], note: null }
const ahead: Undo = {
  ...none,
  turns: [
    { run_id: 'r2', topic: 'Make files', turn: 2, request: 'Make a.txt' },
    { run_id: 'r3', topic: 'Nightly look', turn: 1, request: '' },
    // (The topic's name is its first turn's: each turn says its own request too.)
    { run_id: 'r4', topic: 'Make files', turn: 3, request: 'eight' },
  ],
  revert: ['b.txt'],
  skip: [{ path: 'a.txt', why: 'a.txt has changed since this edit; revert it by hand' }],
  reject: ['c.txt'],
  copies: [{ folder: 'C:/kept/tree', files: ['c.txt'] }],
  commands: ['pip install something'],
  stays: ["KOLONİ's commit abc1234 of what was taken stays in git history"],
}

/** Answers by method, in turn: the last answer of a method is given again. */
function serve(answers: Record<string, (Undo | [number, string])[]>) {
  const asked = vi.fn(async (_url: string, init?: RequestInit) => {
    const list = answers[init?.method ?? 'GET']
    const said = list.length > 1 ? (list.shift() as Undo | [number, string]) : list[0]
    return Array.isArray(said)
      ? new Response(JSON.stringify({ detail: said[1] }), { status: said[0] })
      : new Response(JSON.stringify(said), { status: 200 })
  })
  vi.stubGlobal('fetch', asked)
  return asked
}

test('it looks ahead first - the messages whose changes go, the copy whose folder is deleted, what stays - and restores only when confirmed; the chat stays (slice 107)', async () => {
  const asked = serve({ GET: [ahead], POST: [{ ...ahead, skip: [], note: 'A turn started while this was done: what it does is not taken back.' }] })
  const onClose = vi.fn()
  render(<UndoCard path="/conversations/c1/restore?before=r2" title="Restore to before your 10:42 message" confirm="Restore" onClose={onClose} />)
  const card = screen.getByRole('region', { name: 'Restore to before your 10:42 message' })
  const turns = await within(card).findByRole('region', { name: 'Messages whose changes are taken back' })
  expect(within(turns).getAllByRole('listitem').map(li => li.textContent)).toEqual(['“Make a.txt”', 'A message with no words', '“eight”'])
  // What it does and does not do, first (§6).
  expect(card).toHaveTextContent('The chat stays as it is: no message is deleted.')
  expect(card).toHaveTextContent('What commands did, and notes put in memory, are not taken back.')
  expect(within(card).getByRole('region', { name: 'Will be reverted' })).toHaveTextContent('b.txt')
  expect(within(card).getByRole('region', { name: 'Will be skipped' })).toHaveTextContent('a.txt — a.txt has changed since')
  expect(within(card).getByRole('region', { name: 'Kept working copy to discard — the folder is deleted' })).toHaveTextContent(
    'C:/kept/tree — these files exist only there: c.txt',
  )
  expect(within(card).getByRole('region', { name: /cannot be taken back/ })).toHaveTextContent('pip install something')
  expect(within(card).getByRole('region', { name: 'Also not taken back' })).toHaveTextContent('stays in git history')
  expect(asked).toHaveBeenCalledTimes(1) // the look ahead alone

  await userEvent.click(within(card).getByRole('button', { name: 'Restore' }))
  expect(await within(card).findByRole('region', { name: 'Reverted' })).toHaveTextContent('b.txt')
  expect(asked.mock.calls[1][1]?.method).toBe('POST')
  // only the turns it showed
  expect(String(asked.mock.calls[1][0])).toBe('/api/conversations/c1/restore?before=r2&through=r4')
  expect(within(card).getByRole('note')).toHaveTextContent('A turn started while this was done')
  expect(within(card).queryByRole('button', { name: 'Restore' })).toBeNull()
  expect(within(card).getByRole('button', { name: 'Close' })).toHaveFocus()
  await userEvent.click(within(card).getByRole('button', { name: 'Close' }))
  expect(onClose).toHaveBeenCalled()
})

test('a refused restore says why and looks again', async () => {
  const more = { ...ahead, turns: [...ahead.turns, { run_id: 'r5', topic: 'Nightly look', turn: 2, request: '' }] }
  const asked = serve({ GET: [ahead, more], POST: [[409, 'a turn ended since you looked; look again']] })
  render(<UndoCard path="/conversations/c1/restore?before=r2" title="Restore to before your 10:42 message" confirm="Restore" onClose={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Restore' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('look again')
  await vi.waitFor(() => expect(screen.getAllByText('A message with no words')).toHaveLength(2))
  expect(asked).toHaveBeenCalledTimes(3)
})

test('a long request is cut as the turn list cuts a message; one that never started says so', async () => {
  const turns = [{ run_id: 'r1', topic: 'Talk', turn: 1, request: `${'x'.repeat(60)}yz` }, { run_id: 'r2', topic: 'Talk', turn: null, request: 'later' }]
  serve({ GET: [{ ...none, turns }] })
  render(<UndoCard path="/runs/r1/undo" title="Undo these changes" confirm="Undo" onClose={() => {}} />)
  expect(await screen.findByText(`“${'x'.repeat(60)}…”`)).toBeInTheDocument()
  expect(screen.getByText('“later” (it never started)')).toBeInTheDocument()
})

test('an undo posts to the turn alone, with no turns to check', async () => {
  const asked = serve({ GET: [{ ...none, turns: [{ run_id: 'r1', topic: 'Talk', turn: 1, request: '' }], revert: ['a.txt'] }], POST: [none] })
  render(<UndoCard path="/runs/r1/undo" title="Undo these changes" confirm="Undo" onClose={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Undo' }))
  await screen.findByRole('button', { name: 'Close' })
  expect(String(asked.mock.calls[1][0])).toBe('/api/runs/r1/undo')
})

test('a turn still running says why, and nothing is offered to do', async () => {
  serve({ GET: [[409, 'a turn of these is still running or waiting to: stop it first']] })
  render(<UndoCard path="/runs/r1/undo" title="Undo these changes" confirm="Undo" onClose={() => {}} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('stop it first')
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
})

test('nothing to take back is said, with nothing to confirm; Esc closes', async () => {
  serve({ GET: [{ ...none, turns: [{ run_id: 'r1', topic: 'Talk', turn: 1, request: '' }] }] })
  const onClose = vi.fn()
  render(<UndoCard path="/runs/r1/undo" title="Undo these changes" confirm="Undo" onClose={onClose} />)
  expect(await screen.findByText('Nothing to take back.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  await userEvent.keyboard('{Escape}')
  expect(onClose).toHaveBeenCalledTimes(2)
})

test('files changed that are not on record are never "nothing to take back"', async () => {
  serve({ GET: [{ ...none, stays: ['3 more files changed at the same time; they are not recorded one by one'] }] })
  render(<UndoCard path="/runs/r1/undo" title="Undo these changes" confirm="Undo" onClose={() => {}} />)
  expect(await screen.findByRole('region', { name: 'Also not taken back' })).toHaveTextContent('3 more files')
  expect(screen.queryByText('Nothing to take back.')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
})
