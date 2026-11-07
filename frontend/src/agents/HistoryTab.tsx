import { type ReactNode, useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { RolesHistory } from '../api/types'
import { modelName } from '../shell/modelName'

type Count = RolesHistory['roles'][number]
type Job = RolesHistory['jobs'][number]
/** How a job ended, in the boxes' three colours (decision 2): the record's word, said plainly. */
const ENDED: Record<string, [string, string]> = {
  completed: ['done', 'tag-ok'],
  failed: ['failed', 'tag-del'],
  cancelled: ['stopped', 'tag-del'],
  interrupted: ['interrupted', 'tag-del'],
}
const total = (one: Count) => one.done + one.failed + one.running

/** Done of those that ended, as a whole per cent; null where none has ended. */
function donePart(rows: Count[]) {
  const done = rows.reduce((n, one) => n + one.done, 0)
  const ended = done + rows.reduce((n, one) => n + one.failed, 0)
  return ended ? Math.round((done / ended) * 100) : null
}

/** One box (Roles, Teams or Recipes): a bar each, as long as its count beside the box's most, split by how they ended. */
function Bars({ title, unit, rows, foot }: { title: string; unit: string; rows: Count[]; foot?: string }) {
  const most = Math.max(1, ...rows.map(total))
  return (
    <section className="history-box" aria-label={title}>
      <h3>
        {title} <span className="muted">· {unit}, and how they ended</span>
      </h3>
      {rows.length === 0 && <p className="muted">None in this period.</p>}
      {rows.map(one => {
        const part = donePart([one])
        return (
          <div key={one.name} className="history-row">
            <span className="history-name">{one.name}</span>
            <span className="history-bar" aria-hidden="true">
              {(['done', 'failed', 'running'] as const).map(end => one[end] > 0 && <i key={end} className={`history-${end}`} style={{ width: `${(one[end] / most) * 100}%` }} />)}
            </span>
            <span className="muted history-n">
              {total(one)}
              {part !== null && ` · ${part}%`}
              <span className="visually-hidden">
                : {one.done} done, {one.failed} failed or stopped, {one.running} in progress
              </span>
            </span>
          </div>
        )
      })}
      {foot && <p className="muted history-foot">{foot}</p>}
    </section>
  )
}

interface Props {
  /** The record of these days (`/roles/history`). Throws ApiError. */
  onHistory?: (days: number) => Promise<RolesHistory>
  onOpenConversation?: (conversationId: string) => void
  /** A role's own record, model by model (its last 30 days), shown while the list is of that role. */
  recordOf: (role: string) => ReactNode
}

/**
 * 0.1.0-ui: the Agents page's History - what the roles, teams and recipes did, from the record as it is: totals, a box
 * each with how their work ended, and the jobs, filtered; a job opens its chat. A turn's own Lead is no role's job.
 */
export function HistoryTab({ onHistory, onOpenConversation, recordOf }: Props) {
  const [days, setDays] = useState(30)
  const [read, setRead] = useState<RolesHistory | string | null>(null)
  const [role, setRole] = useState('')
  const [team, setTeam] = useState('')
  const [recipe, setRecipe] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let latest = true
    onHistory?.(days).then(
      got => latest && setRead(got),
      err => latest && setRead(errorText(err)),
    )
    return () => {
      latest = false
    }
  }, [onHistory, days])
  const history = typeof read === 'object' ? read : null
  const jobs = (history?.jobs ?? []).filter(
    (job: Job) =>
      (!role || job.role_name === role) &&
      (!team || job.teams.includes(team)) &&
      (!recipe || job.recipes.includes(recipe)) &&
      (!failed || (job.status in ENDED && job.status !== 'completed')),
  )
  const filters: [string, string, string, (v: string) => void, Count[]][] = history
    ? [
        ['Role', 'Every role', role, setRole, history.roles],
        ['Team', 'Every team', team, setTeam, history.teams],
        ['Recipe', 'Every recipe', recipe, setRecipe, history.recipes],
      ]
    : []
  return (
    <div className="history">
      <div className="history-head">
        <label htmlFor="history-days" className="muted">
          Period
        </label>
        <select id="history-days" className="input" value={days} onChange={e => setDays(Number(e.target.value))}>
          <option value={30}>Last 30 days</option>
          <option value={7}>Last 7 days</option>
        </select>
      </div>
      {typeof read === 'string' && (
        <p role="alert" className="alert">
          The history could not be read: {read}
        </p>
      )}
      {read === null && <p className="muted">Reading the record…</p>}
      {history && (
        <>
          <div className="history-stats">
            {(
              [
                [history.roles.reduce((n, one) => n + total(one), 0), 'agents opened'],
                [donePart(history.roles) === null ? '–' : `${donePart(history.roles)}%`, 'ended done'],
                [history.teams.reduce((n, one) => n + total(one), 0), 'team runs'],
                [history.recipes.reduce((n, one) => n + total(one), 0), 'recipe runs'],
              ] as const
            ).map(([n, label]) => (
              <div key={label} className="history-stat">
                <b>{n}</b>
                <span className="muted">{label}</span>
              </div>
            ))}
          </div>
          <div className="history-boxes">
            <Bars title="Roles" unit="jobs" rows={history.roles} foot={`${history.lead_turns} ${history.lead_turns === 1 ? 'turn' : 'turns'} led by the Orchestrator`} />
            <Bars title="Teams" unit="runs" rows={history.teams} />
            <Bars title="Recipes" unit="runs" rows={history.recipes} />
          </div>
          <p className="muted history-key" aria-hidden="true">
            <i className="history-done" /> done <i className="history-failed" /> failed or stopped <i className="history-running" /> in progress
          </p>
          <section className="history-box history-jobs" aria-label="Jobs">
            <div className="history-filters">
              {filters.map(([label, every, value, change, rows]) => (
                <select key={label} className="input" aria-label={label} value={value} onChange={e => change(e.target.value)}>
                  <option value="">{every}</option>
                  {rows.map(one => (
                    <option key={one.name} value={one.name}>
                      {one.name}
                    </option>
                  ))}
                </select>
              ))}
              <label className="choice">
                <input type="checkbox" checked={failed} onChange={e => setFailed(e.target.checked)} />
                Failed only
              </label>
            </div>
            {jobs.length === 0 ? (
              <p className="muted">No job like that in this period.</p>
            ) : (
              <div className="tools-table">
                <table className="usage-table">
                  <thead>
                    <tr>
                      <th scope="col">When</th>
                      <th scope="col">Role</th>
                      <th scope="col">Chat</th>
                      <th scope="col">Model</th>
                      <th scope="col">Ended</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map(job => {
                      const [word, tag] = ENDED[job.status] ?? ['in progress', '']
                      return (
                        <tr key={job.id}>
                          <td className="muted">{new Date(job.created_at).toLocaleString()}</td>
                          <td>{job.role_name}</td>
                          <td>
                            {onOpenConversation ? (
                              <button type="button" className="link-btn" onClick={() => onOpenConversation(job.conversation_id)}>
                                {job.conversation_title}
                              </button>
                            ) : (
                              job.conversation_title
                            )}
                          </td>
                          <td className="mono">{job.model_id ? modelName(job.model_id) : (job.provider_name ?? 'unknown')}</td>
                          <td>
                            <span className={`tag ${tag}`}>{word}</span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {/* shortcut: the newest jobs_limit jobs of the period are listed (the boxes count them all); page them if more are wanted. */}
            {history.jobs.length === history.jobs_limit && <p className="muted">The newest {history.jobs_limit} jobs of the period.</p>}
          </section>
          {role && recordOf(role)}
        </>
      )}
    </div>
  )
}
