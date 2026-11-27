import { useId, useState } from 'react'
import type { Away, Waiting } from '../api/types'
import { JobRow } from '../backlog/Away'
import { STATE_WORD, clock } from '../backlog/awayText'
import { Cell } from '../shell/Cell'
import { CELL, jobStands } from './cells'
import { openDecisions } from './decisionLog'
import { NightStrip } from './NightStrip'
import { axisOf, isNews, nightLede, nightTitle, spentLine } from './nightText'

/** What was decided for you on the night's jobs, and how many of those you have not seen - Decided for you, at them. */
function Decided({ away }: { away: Away }) {
  const rows = away.jobs.flatMap(job => job.decisions)
  const unseen = rows.filter(row => row.seen === false).length
  if (!rows.length) return <span>Nothing was decided for you on its jobs.</span>
  return (
    <span>
      {rows.length} decided for you on its jobs{unseen > 0 && `, ${unseen} not seen`}{' '}
      <button type="button" className="link-btn" onClick={() => openDecisions(unseen > 0)}>
        See them
      </button>
    </span>
  )
}

/** The report's foot: what was decided on its jobs, and why the night ended where its record says (its money limit,
 *  its time, Stop all). */
function Foot({ away }: { away: Away }) {
  return (
    <>
      <Decided away={away} />
      {away.why && <span>{away.why}</span>}
    </>
  )
}

/** No news: one line - and, a night there is, the way to its whole report. */
function Nothing({ away, onReport }: { away: Away | null; onReport?: () => void }) {
  return (
    <p className="ready-nothing muted">
      Nothing new since you last looked.
      {away?.status === 'ended' && onReport && (
        <>
          {' '}
          <button type="button" className="link-btn" onClick={onReport}>
            The whole report
          </button>
        </>
      )}
    </p>
  )
}

/** The report's words: its one sentence and a row per job - its cell, what came of it, its branch, what you can do
 *  about it. */
function Body({ away, onOpen }: { away: Away; onOpen: (conversationId: string) => void }) {
  return (
    <>
      <p className="ready-lede">{nightLede(away)}</p>
      <ol className="away-jobs ready-jobs" aria-label="The night's jobs, as they came out">
        {away.jobs.map(job => (
          <JobRow
            key={job.task_id ?? job.title}
            away={away}
            job={job}
            onOpen={onOpen}
            report={<Cell {...CELL[jobStands(job)]} label={STATE_WORD[job.state] || 'Planned'} />}
          />
        ))}
      </ol>
    </>
  )
}

/** Whether the night is news - or was, while this page has shown it: once on screen it is seen (the strip says so),
 *  and its report stays until another night comes. A night planned, then gone away under the same id, shows at once. */
function useNews(away: Away | null): boolean {
  const [shown, setShown] = useState<string | null>(null)
  const id = away?.id ?? null
  const news = isNews(away)
  if (news && shown !== id) setShown(id)
  return news || (id !== null && shown === id)
}

/**
 * Ready for you's "what was done" (0.1.10): the project's last ☾ Away, while it works and once it ended - one sentence,
 * a row per job, the night's lanes on its clock, what was decided for you and what it spent; Copy report as Markdown.
 * A night that is no news - none, or one ended over a day ago that you have seen - is one line. `hidden`: its tab is not
 * shown, so the night is not seen yet.
 */
export function Report({
  away,
  parked,
  onReport,
  onOpen,
  hidden,
}: {
  away: Away | null
  parked: Waiting[]
  onReport?: () => void
  onOpen: (conversationId: string) => void
  hidden?: boolean
}) {
  const id = useId()
  const news = useNews(away)
  if (!news || !away || (away.status !== 'running' && away.status !== 'ended'))
    return <Nothing away={away} onReport={onReport} />
  if (away.status === 'ended' && axisOf(away))
    return (
      <NightStrip away={away} parked={parked} onReport={onReport} foot={<Foot away={away} />} hidden={hidden}>
        <Body away={away} onOpen={onOpen} />
      </NightStrip>
    )
  return (
    <section className="night-strip" aria-labelledby={id}>
      <div className="night-head">
        <h3 id={id}>
          {away.status === 'running' ? `☾ While you're away, since ${clock(away.started_at)}` : nightTitle(away)}
        </h3>
      </div>
      <Body away={away} onOpen={onOpen} />
      <p className="ready-report-foot">
        <Foot away={away} />
        <span>{spentLine(away)}</span>
      </p>
    </section>
  )
}
