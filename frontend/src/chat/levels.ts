import type { Conversation, PermissionMode, Project } from '../api/types'
import { AFTER_CHANGE } from '../shell/sections/AfterChange'
import { runsSaid } from '../shell/sections/afterChangeWords'

/** Each permission level: its name, its short name on the comb's button, what it does in a line, and its comb's cells (0.1.5). */
export const LEVELS: Record<PermissionMode, { name: string; short: string; says: string; cells: 1 | 2 | 3 }> = {
  ask: { name: 'Ask before changes', short: 'Ask', says: 'Each file change and command waits for your card', cells: 1 },
  auto_edit: {
    name: 'Auto-edit files',
    short: 'Auto-edit',
    says: 'Writes files at once (revertible); commands still ask',
    cells: 2,
  },
  full_auto: {
    name: 'Full auto',
    short: 'Full auto',
    says: 'Changes and commands run; only harmful or risky actions ask',
    cells: 3,
  },
}

/** What Plan first does (slice 49). */
export const PLAN_FIRST = 'Each new message gets a plan to approve before anything changes'

/** S10 (plan decision 17): Test and review changes, for one chat - this chat's word (null: the project's), the project's After a change, the command it runs and its Fix rounds. */
export interface Checks {
  chat: Conversation['after_change']
  project: Project['after_change']
  /** What runs (`testsRun`): the project's command, or that KOLONİ finds one. */
  command: string
  /** The project's Fix rounds; null: until it passes (k-canli-016). */
  rounds: number | null
  onChange: (value: Conversation['after_change']) => void
}

/** Whether this chat's changes are checked: its own word, else the project's (anything but Nothing). */
export const checksOn = ({ chat, project }: Pick<Checks, 'chat' | 'project'>) =>
  chat ? chat === 'on' : project !== 'nothing'

const NONE_HERE = 'nothing is tested or reviewed; each answer says “Not checked”.'

/** The switch's line: what this chat's changes get - as the project, off, or on against it - with the command it runs and the Fix rounds. */
export function checksSaid({ chat, project, command, rounds }: Omit<Checks, 'onChange'>): string {
  const theirs = AFTER_CHANGE.find(([value]) => value === project)?.[1] ?? project
  // (On in a project at Nothing is Test and review for this chat: a review too.)
  const runs = runsSaid(command, project !== 'tests', rounds)
  if (chat === 'off') return `Off for this chat: ${NONE_HERE}`
  if (chat === 'on')
    return project === 'nothing'
      ? `On for this chat · the project's is ${theirs}: ${runs}`
      : `On for this chat: ${runs}`
  return `As the project: ${project === 'nothing' ? NONE_HERE : runs}`
}

/** What turning it on or off saves: the project's (null) where that already says so, else this chat's own word. */
export const checksValue = (on: boolean, project: Project['after_change']): Conversation['after_change'] =>
  on === (project !== 'nothing') ? null : on ? 'on' : 'off'

/** Decision 17: Full auto does not lock the switch - with it off, the menu says what that leaves. */
export const NO_CHECKS_AT_FULL_AUTO = 'Full auto with no checks: nothing checks this chat’s changes'
