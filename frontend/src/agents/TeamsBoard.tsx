import { ArrowDown, ArrowUp, X } from '@phosphor-icons/react'
import { type CSSProperties, type DragEvent, Fragment, useState } from 'react'
import type { Category, Provider, Recipe, Role, RoleModel, RolesActivity, Team } from '../api/types'
import { cannotOf, draggedRole, FROM_LIBRARY, kindColour, kindName, lastLine, ruleText } from './chart'
import { Avatar } from './RoleLibrary'
import type { PanelTab, RoleChange } from './RolePanel'
import { AddRole } from './roleParts'
import { ORCHESTRATOR } from './agentStatus'
import { teamColours } from './teamRun'

export interface TeamChange {
  name?: string
  lead_on?: boolean
  lead_may_pick?: boolean
  /** The recipe it runs by where a chat picks none (slice 84a); null: none. */
  default_recipe_id?: string | null
}
export interface StageChange {
  name?: string
  together?: boolean
}
/** What changes a team, its stages and who sits in which (the store's methods, by their names). Each throws ApiError. */
export interface TeamActions {
  createTeam: (name: string) => Promise<void>
  changeTeam: (teamId: string, change: TeamChange) => Promise<void>
  deleteTeam: (teamId: string) => Promise<void>
  addStage: (teamId: string, name: string) => Promise<void>
  changeStage: (teamId: string, stageId: string, change: StageChange) => Promise<void>
  orderStages: (teamId: string, order: string[]) => Promise<void>
  deleteStage: (teamId: string, stageId: string) => Promise<void>
  placeRole: (teamId: string, roleId: string, stageId: string) => Promise<void>
}

/** When a team's lead runs it (app/agent.py `_rows`): only beside another team in a chat. */
const LEAD_WHEN = 'Steps in only when this team works beside another team; else the Orchestrator runs it.'
/** The team open, as this browser remembers it (slice 63b): one at a time. */
const OPEN_KEY = 'koloni-agents-team'
const remembered = () => {
  try {
    return localStorage.getItem(OPEN_KEY)
  } catch {
    return null
  }
}
const remember = (teamId: string | null) => {
  try {
    if (teamId) localStorage.setItem(OPEN_KEY, teamId)
    else localStorage.removeItem(OPEN_KEY)
  } catch {
    // (Not kept: it is open for this visit.)
  }
}

/** A name typed in place: Enter saves, Esc puts it away. */
export function NameForm({ label, value = '', button, max, onSave, onCancel }: { label: string; value?: string; button: string; max: number; onSave: (name: string) => void; onCancel: () => void }) {
  const [name, setName] = useState(value)
  return (
    <form
      className="agents-new-team"
      onSubmit={e => {
        e.preventDefault()
        onSave(name.trim())
      }}
    >
      <input className="input" aria-label={label} maxLength={max} autoFocus value={name} onChange={e => setName(e.target.value)} onKeyDown={e => e.key === 'Escape' && onCancel()} />
      <button type="submit" className="btn btn-small" disabled={!name.trim()}>
        {button}
      </button>
    </form>
  )
}

interface RowProps {
  team: Team
  /** K-bilgi: the open project - a role's "knows:" chip is of its knowledge there (or every project's). */
  projectId?: string | null
  /** Its colour among the teams shown (`teamColours`). */
  colour: string
  /** The roles a stage may hold (not the Lead's, not a lead's). */
  roles: Role[]
  categories: Category[]
  /** KOLONİ's recipes, one of which may be the team's default. */
  recipes: Recipe[]
  selected: string | null
  /** The role open beside: the teams it is in are marked, the others faded. */
  marked: Role | null
  /** A role being dragged from the library or a stage: where it would land is said. */
  dragging: Role | null
  open: boolean
  onToggle: () => void
  /** A role opened beside, on one of its panel's tabs. */
  onOpen: (roleId: string, tab?: PanelTab) => void
  onPatch: (roleId: string, change: RoleChange) => Promise<void>
  actions?: TeamActions
  act: (work: Promise<void> | undefined) => void
  say: (words: string) => void
  /** "New role…" from a stage: made beside, then put in that stage. */
  onNewRole: (teamId: string, stageId: string) => void
  /** Who uses what, by role name: what stands in a stage's roles' way is marked on it. */
  models?: Record<string, RoleModel>
  /** The providers set up: a lead with a model of its own is said by its provider's name. */
  providers?: Provider[]
}

const LEAD_PARTS: [string, PanelTab][] = [
  ['Instructions', 'Instructions'],
  ['Model', 'Overview'],
  ['Tools', 'Tools'],
]

/** A team (slice 63b): one line folded - its stages, faces, default recipe, lead; open, its lead, stages side by side and foot. */
function TeamRow({ team, projectId = null, colour, roles, categories, recipes, selected, marked, dragging, open, onToggle, onOpen, onPatch, actions, act, say, onNewRole, models, providers = [] }: RowProps) {
  const [edit, setEdit] = useState<'rename' | 'delete' | 'stage' | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const byId = new Map(roles.map(role => [role.id, role]))
  const stageOf = (roleId: string) => team.stages.find(stage => stage.roles.includes(roleId))
  const members = team.stages.flatMap(stage => stage.roles.flatMap(id => byId.get(id) ?? []))
  const lead = team.lead
  const recipe = recipes.find(one => one.id === team.default_recipe_id)
  // (By a recipe of its own its stages' roles are its steps' agents.)
  const cannot = (role: Role) => cannotOf(models?.[role.name], ...(recipe ? (['step'] as const) : []))
  const stageCannot = (stage: Team['stages'][number]) =>
    stage.roles.flatMap(id => byId.get(id) ?? []).flatMap(role => cannot(role).map(line => `${role.name}: ${line}`))
  const hit = marked !== null && members.some(role => role.id === marked.id)
  const place = (role: Role, stage: Team['stages'][number]) => {
    const was = stageOf(role.id)
    act(actions?.placeRole(team.id, role.id, stage.id).then(() => say(`${role.name} is in ${stage.name} now${was ? `, not ${was.name}` : ''}.`)))
  }
  const takeOut = (role: Role) => act(onPatch(role.id, { teams: role.teams.filter(id => id !== team.id) }).then(() => say(`${role.name} is out of ${team.name} now.`)))
  const move = (at: number, by: number) => {
    const order = team.stages.map(stage => stage.id)
    ;[order[at], order[at + by]] = [order[at + by], order[at]]
    act(actions?.orderStages(team.id, order))
  }
  const remove = (stage: Team['stages'][number]) => {
    const first = team.stages.find(one => one.id !== stage.id)
    const names = stage.roles.flatMap(id => byId.get(id)?.name ?? [])
    act(
      actions?.deleteStage(team.id, stage.id).then(() =>
        say(names.length ? `${stage.name} removed: ${names.join(', ')} ${names.length === 1 ? 'is' : 'are'} in ${first?.name} now.` : `${stage.name} removed.`),
      ),
    )
  }
  // A role dragged from the library, or from another stage of this team: put in this one.
  const drop = (stage: Team['stages'][number]) => (event: DragEvent) => {
    const [from, roleId] = draggedRole(event)
    const role = byId.get(roleId)
    if ((from !== team.id && from !== FROM_LIBRARY) || !role) return
    event.preventDefault()
    if (stageOf(role.id)?.id !== stage.id) place(role, stage)
  }
  return (
    <section className={`team-box${marked ? (hit ? ' team-box-hit' : ' team-box-dim') : ''}`} aria-label={team.name} style={{ '--c': colour } as CSSProperties}>
      <div className="team-head">
        <button type="button" className="team-toggle" aria-expanded={open} onClick={onToggle}>
          <span className="team-chev" aria-hidden="true">
            {open ? '▾' : '▸'}
          </span>
          <span className="team-name">{team.name}</span>
          <span className="team-flow">
            {team.stages.map((stage, at) => (
              <Fragment key={stage.id}>
                {at > 0 && (
                  <span className="team-arr" aria-hidden="true">
                    →
                  </span>
                )}
                <span className="team-st">
                  {stage.roles.length ? (
                    <>
                      <b>{stage.name}</b> {stage.roles.length}
                    </>
                  ) : (
                    stage.name
                  )}
                  {marked && stage.roles.includes(marked.id) && <b className="team-st-hit"> · {marked.name}</b>}
                  {/* (Said in full on the role in the stage, open: here a mark and its tooltip.) */}
                  {stageCannot(stage).length > 0 && (
                    <span className="team-st-warn" title={stageCannot(stage).join('\n')} aria-hidden="true">
                      {' '}
                      ⚠
                    </span>
                  )}
                </span>
              </Fragment>
            ))}
          </span>
          <span className="team-faces" aria-hidden="true">
            {members.slice(0, 5).map(role => (
              <Avatar key={role.id} name={role.name} colour={kindColour(categories, role.kind)} />
            ))}
            {members.length > 5 && <span className="role-av role-av-more">+{members.length - 5}</span>}
          </span>
          <span className={`team-pill${recipe ? '' : ' team-pill-none'}`}>{recipe?.name ?? 'no recipe'}</span>
        </button>
        <label className="team-leadmark">
          <input type="checkbox" role="switch" className="model-agents" aria-label={`${lead.name} on`} checked={team.lead_on} onChange={e => act(actions?.changeTeam(team.id, { lead_on: e.target.checked }))} />
          {team.lead_on ? 'lead' : 'lead off'}
        </label>
      </div>
      {open && (
        <div className="team-open">
          <div className={`team-lead-row${team.lead_on ? '' : ' team-lead-off'}${selected === lead.id ? ' team-lead-chosen' : ''}`}>
            <Avatar name={team.name} colour={colour} />
            <span className="team-lead-what">
              <button type="button" className="team-lead-name" aria-current={selected === lead.id || undefined} onClick={() => onOpen(lead.id)}>
                {lead.name}
              </button>
              <span className="muted">— shown as {team.name} coordinator</span>
              <span className="muted">{team.lead_on ? ruleText(lead, providers) : `Off: the Orchestrator always runs ${team.name} itself`}</span>
            </span>
            {team.lead_on && <span className="muted team-lead-when">{LEAD_WHEN}</span>}
            <span className="team-lead-links">
              {LEAD_PARTS.map(([title, tab]) => (
                <button key={title} type="button" className="link-btn" aria-label={`${lead.name}: ${title}`} onClick={() => onOpen(lead.id, tab)}>
                  {title}
                </button>
              ))}
            </span>
          </div>
          <div className="team-lanes">
            {team.stages.map((stage, at) => {
              const here = stage.roles.flatMap(id => byId.get(id) ?? [])
              return (
                <section key={stage.id} className="team-stage" aria-label={`Stage ${at + 1}, ${stage.name}`} onDragOver={e => e.preventDefault()} onDrop={drop(stage)}>
                  {/* The heading is the stage's number and name alone; what changes it stands beside it. */}
                  <div className="team-stage-head">
                    {renaming === stage.id ? (
                      <NameForm label="Stage’s new name" value={stage.name} button="Rename" max={60} onSave={name => act(actions?.changeStage(team.id, stage.id, { name }).then(() => setRenaming(null)))} onCancel={() => setRenaming(null)} />
                    ) : (
                      <h4>
                        <span className="team-stage-n" aria-hidden="true">
                          {at + 1}
                        </span>
                        <button type="button" className="team-stage-name" title="Click to rename" aria-label={`Rename stage ${stage.name}`} onClick={() => setRenaming(stage.id)}>
                          {stage.name}
                        </button>
                      </h4>
                    )}
                    {/* shortcut: a stage moves by these buttons, not by drag as the design draws it; add a drag if they are slow with many stages. */}
                    <span className="team-stage-tools">
                      <button type="button" className="icon-btn" aria-label={`Move ${stage.name} up`} disabled={at === 0} onClick={() => move(at, -1)}>
                        <ArrowUp size={12} />
                      </button>
                      <button type="button" className="icon-btn" aria-label={`Move ${stage.name} down`} disabled={at === team.stages.length - 1} onClick={() => move(at, 1)}>
                        <ArrowDown size={12} />
                      </button>
                      {/* The server keeps a team with one stage at least: the last one stays. */}
                      <button type="button" className="icon-btn" aria-label={`Remove stage ${stage.name}`} disabled={team.stages.length === 1} onClick={() => remove(stage)}>
                        <X size={12} />
                      </button>
                    </span>
                    <label className="team-stage-together">
                      <input type="checkbox" aria-label={`${stage.name}: all at once`} checked={stage.together} onChange={e => act(actions?.changeStage(team.id, stage.id, { together: e.target.checked }))} />
                      all at once
                    </label>
                  </div>
                  {here.map(role => (
                    <div key={role.id} className={`team-mini${role.enabled ? '' : ' team-mini-off'}${marked?.id === role.id ? ' team-mini-hit' : ''}`} draggable onDragStart={e => e.dataTransfer.setData('text/plain', `${team.id} ${role.id}`)}>
                      <Avatar name={role.name} colour={kindColour(categories, role.kind)} />
                      <button type="button" className="team-mini-open" title={role.name} aria-current={selected === role.id || undefined} onClick={() => onOpen(role.id)}>
                        {role.name}
                      </button>
                      {/* K-uzman: an expert is a member as any role is; what it knows is said beside it. */}
                      {(role.knows ?? []).filter(one => one.mode === 'full' && (one.project_id === null || one.project_id === projectId)).map(one => one.topic).filter((topic, at, all) => all.indexOf(topic) === at).map(topic => (
                        <span key={topic} className="chip-knows" title="advises · reads only">
                          knows: {topic}
                        </span>
                      ))}
                      {cannot(role).length > 0 && (
                        <span className="team-st-warn" role="img" aria-label={cannot(role).join(' ')} title={cannot(role).join('\n')}>
                          ⚠
                        </span>
                      )}
                      <button type="button" className="chip-x" aria-label={`Take ${role.name} out of ${team.name}`} onClick={() => takeOut(role)}>
                        <X size={10} />
                      </button>
                    </div>
                  ))}
                  {dragging && !stage.roles.includes(dragging.id) ? (
                    <p className="team-drop">
                      Drop: {dragging.name} joins {stage.name}
                    </p>
                  ) : (
                    here.length === 0 && <p className="muted team-empty">No role yet: drop one here, or add one</p>
                  )}
                  {/* shortcut: one role a pick, not the design's tick boxes. Add ticks if teams are filled many roles at a time. */}
                  <AddRole title={`${team.name}, ${stage.name}`} label="+ Add a role" others={roles.filter(role => !stage.roles.includes(role.id))} kindOf={role => kindName(categories, role.kind)} onPick={role => (role ? place(role, stage) : onNewRole(team.id, stage.id))} />
                </section>
              )
            })}
            {edit === 'stage' ? (
              <NameForm label="New stage’s name" button="Add stage" max={60} onSave={name => act(actions?.addStage(team.id, name).then(() => setEdit(null)))} onCancel={() => setEdit(null)} />
            ) : (
              <button type="button" className="agents-add team-add-stage" onClick={() => setEdit('stage')}>
                + Add a stage
              </button>
            )}
          </div>
          {/* shortcut: no budget in it, as the design draws: a team has none to show; add it here when teams get one. */}
          <div className="team-foot muted">
            <label>
              Default recipe
              <select className="chip" aria-label={`${team.name}'s default recipe`} value={team.default_recipe_id ?? ''} onChange={e => act(actions?.changeTeam(team.id, { default_recipe_id: e.target.value || null }))}>
                <option value="">none</option>
                {recipes.map(one => (
                  <option key={one.id} value={one.id}>
                    {one.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <input type="checkbox" aria-label={`The Orchestrator may pick ${team.name}`} checked={team.lead_may_pick} onChange={e => act(actions?.changeTeam(team.id, { lead_may_pick: e.target.checked }))} />
              <span>The Orchestrator may pick it</span>
            </label>
            {edit === 'rename' ? (
              <NameForm label="Team’s new name" value={team.name} button="Rename team" max={55} onSave={name => act(actions?.changeTeam(team.id, { name }).then(() => setEdit(null)))} onCancel={() => setEdit(null)} />
            ) : edit === 'delete' ? (
              <span className="team-foot-ask">
                Delete {team.name}? Its roles stay and its lead goes; its conversations will use every team.
                <button type="button" className="btn btn-small btn-danger" onClick={() => act(actions?.deleteTeam(team.id))}>
                  Delete team
                </button>
                <button type="button" className="btn btn-small" onClick={() => setEdit(null)}>
                  Cancel
                </button>
              </span>
            ) : (
              <>
                <button type="button" className="link-btn" aria-label={`Rename ${team.name}`} onClick={() => setEdit('rename')}>
                  Rename
                </button>
                <button type="button" className="link-btn team-foot-delete" aria-label={`Delete ${team.name}`} onClick={() => setEdit('delete')}>
                  Delete team
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

interface Props extends Omit<RowProps, 'team' | 'colour' | 'open' | 'onToggle'> {
  lead: Role | undefined
  teams: Team[]
  activity: RolesActivity | null
}

/** The teams (slice 63b): the Lead's strip on top, then each team a folded row; one opened at a time, as the browser remembers. */
export function TeamsBoard({ lead, teams, activity, ...row }: Props) {
  const [open, setOpen] = useState<string | null>(remembered)
  const toggle = (teamId: string) => {
    const next = open === teamId ? null : teamId
    setOpen(next)
    remember(next)
  }
  const { marked } = row
  const hits = marked ? teams.filter(team => team.stages.some(stage => stage.roles.includes(marked.id))).length : 0
  const colours = teamColours(teams.map(team => team.id))
  return (
    <div className="teams-board">
      {lead && (
        <div className={`lead-strip${row.selected === lead.id ? ' lead-strip-chosen' : ''}`}>
          <Avatar name="Lead" colour="var(--accent-fill)" />
          <span className="lead-strip-what">
            <b>Lead</b> <span className="muted">— shown as {ORCHESTRATOR}</span>
            {(activity?.running[lead.name] ?? 0) > 0 && <span className="role-card-now">now</span>}
            <span className="muted">
              {' '}
              · {lead.description}
              {activity && ` · ${lastLine(lead, activity.last[lead.name])}`}
            </span>
          </span>
          <button type="button" className="btn btn-small" aria-label="Open the Lead" aria-current={row.selected === lead.id || undefined} onClick={() => row.onOpen(lead.id)}>
            Open
          </button>
        </div>
      )}
      <p className="muted teams-note">
        {marked
          ? `${marked.name} is in ${hits} of ${teams.length} teams · the others are faded while it is open`
          : `${teams.length === 1 ? '1 team' : `${teams.length} teams`} · one open at a time · drag a role from the left into a stage`}
      </p>
      {teams.map(team => (
        <TeamRow key={team.id} team={team} colour={colours.get(team.id)!} open={team.id === open} onToggle={() => toggle(team.id)} {...row} />
      ))}
      <p className="agents-legend muted">
        A stage’s name and order are the team’s own; a role sits in one stage of a team, and may be in several teams. A chat’s team runs by
        the recipe picked for it, else by its default recipe; with none, the Orchestrator may open any of its roles. A default recipe is one of
        KOLONİ’s, not a folder’s own: a team is every folder’s.
      </p>
    </div>
  )
}
