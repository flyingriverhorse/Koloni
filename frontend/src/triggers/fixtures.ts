// Record builders for the trigger tests.
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Trigger, TriggerRun } from '../api/types'

/** A trigger by the clock, every hour, that allows nothing and has never come due. */
export function trigger(over: Partial<Trigger> = {}): Trigger {
  return {
    id: 't1',
    project_id: 'p',
    conversation_id: 'c',
    name: 'Nightly look',
    kind: 'schedule',
    config: { every_minutes: 60 },
    message: 'Look the project over.',
    permissions: { write: false, commands: [], agents: 0 },
    command_lines: [],
    budget: { steps: 15, minutes: 10, per_day: 24 },
    catch_up: true,
    enabled: true,
    ends: null,
    ran: 0,
    run_unchanged: false,
    failures: 0,
    off_because: null,
    last_run_at: null,
    last_result: null,
    next_at: null,
    slowed: null,
    idle: 0,
    last_words: null,
    created_at: '2026-10-05T09:00:00Z',
    updated_at: '2026-10-05T09:00:00Z',
    changes: [],
    runs: [],
    ...over,
  }
}

/** One time a trigger came due; with an outcome of null its turn is still running. */
export function triggerRun(id: string, outcome: TriggerRun['outcome'], over: Partial<TriggerRun> = {}): TriggerRun {
  return {
    id,
    run_id: outcome?.startsWith('skipped') ? null : `run-${id}`,
    at: '2026-10-05T10:00:00Z',
    outcome,
    late: false,
    note: null,
    ...over,
  }
}

/** "New trigger" opened and one of its list picked: a blank one unless named. */
export async function newTrigger(item: string | RegExp = 'Start from blank') {
  await userEvent.click(screen.getByRole('button', { name: 'New trigger' }))
  await userEvent.click(screen.getByRole('menuitem', { name: item }))
}

/** One of a trigger's actions behind its ⋯. */
export async function moreOf(name: string, item: string | RegExp) {
  await userEvent.click(screen.getByRole('button', { name: `More for ${name}` }))
  await userEvent.click(screen.getByRole('menuitem', { name: item }))
}
