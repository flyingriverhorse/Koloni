import type { AwayJob } from '../api/types'

/** A time as this machine's clock says it: "23:42". */
export const clock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : ''
/** An amount in its currency: "0.84 USD". */
export const amount = (n: number | null | undefined, currency?: string | null) =>
  n == null ? '' : `${n.toFixed(2)}${currency ? ` ${currency}` : ''}`

/** How a job stands, in words: its report's row, its tag and the night strip's lane say it alike. */
export const STATE_WORD: Record<AwayJob['state'], string> = {
  planned: '',
  next: 'Next',
  working: 'Working',
  waits: 'Waits for you',
  done: 'Done',
  failed: 'Could not be done',
  stopped: 'Stopped',
}

const some = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`

/** What a job done left, in words: the report's line and its canvas node say it alike. */
export const doneSaid = (job: AwayJob) =>
  job.kept.length
    ? `${some(job.files.length, 'file')} ${job.branch ? 'on its branch' : 'in its copy'}, waits for you` // (D3)
    : job.taken.length
      ? `taken in: ${job.taken.join(', ')}`
      : job.discarded.length
        ? `discarded: ${job.discarded.join(', ')}` // (N12: it changed them, and you said no)
        : 'nothing changed'
