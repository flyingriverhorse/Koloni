import { ArrowDown, ArrowUp, CaretDown, UsersThree, X } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Agent, ChatTeam, ChatTeamIn, Conversation, Project, Provider, Recipe, Role, RoleModel, Run, Team, TeamsMode } from '../api/types'
import { useConfirm } from '../shell/Confirm'
import { usePanel } from '../shell/usePanel'
import { cannotOf } from './chart'
import { stepRoles } from './recipeGraph'
import { chatColours, rowTokens, tokensLine } from './teamRun'

/** A change to a chat's teams: who picks them, and the user's rows (only with Manual). */
export interface TeamsChange {
  teams_mode?: TeamsMode
  teams?: ChatTeamIn[]
}

interface Props {
  conversation: Conversation
  /** The chat's agents, for what each team's reported it used (slice 84b-2). */
  agents: Agent[]
  /** The chat's turns: their teams' colours are the canvas's (B-103). */
  runs?: Run[]
  /** Stop one team's agents (slice 84b-2); the others go on. */
  onStop: (teamId: string) => Promise<void>
  /** Finish now on a team's looped recipe (batch-17): its work to Ready for you with what was found so far. */
  onFinish: (teamId: string) => Promise<void>
  /** Every team there is. */
  teams: Team[]
  /** KOLONİ's recipes, read as the window opens. shortcut: a folder's own are not offered (a row keeps KOLONİ's only, app/db/models.py ConversationTeam); add them with the server's. */
  onRecipes: () => Promise<Recipe[]>
  onChange: (change: TeamsChange) => Promise<void>
  /** The chat's folder: its new chats' teams are saved there. Null: a plain chat. */
  project: Project | null
  onDefault: (change: Required<TeamsChange>) => Promise<void>
  /** The roles and providers there are: a recipe step's role that cannot run where it is now is offered another provider. */
  roles: Role[]
  providers: Provider[]
  /** Who uses what in this chat, read as the window opens. */
  onRoleModels: () => Promise<RoleModel[]>
  /** A role's agents put on a provider and model of the role's own: in every chat. */
  onRunOn: (roleId: string, providerId: string, modelId: string | null) => Promise<void>
}

const MODES: [mode: TeamsMode, label: string, note: string][] = [
  ['lead', 'Orchestrator decides', 'It picks the teams and a recipe for each, and says why.'],
  ['manual', 'Manual', 'You pick the teams it may use; it opens only those a message needs.'],
  ['none', 'No teams', 'As before: it calls any role itself.'],
]

const LABEL: Record<TeamsMode, string> = { lead: 'Orchestrator decides', manual: 'Manual', none: 'No teams' }

const rowsIn = (rows: ChatTeam[]): ChatTeamIn[] => rows.map(({ team_id, recipe_id, no_recipe }) => ({ team_id, recipe_id, no_recipe }))

/** The recipe select's "No recipe" (K-tarifsiz): not even the team's default, in this chat. */
const NO_RECIPE = 'none'
/** A row as its recipe select says it: '' its team's default, NO_RECIPE none, else that recipe. */
const rowOf = (team_id: string, value: string): ChatTeamIn => ({ team_id, recipe_id: value === NO_RECIPE ? null : value || null, no_recipe: value === NO_RECIPE })

/** Rows as one string, to tell whether two lists are the same, in the same order. */
const key = (rows: ChatTeamIn[]) => JSON.stringify(rows.map(row => [row.team_id, row.recipe_id ?? null, row.no_recipe]))

/**
 * "Teams for this chat" (slice 84b), over the canvas's top right: who picks the teams whose roles the Lead may open -
 * the Lead (its picks shown with why, to be changed in Manual), the user (rows of a team and its recipe), or nobody.
 * Each change is saved at once. A row its recipe ran for says where it is, what its agents reported they used, and
 * holds its Stop (slice 84b-2). shortcut: the tokens are of its recipe's last turn, not of every turn of the chat; add
 * the earlier turns' if "so far" is missed.
 */
export function ChatTeams({ conversation, agents, runs = [], onStop, onFinish, teams, onRecipes, onChange, project, onDefault, roles, providers, onRoleModels, onRunOn }: Props) {
  const { open, setOpen, close, button, panel } = usePanel()
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [models, setModels] = useState<Record<string, RoleModel>>({})
  const [error, setError] = useState<string | null>(null)
  // The team whose Stop or Finish now waits for the server's answer: one word at a time.
  const [sending, setSending] = useState<string | null>(null)
  const send = (word: (teamId: string) => Promise<void>, teamId: string) => {
    setSending(teamId)
    void word(teamId)
      .catch(err => setError(errorText(err)))
      .finally(() => setSending(null))
  }
  const mode = conversation.teams_mode
  const rows = conversation.teams
  const teamOf = (id: string) => teams.find(team => team.id === id)
  const recipeName = (id: string | null | undefined) => recipes.find(recipe => recipe.id === id)?.name
  // What the row runs by: its own recipe, else its team's default - none with No recipe.
  const runsBy = (row: ChatTeamIn) => (row.no_recipe ? null : (row.recipe_id ?? teamOf(row.team_id)?.default_recipe_id ?? null))

  function toggle() {
    if (open) return close()
    setError(null)
    setOpen(true)
    onRecipes().then(setRecipes, err => setError(errorText(err)))
  }

  // What stands in a step's way is said where it can be read: a table that could not be read says nothing here (the Roles panel says it).
  const readModels = () =>
    onRoleModels().then(
      read => setModels(Object.fromEntries(read.map(row => [row.role, row]))),
      () => setModels({}),
    )
  // Read again while open as the rows or the roles change (R57: a role changed on its page was not seen here till a reload).
  const reads = open && rows.some(runsBy)
  const rowsKey = key(rowsIn(rows))
  useEffect(() => {
    if (reads) void readModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- (read on those, not on every render's new function)
  }, [reads, rowsKey, roles])

  const confirm = useConfirm()
  function askRunOn(role: string, roleId: string, to: RoleModel['run_on'][number]) {
    const name = providers.find(one => one.id === to.provider_id)?.name ?? 'that provider'
    // (The role's, not this chat's: asked first, as other changes beyond the window are.)
    const asked = `Run ${role} on ${name} in every chat? Its agents run there wherever they are opened, and its tier rule goes.`
    confirm.ask(asked, `Run it on ${name}`, () => void runOn(roleId, to), 'Cancel')
  }
  async function runOn(roleId: string, to: RoleModel['run_on'][number]) {
    setError(null)
    try {
      await onRunOn(roleId, to.provider_id, to.model_id)
      await readModels()
    } catch (err) {
      setError(errorText(err))
    }
  }

  async function save(change: TeamsChange) {
    setError(null)
    try {
      await onChange(change)
    } catch (err) {
      setError(errorText(err))
    }
  }
  const saveRows = (next: ChatTeamIn[]) => save({ teams: next })
  const mine = rowsIn(rows)
  const free = teams.filter(team => !rows.some(row => row.team_id === team.id))
  const move = (at: number, by: number) => {
    const next = [...mine]
    ;[next[at], next[at + by]] = [next[at + by], next[at]]
    return saveRows(next)
  }
  const named = rows.length === 1 ? '1 team' : `${rows.length} teams`
  // Where the row's recipe is, what its agents used, and its Stop while it runs.
  const ran = (row: ChatTeam) =>
    row.state && (
      <div className="muted chat-team-by">
        {row.state.recipe || 'no recipe'}: {row.state.status}
        {row.state.why && ` (${row.state.why})`} · {tokensLine(rowTokens(agents, row.state.agents))}{' '}
        {row.state.status === 'running' && (
          <button type="button" className="btn btn-small" aria-label={`Stop ${row.state.team}`} disabled={sending === row.team_id} onClick={() => send(onStop, row.team_id)}>
            Stop
          </button>
        )}{' '}
        {row.state.status === 'running' && row.state.recipe && (
          <button type="button" className="btn btn-small" aria-label={`Finish ${row.state.team} now`} disabled={sending === row.team_id} onClick={() => send(onFinish, row.team_id)}>
            Finish now
          </button>
        )}
      </div>
    )
  // A step of the row's recipe whose role cannot run where it is now (B-89), said here too, with another provider for the role.
  const cannot = (row: ChatTeam) =>
    (recipes.find(recipe => recipe.id === runsBy(row))?.graph.steps ?? []).flatMap(step => {
      const [names, as] = stepRoles(step.who, teams, roles)
      // Offered only where it could be this step: a model it may run, and not a CLI that also works in the project itself.
      const elsewhere = (name: string) =>
        (models[name]?.run_on ?? []).filter(one => (as === 'room' ? one.room : one.step) && providers.find(p => p.id === one.provider_id)?.name !== models[name]?.provider_name)
      return names.flatMap(name => cannotOf(models[name], as).map(line => ({ step: step.name, role: name, line, id: roles.find(one => one.name === name)?.id, to: elsewhere(name) })))
    })
  const warned = (row: ChatTeam) =>
    cannot(row).map(({ step, role, line, id, to }, at) => (
      // (By place too: a recipe saved before names were one a step may hold two of a name.)
      <div key={`${at} ${step} ${role} ${line}`} className="muted chat-team-by">
        <span className="team-st-warn">
          ⚠ {step}: {role}: {line}
        </span>
        {id && to.length > 0 && (
          <select
            className="input"
            aria-label={`Run ${role} on another provider, in every chat`}
            value=""
            onChange={e => {
              const picked = to.find(one => one.provider_id === e.target.value)
              if (picked) askRunOn(role, id, picked)
            }}
          >
            <option value="">Run {role} on another provider (in every chat)…</option>
            {to.map(one => (
              <option key={one.provider_id} value={one.provider_id}>
                {providers.find(p => p.id === one.provider_id)?.name ?? one.provider_id}
                {one.model_id ? ` (${one.model_id})` : ''}
              </option>
            ))}
          </select>
        )}
      </div>
    ))
  const colours = chatColours({ conversation, runs })
  const dot = (row: ChatTeam) => <span className="team-dot" style={{ background: colours.get(row.team_id) }} aria-hidden="true" />

  return (
    <div className="chat-teams">
      <button ref={button} id="chat-teams-button" type="button" className="btn btn-small" aria-expanded={open} aria-label={`Teams for this chat: ${mode === 'none' ? 'No teams' : `${named}, ${LABEL[mode]}`}`} onClick={toggle}>
        <UsersThree size={13} />
        {mode === 'none' ? 'No teams' : `${named} · ${LABEL[mode]}`}
        <CaretDown size={11} />
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel chat-teams-panel" role="dialog" aria-label="Teams for this chat">
          <div className="kicker">Teams for this chat</div>
          <div role="radiogroup" aria-label="Who picks the teams" className="chat-teams-modes">
            {MODES.map(([value, label, note]) => (
              <label key={value} className="choice" htmlFor={`teams-${value}`}>
                <input id={`teams-${value}`} type="radio" name="teams-mode" checked={mode === value} onChange={() => void save({ teams_mode: value })} />
                <span>
                  {label}
                  <span className="choice-note">{note}</span>
                </span>
              </label>
            ))}
          </div>
          {mode === 'lead' &&
            rows.map(row => (
              <div key={row.team_id} className="chat-team-row">
                <div>
                  {dot(row)}
                  <b>{teamOf(row.team_id)?.name ?? 'A team deleted since'}</b>
                  {runsBy(row) && ` with ${recipeName(runsBy(row)) ?? 'its recipe'}`}
                  <div className="muted chat-team-by">Orchestrator’s pick{row.why && `: “${row.why}”`}</div>
                  {ran(row)}
                  {warned(row)}
                </div>
              </div>
            ))}
          {mode === 'lead' && rows.length === 0 && <p className="muted cmd-approval-note">The Orchestrator picks with your next message, or none for a simple question. Until then it calls any role but one only in teams it may not pick.</p>}
          {mode === 'lead' && rows.length > 0 && <p className="muted cmd-approval-note">To change them, switch to Manual: its picks stay there.</p>}
          {mode === 'manual' &&
            rows.map((row, at) => {
              const team = teamOf(row.team_id)
              const fallback = recipeName(team?.default_recipe_id)
              return (
                <div key={row.team_id} className="chat-team-row">
                  <div className="chat-team-picks">
                    {dot(row)}
                    <select className="input" aria-label={`Team ${at + 1}`} value={row.team_id} onChange={e => void saveRows(mine.map((one, i) => (i === at ? rowOf(e.target.value, '') : one)))}>
                      {[...(team ? [team] : []), ...free].map(one => (
                        <option key={one.id} value={one.id}>
                          {one.name}
                        </option>
                      ))}
                    </select>
                    <span className="muted">with</span>
                    <select className="input" aria-label={`Recipe for ${team?.name ?? `team ${at + 1}`}`} value={row.no_recipe ? NO_RECIPE : (row.recipe_id ?? '')} onChange={e => void saveRows(mine.map((one, i) => (i === at ? rowOf(one.team_id, e.target.value) : one)))}>
                      <option value="">its default ({fallback ?? 'none'})</option>
                      <option value={NO_RECIPE}>No recipe</option>
                      {recipes.map(recipe => (
                        <option key={recipe.id} value={recipe.id}>
                          {recipe.name}
                        </option>
                      ))}
                    </select>
                    {row.picked_by === 'lead' && <span className="muted chat-team-by">Orchestrator’s pick</span>}
                  </div>
                  {ran(row)}
                  {warned(row)}
                  <div className="chat-team-tools">
                    <button type="button" className="icon-btn" aria-label={`Move ${team?.name ?? 'it'} up`} disabled={at === 0} onClick={() => void move(at, -1)}>
                      <ArrowUp size={12} />
                    </button>
                    <button type="button" className="icon-btn" aria-label={`Move ${team?.name ?? 'it'} down`} disabled={at === rows.length - 1} onClick={() => void move(at, 1)}>
                      <ArrowDown size={12} />
                    </button>
                    <button type="button" className="icon-btn" aria-label={`Remove ${team?.name ?? 'it'}`} onClick={() => void saveRows(mine.filter((_, i) => i !== at))}>
                      <X size={12} />
                    </button>
                  </div>
                </div>
              )
            })}
          {mode === 'manual' && free.length > 0 && (
            // (No recipe of its own: the row follows its team's default, as the select says.)
            <button type="button" className="link-btn" onClick={() => void saveRows([...mine, rowOf(free[0].id, '')])}>
              + Add a team with a recipe
            </button>
          )}
          {mode === 'manual' && rows.length === 0 && <p className="muted cmd-approval-note">No team picked: the Orchestrator calls any role, as with No teams.</p>}
          {/* Said where it is so: a chat Run the backlog opens starts from it too (B-78). */}
          {project && project.teams_mode !== 'none' && project.teams_mode === mode && key(project.teams) === key(mode === 'manual' ? mine : []) && (
            <p className="muted cmd-approval-note">This folder’s default for new chats, the To-do list’s too.</p>
          )}
          {project && (project.teams_mode !== mode || key(project.teams) !== key(mode === 'manual' ? mine : [])) && (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setError(null)
                onDefault({ teams_mode: mode, teams: mode === 'manual' ? mine : [] }).catch(err => setError(errorText(err)))
              }}
            >
              Use for new chats in this project
            </button>
          )}
          {confirm.shown()}
          {error && (
            <p role="alert" className="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
