import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Board, Limits, Provider } from '../api/types'
import { Toasts } from '../shell/Toasts'
import type { Near } from './limitsText'
import { PlanUse } from './PlanUse'

const provider = (id: string, name: string, kind: Provider['kind']) => ({ id, name, kind }) as Provider
const reading = (windows: Limits['windows'], read_at = new Date().toISOString()): Limits => ({ unknown: null, read_at, source: null, plan: null, windows, credits: null })
const claude = reading(
  [
    { name: 'five_hour', minutes: 300, used_percent: 42.4, resets_at: null, stale: false },
    { name: 'seven_day', minutes: 10080, used_percent: 93, resets_at: null, stale: false },
  ],
  new Date(Date.now() - 4 * 3600000).toISOString(),
)
const codex = reading([{ name: null, minutes: 300, used_percent: 8, resets_at: null, stale: false }])
const providers = [provider('l', 'Local', 'openai_compat'), provider('k', 'Claude Code', 'claude_cli'), provider('c', 'Codex', 'codex_cli')]

test('each plan with a reading shows its fuller window used, in one button that opens Usage', async () => {
  const told: Record<string, Limits> = { k: claude, c: codex }
  const onLimits = vi.fn((id: string) => Promise.resolve(told[id]))
  const onOpen = vi.fn()
  render(<PlanUse providers={providers} onLimits={onLimits} every={60000} onOpen={onOpen} />)
  const button = await screen.findByRole('button', { name: 'Plan use: Claude Code 93% of the week, Codex 8% of 5 hours; open Usage' })
  expect(button).toHaveTextContent('Claude Code93%Codex8%')
  // How old the reading is goes in the title, as the Models card says it.
  expect(button).toHaveAttribute('title', 'Claude Code: 93% of the week used, read 4 h ago\nCodex: 8% of 5 hours used, read just now')
  // Only the CLIs are asked; an API key has no plan to read.
  expect(onLimits.mock.calls.map(([id]) => id).sort()).toEqual(['c', 'k'])
  await userEvent.click(button)
  expect(onOpen).toHaveBeenCalledOnce()
})

test('a plan with no reading, a stale window or a failed read shows nothing - never a made-up 0%', async () => {
  const told: Record<string, Limits> = {
    k: { ...reading([]), unknown: 'not run yet' },
    c: reading([{ name: null, minutes: 300, used_percent: null, resets_at: null, stale: true }]),
  }
  const onLimits = vi.fn((id: string) => (id in told ? Promise.resolve(told[id]) : Promise.reject(new Error('no'))))
  const { container } = render(
    <PlanUse providers={[...providers, provider('a', 'agy', 'agy_cli')]} onLimits={onLimits} every={60000} onOpen={() => {}} />,
  )
  expect(onLimits).toHaveBeenCalledTimes(3)
  // Every answer has come and been drawn.
  await act(() => new Promise(done => setTimeout(done, 0)))
  expect(container).toBeEmptyDOMElement()
})

test('a week fuller than its 5 hours is what the bar shows (B-48: "Codex 0%" while 84% of the week was left)', async () => {
  const both = reading([
    { name: null, minutes: 300, used_percent: 0, resets_at: null, stale: false },
    { name: null, minutes: 10080, used_percent: 16, resets_at: null, stale: false },
  ])
  render(<PlanUse providers={[provider('c', 'Codex', 'codex_cli')]} onLimits={() => Promise.resolve(both)} every={60000} onOpen={() => {}} />)
  expect(await screen.findByRole('button', { name: 'Plan use: Codex 16% of the week; open Usage' })).toHaveTextContent('Codex16%')
})

test('another plan with no 5 hours shows the window it has, named in the label', async () => {
  const week = reading([{ name: 'weekly', minutes: 10080, used_percent: 61, resets_at: null, stale: false }])
  render(<PlanUse providers={[provider('a', 'agy', 'agy_cli')]} onLimits={() => Promise.resolve(week)} every={60000} onOpen={() => {}} />)
  expect(await screen.findByRole('button', { name: 'Plan use: agy 61% of the week; open Usage' })).toHaveTextContent('agy61%')
})

test('a plan from 80% used on is marked to be shown in the warning colour; one under it is not', async () => {
  const told: Record<string, Limits> = {
    k: reading([{ name: null, minutes: 300, used_percent: 79.4, resets_at: null, stale: false }]),
    c: reading([{ name: null, minutes: 300, used_percent: 80, resets_at: null, stale: false }]),
  }
  render(<PlanUse providers={providers} onLimits={id => Promise.resolve(told[id])} every={60000} onOpen={() => {}} />)
  const button = await screen.findByRole('button', { name: /^Plan use: Claude Code 79%.*Codex 80%/ })
  expect(Array.from(button.querySelectorAll('.plan-use-hot'), meter => meter.textContent)).toEqual(['Codex80%'])
})

test('a window at 90% or more is told as near its limit; a stale one, or one of no known share, never is', async () => {
  const told: Record<string, Limits> = {
    k: reading([
      { name: 'five_hour', minutes: 300, used_percent: 91.4, resets_at: '2026-10-25T18:10:00Z', stale: false },
      { name: 'seven_day', minutes: 10080, used_percent: 95, resets_at: null, stale: true },
    ]),
    c: reading([{ name: null, minutes: 300, used_percent: null, resets_at: null, stale: false }]),
  }
  const onNear = vi.fn()
  render(<PlanUse providers={providers} onLimits={id => Promise.resolve(told[id])} every={60000} onOpen={() => {}} onNear={onNear} />)
  await screen.findByRole('button', { name: /^Plan use: Claude Code 91%/ })
  expect(onNear).toHaveBeenLastCalledWith([{ key: 'k five_hour', resets_at: '2026-10-25T18:10:00Z', text: expect.stringMatching(/^Claude Code is near its limit: 91% of 5 hours used, resets /) }])
})

test('near its limit is said in a toast once for each time its window resets, and Open goes to Usage', async () => {
  const board: Board = { backlog_waiting: 0, limit: null, running: 0, conversations: [], conflicts: [] }
  const onUsage = vi.fn()
  const near = (resets_at: string | null): Near[] => [{ key: 'k five_hour', resets_at, text: `Claude Code is near its limit (${resets_at})` }]
  const toasts = (shown: Near[]) => <Toasts board={board} near={shown} shownId={null} onOpen={vi.fn()} onUsage={onUsage} />
  const { rerender, container } = render(toasts([]))
  rerender(toasts(near('2026-10-25T18:10:00Z')))
  expect(container.querySelectorAll('.toast')).toHaveLength(1)
  await userEvent.click(screen.getByRole('button', { name: 'Open' }))
  expect(onUsage).toHaveBeenCalled()
  // read again, the same window - or its reset said a few minutes apart - is not said again
  rerender(toasts(near('2026-10-25T18:10:00Z')))
  rerender(toasts(near('2026-10-25T18:14:00Z')))
  expect(container.querySelectorAll('.toast')).toHaveLength(0)
  // the next window, near again, is
  rerender(toasts(near('2026-10-25T23:10:00Z')))
  expect(container.querySelector('.toast')).toHaveTextContent('Claude Code is near its limit (2026-10-25T23:10:00Z)')
})

test('K-claude-hesap: two Claude Code accounts side by side each say their own name, the whole of it in its title', async () => {
  const long = 'Claude Code - the work account of the team'
  render(
    <PlanUse
      providers={[provider('a', long, 'claude_cli'), provider('b', 'Home', 'claude_cli')]}
      onLimits={() => Promise.resolve(codex)}
      every={60000}
      onOpen={() => {}}
    />,
  )
  const button = await screen.findByRole('button', { name: `Plan use: ${long} 8% of 5 hours, Home 8% of 5 hours; open Usage` })
  expect(button).toHaveTextContent(`${long}8%Home8%`)
  expect(screen.getByText(long)).toHaveAttribute('title', long)
  expect(screen.getByText(long)).toHaveClass('plan-use-name') // (cut with an ellipsis by the theme where long)
})
