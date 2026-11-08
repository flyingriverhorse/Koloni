import { useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Role, Skill, SkillRecordRow } from '../api/types'
import { modelName } from '../shell/modelName'
import { money } from '../usage/cost'
import type { RoleChange } from './RolePanel'

/** A row of the record says how its models did only from this many jobs (app/record.py SCORED_FROM). */
export const ENOUGH_JOBS = 5

/**
 * What a role lacks of what a skill's `allowed-tools` asks (app/skills.py `lacking`): a group none of whose tools it
 * has on - one switched off on the Tools page is not had - and an MCP server it is not given, or one switched off
 * (`serversOff`, as skills_mixin `_skill_split` has it).
 */
export function lacking(skill: Skill, role: Pick<Role, 'tools' | 'mcp'>, off: string[], serversOff: string[] = []): string[] {
  const has = (tool: string) => role.tools.includes(tool) && !off.includes(tool)
  return [
    ...skill.needs.groups.filter(group => !skill.needs.tools[group]?.some(has)),
    ...skill.needs.mcp.filter(server => !role.mcp.includes(server) || serversOff.includes(server)).map(server => `MCP server ${server}`),
  ]
}

/**
 * Why a skill is not given to a role's agents, in the words the server keeps on the agent (app/skills.py `split`);
 * null: it can be.
 * shortcut: a model that makes no tool calls is said on the spawn card only (the role's model is known when its agent
 * starts); say it here too if a role is seen with such a model of its own.
 */
export function cannotRun(skill: Skill, role: Pick<Role, 'tools' | 'mcp'>, off: string[], serversOff: string[] = []): string | null {
  if (!skill.enabled) return 'off on the Tools page'
  const missing = lacking(skill, role, off, serversOff)
  return missing.length > 0 ? `no ${missing.join(', no ')}` : null
}

const MEASURES = ['Taken in', 'Cost', 'Steps'] as const
type Measure = (typeof MEASURES)[number]

/** How the models did with a skill, a bar a row - jobs taken in, middle cost or steps - from five jobs on; data, no judgment. */
export function SkillBars({ rows }: { rows: SkillRecordRow[] }) {
  const [measure, setMeasure] = useState<Measure>('Taken in')
  if (rows.length === 0) return <p className="muted provider-note">No agent had it in the last 30 days.</p>
  const of = (row: SkillRecordRow) => (measure === 'Cost' ? (row.cost?.amount ?? null) : row.steps)
  const most = Math.max(0, ...rows.filter(row => row.agents >= ENOUGH_JOBS).map(row => of(row) ?? 0))
  return (
    <div className="skill-bars">
      <div className="skill-measures" role="group" aria-label="What the bars show">
        {MEASURES.map(one => (
          <button key={one} type="button" className="btn btn-small" aria-pressed={measure === one} onClick={() => setMeasure(one)}>
            {one}
          </button>
        ))}
      </div>
      {rows.map(row => {
        const where = `${row.provider_name ?? 'a provider not on record'} · ${row.model_id ? modelName(row.model_id) : 'a model not on record'} · ${row.role_name}`
        const value = measure === 'Taken in' ? row.taken_in : of(row)
        const said = measure === 'Taken in' ? `${row.taken_in}/${row.agents}` : measure === 'Cost' ? money(row.cost) : row.steps === null ? '–' : `${Math.round(row.steps)} steps`
        const enough = row.agents >= ENOUGH_JOBS
        return (
          // Given and never read (nor given whole in the brief, R190): greyer - its numbers say little of the skill.
          <div key={where} className={`skill-bar${row.used || row.in_brief ? '' : ' skill-bar-given'}`}>
            <span className="mono">{where}</span>
            {enough && value !== null ? (
              <meter className="budget-meter" aria-label={`${where}: ${measure.toLowerCase()}`} min={0} max={(measure === 'Taken in' ? row.agents : most) || 1} value={value} />
            ) : (
              <span />
            )}
            <span className="mono">{enough ? said : '< 5 jobs'}</span>
            <span className="muted">
              {[row.used && `read in ${row.used} of ${row.agents}`, row.in_brief && `given in full in its brief in ${row.in_brief} of ${row.agents}`].filter(Boolean).join(' · ') || 'given, not read'}
            </span>
          </div>
        )
      })}
      <p className="muted provider-note">30 days · Data, not an instruction.</p>
    </div>
  )
}

interface Props {
  skill: Skill
  /** Every role: where it is given, each with its box. */
  roles: Role[]
  /** KOLONİ's own tools, and the MCP servers, switched off on the Tools page. */
  off: string[]
  serversOff?: string[]
  /** Throws ApiError. */
  onRecord?: () => Promise<SkillRecordRow[]>
  /** Gives or takes it, or a group of tools it asks for, on a role. Throws ApiError. */
  onPatchRole?: (roleId: string, change: RoleChange) => Promise<void>
}

/** A skill unfolded under its row on the Tools page: what it is, what it asks, which roles have it, how it did. */
export function SkillWindow({ skill, roles, off, serversOff, onRecord, onPatchRole }: Props) {
  const [rows, setRows] = useState<SkillRecordRow[] | string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let latest = true
    onRecord?.().then(
      read => latest && setRows(read.filter(row => row.skill === skill.name)),
      err => latest && setRows(errorText(err)),
    )
    return () => {
      latest = false
    }
  }, [onRecord, skill.name])
  const patch = (role: Role, change: RoleChange) => {
    setError(null)
    onPatchRole?.(role.id, change).catch(err => setError(errorText(err)))
  }
  const asked = [...skill.needs.groups, ...skill.needs.mcp.map(server => `MCP server ${server}`)]
  return (
    <div className="skill-window" role="group" aria-label={`Skill ${skill.name}`}>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <dl className="seen-list">
        <dt>What</dt>
        <dd>{skill.description || <span className="muted">It says nothing of itself.</span>}</dd>
        {/* With no allowed-tools nothing is said: it may run anywhere, or not - its record shows. */}
        {asked.length + skill.needs.unknown.length > 0 && (
          <>
            <dt>Asks for</dt>
            <dd className="chips">
              {asked.map(one => (
                <span key={one} className="chip">
                  {one}
                </span>
              ))}
              {skill.needs.unknown.map(one => (
                <span key={one} className="chip mono" title="Not one of KOLONİ’s tools: it keeps the skill from no role">
                  {one} (unknown)
                </span>
              ))}
            </dd>
          </>
        )}
        <dt>Roles that may use it</dt>
        <dd className="skill-roles">
          {/* (Not the Observer: no agent is opened in it, so it has no skills, as its panel shows none.) */}
          {roles
            .filter(role => !(role.builtin && role.name === 'Observer'))
            .map(role => {
            // As the role's tile had it (K-skill-uyum): one it cannot run there is not given, and says why.
            const not = cannotRun(skill, role, off, serversOff)
            const has = role.skills.includes(skill.name)
            const missing = lacking(skill, role, off, serversOff)
            return (
              <span key={role.id} className="skill-role">
                <label className="choice">
                  <input
                    type="checkbox"
                    checked={has}
                    disabled={!onPatchRole || (!!not && !has)}
                    onChange={() => patch(role, { skills: has ? role.skills.filter(name => name !== skill.name) : [...role.skills, skill.name] })}
                  />
                  <span>
                    {not ? <span className="no">✗</span> : has && <span className="ok">✓</span>} {role.name}
                    {not && <span className="muted"> ({not})</span>}
                  </span>
                </label>
                {onPatchRole &&
                  skill.enabled &&
                  skill.needs.groups
                    .filter(group => missing.includes(group))
                    .map(group => (
                      <button
                        key={group}
                        type="button"
                        className="btn btn-small"
                        onClick={() => patch(role, { tools: [...role.tools, ...skill.needs.tools[group].filter(tool => !role.tools.includes(tool))] })}
                      >
                        Give {role.name} {group}
                      </button>
                    ))}
              </span>
            )
          })}
        </dd>
        <dt>Did lately</dt>
        <dd>{typeof rows === 'string' ? <span className="muted">The record could not be read: {rows}</span> : rows && <SkillBars rows={rows} />}</dd>
      </dl>
    </div>
  )
}
