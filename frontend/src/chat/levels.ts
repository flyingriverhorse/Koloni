import type { PermissionMode } from '../api/types'

/** Each permission level: its name, its short name on the comb's button, what it does in a line, and its comb's cells (0.1.5). */
export const LEVELS: Record<PermissionMode, { name: string; short: string; says: string; cells: 1 | 2 | 3 }> = {
  ask: { name: 'Ask before changes', short: 'Ask', says: 'Each file change and command waits for your card', cells: 1 },
  auto_edit: { name: 'Auto-edit files', short: 'Auto-edit', says: 'Writes files at once (revertible); commands still ask', cells: 2 },
  full_auto: { name: 'Full auto', short: 'Full auto', says: 'Changes and commands run; only harmful or risky actions ask', cells: 3 },
}

/** What Plan first does (slice 49). */
export const PLAN_FIRST = 'Each new message gets a plan to approve before anything changes'
