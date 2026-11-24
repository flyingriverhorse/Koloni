import type { AgentLive } from '../state/applyEvent'

type Step = NonNullable<AgentLive['plan']>[number]

/** How far each step of a CLI's plan is (89j), as a mark before its words. */
export const STEP_MARK: Record<Step['status'], string> = { completed: '✓', inProgress: '▸', pending: '·' }

/** "plan 2/5": the steps of its CLI's plan done, of all of them. */
export function planCount(plan: Step[]): string {
  return `plan ${plan.filter(step => step.status === 'completed').length}/${plan.length}`
}

/** Its plan, a step a line: for under the pointer, where it is plain text. */
export function planLines(plan: Step[]): string {
  return plan.map(step => `${STEP_MARK[step.status]} ${step.step}`).join('\n')
}
