import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import type { Hold } from '../api/types'
import { HoldStatus } from './HoldStatus'

afterEach(() => vi.unstubAllGlobals())

const calm: Hold = { held: false, since: null, running: 3, triggers: 2, backlogs: ['shop'], nights: ['shop'], stopped: [], stopping: 0 }
const held: Hold = {
  ...calm,
  held: true,
  since: '2026-10-27T09:30:00Z',
  running: 0,
  stopped: [
    { run_id: 'r1', conversation_id: 'c1', title: 'Fix the tests', project: 'shop', created_at: '2026-10-27T09:20:00Z' },
    { run_id: 'r2', conversation_id: 'c1', title: 'Fix the tests', project: 'shop', created_at: '2026-10-27T09:10:00Z' },
    { run_id: 'r3', conversation_id: 'c2', title: 'Nightly look', project: 'shop', created_at: '2026-10-27T09:00:00Z' },
  ],
  stays_stopped: '3 stopped turns stay stopped - send a message to go on.',
}

/** GET answers `reading`; each POST answers the next of `posted`, and from then on GET answers it too. */
function serve(reading: Hold, posted: Hold[]) {
  let now = reading
  const asked = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') now = posted.shift()!
    return new Response(JSON.stringify(now), { status: 200 })
  })
  vi.stubGlobal('fetch', asked)
  return asked
}

test('Stop everything asks first, saying what runs and what will be held - and Cancel stops nothing', async () => {
  const asked = serve(calm, [])
  render(<HoldStatus every={60_000} onOpen={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Stop everything' }))
  const ask = screen.getByRole('dialog', { name: 'Stop everything' })
  expect(ask).toHaveTextContent('3 turns running in your chats will stop. 2 triggers, 1 backlog and 1 project working while you’re away are held until you resume.')
  expect(ask).toHaveTextContent('Your own messages still run')
  await userEvent.click(within(ask).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(asked.mock.calls.every(([, init]) => init?.method !== 'POST')).toBe(true)
})

test('once confirmed it lists what stopped and what is held; the bar says Held, and Resume lets it go', async () => {
  const asked = serve(calm, [held, calm])
  const onOpen = vi.fn()
  render(<HoldStatus every={60_000} onOpen={onOpen} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Stop everything' }))
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Stop everything' }))
  const list = await screen.findByRole('dialog', { name: 'Everything is held' })
  expect(asked.mock.calls.find(([, init]) => init?.method === 'POST')?.[0]).toBe('/api/hold')
  const stopped = within(list).getByRole('region', { name: 'Stopped' })
  expect(within(stopped).getAllByRole('listitem').map(li => li.textContent)).toEqual([
    'Fix the tests · 2 turns',
    'Nightly look',
  ])
  expect(within(list).getByRole('region', { name: 'Held' })).toHaveTextContent('2 triggers on')
  expect(list).toHaveTextContent('times missed while held are skipped, also for triggers that catch up, and files changed meanwhile start nothing')
  expect(within(list).getByRole('region', { name: 'Held' })).toHaveTextContent('Backlog of shop: its next task waits')
  expect(within(list).getByRole('region', { name: 'Held' })).toHaveTextContent('While you’re away · shop: its next job waits')
  expect(list).toHaveTextContent('Your own messages still run')
  // R147: Resume does not start again what it stopped
  expect(list).toHaveTextContent('Resume: 3 stopped turns stay stopped - send a message to go on.')
  expect(screen.getByRole('button', { name: 'Held · Resume' })).toBeInTheDocument()

  await userEvent.click(within(list).getByRole('button', { name: 'Resume' }))
  expect(await screen.findByRole('button', { name: 'Stop everything' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(asked.mock.calls.filter(([, init]) => init?.method === 'POST').map(([url]) => url)).toEqual(['/api/hold', '/api/hold/resume'])
})

test('held from before (a restart, another tab), the bar says so and a stopped chat opens from the list', async () => {
  serve(held, [])
  const onOpen = vi.fn()
  render(<HoldStatus every={60_000} onOpen={onOpen} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Held · Resume' }))
  await userEvent.click(within(screen.getByRole('dialog', { name: 'Everything is held' })).getByRole('button', { name: 'Nightly look' }))
  expect(onOpen).toHaveBeenCalledWith('c2')
})

test('chats of one title are told apart in the list: by project where those differ, else by when the turn was sent (B-175)', async () => {
  const at = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const stopped = (...rows: [string, string, string | null, string][]) =>
    rows.map(([run_id, conversation_id, project, created_at]) => ({ run_id, conversation_id, title: 'New conversation', project, created_at }))
  const both = { ...held, stopped: [...stopped(['r1', 'c1', 'shop', '2026-10-27T09:20:00Z'], ['r2', 'c3', 'blog', '2026-10-27T09:10:00Z']), held.stopped[2]] }
  serve(both, [])
  const { unmount } = render(<HoldStatus every={60_000} onOpen={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Held · Resume' }))
  const list = within(screen.getByRole('dialog')).getByRole('region', { name: 'Stopped' })
  expect(within(list).getAllByRole('listitem').map(li => li.textContent)).toEqual(['New conversation · shop', 'New conversation · blog', 'Nightly look'])
  unmount()

  serve({ ...held, stopped: stopped(['r1', 'c1', 'shop', '2026-10-27T09:20:00Z'], ['r2', 'c2', 'shop', '2026-10-27T09:10:00Z']) }, [])
  render(<HoldStatus every={60_000} onOpen={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Held · Resume' }))
  const same = within(screen.getByRole('dialog')).getByRole('region', { name: 'Stopped' })
  expect(within(same).getAllByRole('listitem').map(li => li.textContent)).toEqual([
    `New conversation · ${at('2026-10-27T09:20:00Z')}`,
    `New conversation · ${at('2026-10-27T09:10:00Z')}`,
  ])
  cleanup()

  // B-180: sent in one minute - to the second
  const second = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  serve({ ...held, stopped: stopped(['r1', 'c1', 'shop', '2026-10-27T09:20:40Z'], ['r2', 'c2', 'shop', '2026-10-27T09:20:05Z']) }, [])
  render(<HoldStatus every={60_000} onOpen={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Held · Resume' }))
  const minute = within(screen.getByRole('dialog')).getByRole('region', { name: 'Stopped' })
  expect(within(minute).getAllByRole('listitem').map(li => li.textContent)).toEqual([
    `New conversation · ${second('2026-10-27T09:20:40Z')}`,
    `New conversation · ${second('2026-10-27T09:20:05Z')}`,
  ])
})

test('it tells the bar whether it holds, and once resumed that it does not', async () => {
  serve(held, [calm])
  const onHeld = vi.fn()
  render(<HoldStatus every={60_000} onOpen={() => {}} onHeld={onHeld} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Held · Resume' }))
  expect(onHeld).toHaveBeenLastCalledWith(true)
  await userEvent.click(within(screen.getByRole('dialog', { name: 'Everything is held' })).getByRole('button', { name: 'Resume' }))
  await screen.findByRole('button', { name: 'Stop everything' })
  expect(onHeld).toHaveBeenLastCalledWith(false)
})

test('a turn slow to stop is said to be stopping, not left out; the button says Stopping… while it asks', async () => {
  let answer: (said: Response) => void = () => {}
  const asked = vi.fn(async (_url: string, init?: RequestInit) =>
    init?.method === 'POST' ? new Promise<Response>(done => (answer = done)) : new Response(JSON.stringify(calm), { status: 200 }),
  )
  vi.stubGlobal('fetch', asked)
  render(<HoldStatus every={60_000} onOpen={() => {}} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Stop everything' }))
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Stop everything' }))
  expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'Stopping…' })).toBeDisabled()
  answer(new Response(JSON.stringify({ ...calm, held: true, since: '2026-10-27T09:30:00Z', stopping: 2 }), { status: 200 }))
  const stopped = within(await screen.findByRole('dialog', { name: 'Everything is held' })).getByRole('region', { name: 'Stopped' })
  expect(stopped).toHaveTextContent('2 turns still stopping…')
  expect(stopped).not.toHaveTextContent('Nothing was running.')
})

test('an answer that is not the hold as the server gives it is taken for not held: nothing is shown, nothing breaks', async () => {
  const asked = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 }))
  vi.stubGlobal('fetch', asked)
  render(
    <div data-testid="bar">
      <HoldStatus every={60_000} onOpen={() => {}} />
      <span>the rest of the bar</span>
    </div>,
  )
  await waitFor(() => expect(asked).toHaveBeenCalled())
  await act(async () => {})
  // (A throw here would take the whole tree down with it, the rest of the bar too.)
  expect(screen.getByTestId('bar')).toHaveTextContent(/^the rest of the bar$/)
  expect(screen.queryByRole('button')).toBeNull()
})
