import type { AwayJob } from '../api/types'

const some = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`

/** What a job done left, in words: the report's line and its canvas node say it alike. */
export const doneSaid = (job: AwayJob) =>
  job.kept.length ? `${some(job.files.length, 'file')} in its copy, waits for you` : job.taken.length ? `taken in: ${job.taken.join(', ')}` : 'nothing changed'
