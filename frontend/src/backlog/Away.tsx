import { Moon } from '@phosphor-icons/react'
import { type CSSProperties, useEffect, useState } from 'react'
import type { Away, AwayJob } from '../api/types'
import { AwayPanel } from '../chat/AwayPanel'
import { useAsk } from '../memory/useAsk'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { amount, clock, doneSaid } from './awayText'
import { WaitingForYou } from './WaitingForYou'

const STATE_WORD: Record<AwayJob['state'], string> = {
  planned: '',
  next: 'Next',
  working: 'Working',
  waits: 'Waits for you',
  done: 'Done',
  failed: 'Could not be done',
  stopped: 'Stopped',
}
const STATE_MARK: Record<AwayJob['state'], string> = {
  planned: '',
  next: '·',
  working: '●',
  waits: '!',
  done: '✓',
  failed: '✕',
  stopped: '■',
}
/** A job done that left nothing: nothing kept in its copy, nothing taken in from it. */
const unchanged = (job: AwayJob) => job.state === 'done' && !job.kept.length && !job.taken.length
/** How long from one time to another (now, without it): "1 h 48 m". */
function lasted(from: string | null, to: string | null) {
  if (!from) return ''
  const minutes = Math.max(0, Math.round(((to ? Date.parse(to) : Date.now()) - Date.parse(from)) / 60000))
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} m` : `${minutes} m`
}

/**
 * ☾ Away: the Orchestrator's one line under its answer, once it put the work on To-do - "Go away now? Until 08:00 · at
 * most 2.00 USD". Go away takes this chat's new tasks with the limits it heard; Change opens the Away panel here.
 */
export function AwayOffer({ conv, offer }: { conv: ConvState; offer: Away }) {
  const [changing, setChanging] = useState(false)
  const { busy, error, ask } = useAsk()
  const backlog = useApp(s => s.backlog)
  useEffect(() => {
    if (!backlog) void useApp.getState().loadBacklog()
  }, [backlog])
  const cid = conv.conversation.id
  if (changing) return <AwayPanel conv={conv} offer={offer} onClose={() => setChanging(false)} />
  // (Only what its Orchestrator put on To-do in that turn, still open: anything else is the panel's to tick.)
  const mine = offer.jobs.filter(job =>
    backlog?.some(t => t.id === job.task_id && (t.status === 'proposed' || t.status === 'todo')),
  )
  // (Each one it sends, named - at most ten: the line wraps. None of its own: ticked in Change.)
  const named = offer.jobs.length ? mine.map(job => job.title).join(', ') : 'Tick the tasks to take in Change'
  const said = [
    named,
    offer.until && `Until ${clock(offer.until)}`,
    offer.money != null && `at most ${amount(offer.money, offer.currency)}`,
    offer.kept_out.length > 0 && `kept out ${offer.kept_out.join(', ')}`,
  ]
  const go = () =>
    void ask(() =>
      useApp.getState().goAway(cid, {
        task_ids: mine.map(job => job.task_id!),
        order: [],
        until: clock(offer.until) || null,
        money: offer.money,
        kept_out: offer.kept_out,
      }),
    )
  return (
    <div className="away-offer" role="group" aria-label="Go away now?">
      <span aria-hidden>☾</span> <b>Go away now?</b> {said.filter(Boolean).join(' · ')}
      {offer.jobs.length > 0 && (
        <button type="button" className="btn btn-small btn-primary" disabled={busy || !backlog} onClick={go}>
          Go away
        </button>
      )}
      <button type="button" className="btn btn-small" onClick={() => setChanging(true)}>
        Change
      </button>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}

/**
 * ☾ Away's summary in the chat you went away from: its span, what was done and waits in Ready, what was decided for
 * you, what waits for your word (answered here) and what it spent - the project's newest Away; else its one line.
 */
export function AwaySummary({ line, conv }: { line: string; conv: ConvState }) {
  const away = useApp(s => s.away)
  const [head, sums] = line.split(/\): /, 2)
  if (!away || away.status !== 'ended' || away.conversation_id !== conv.conversation.id || sums === undefined)
    return (
      <p className="msg msg-from away-said" role="note">
        <Moon size={13} />
        {line}
      </p>
    )
  const done = away.jobs.filter(job => job.state === 'done')
  const open = (cid: string) => void useApp.getState().openConversation(cid)
  return (
    <section className="msg msg-from away-summary" aria-label="While you were away">
      <h3 className="away-head">
        <span aria-hidden>☾</span> {head})
      </h3>
      <p className="away-sums-line">{sums}</p>
      {done.length > 0 && (
        <p className="away-line">
          <span className="away-k">done</span> {done.map(job => job.title).join(' · ')} - wait in Ready to take in
        </p>
      )}
      {away.decided.length > 0 && (
        <p className="away-line">
          <span className="away-k">decided</span> {away.decided.join(' · ')}
        </p>
      )}
      <WaitingForYou away={away} />
      <ol className="away-jobs">
        {away.jobs
          .filter(job => job.state === 'waits')
          .map(job => (
            <JobRow key={job.task_id ?? job.title} away={away} job={job} onOpen={open} />
          ))}
      </ol>
      <div className="memory-actions">
        <button type="button" className="btn btn-small btn-primary" onClick={() => useApp.getState().showReady(true)}>
          Review and take in
        </button>
        <button
          type="button"
          className="btn btn-small"
          onClick={() =>
            void useApp
              .getState()
              .openTurn(away.conversation_id, away.run_id)
              .then(() => useApp.getState().select('away:' + away.id))
          }
        >
          On the canvas
        </button>
      </div>
    </section>
  )
}

/** At the top of a night job's chat (B-150): which night it is of, and the way back to that night's report on the canvas. */
export function AwayFrom({ chat }: { chat: string }) {
  // shortcut: only the project's last night is known here - a job's chat of an older one has no link; upgrade with its night on the chat's snapshot.
  const away = useApp(s => s.away)
  if (!away?.started_at || !away.jobs.some(job => job.conversation_id === chat)) return null
  const back = () =>
    void useApp
      .getState()
      .openTurn(away.conversation_id, away.run_id)
      .then(() => useApp.getState().select('away:' + away.id))
  return (
    <button type="button" className="link-btn away-from" onClick={back}>
      <Moon size={13} /> From the jobs started at {clock(away.started_at)} while you were away — back to their report
    </button>
  )
}

/** In the top bar on every page while you're away: which To-do task of how many, until when; I'm back and Stop all. */
export function AwayStatus({ away, onOpen }: { away: Away | null; onOpen: () => void }) {
  const { busy, ask } = useAsk()
  if (!away || away.status !== 'running') return null
  const at = away.jobs.findIndex(job => job.state === 'working')
  const n = at >= 0 ? at + 1 : away.jobs.filter(job => job.state !== 'next').length
  return (
    <span className="away-status">
      <button type="button" className="away-pill" onClick={onOpen}>
        ☾ Away · To-do {n} of {away.jobs.length}
        {away.until && ` · until ${clock(away.until)}`}
      </button>
      <button
        type="button"
        className="btn btn-small"
        disabled={busy}
        onClick={() => void ask(() => useApp.getState().comeBack(away.id))}
      >
        I’m back
      </button>
      <button
        type="button"
        className="btn btn-small"
        disabled={busy}
        onClick={() => void ask(() => useApp.getState().awayDo(away.id, 'stop'))}
      >
        Stop all
      </button>
    </span>
  )
}

/** The line under a job's title, as it stands. */
const lineOf = (away: Away, job: AwayJob) =>
  job.state === 'done'
    ? [doneSaid(job), amount(job.spent, away.currency)].filter(Boolean).join(' · ')
    : job.state === 'next'
      ? 'Not started'
      : // (Live: a command it waits for was said twice - as its why, and on its Allow line.)
        job.asks.some(one => one.kind && one.text === job.why)
        ? null
        : job.why

/** One job of a night, with what you can do about it as it stands. */
export function JobRow({ away, job, onOpen }: { away: Away; job: AwayJob; onOpen: (cid: string) => void }) {
  const { busy, error, ask } = useAsk()
  const store = useApp.getState
  const chat = job.conversation_id
  const line = lineOf(away, job)
  // B-122: a job that changed nothing is not "done" as one with work to take in is.
  const word = unchanged(job) ? 'Done, nothing changed' : STATE_WORD[job.state]
  /** What you can do about it: answer what it asks, Take in, Try again, open its chat. */
  const actions = () => (
    <div className="memory-actions">
      {job.state === 'waits' &&
        job.asks
          .filter(one => one.kind)
          .map(one => (
            <span key={one.id} className="away-ask">
              <span className="mono">{one.text}</span>
              <button
                type="button"
                className="btn btn-small btn-primary"
                disabled={busy}
                onClick={() => void ask(() => store().answerAsk(one, true))}
              >
                Allow and go on
              </button>
              <button
                type="button"
                className="btn btn-small"
                disabled={busy}
                onClick={() => void ask(() => store().answerAsk(one, false))}
              >
                Refuse
              </button>
            </span>
          ))}
      {/* (One that needs the project itself waits with its copy: Take in it as it is, then do the rest there.) */}
      {(job.state === 'done' || job.state === 'waits') && job.kept.length > 0 && (
        // (Not taken - a line that clashes with the project's, say: its chat's card of the kept copy decides it.)
        <button
          type="button"
          className="btn btn-small btn-primary"
          disabled={busy}
          onClick={() => void ask(() => store().takeIn(job.kept)).then(done => done || !chat || onOpen(chat))}
        >
          Take in
        </button>
      )}
      {(job.state === 'failed' || job.state === 'stopped') && away.status === 'ended' && job.task_id && (
        <button
          type="button"
          className="btn btn-small"
          disabled={busy}
          onClick={() => void ask(() => store().awayDo(away.id, `jobs/${job.task_id}/again`))}
        >
          Try again
        </button>
      )}
      {chat && (
        <button type="button" className="btn btn-small" onClick={() => onOpen(chat)}>
          {job.state === 'done' && job.kept.length ? 'See the changes' : 'Open its chat'}
        </button>
      )}
    </div>
  )
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
          <div className="away-shared">
            Its copy changed {job.kept_out.join(', ')}, where you said not to: look before you take it in.
          </div>
        )}
        {job.shared.length > 0 && (
          <div className="away-shared">
            Another job changed {job.shared.join(', ')} too: the two are joined line by line when you take both in.
          </div>
        )}
        {actions()}
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
        {away.spent == null
          ? 'spent: not known'
          : `${away.at_least ? 'at least ' : ''}${amount(away.spent, away.currency)}`}
        {away.money != null && ` of ${amount(away.money, away.currency)}`}
      </span>
      {away.status === 'running' && (
        <button
          type="button"
          className="btn btn-small"
          disabled={busy}
          onClick={() => void ask(() => useApp.getState().awayDo(away.id, 'stop'))}
        >
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
      <WaitingForYou away={away} />
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
            ☾ {away.status === 'running' ? "While you're away" : 'While you were away'}: {done} of {away.jobs.length}{' '}
            done
          </summary>
          {night}
        </details>
      )}
    </section>
  )
}

/** The report's sums: how many jobs were done, wait, could not be done and were stopped. */
function AwaySums({ away, toTake }: { away: Away; toTake: number }) {
  return (
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
      {away.decided.length > 0 && (
        <span className="away-decided">
          <b>{away.decided.length}</b> decided for you
        </span>
      )}
    </div>
  )
}

/** The report's section for the places kept out: what tried to change them, or that nothing did. */
function KeptOut({ away }: { away: Away }) {
  return (
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
        {away.spent != null &&
          ` · ${amount(away.spent, away.currency)}${away.money != null ? ` of ${amount(away.money, away.currency)}` : ''}`}{' '}
        ·{' '}
        {someIn
          ? 'what you took in is in your project, the rest only once you take it in'
          : 'nothing of it is in your project before you take it in'}
      </div>
      {away.why && <div className="muted">{away.why}</div>}
      <AwaySums away={away} toTake={toTake} />
      {kept.length > 1 && (
        <button
          type="button"
          className="btn btn-small btn-primary nodrag"
          disabled={busy}
          onClick={() => void ask(() => useApp.getState().takeIn(kept))}
        >
          Take in all ({done.filter(job => job.kept.length).length})
        </button>
      )}
      {section('Done', done)}
      <WaitingForYou away={away} />
      {section('Waits for your word', of('waits'))}
      {section('Could not be done', of('failed'))}
      {section('Stopped', of('stopped'))}
      {section('Not started', of('next'))}
      {away.decided.length > 0 && (
        <div className="away-sec">
          <h4>Decided for you</h4>
          <ul>
            {away.decided.map((said, i) => (
              <li key={i}>{said}</li>
            ))}
          </ul>
        </div>
      )}
      {away.proposed.length > 0 && (
        <div className="away-sec">
          <h4>Proposed while you were away, not started</h4>
          {away.proposed.map(task => (
            <div key={task.id} className="away-job">
              <div className="away-grow">
                <b>{task.title}</b>
                {task.detail && <div className="muted away-line">{task.detail}</div>}
              </div>
              <button
                type="button"
                className="btn btn-small"
                disabled={busy}
                onClick={() => void ask(() => useApp.getState().decideTask(task.id, 'approve'))}
              >
                Add to To-do
              </button>
              <button
                type="button"
                className="btn btn-small"
                disabled={busy}
                onClick={() => void ask(() => useApp.getState().decideTask(task.id, 'reject'))}
              >
                Dismiss
              </button>
            </div>
          ))}
        </div>
      )}
      {away.kept_out.length > 0 && <KeptOut away={away} />}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
