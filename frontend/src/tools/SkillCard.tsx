import { CaretDown } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import type { PendingSkill, Role, Skill, SkillRecordRow } from '../api/types'
import type { RoleChange } from '../agents/RolePanel'
import { Licence, ScriptsLeave, SkillText } from '../agents/SkillApproval'
import { cannotRun, ENOUGH_JOBS, givenSaid, SkillWindow } from '../agents/SkillWindow'
import { Cell } from '../shell/Cell'
import { modelName } from '../shell/modelName'
import { RUNS_CELL } from './cells'
import { count } from './paste'

/** How many of a skill's rows of the record its card shows; every one is under it, unfolded. */
const FIRST_READS = 3

/** Where a row of the record ran, short: its model and its role. */
const ranWith = (row: SkillRecordRow) =>
  `${row.model_id ? modelName(row.model_id) : 'a model not on record'} · ${row.role_name}`

/** The last 30 days on a skill's card: each model and role it was given with, and how many of their agents read it. */
function Reads({ skill, rows }: { skill: string; rows: SkillRecordRow[] }) {
  if (rows.length === 0) return <p className="muted tools-reads">No agent had it in the last 30 days.</p>
  return (
    <div className="tools-reads" role="group" aria-label={`${skill} in the last 30 days`}>
      <span className="muted">Last 30 days</span>
      {rows.slice(0, FIRST_READS).map((row, at) => {
        const where = ranWith(row)
        return (
          // Given and never read (nor given whole in the brief): said so - its numbers say little of the skill.
          <div key={at} className={`tools-read${row.used || row.in_brief ? '' : ' tools-read-given'}`}>
            <span className="mono">{where}</span>
            {/* A bar from five jobs, as its record has it (`SkillBars`); the words always. */}
            {row.agents >= ENOUGH_JOBS ? (
              <meter className="budget-meter" aria-label={`${where}: read`} min={0} max={row.agents} value={row.used} />
            ) : (
              <span />
            )}
            <span>{givenSaid(row)}</span>
          </div>
        )
      })}
      {rows.length > FIRST_READS && (
        <span className="muted">{count(rows.length - FIRST_READS, 'more row')}: open it to see them</span>
      )}
    </div>
  )
}

interface Props {
  skill: Skill
  roles: Role[]
  /** KOLONİ's own tools and the MCP servers switched off: a skill that asks for one cannot run. */
  off: string[]
  serversOff?: string[]
  /** Its rows of the record; null while not read, or where it could not be (unfolded, its window says why). */
  rows: SkillRecordRow[] | null
  shown: boolean
  onOpen: () => void
  onSwitch: () => void
  onLeave: (on: boolean) => void
  /** Asks first (`question`, while it asks). */
  onDelete: () => void
  question: ReactNode
  onRecord: () => Promise<SkillRecordRow[]>
  onPatchRole?: (roleId: string, change: RoleChange) => Promise<void>
}

/**
 * A skill's card (0.1.10): its switch, its name, where it came from, its line and the roles it is given to (✗ where it
 * cannot run there), how it was read in the last 30 days; unfolded, what it asks, its roles, SKILL.md, its scripts'
 * leave, how it did and Delete.
 */
export function SkillCard({ skill, roles, off, serversOff, rows, shown, question, ...on }: Props) {
  const given = roles.filter(role => role.skills.includes(skill.name))
  return (
    <li className={`tools-skill${shown ? ' tools-open' : ''}`}>
      <div className="tools-row">
        <input
          type="checkbox"
          role="switch"
          className="switch"
          aria-label={`${skill.name} on`}
          checked={skill.enabled}
          onChange={on.onSwitch}
        />
        <button
          id={`tools-skill-${skill.id}`}
          type="button"
          className="tools-row-open"
          aria-expanded={shown}
          aria-controls={`tools-skill-box-${skill.id}`}
          onClick={on.onOpen}
        >
          <span className="tools-row-text">
            <span className="tools-row-name">{skill.name}</span>
            <span className="muted mono tools-command" title={skill.source}>
              from {skill.source} · {count(skill.files.length, 'file')}
            </span>
            <span className="muted tools-row-sub">{skill.description || 'It says nothing of itself.'}</span>
            {/* As the mockup: where it is given, and where it cannot run there. */}
            <span className="chips">
              {given.length === 0 ? (
                <span className="muted">no role</span>
              ) : (
                given.map(role => (
                  <span key={role.id} className="chip">
                    {cannotRun(skill, role, off, serversOff) && <span className="no">✗ </span>}
                    {role.name}
                  </span>
                ))
              )}
            </span>
          </span>
          <CaretDown size={13} aria-hidden className="tools-row-caret" />
        </button>
      </div>
      {rows && <Reads skill={skill.name} rows={rows.filter(row => row.skill === skill.name)} />}
      <div id={`tools-skill-box-${skill.id}`} className="tools-skill-box" hidden={!shown}>
        {shown && (
          <>
            <span className="muted mono tools-card-note">
              {skill.version && `v${skill.version} · `}from {skill.source} · <Licence skill={skill} />
            </span>
            <SkillWindow
              skill={skill}
              roles={roles}
              off={off}
              serversOff={serversOff}
              onRecord={on.onRecord}
              onPatchRole={on.onPatchRole}
            />
            <SkillText skill={skill} />
            <ScriptsLeave
              id={`skill-leave-${skill.id}`}
              skill={skill}
              checked={skill.scripts_run_unasked}
              onChange={on.onLeave}
            />
            <div>
              <button type="button" className="btn btn-small btn-danger" onClick={on.onDelete}>
                Delete skill {skill.name}
              </button>
            </div>
            {question}
          </>
        )}
      </div>
    </li>
  )
}

/**
 * The skills agents proposed, each waiting for your word (0.1.10). Its yes is on its own card on Ready for you, which
 * shows its whole text and its scripts' leave first: not here.
 */
export function Proposals({ proposals, onReady }: { proposals: PendingSkill[]; onReady?: () => void }) {
  if (proposals.length === 0) return null
  return (
    <section className="tools-proposed" aria-labelledby="tools-proposed-head">
      <h3 id="tools-proposed-head" className="kicker">
        Proposed by agents
      </h3>
      <ul className="tools-skills">
        {proposals.map(skill => (
          <li key={skill.tool_call_id} className="tools-skill tools-proposal">
            <span className="tools-row-name">
              <Cell {...RUNS_CELL.ask} label="waits for your word" hidden />
              {skill.name} <span className="tag tag-accent">waits for your word</span>
            </span>
            <span className="muted tools-row-sub">{skill.description || 'It says nothing of itself.'}</span>
            <span className="muted provider-note">
              {skill.roles.length > 0 ? `For ${skill.roles.join(', ')}.` : 'For no role yet.'} It is added only once you
              say yes on its card, which shows its whole text and its scripts first.
            </span>
            {onReady && (
              <span>
                <button type="button" className="btn btn-small btn-primary" onClick={onReady}>
                  Open on Ready for you
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
