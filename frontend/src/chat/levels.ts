import type { Conversation, PermissionMode, Project } from '../api/types'
import { AFTER_CHANGE } from '../shell/sections/AfterChange'

/** Each permission level: its name, its short name on the comb's button, what it does in a line, and its comb's cells (0.1.5). */
export const LEVELS: Record<PermissionMode, { name: string; short: string; says: string; cells: 1 | 2 | 3 }> = {
  ask: { name: 'Ask before changes', short: 'Ask', says: 'Each file change and command waits for your card', cells: 1 },
  auto_edit: { name: 'Auto-edit files', short: 'Auto-edit', says: 'Writes files at once (revertible); commands still ask', cells: 2 },
  full_auto: { name: 'Full auto', short: 'Full auto', says: 'Changes and commands run; only harmful or risky actions ask', cells: 3 },
}

/** What Plan first does (slice 49). */
export const PLAN_FIRST = 'Each new message gets a plan to approve before anything changes'

/** S10 (plan decision 17): Check after a change for one chat - this chat's word (null: the project's), and the project's After a change. */
export interface Checks {
  chat: Conversation['after_change']
  project: Project['after_change']
  onChange: (value: Conversation['after_change']) => void
}

/** Whether this chat's changes are checked: its own word, else the project's (anything but Nothing). */
export const checksOn = ({ chat, project }: Pick<Checks, 'chat' | 'project'>) => (chat ? chat === 'on' : project !== 'nothing')

/** The switch's line: what this chat says against the project's setting. */
export function checksSaid({ chat, project }: Pick<Checks, 'chat' | 'project'>): string {
  const theirs = AFTER_CHANGE.find(([value]) => value === project)?.[1] ?? project
  if (!chat) return `As the project: ${theirs}`
  return `${chat === 'off' ? 'Off' : 'On'} for this chat · the project's is ${theirs}`
}

/** What turning it on or off saves: the project's (null) where that already says so, else this chat's own word. */
export const checksValue = (on: boolean, project: Project['after_change']): Conversation['after_change'] =>
  on === (project !== 'nothing') ? null : on ? 'on' : 'off'

/** Decision 17: Full auto does not lock the switch - with it off, the menu says what that leaves. */
export const NO_CHECKS_AT_FULL_AUTO = 'Full auto with no checks: nothing checks this chat’s changes'
