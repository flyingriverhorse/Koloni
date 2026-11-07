import { type LoadModels } from '../models/ModelNameInput'
import { FillTiers } from '../models/FillTiers'
import { type LoadFacts } from '../models/levels'
import { Plus } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import { type Category, type Effort, type FillAll, type FilledProvider, type Knowledge, type KnowledgeItem, type Recipes, type RecordRow, type Provider, type Role, type RoleModel, type RolesActivity, type RolesHistory, type Skill, type Team, type Tier } from '../api/types'
import { drawn, kindName } from './chart'
import { ExpertForm, type KnowledgeActions } from './KnowledgeTab'
import { type PanelTab, type Part, type RoleChange, RolePanel } from './RolePanel'
import { type CategoryActions, RoleLibrary } from './RoleLibrary'
import { EXPERT_TOOLS } from './roleTools'
import { HistoryTab } from './HistoryTab'
import { type RecipeActions, RecipesTab } from './RecipesTab'
import { NameForm, type TeamActions, TeamsBoard } from './TeamsBoard'
import { RecordTable } from './RecordTable'
import { RoleEditor } from './RoleEditor'


export interface RoleValues {
  name: string
  description: string
  instructions: string
  tools: string[]
  /** The role's own model; null follows the conversation. */
  provider_id: string | null
  model_id: string | null
  /** K-rol-model-sirasi: tried first, in this order; one not had now is passed over. null: none. */
  models: Role['models']
  /** Without a model of its own: always the first model of this tier (your rule); null: the Lead picks, from `tier_min` to `tier_max`. */
  tier: Role['tier']
  tier_min: Tier | null
  tier_max: Tier | null
  /** Its category's key (slice 63b). */
  kind: string
  /** The providers (ids) that may be picked for a sub-agent of this role; null: all in the team guide, empty: none. */
  pick_from: string[] | null
  /** How far one agent of this role may go; null: no limit of the role's. */
  max_steps: number | null
  max_tokens: number | null
  /** Its agents' reasoning level, and the most one asked for a task may get; null: the model's own, no most. */
  effort: Effort | null
  max_effort: Effort | null
  /** How many tokens its agents' model reads at most, as you set it; null: as found. */
  context_window: number | null
  /** The skills (their names) its agents are given. */
  skills: string[]
  /** 89g: also offered to a Claude Code Lead as one of its own sub-agents. */
  inside_cli: boolean
  /** A new role's team, where it is added in one (slice 81d); a role's own are changed from its panel. */
  teams?: string[]
}

export interface Props {
  roles: Role[]
  /** Open on this one (from Ctrl+K) rather than the first. */
  picked?: string
  providers?: Provider[]
  onModels?: LoadModels
  /** What is known of the model being picked for the role: its levels and window. */
  onFacts?: LoadFacts
  onSave: (roleId: string, values: RoleValues) => Promise<void>
  /** Answers with the role made, where it can (the store does). */
  onCreate: (values: RoleValues) => Promise<Role | void>
  onDelete: (roleId: string) => Promise<void>
  onReset: (roleId: string) => Promise<void>
  /** What was measured of the agents that ended in the last 30 days, by role and model. Throws ApiError. */
  onRecord?: () => Promise<RecordRow[]>
  /** What each role's agents would run on now: read for the reasoning levels that model takes. Throws ApiError. */
  onRoleModels?: () => Promise<RoleModel[]>
  /** The skills KOLONİ keeps, listed on a role's Tools tab; the Tools page, where a role is given one (on that skill). */
  skills?: Skill[]
  onOpenSkills?: (skill?: string) => void
  /** Every provider's tiers from the catalogue, previewed, then saved in one go. */
  onFillAll?: () => Promise<FillAll>
  onSaveFillAll?: (providers: FilledProvider[]) => Promise<void>
  /** The teams (slice 62), and what makes and changes one, its stages and who sits in which (63a). */
  teams?: Team[]
  teamActions?: TeamActions
  /** The roles' categories (slice 63b), and what changes them. */
  categories?: Category[]
  categoryActions?: CategoryActions
  /** The recipes (slice 84a): what reads, saves and drafts one; and the folder open now, whose own recipes are listed with them. */
  recipeActions?: RecipeActions
  projectId?: string | null
  /** A role's category, on / off or teams, changed at once. Throws ApiError. */
  onPatch?: (roleId: string, change: RoleChange) => Promise<void>
  /** What the chart draws from the record, and the History tab's days. Each throws ApiError. */
  onActivity?: () => Promise<RolesActivity>
  onHistory?: (days: number) => Promise<RolesHistory>
  onOpenConversation?: (conversationId: string) => void
  /** The Tools page, where a role is given an MCP server (on that server, by its name). */
  onOpenTools?: (server?: string) => void
  /** KOLONİ's own tools switched off there (slice 61): a role keeps them, no agent is offered them. */
  off?: string[]
  /** The MCP servers switched off there: given to no agent. */
  serversOff?: string[]
  /** K-bilgi: what makes an expert, and gives a role a knowledge. */
  knowledgeActions?: KnowledgeActions
  /** K-bilgi: the open project's Knowledge page (a role's Knowledge tab turns each on or off), and where it opens. */
  knowledge?: KnowledgeItem[]
  onOpenKnowledge?: () => void
}

export const EMPTY: RoleValues = {
  name: '',
  description: '',
  instructions: '',
  tools: [],
  provider_id: null,
  model_id: null,
  models: null,
  tier: null,
  tier_min: null,
  tier_max: null,
  kind: 'build',
  pick_from: null,
  max_steps: null,
  max_tokens: null,
  effort: null,
  max_effort: null,
  context_window: null,
  skills: [],
  inside_cli: false,
}


/** A role's model's window as found, and where from: the provider says it (Anthropic's Models API, llama-server's `/props`). */
function foundOf(row: RoleModel | undefined, providers: Provider[]) {
  if (!row) return undefined
  const window = row.context_window ?? null
  const anthropic = providers.find(p => p.name === row.provider_name)?.kind === 'anthropic'
  return { window, from: anthropic ? 'from Anthropic' : 'from the server' }
}

/** The roles agents can take: built-in ones, your own, and any an agent created. */
// One array for "no providers": a new one at each render would read the roles' models again each time.
const NO_PROVIDERS: Provider[] = []
const NO_TEAMS: Team[] = []
const NO_CATEGORIES: Category[] = []

type Tab = 'team' | 'recipes' | 'history'
const TABS: [Tab, string][] = [
  ['team', 'Teams & roles'],
  ['recipes', 'Recipes'],
  ['history', 'History'],
]

/**
 * The Agents page (slices 81b, 63a, 84a, 63b): Teams & roles - the roles once, by category, on the left, the Lead and the
 * teams in the middle, one open; Recipes, the steps of a piece of work drawn. A role, or a team's lead, opened beside them.
 */
export function AgentsPage({ roles, providers = NO_PROVIDERS, teams = NO_TEAMS, categories = NO_CATEGORIES, categoryActions, onModels, onRecord, onRoleModels, onFillAll, onSaveFillAll, teamActions, recipeActions, projectId = null, onPatch, onActivity, onHistory, onOpenConversation, onOpenTools, off, serversOff, skills, onOpenSkills, picked, knowledgeActions, knowledge: knowledgeItems, onOpenKnowledge, ...handlers }: Props) {
  const [selected, setSelected] = useState<string | null>(picked ?? null)
  // The tab a team's lead's link opens its panel on.
  const [panelTab, setPanelTab] = useState<PanelTab>('Overview')
  // A role dragged from the library: the open team says where it lands.
  const [dragging, setDragging] = useState<Role | null>(null)
  // A narrow window's library, open over the teams.
  const [drawer, setDrawer] = useState(false)
  // (Closed, the focus goes back to the button that opened it.)
  const drawerButton = useRef<HTMLButtonElement>(null)
  // A new role being made, and the kind of work or the team of the group it is added in; started blank, as an expert
  // or as a copy of a role (its id; '' until one is picked).
  const [adding, setAdding] = useState<{ kind: string; team?: string; stage?: string } | null>(null)
  const [start, setStart] = useState<'blank' | 'expert' | 'copy'>('blank')
  const [copyId, setCopyId] = useState('')
  // A role added to a group from its menu is said for a moment.
  const [said, setSaid] = useState<string | null>(null)
  useEffect(() => {
    if (!said) return
    const gone = setTimeout(() => setSaid(null), 4000)
    return () => clearTimeout(gone)
  }, [said])
  // shortcut: the tab is the page's, not in the address (the app has no routes; Models keeps its tab the same way).
  const [tab, setTab] = useState<Tab>('team')
  const [naming, setNaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The recipes, for their tab and a team's default: read when the page opens, when the folder changes and after a save.
  const [recipes, setRecipes] = useState<Recipes | string | null>(null)
  const [recipesRead, readRecipes] = useState(0)
  // (The store's method, which stays the same: the store itself is new at each change.)
  const readList = recipeActions?.recipes
  useEffect(() => {
    let latest = true
    readList?.(projectId).then(
      read => latest && setRecipes(read),
      err => latest && setRecipes(errorText(err)),
    )
    return () => {
      latest = false
    }
  }, [readList, projectId, recipesRead])
  // Read once when the page opens: what ended later is in the next reading.
  const [record, setRecord] = useState<RecordRow[] | string>([])
  useEffect(() => {
    let latest = true
    onRecord?.().then(
      rows => latest && setRecord(rows),
      err => latest && setRecord(errorText(err)),
    )
    return () => {
      latest = false
    }
  }, [onRecord])
  // What each role's agents would run on now, by role name, with the levels that model takes and its window as
  // found: read again when a role changes, or a provider (a tier may now find a model).
  // shortcut: of the model as saved, not one being picked in the editor; upgrade if a picked model's levels are wanted before saving.
  const [models, setModels] = useState<Record<string, RoleModel> | 'failed'>({})
  useEffect(() => {
    let latest = true
    onRoleModels?.().then(
      rows => latest && setModels(Object.fromEntries(rows.map(row => [row.role, row]))),
      () => latest && setModels('failed'),
    )
    return () => {
      latest = false
    }
  }, [onRoleModels, roles, providers])
  // Who is at work, where each role last ran, the Lead's jobs: read when the page opens and when a role changes.
  const [activity, setActivity] = useState<RolesActivity | null>(null)
  useEffect(() => {
    let latest = true
    onActivity?.().then(
      read => latest && setActivity(read),
      () => latest && setActivity(null),
    )
    return () => {
      latest = false
    }
  }, [onActivity, roles])

  const act = (work: Promise<void> | undefined) => {
    setError(null)
    work?.catch(err => setError(errorText(err)))
  }
  const lead = roles.find(role => role.builtin && role.name === 'Lead')
  const library = drawn(roles)
  // A team's lead is in no list of roles: it is opened from its team.
  const current = adding === null ? ([...roles, ...teams.map(one => one.lead)].find(role => role.id === selected) ?? null) : null
  // A role of the library open beside: the teams it is in are marked.
  const marked = current && library.some(role => role.id === current.id) ? current : null
  const known = models === 'failed' ? undefined : models
  const runs = (role: Role) => known?.[role.name]
  const copy = start === 'copy' ? roles.find(role => role.id === copyId) : undefined
  const editor = (role: Role | null) => (at: Part | undefined, done: () => void) => (
    // Keyed by role and its last change so a save, reset or switch reloads the form; a new one by what it copies.
    <RoleEditor
      key={role ? `${role.id}:${role.updated_at}` : `new:${adding?.kind}:${adding?.team}:${copy?.id}`}
      role={role}
      at={at}
      copyOf={role ? undefined : copy}
      kind={adding?.kind}
      team={adding?.team}
      teamLead={!!role && teams.some(one => one.lead.id === role.id)}
      runs={role ? runs(role) : undefined}
      takes={!role ? undefined : models === 'failed' ? null : models[role.name] && (models[role.name].efforts ?? null)}
      found={!role ? undefined : models === 'failed' ? null : foundOf(models[role.name], providers)}
      providers={providers}
      categories={categories}
      onModels={onModels}
      off={off}
      {...handlers}
      onCreate={create}
      onCancel={done}
      onDone={done}
    />
  )
  async function create(values: RoleValues) {
    const made = await handlers.onCreate(values)
    if (!made) return made
    // Made: what follows is tried one by one, and what is refused is said - the form closes on the role either way, so
    // Create is never pressed again for a role that is there.
    const left: string[] = []
    const tryIt = (what: string, work: Promise<void> | undefined) => work?.catch(err => void left.push(`${what} — ${errorText(err)}`))
    // Asked from a stage: in that stage, not the one named as its category was.
    if (adding?.team && adding.stage) await tryIt('its stage', teamActions?.placeRole(adding.team, made.id, adding.stage))
    // A copy's servers, skills and knowledge, which a new role is not made with (decision 6); not its teams.
    if (copy) {
      if (copy.mcp.length) await tryIt('its servers', onPatch?.(made.id, { mcp: copy.mcp }))
      if (copy.skills.length) await tryIt('its skills', onPatch?.(made.id, { skills: copy.skills }))
      for (const one of copy.knows ?? [])
        await tryIt(knowledgeItems?.find(item => item.id === one.knowledge_id)?.knowledge.topic ?? 'a knowledge', knowledgeActions?.useKnowledge?.(one.knowledge_id, made.id, one.mode))
    }
    setSelected(made.id)
    setError(left.length ? `Made ${made.name}; not given: ${left.join('; ')}` : null)
    return made
  }
  // K-bilgi: an expert's knowledge is the project's (its Knowledge page); the role uses it in full.
  async function createExpert(name: string, knowledge: Knowledge) {
    if (!projectId || !knowledgeActions?.createExpert) throw new Error('Open a folder first: knowledge is kept in a project.')
    // (One request: the role, its knowledge and the role using it, or none of them.)
    const made = await knowledgeActions.createExpert(
      {
        ...EMPTY,
        name,
        // (The server knows these words: app/knows.py EXPERT_DESCRIPTION, kept in step.)
        description: `Knows ${knowledge.topic}: answers from its sources, advises and reads only.`,
        tools: EXPERT_TOOLS,
        // (An expert advises: a category of planning where there is one.)
        kind: categories.find(one => one.key === 'plan')?.key ?? adding?.kind ?? 'build',
        ...(adding?.team && { teams: [adding.team] }),
      },
      knowledge,
    )
    // Asked from a stage: in that stage, as `create` places one.
    if (adding?.team && adding.stage) await teamActions?.placeRole(adding.team, made.id, adding.stage)
    setAdding(null)
  }
  const newRole = (team?: string, stage?: string) => {
    setAdding({ kind: 'build', team, stage })
    setStart('blank')
    setCopyId('')
    setSelected(null)
  }
  const open = (id: string, on: PanelTab = 'Overview') => {
    setSelected(id)
    setPanelTab(on)
    setAdding(null)
    setDrawer(false)
  }
  return (
    <div className="paged">
      <div className="page-head">
        <h2>Agents</h2>
        <span className="muted">Who does the work, in which teams, by which recipes</span>
        {tab === 'team' && (
          <div className="page-head-right">
            <button type="button" className="btn btn-small" onClick={() => newRole()}>
              <Plus size={13} />
              New role
            </button>
            <button type="button" className="btn btn-primary btn-small" onClick={() => setNaming(true)}>
              <Plus size={13} />
              New team
            </button>
          </div>
        )}
      </div>
      <FillTiers providers={providers} onFillAll={onFillAll} onSaveFillAll={onSaveFillAll} />
      {/* The arrow keys go from tab to tab, Home and End to the ends, the chosen one alone in the Tab order (the tabs pattern). */}
      <div
        className="tabs agents-tabs"
        role="tablist"
        aria-label="Agents"
        onKeyDown={e => {
          const at = TABS.findIndex(([one]) => one === tab)
          const to = { ArrowRight: at + 1, ArrowLeft: at - 1 + TABS.length, Home: 0, End: TABS.length - 1 }[e.key]
          if (to === undefined) return
          e.preventDefault()
          const next = TABS[to % TABS.length][0]
          setTab(next)
          document.getElementById(`agents-tab-${next}`)?.focus()
        }}
      >
        {TABS.map(([one, title]) => (
          <button key={one} id={`agents-tab-${one}`} type="button" role="tab" className="tab" aria-selected={tab === one} tabIndex={tab === one ? 0 : -1} onClick={() => setTab(one)}>
            {title}
          </button>
        ))}
      </div>
      {(tab === 'recipes' || naming) && (
        <div className="agents-bar">
          {tab === 'recipes' ? (
            <span className="muted provider-note">A recipe says who does each step, what runs at once and how far it loops back. A chat’s team runs by the recipe picked for it, else by its team’s default.</span>
          ) : (
            <NameForm label="New team’s name" button="Add team" max={55} onSave={name => act(teamActions?.createTeam(name).then(() => setNaming(false)))} onCancel={() => setNaming(false)} />
          )}
        </div>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {/* B-170: read out, not drawn - drawn, it pushed the page down and back as it came and went. */}
      <span role="status" className="visually-hidden">
        {said}
      </span>
      <div role="tabpanel" aria-labelledby={`agents-tab-${tab}`} className={`agents-page${dragging ? ' agents-dragging' : ''}`}>
        {tab === 'history' ? (
          <HistoryTab
            onHistory={onHistory}
            onOpenConversation={onOpenConversation}
            recordOf={name =>
              typeof record === 'string' ? (
                <p role="alert" className="alert">
                  The record could not be read: {record}
                </p>
              ) : (
                <RecordTable record={record.filter(row => row.role_name === name)} />
              )
            }
          />
        ) : tab === 'recipes' ? (
          <RecipesTab roles={library} teams={teams} list={recipes} projectId={projectId} actions={recipeActions} reload={() => readRecipes(n => n + 1)} models={known} providers={providers} onModels={onModels} />
        ) : (
          <>
            <RoleLibrary
              roles={library}
              categories={categories}
              selected={current?.id ?? null}
              onOpen={id => open(id)}
              onSwitch={(role, on) => act(onPatch?.(role.id, { enabled: on }))}
              onKind={(role, key) => {
                setSaid(null)
                act(onPatch?.(role.id, { kind: key }).then(() => setSaid(`${role.name} is in ${kindName(categories, key)} now.`)))
              }}
              onDrag={setDragging}
              actions={categoryActions}
              act={act}
              open={drawer}
              onClose={() => {
                setDrawer(false)
                drawerButton.current?.focus()
              }}
            />
            <div className="agents-teams">
              {/* A narrow window's library, folded to this (slice 63b). */}
              <button ref={drawerButton} type="button" className="btn btn-small role-lib-toggle" aria-expanded={drawer} onClick={() => setDrawer(!drawer)}>
                Roles ▸ {library.length}
              </button>
              <TeamsBoard
                projectId={projectId}
                lead={lead}
                teams={teams}
                roles={library}
                categories={categories}
                activity={activity}
                selected={current?.id ?? null}
                marked={marked}
                dragging={dragging}
                onOpen={open}
                onPatch={(roleId, change) => onPatch?.(roleId, change) ?? Promise.resolve()}
                // A team's default is one of KOLONİ's recipes: a team is every folder's.
                recipes={recipes && typeof recipes !== 'string' ? recipes.recipes.filter(one => !one.project_id) : []}
                actions={teamActions}
                act={act}
                say={setSaid}
                onNewRole={newRole}
                models={known}
                providers={providers}
              />
            </div>
          </>
        )}
        {tab !== 'team' ? null : adding !== null ? (
          <aside className="role-panel" aria-label="New role">
            <div className="role-panel-head">
              <div>
                <h2>New role</h2>
                <span className="muted">Agents in this role are opened by the Orchestrator or a team lead.</span>
              </div>
            </div>
            <div className="files-modes role-starts" role="group" aria-label="Start from">
              {(
                [
                  ['blank', 'Blank'],
                  ['expert', 'An expert'],
                  ['copy', 'A copy'],
                ] as const
              ).map(([one, title]) => (
                <button key={one} type="button" className="view-run" aria-pressed={start === one} onClick={() => setStart(one)}>
                  {title}
                </button>
              ))}
            </div>
            {start === 'copy' && (
              <div className="field">
                <label htmlFor="role-copy">Copy of</label>
                <select id="role-copy" className="input" value={copyId} onChange={e => setCopyId(e.target.value)}>
                  <option value="">Pick a role…</option>
                  {library.map(role => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {start === 'expert' ? (
              <>
                <ExpertForm providers={providers} onCreate={createExpert} onCancel={() => setAdding(null)} />
                <p className="muted role-expert-may">
                  <b>It may:</b> reads only — an expert changes nothing.
                </p>
              </>
            ) : (
              (start === 'blank' || copy) && editor(null)(undefined, () => setAdding(null))
            )}
          </aside>
        ) : (
          current && (
            <RolePanel
              key={`${current.id}:${panelTab}`}
              role={current}
              teams={teams}
              categories={categories}
              onNewCategory={categoryActions?.addCategory}
              tab={panelTab}
              onPatch={(roleId, change) => onPatch?.(roleId, change) ?? Promise.resolve()}
              onOpenTools={onOpenTools}
              off={off}
              serversOff={serversOff}
              skills={skills}
              onOpenSkills={onOpenSkills}
              editor={editor(current)}
              runs={runs(current)}
              providers={providers}
              knowledge={{ projectId, actions: knowledgeActions, items: knowledgeItems, onOpen: onOpenKnowledge }}
              onClose={() => setSelected(null)}
            />
          )
        )}
      </div>
    </div>
  )
}
