import { type ReactNode, useEffect, useId, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Away, AwayJob, Decision, Waiting } from '../api/types'
import { STATE_WORD, clock } from '../backlog/awayText'
import { stamp, whoOf } from './decisionLog'
import { type Axis, axisOf, nightMarkdown, nightTitle, place, spentLine, uncheckedOf } from './nightText'

const HEX = '8,1 15,5 15,13 8,17 1,13 1,5'
/** A job's bar, by how it came out: finished; waits for you (on a card, or on what it parked); stopped or could not be
 *  done. One at work or not started has none. */
const BAR: Partial<Record<AwayJob['state'], string>> = {
  done: 'night-done',
  waits: 'night-waits',
  failed: 'night-off',
  stopped: 'night-off',
}

/** A decision on its job's lane, at its time: a hexagon in its decider's colour, filled while it waits for your OK. */
function Hex({ row, axis }: { row: Decision; axis: Axis }) {
  return (
    <svg
      className={`night-hex who-${row.who}`}
      width="16"
      height="18"
      viewBox="0 0 16 18"
      style={{ left: `calc(${place(axis, row.at)}% - 8px)` }}
      aria-hidden="true"
    >
      <title>{`${stamp(row.at)} ${whoOf(row)}: ${row.what}`}</title>
      <polygon points={HEX} className={row.seen === false ? 'night-unseen' : undefined} />
    </svg>
  )
}

/** A job's lane: its title, its bar from its start to its end - none where the record lacks either -, its decisions. */
function Lane({ job, axis, push }: { job: AwayJob; axis: Axis; push: boolean }) {
  const span = job.started_at && job.ended_at ? ([job.started_at, job.ended_at] as const) : null
  const bar = span && BAR[job.state]
  const unseen = job.decisions.filter(one => one.seen === false).length
  const said = [
    STATE_WORD[job.state],
    span && `${clock(span[0])} to ${clock(span[1])}`,
    job.decisions.length > 0 && `${job.decisions.length} decided for you, ${unseen} not seen`,
    push && 'its push waits for you',
  ]
  return (
    <li className="night-row" aria-label={`${job.title}: ${said.filter(Boolean).join(', ')}`}>
      <span className="night-job">
        <span className="night-title">{job.title}</span>
        {push && <span className="night-push">push waits for you</span>}
      </span>
      <div className="night-lane">
        {span && bar && (
          <div
            className={`night-bar ${bar}`}
            style={{ left: `${place(axis, span[0])}%`, width: `${place(axis, span[1]) - place(axis, span[0])}%` }}
          />
        )}
        {job.decisions.map(row => (
          <Hex key={row.id} row={row} axis={axis} />
        ))}
      </div>
    </li>
  )
}

/** What the strip's marks mean - a bar's kind only where one is drawn. */
function Legend({ away }: { away: Away }) {
  const drawn = new Set(away.jobs.flatMap(job => (job.started_at && job.ended_at ? [BAR[job.state]] : [])))
  const bars: [string, string][] = [
    ['night-done', 'Finished'],
    ['night-waits', 'Waits for you'],
    ['night-off', 'Stopped or could not be done'],
  ]
  return (
    <>
      {bars
        .filter(([kind]) => drawn.has(kind))
        .map(([kind, word]) => (
          <span key={kind} className="night-key">
            <span aria-hidden="true" className={`night-bar ${kind}`} />
            {word}
          </span>
        ))}
      <span className="night-key">
        <svg aria-hidden="true" width="12" height="14" viewBox="0 0 16 18" className="night-hex-key">
          <polygon points={HEX} className="night-unseen" />
        </svg>
        Decision you haven’t seen
      </span>
      <span className="night-key">
        <svg aria-hidden="true" width="12" height="14" viewBox="0 0 16 18" className="night-hex-key">
          <polygon points={HEX} />
        </svg>
        Seen
      </span>
    </>
  )
}

/** Not checked, as a count that opens on its lines, job by job - a job no record says of, "not known". */
function Unchecked({ away }: { away: Away }) {
  const [open, setOpen] = useState(false)
  const jobs = uncheckedOf(away)
  const n = jobs.reduce((sum, one) => sum + (one.lines?.length ?? 0), 0)
  const unknown = jobs.filter(one => one.lines === null).length
  const said = [
    `${n} ${n === 1 ? 'thing' : 'things'}`,
    unknown > 0 && `${unknown} ${unknown === 1 ? 'job' : 'jobs'} not known`,
  ]
  if (!n && !unknown) return <span className="night-unchecked">Not checked: nothing</span>
  return (
    <>
      <span className="night-unchecked">
        Not checked:{' '}
        <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
          {said.filter(Boolean).join(', ')}
        </button>
      </span>
      {open && (
        <ul className="night-unchecked-list">
          {jobs.flatMap(({ job, lines }) =>
            (lines ?? ['not known: no record of its checks']).map((line, i) => (
              <li key={`${job.task_id ?? job.title}:${i}`}>
                <b>{job.title}</b>: {line}
              </li>
            )),
          )}
        </ul>
      )}
    </>
  )
}

/** The strip's title, the whole report and Copy as Markdown of it. */
function Head({ id, away, parked, onReport }: { id: string; away: Away; parked: Waiting[]; onReport?: () => void }) {
  const [said, setSaid] = useState<string | null>(null)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(nightMarkdown(away, parked))
      setSaid('Copied')
    } catch (err) {
      setSaid(`Not copied: ${errorText(err)}`)
    }
  }
  return (
    <div className="night-head">
      <h3 id={id}>{nightTitle(away)}</h3>
      <div className="night-tools">
        {onReport && (
          <button type="button" className="link-btn" onClick={onReport}>
            The whole report
          </button>
        )}
        <button type="button" className="btn btn-small" onClick={() => void copy()}>
          Copy report as Markdown
        </button>
        {said && (
          <span role="status" className="muted">
            {said}
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * Ready for you's night (karar defteri, Part B; §3.4; 0.1.10 the frame of its report, `children` under its title): the
 * project's last ☾ Away, once it ended - a lane per job, its bar
 * from its start to its end as its turns' records say (none where they lack either), the decisions made for you in its
 * chat that night at their times, filled while they wait for your OK; what was not checked and what it spent; the whole
 * report and Copy as Markdown of it. Nothing of it is guessed: a time, a state or a cost no record holds is not drawn.
 * On screen, the night is seen: KOLONİ opened from now on does not open Ready for you on it again (the morning, App).
 */
export function NightStrip({
  away,
  parked,
  onReport,
  children,
  foot,
}: {
  away: Away
  parked: Waiting[]
  onReport?: () => void
  children?: ReactNode
  /** First in its foot: what was decided for you that night. */
  foot?: ReactNode
}) {
  const id = useId()
  const axis = away.status === 'ended' ? axisOf(away) : null
  const unseen = axis && !away.seen_at ? away.id : null
  useEffect(() => {
    if (unseen) void api.post('/away/' + unseen + '/seen').catch(() => {})
  }, [unseen])
  if (!axis) return null
  const pushes = new Set(parked.flatMap(row => (row.kind === 'push' && !row.decision ? [row.task_id] : [])))
  return (
    <section className="night-strip" aria-labelledby={id}>
      <Head id={id} away={away} parked={parked} onReport={onReport} />
      {children}
      <div className="night-row night-axis-row" aria-hidden="true">
        <span />
        <div className="night-axis">
          {axis.ticks.map(tick => (
            <span key={tick} style={{ left: `${place(axis, tick)}%` }}>
              {clock(new Date(tick).toISOString())}
            </span>
          ))}
        </div>
      </div>
      <ol className="night-lanes" aria-label="The night's jobs">
        {away.jobs.map(job => (
          <Lane key={job.task_id ?? job.title} job={job} axis={axis} push={pushes.has(job.task_id ?? '')} />
        ))}
      </ol>
      <div className="night-foot">
        {foot}
        <Legend away={away} />
        <Unchecked away={away} />
        <span>{spentLine(away)}</span>
      </div>
    </section>
  )
}
