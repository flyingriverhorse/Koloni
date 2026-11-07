import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Board, Budget, Project } from '../api/types'
import { Composer } from '../chat/Composer'
import { ProjectSettings } from '../shell/ProjectSettings'
import { Toasts } from '../shell/Toasts'
import { resetStoreForTests } from '../state/store'
import { BudgetPill, BudgetSection } from './Budget'

afterEach(() => resetStoreForTests())

const spend = (over: Partial<Budget> = {}): Budget => ({
  budget: 12,
  currency: 'USD',
  spent: 10.5,
  share: 0.875,
  warn: true,
  over: false,
  at_least: false,
  unpriced_runs: 0,
  ...over,
})
const under = spend({ spent: 6, share: 0.5, warn: false })

test('the top bar’s pill shows only near the budget: from 80% on, rounded down, or while it is not enforced; it opens Usage', async () => {
  const onOpen = vi.fn()
  const pill = () => screen.getByRole('button', { name: /^Budget / })
  const { rerender } = render(<BudgetPill budget={under} onOpen={onOpen} />)
  expect(screen.queryByRole('button')).toBeNull()
  rerender(<BudgetPill budget={null} onOpen={onOpen} />)
  expect(screen.queryByRole('button')).toBeNull()
  rerender(<BudgetPill budget={spend()} onOpen={onOpen} />)
  expect(pill()).toHaveAccessibleName('Budget 87%')
  expect(pill()).toHaveTextContent(/^ ?87%$/)
  expect(pill()).toHaveAccessibleDescription('This project has used 87% of its monthly budget. Opens Usage.')
  await userEvent.click(pill())
  expect(onOpen).toHaveBeenCalledTimes(1)
  rerender(<BudgetPill budget={spend({ spent: 11.99, share: 0.9999 })} onOpen={onOpen} />)
  expect(pill()).toHaveAccessibleName('Budget 99%')
  rerender(<BudgetPill budget={spend({ spent: 13, share: 13 / 12, over: true })} onOpen={onOpen} />)
  // Over it, in sight and in its name alike.
  expect(pill()).toHaveTextContent(/^ ?over · 108%$/)
  expect(pill()).toHaveAccessibleName('Budget over · 108%')
  expect(pill()).toHaveAccessibleDescription(/used 108% of its monthly budget: a new message asks before its work starts, and triggers start none/)
  // A part of it is only the least it cost; 0.29 is 29%, though 0.29 * 100 is 28.999…
  rerender(<BudgetPill budget={spend({ spent: 3.48, share: 0.29, warn: true, at_least: true })} onOpen={onOpen} />)
  expect(pill()).toHaveAccessibleDescription(/This project has used at least 29% of its monthly budget/)
  // Costs in two currencies: nothing is added up, and the pill says the budget holds nothing back.
  rerender(<BudgetPill budget={spend({ currency: null, spent: null, share: null, warn: false })} onOpen={onOpen} />)
  expect(pill()).toHaveAccessibleName('Budget not enforced')
  expect(pill()).toHaveAccessibleDescription(/This budget is not enforced: prices are in more than one currency/)
})

test('Usage shows this month’s spend against the budget, a bar and its numbers; unpriced turns said apart', () => {
  const { rerender } = render(<BudgetSection budget={spend({ unpriced_runs: 2 })} />)
  const bar = screen.getByRole('meter', { name: 'Monthly budget used' })
  expect(bar).toHaveAttribute('value', '10.5')
  expect(bar).toHaveAttribute('max', '12')
  expect(screen.getByText(/≈ 10\.50 USD of 12 USD/)).toBeInTheDocument()
  expect(screen.getByText(/87% used/)).toBeInTheDocument()
  expect(screen.getByText(/2 messages this month ran on a model with no price/)).toBeInTheDocument()
  expect(screen.queryByText(/a new message asks/)).toBeNull()
  // Over it, what that means is in sight here, where the top bar's pill leads.
  rerender(<BudgetSection budget={spend({ spent: 13, share: 13 / 12, over: true })} />)
  expect(screen.getByText(/used 108% of its monthly budget: a new message asks before its work starts, and triggers start none/)).toBeVisible()
  rerender(<BudgetSection budget={spend({ currency: null, spent: null, share: null, warn: false })} />)
  expect(screen.queryByRole('meter')).toBeNull()
  expect(screen.getByText(/This budget is not enforced: prices are in more than one currency/)).toBeInTheDocument()
  rerender(<BudgetSection budget={spend({ at_least: true })} />)
  expect(screen.getByText(/≥ 10\.50 USD of 12 USD/)).toBeInTheDocument()
  // Read here, set in the project's settings.
  const onSettings = vi.fn()
  rerender(<BudgetSection budget={spend()} onSettings={onSettings} />)
  screen.getByRole('button', { name: 'Change in Settings →' }).click()
  expect(onSettings).toHaveBeenCalledTimes(1)
  rerender(<BudgetSection budget={spend({ budget: null, share: null, warn: false })} />)
  expect(screen.queryByRole('region', { name: 'This month’s budget' })).toBeNull()
})

test('the monthly budget is set and taken away in Limits and money, an amount above zero or nothing', async () => {
  const full: Project = {
    ...{ id: 'p', name: 'demo', root_path: 'C:/demo', created_at: 't', exec_location: 'host', docker_image: null, docker_network: false },
    ...{ search_url: null, search_order: 'builtin', search_agy: false, has_notify_url: false, notify_format: 'slack', notify_desktop: false },
    ...{ turn_token_limit: null, max_agents: null, continue_steps: 25, monthly_budget: null, check_command: null, measure_command: null, finish_tests: null, finish_tests_auto: { on: false, command: null, reason: 'test time not known yet' }, memory_links: [], embedding_provider_id: null, embedding_model: 'text-embedding-3-small', git_commit: false, finish_way: null, auto_notes: false },
    ...{ observe_reports: false, suggest_tasks: true, suggest_tier: 'fast', day_note_at: null, also_in: [], read_in: [], teams_mode: 'none', teams: [] },
    ...{ hide_secrets: true, canary: true, lead_work: 'delegates', when_away: 'waits', away_minutes: 10, spawn_approval: 'auto', spawn_max_depth: 2, spawn_max_agents: 6, spawn_max_parallel: 2, discussion_budget: null, room_posts: 40, room_tokens: null, room_minutes: 30, pass_env: null, held_env: [], koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} } },
  }
  const onSave = vi.fn().mockResolvedValue(undefined)
  const base = { dockerAvailable: true, dockerError: null, desktopAvailable: true, onSave }
  const { unmount } = render(<ProjectSettings {...base} project={full} />)
  await userEvent.click(screen.getByRole('button', { name: /^Limits and money/ }))
  const field = screen.getByLabelText('Monthly budget')
  expect(field).toHaveAccessibleDescription(/In the currency of your prices .* At 80% you are told\. At 100% a new message asks before its work starts, and triggers start none/)
  for (const wrong of ['0', '-5', 'ten']) {
    await userEvent.clear(field)
    await userEvent.type(field, wrong)
    expect(field).toBeInvalid()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  }
  await userEvent.clear(field)
  await userEvent.type(field, '12,5')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenCalledWith({ monthly_budget: 12.5 })
  unmount()
  const { unmount: again } = render(<ProjectSettings {...base} project={{ ...full, monthly_budget: 12.5 }} />)
  await userEvent.click(screen.getByRole('button', { name: /^Limits and money/ }))
  expect(screen.getByLabelText('Monthly budget')).toHaveValue('12.5')
  again()
  // With the spend read, its currency is named.
  const { rerender } = render(<ProjectSettings {...base} project={{ ...full, monthly_budget: 12.5 }} spend={spend()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Limits and money/ }))
  expect(screen.getByLabelText('Monthly budget')).toHaveAccessibleDescription(/ - now USD\./)
  await userEvent.clear(screen.getByLabelText('Monthly budget'))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(onSave).toHaveBeenLastCalledWith({ monthly_budget: null })
  // A budget that holds nothing back says so where it is set.
  rerender(<ProjectSettings {...base} project={{ ...full, monthly_budget: 12.5 }} spend={spend({ currency: null, spent: null, share: null, warn: false })} />)
  expect(screen.getByLabelText('Monthly budget')).toHaveAccessibleDescription(/This budget is not enforced: prices are in more than one currency\./)
})

test('over the budget a message waits for the user’s word: Go on sends it over, Cancel keeps it', async () => {
  const onSend = vi.fn().mockRejectedValueOnce(new ApiError(409, "this project is over this month's budget (13 of 12 USD): say to go on over it"))
  const props = { running: false, permissionMode: 'ask' as const, onSend, onStop: vi.fn(), onPermissionMode: vi.fn() }
  render(<Composer {...props} />)
  const box = screen.getByLabelText('Message')
  await userEvent.type(box, 'more{Enter}')
  const card = screen.getByRole('group', { name: 'Over this month’s budget' })
  expect(card).toHaveTextContent('Over this month’s budget. Send it anyway?')
  expect(screen.getByRole('button', { name: 'Go on anyway' })).toHaveFocus()
  expect(screen.queryByText(/say to go on over it/)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('group', { name: 'Over this month’s budget' })).toBeNull()
  expect(box).toHaveFocus()
  expect(box).toHaveValue('more')
  onSend.mockRejectedValueOnce(new ApiError(409, "this project is over this month's budget"))
  await userEvent.type(box, '{Enter}')
  onSend.mockResolvedValueOnce(undefined)
  await userEvent.click(screen.getByRole('button', { name: 'Go on anyway' }))
  expect(onSend).toHaveBeenLastCalledWith('more', false, true)
  expect(box).toHaveValue('')
  expect(screen.queryByRole('group', { name: 'Over this month’s budget' })).toBeNull()
})

test('reaching 80% is said once in a toast, whose Open goes to Usage', async () => {
  const board: Board = { backlog_waiting: 0, limit: null, running: 0, conversations: [], conflicts: [] }
  const onUsage = vi.fn()
  const toasts = (budget: Budget | null) => <Toasts board={board} budget={budget} shownId={null} onOpen={vi.fn()} onUsage={onUsage} />
  const { rerender, container } = render(toasts(null))
  // The first reading is how things stand, not news.
  rerender(toasts(under))
  expect(container.querySelectorAll('.toast')).toHaveLength(0)
  rerender(toasts(spend()))
  expect(container.querySelector('.toast')).toHaveTextContent('This project has used 87% of its monthly budget')
  rerender(toasts(spend({ spent: 11, share: 11 / 12 })))
  expect(container.querySelectorAll('.toast')).toHaveLength(1)
  await userEvent.click(screen.getByRole('button', { name: 'Open' }))
  expect(onUsage).toHaveBeenCalled()
  expect(container.querySelectorAll('.toast')).toHaveLength(0)
})
