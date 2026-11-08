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

type Queue = NonNullable<AgentLive['queue']>

/** "2 min 43 s", "60 min", "43 s". */
function spell(seconds: number): string {
  const min = Math.floor(seconds / 60)
  const s = seconds % 60
  return [min > 0 && `${min} min`, (s > 0 || min === 0) && `${s} s`].filter(Boolean).join(' ')
}

/** Its CLI's model is queued (K-qoder-kuyruk): one line, as it stands now; the rest of the window goes on as it was.
 * shortcut: "Qoder" - the only CLI with a queue line (measured 29 Oct 2026); name the CLI from the provider if
 * another gets one. */
export function queueLine(queue: Queue): string {
  return [
    "Qoder: in the model's queue",
    queue.elapsed_s !== null && ` for ${spell(queue.elapsed_s)}`,
    queue.max_s !== null && ` (waits up to ${spell(queue.max_s)})`,
    queue.available === false && ', the service says it is not available',
  ].filter(Boolean).join('')
}
