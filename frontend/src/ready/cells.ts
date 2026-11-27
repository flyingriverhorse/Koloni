import type { AwayJob, BacklogTask } from '../api/types'
import type { CellFill, CellTone } from '../shell/Cell'

/** How a job or a task stands, as Ready for you's cells say it - in the report, what waits for you and To-do alike. */
export type Stands = 'done' | 'running' | 'yours' | 'stuck' | 'queued' | 'proposed'

/** Each state's cell: done green, at work honey, your word a honey rim lightly filled, stuck red-orange, queued empty,
 *  proposed a thin rim. */
export const CELL: Record<Stands, { tone: CellTone; fill: CellFill }> = {
  done: { tone: 'ok', fill: 'full' },
  running: { tone: 'honey', fill: 'full' },
  yours: { tone: 'honey', fill: 'soft' },
  stuck: { tone: 'warn', fill: 'full' },
  queued: { tone: 'plain', fill: 'none' },
  proposed: { tone: 'plain', fill: 'thin' },
}

/** Each state in words: the legend's, and a cell's label where nothing more is said. */
export const STANDS_WORD: Record<Stands, string> = {
  done: 'done',
  running: 'at work',
  yours: 'waits for your word',
  stuck: 'stuck',
  queued: 'queued',
  proposed: 'proposed',
}

/** A night's job: done, at work, waiting for you, could not be done; one not started or stopped is empty. */
export const jobStands = (job: AwayJob): Stands =>
  job.state === 'done'
    ? 'done'
    : job.state === 'working'
      ? 'running'
      : job.state === 'waits'
        ? 'yours'
        : job.state === 'failed'
          ? 'stuck'
          : 'queued'

/**
 * A To-do task, with its word on its row: done; waiting for you (on a card in its chat, at "done?", its work to take
 * in, its push); at work; stuck; else queued or to do. `push`: the night parked a push of it for you.
 */
export function taskStands(task: BacklogTask, push = false): [Stands, string] {
  if (task.status === 'done') return ['done', 'done']
  if (push) return ['yours', 'push waits for you']
  if (task.status === 'review') return ['yours', task.not_in ? 'waits for Take in' : 'done?']
  if (task.status === 'doing') return task.waiting ? ['yours', 'waits for you'] : ['running', 'at work']
  if (task.status === 'blocked') return ['stuck', task.stuck ? 'stuck' : 'blocked']
  if (task.status === 'proposed') return ['proposed', 'proposed']
  return ['queued', task.place != null ? 'queued' : 'to do']
}
