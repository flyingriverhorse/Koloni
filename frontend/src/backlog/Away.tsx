import { Moon, PencilSimple, X } from '@phosphor-icons/react'
import { useState, type CSSProperties } from 'react'
import type { Away, AwayChange, AwayJob } from '../api/types'
import { useAsk } from '../memory/useAsk'
import { useApp } from '../state/store'
import { doneSaid } from './awayText'

/** A time as this machine's clock says it: "23:42". */
const clock = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : ''
const amount = (n: number | null | undefined, currency?: string | null) => (n == null ? '' : `${n.toFixed(2)}${currency ? ` ${currency}` : ''}`)
const STATE_WORD: Record<AwayJob['state'], string> = {
  planned: '',
  next: 'Next',
  working: 'Working',
  waits: 'Waits for you',
  done: 'Done',
  failed: 'Could not be done',
  stopped: 'Stopped',
}
const STATE_MARK: Record<AwayJob['state'], string> = { planned: '', next: '·', working: '●', waits: '!', done: '✓', failed: '✕', stopped: '■' }
type Job = NonNullable<AwayChange['jobs']>[number]
/** A job done that left nothing: nothing kept in its copy, nothing taken in from it. */
const unchanged = (job: AwayJob) => job.state === 'done' && !job.kept.length && !job.taken.length
// (task_id kept: a job that is a To-do task stays that task when the card is changed - B-409.)
const toJob = ({ title, line, team, recipe, task_id }: AwayJob): Job => ({ title, line, team, recipe, task_id })

/** Hours from now to a time; 0 for none. */
const hoursTo = (iso: string | null | undefined) => (iso ? (Date.parse(iso) - Date.now()) / 3_600_000 : 0)

/** How far off a stop is, said beside it: under an hour too (live, it was said only past 12 hours). */
const inAbout = (hours: number) =>
  hours <= 0 ? '' : ` (that is in about ${hours < 1 ? `${Math.max(1, Math.round(hours * 60))} minutes` : `${Math.round(hours)} hours`}${hours > 12 ? ', tomorrow' : ''})`

/** How long from one time to another (now, without it): "1 h 48 m". */
function lasted(from: string | null, to: string | null) {
  if (!from) return ''
  const minutes = Math.max(0, Math.round(((to ? Date.parse(to) : Date.now()) - Date.parse(from)) / 60000))
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} m` : `${minutes} m`
}

/**
 * The Lead's "While you're away" card in the chat (slice 106): the night's jobs, the places kept out and
 * the limits, all yours to change; only Start starts it. Once started or put away, one line says so.
 */
export function AwayCard({ card }: { card: Away }) {
  const { busy, error, ask } = useAsk()
  const [editing, setEditing] = useState<{ jobs: Job[]; kept: string } | null>(null)
  // (The chat the card is in: its project's "When you're away", every chat's - tek-ev.)
  const whenAway = useApp(s =>
    s.conv?.conversation.id === card.conversation_id ? (s.projects.find(p => p.id === s.conv?.conversation.project_id)?.when_away ?? null) : null,
  )
  const act = (action: 'change' | 'start' | 'dismiss', change?: AwayChange) => ask(() => useApp.getState().awayDo(card.id, action, change))
  if (card.status !== 'planned') {
    return (
      <p className="away-said muted" role="note">
        <Moon size={13} />{' '}
        {card.status === 'dismissed'
          ? 'Not now: this card was put away.'
          : card.status === 'running'
            ? `Started at ${clock(card.started_at)}: working while you're away. Its jobs are on the To-do list.`
            : `${card.why ?? 'Every job was looked at.'} The report is on the canvas.`}
      </p>
    )
  }
  const jobs = card.jobs.map(toJob)
  const save = () =>
    editing &&
    void act('change', {
      jobs: editing.jobs.filter(job => job.title.trim()),
      kept_out: editing.kept.split(/[,\n]/).map(one => one.trim()).filter(Boolean),
    }).then(done => done && setEditing(null))
  return (
    <section className="away-card" aria-label="While you're away">
      <h3 className="away-head">
        <span className="away-moon" aria-hidden="true">
          ☾
        </span>
        While you're away
      </h3>
      <p className="muted">The Orchestrator's jobs for while you're away: change anything before you start.</p>
      <ol className="away-tasks">
        {(editing?.jobs ?? jobs).map((job, i) => (
          <li key={i} className="away-task">
            <span className="away-n">{i + 1}</span>
            {editing ? (
              <div className="away-grow">
                <input
                  className="input"
                  aria-label={`Job ${i + 1}`}
                  maxLength={200}
                  value={job.title}
                  onChange={e => setEditing({ ...editing, jobs: editing.jobs.map((one, j) => (j === i ? { ...one, title: e.target.value } : one)) })}
                />
                <input
                  className="input"
                  aria-label={`What makes job ${i + 1} done`}
                  placeholder="What makes it done (optional)"
                  maxLength={4000}
                  value={job.line ?? ''}
                  onChange={e => setEditing({ ...editing, jobs: editing.jobs.map((one, j) => (j === i ? { ...one, line: e.target.value || null } : one)) })}
                />
              </div>
            ) : (
              <div className="away-grow">
                <b>{job.title}</b>
                {job.line && <div className="muted away-line">{job.line}</div>}
              </div>
            )}
            {(job.team || job.recipe) && <span className="tag">{[job.team, job.recipe].filter(Boolean).join(' · ')}</span>}
            {!editing && (
              <button type="button" className="icon-btn" aria-label={`Change ${job.title}`} onClick={() => setEditing({ jobs, kept: card.kept_out.join(', ') })}>
                <PencilSimple size={13} />
              </button>
            )}
            <button
              type="button"
              className="icon-btn"
              aria-label={`Take out ${job.title}`}
              disabled={busy || (editing?.jobs ?? jobs).length === 1}
              onClick={() =>
                editing ? setEditing({ ...editing, jobs: editing.jobs.filter((_, j) => j !== i) }) : void act('change', { jobs: jobs.filter((_, j) => j !== i) })
              }
            >
              <X size={13} />
            </button>
          </li>
        ))}
      </ol>
      {editing && (
        <>
          <button type="button" className="away-add" disabled={editing.jobs.length >= 10} onClick={() => setEditing({ ...editing, jobs: [...editing.jobs, { title: '', line: null, team: null, recipe: null }] })}>
            + Add a job
          </button>
          <label className="field" htmlFor={`away-kept-${card.id}`}>
            <span>Kept out (files or folders of the project: one a line, or commas between)</span>
            <textarea id={`away-kept-${card.id}`} className="input mono" rows={2} value={editing.kept} onChange={e => setEditing({ ...editing, kept: e.target.value })} />
          </label>
        </>
      )}
      <ul className="away-rules">
        <li>
          <b>Each job works in its own copy.</b> Your project does not change while you're away; you take the work in when you're back.
        </li>
        <li>
          <b>If a job needs your word, it waits</b> and the next one goes on.{' '}
          {/* (K-vekil-karar: suggested here, one click - never turned on unasked.) */}
          {whenAway === 'lead' ? (
            'The Orchestrator answers what it safely can for you; you see it under "Decided for you".'
          ) : whenAway === 'waits' ? (
            <button type="button" className="link-btn" disabled={busy} onClick={() => void ask(() => useApp.getState().saveProjectSettings({ when_away: 'lead' }))}>
              Let the Orchestrator answer what it safely can
            </button>
          ) : null}
        </li>
        <li>
          {card.kept_out.length ? (
            <>
              Kept out: {card.kept_out.map(path => <span key={path} className="away-inline mono">{path}</span>)}
            </>
          ) : (
            'Nothing is kept out.'
          )}
        </li>
        <Limits card={card} busy={busy} onChange={change => void act('change', change)} />
        <li>A job works at most {card.job_minutes} minutes: then it stops, what it did kept in its copy, and the next one goes on.</li>
      </ul>
      <div className="memory-actions">
        {editing ? (
          <>
            <button type="button" className="btn btn-small btn-primary" disabled={busy || !editing.jobs.some(job => job.title.trim())} onClick={save}>
              Save the list
            </button>
            <button type="button" className="btn btn-small" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void act('start')}>
              Start
            </button>
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => setEditing({ jobs, kept: card.kept_out.join(', ') })}>
              Change the list
            </button>
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => void act('dismiss')}>
              Not now
            </button>
            <span className="muted">The jobs go onto the To-do list too.</span>
          </>
        )}
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}

/** The card's limits: a stop time and a spend limit, each only if set (the user, 6 Nov: no defaults). */
function Limits({ card, busy, onChange }: { card: Away; busy: boolean; onChange: (change: AwayChange) => void }) {
  return (
    <li>
      Stop at{' '}
      <input
        type="time"
        className="input away-inline"
        aria-label="Stop at"
        defaultValue={clock(card.until)}
        disabled={busy}
        onBlur={e => e.target.value !== clock(card.until) && onChange({ until: e.target.value || null })}
      />{' '}
      {!card.until && '(empty: no time limit) '}
      or after{' '}
      <input
        type="number"
        className="input away-inline"
        aria-label="Stop after spending"
        min={0}
        step={0.5}
        defaultValue={card.money ?? ''}
        disabled={busy}
        onBlur={e => String(card.money ?? '') !== e.target.value && onChange({ money: e.target.value === '' ? null : Number(e.target.value) })}
      /> {card.currency}{card.money == null && ' (empty: no spend limit)'}, whichever comes first{inAbout(hoursTo(card.until))}.
      {card.on_plan ? ` No money is counted on ${card.on_plan}, a plan: there only the time holds${card.until ? '' : ', once you set one'}.` : ''} Your provider limits hold too.
    </li>
  )
}

/** At the top of a night job's chat (B-150): which night it is of, and the way back to that night's report on the canvas. */
export function AwayFrom({ chat }: { chat: string }) {
  // shortcut: only the project's last night is known here - a job's chat of an older one has no link; upgrade with its night on the chat's snapshot.
  const away = useApp(s => s.away)
  if (!away?.started_at || !away.jobs.some(job => job.conversation_id === chat)) return null
  const back = () => void useApp.getState().openTurn(away.conversation_id, away.run_id).then(() => useApp.getState().select('away:' + away.id))
  return (
    <button type="button" className="link-btn away-from" onClick={back}>
      <Moon size={13} /> From the jobs started at {clock(away.started_at)} while you were away — back to their report
    </button>
  )
}

/** In the top bar on every page while a night runs: which job, until when, and Stop all. */
export function AwayStatus({ away, onOpen }: { away: Away | null; onOpen: () => void }) {
  const { busy, ask } = useAsk()
  if (!away || away.status !== 'running') return null
  const at = away.jobs.findIndex(job => job.state === 'working')
  const n = at >= 0 ? at + 1 : away.jobs.filter(job => job.state !== 'next').length
  return (
    <span className="away-status">
      <button type="button" className="away-pill" onClick={onOpen}>
        ☾ Away · job {n} of {away.jobs.length}
        {away.until && ` · until ${clock(away.until)}`}
      </button>
      <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => useApp.getState().awayDo(away.id, 'stop'))}>
        Stop all
      </button>
    </span>
  )
}

/** One job of a night, with what you can do about it as it stands. */
export function JobRow({ away, job, onOpen }: { away: Away; job: AwayJob; onOpen: (cid: string) => void }) {
  const { busy, error, ask } = useAsk()
  const store = useApp.getState
  const chat = job.conversation_id
  const line =
    job.state === 'done'
      ? [doneSaid(job), amount(job.spent, away.currency)].filter(Boolean).join(' · ')
      : job.state === 'next'
        ? 'Not started'
        : // (Live: a command it waits for was said twice - as its why, and on its Allow line.)
          job.asks.some(one => one.kind && one.text === job.why)
          ? null
          : job.why
  // B-122: a job that changed nothing is not "done" as one with work to take in is.
  const word = unchanged(job) ? 'Done, nothing changed' : STATE_WORD[job.state]
  return (
    <li className={`away-job away-${job.state}`} aria-label={`${job.title}: ${word}`}>
      <span className="away-mark" aria-hidden="true">
        {STATE_MARK[job.state]}
      </span>
      <div className="away-grow">
        <b>{job.title}</b>
        {line && <div className="muted away-line">{line}</div>}
        {job.state === 'working' && job.now && <span className="away-now mono">{job.now}</span>}
        {job.checks.length > 0 && <div className="muted away-line">{job.checks.join(' · ')}</div>}
        {job.assessment && <q className="away-view">{job.assessment}</q>}
        {job.kept_out.length > 0 && (
          <div className="away-shared">Its copy changed {job.kept_out.join(', ')}, where you said not to: look before you take it in.</div>
        )}
        {job.shared.length > 0 && (
          <div className="away-shared">Another job changed {job.shared.join(', ')} too: the two are joined line by line when you take both in.</div>
        )}
        <div className="memory-actions">
          {job.state === 'waits' &&
            job.asks
              .filter(one => one.kind)
              .map(one => (
                <span key={one.id} className="away-ask">
                  <span className="mono">{one.text}</span>
                  <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void ask(() => store().answerAsk(one, true))}>
                    Allow and go on
                  </button>
                  <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => store().answerAsk(one, false))}>
                    Refuse
                  </button>
                </span>
              ))}
          {/* (One that needs the project itself waits with its copy: Take in it as it is, then do the rest there.) */}
          {(job.state === 'done' || job.state === 'waits') && job.kept.length > 0 && (
            // (Not taken - a line that clashes with the project's, say: its chat's card of the kept copy decides it.)
            <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void ask(() => store().takeIn(job.kept)).then(done => done || !chat || onOpen(chat))}>
              Take in
            </button>
          )}
          {(job.state === 'failed' || job.state === 'stopped') && away.status === 'ended' && job.task_id && (
            <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => store().awayDo(away.id, `jobs/${job.task_id}/again`))}>
              Try again
            </button>
          )}
          {chat && (
            <button type="button" className="btn btn-small" onClick={() => onOpen(chat)}>
              {job.state === 'done' && job.kept.length ? 'See the changes' : 'Open its chat'}
            </button>
          )}
        </div>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
      </div>
      <span className="away-tag">{word}</span>
    </li>
  )
}

/** The night's strip: since when, what it spent against its limit, and Stop all while it runs. */
function Strip({ away }: { away: Away }) {
  const { busy, error, ask } = useAsk()
  const share = away.spent != null && away.money ? Math.min(1, away.spent / away.money) : null
  return (
    <div className="away-strip" role="status">
      <b>{away.status === 'running' ? "☾ Working while you're away" : '☾ While you were away'}</b>
      <span className="muted">
        started {clock(away.started_at)} · {lasted(away.started_at, away.ended_at)}
      </span>
      {share !== null && (
        <span className="away-meter" aria-hidden="true">
          <i style={{ width: `${share * 100}%` } as CSSProperties} />
        </span>
      )}
      <span className="muted">
        {away.spent == null ? 'spent: not known' : `${away.at_least ? 'at least ' : ''}${amount(away.spent, away.currency)}`}
        {away.money != null && ` of ${amount(away.money, away.currency)}`}
      </span>
      {away.status === 'running' && (
        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => useApp.getState().awayDo(away.id, 'stop'))}>
          Stop all
        </button>
      )}
      {away.status === 'ended' && away.why && <span className="muted">{away.why}</span>}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/** A job that waits for you, or has a decision of yours on its row: a Take in, a Try again. */
const needsYou = (away: Away, job: AwayJob) =>
  job.state === 'waits' ||
  (job.state === 'done' && job.kept.length > 0) ||
  ((job.state === 'failed' || job.state === 'stopped') && away.status === 'ended' && !!job.task_id)

/**
 * The To-do page's part of a night: one line, which opens on the strip and each job as it stands right
 * now - open by itself, never folded, while a job waits for your decision.
 */
export function AwayNight({ away, onOpen }: { away: Away; onOpen: (cid: string) => void }) {
  const night = (
    <>
      <Strip away={away} />
      <ol className="away-jobs">
        {away.jobs.map(job => (
          <JobRow key={job.task_id ?? job.title} away={away} job={job} onOpen={onOpen} />
        ))}
      </ol>
    </>
  )
  const done = away.jobs.filter(job => job.state === 'done').length
  return (
    <section className="memory-section" aria-label="While you're away">
      {away.jobs.some(job => needsYou(away, job)) ? (
        night
      ) : (
        // (Stop all is in the top bar too, while it runs.)
        <details className="more">
          <summary>
            ☾ {away.status === 'running' ? "While you're away" : 'While you were away'}: {done} of {away.jobs.length} done
          </summary>
          {night}
        </details>
      )}
    </section>
  )
}

/**
 * The morning's report (slice 106), on the canvas as the night's own node: what was done, for you to take
 * in; what waits for your word; what could not be done; what was proposed and not started; and the places
 * kept out. Nothing of it is in the project before your Take in.
 */
export function AwayReport({ away, onOpen }: { away: Away; onOpen: (cid: string) => void }) {
  const { busy, error, ask } = useAsk()
  const of = (state: AwayJob['state']) => away.jobs.filter(job => job.state === state)
  const done = of('done')
  const kept = done.flatMap(job => job.kept)
  // B-123: as Take in goes - what waits for it, and whether any of it is in the project now.
  const toTake = done.filter(job => job.kept.length).length
  const someIn = away.jobs.some(job => job.taken.length)
  const section = (title: string, jobs: AwayJob[]) =>
    jobs.length > 0 && (
      <div className="away-sec">
        <h4>{title}</h4>
        <ol className="away-jobs">
          {jobs.map(job => (
            <JobRow key={job.task_id ?? job.title} away={away} job={job} onOpen={onOpen} />
          ))}
        </ol>
      </div>
    )
  return (
    <div className="away-report">
      <div className="muted">
        {clock(away.started_at)} → {clock(away.ended_at) || 'now'} · {lasted(away.started_at, away.ended_at)}
        {away.spent != null && ` · ${amount(away.spent, away.currency)}${away.money != null ? ` of ${amount(away.money, away.currency)}` : ''}`} ·{' '}
        {someIn ? 'what you took in is in your project, the rest only once you take it in' : 'nothing of it is in your project before you take it in'}
      </div>
      {away.why && <div className="muted">{away.why}</div>}
      <div className="away-sums">
        <span className="away-done">
          <b>{away.counts.done ?? 0}</b> done{toTake ? `, ${toTake} for you to take in` : ''}
        </span>
        <span className="away-waits">
          <b>{away.counts.waits ?? 0}</b> {(away.counts.waits ?? 0) === 1 ? 'waits' : 'wait'} for your word
        </span>
        <span className="away-failed">
          <b>{away.counts.failed ?? 0}</b> could not be done
        </span>
        {(away.counts.stopped ?? 0) > 0 && (
          <span className="away-stopped">
            <b>{away.counts.stopped}</b> stopped
          </span>
        )}
      </div>
      {kept.length > 1 && (
        <button type="button" className="btn btn-small btn-primary nodrag" disabled={busy} onClick={() => void ask(() => useApp.getState().takeIn(kept))}>
          Take in all ({done.filter(job => job.kept.length).length})
        </button>
      )}
      {section('Done', done)}
      {section('Waits for your word', of('waits'))}
      {section('Could not be done', of('failed'))}
      {section('Stopped', of('stopped'))}
      {section('Not started', of('next'))}
      {away.proposed.length > 0 && (
        <div className="away-sec">
          <h4>Proposed while you were away, not started</h4>
          {away.proposed.map(task => (
            <div key={task.id} className="away-job">
              <div className="away-grow">
                <b>{task.title}</b>
                {task.detail && <div className="muted away-line">{task.detail}</div>}
              </div>
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => useApp.getState().decideTask(task.id, 'approve'))}>
                Add to To-do
              </button>
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => void ask(() => useApp.getState().decideTask(task.id, 'reject'))}>
                Dismiss
              </button>
            </div>
          ))}
        </div>
      )}
      {away.kept_out.length > 0 && (
        <div className="away-sec">
          <h4>Kept out, as you asked</h4>
          {away.tried.length || away.slipped.length ? (
            <ul>
              {away.tried.map((one, i) => (
                <li key={i} className="mono">
                  {one.what} - refused
                </li>
              ))}
              {/* (found in its copy in the morning, not refused at night: look before you take it in) */}
              {away.slipped.map((one, i) => (
                <li key={`s${i}`} className="mono away-shared">
                  {one.what}
                </li>
              ))}
            </ul>
          ) : (
            <div className="muted">Nothing tried to change {away.kept_out.join(', ')}.</div>
          )}
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
