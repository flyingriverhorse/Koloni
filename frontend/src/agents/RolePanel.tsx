import { Check, X } from '@phosphor-icons/react'
import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import { type Category, type Colour, type KnowledgeItem, type Provider, type Role, type RoleModel, type Skill, type Team } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { titleOf } from './agentStatus'
import { canSwitch, kindColour, mayDo } from './chart'
import { Avatar, CategoryForm } from './RoleLibrary'
import { type KnowledgeActions, KnowledgeTab } from './KnowledgeTab'
import { ModelAnswers } from './ModelCards'
import { ROLE_TOOLS, type RoleTool, TOOL_GROUPS } from './roleTools'
import { cannotRun } from './SkillWindow'

/** The sections of a role's form (one form, new or edited: decision 5), and the Model part's cards; an Edit link opens it at its own. */
export type Part = 'what' | 'model' | 'thinking' | 'window' | 'picks' | 'inside' | 'tools' | 'limits'
export type RoleChange = Partial<Pick<Role, 'kind' | 'enabled' | 'teams' | 'tools' | 'mcp' | 'skills' | 'provider_id' | 'model_id' | 'tier' | 'tier_min' | 'tier_max'>>

// 0.1.0-ui: what its agents did is the Agents page's History tab.
const TABS = ['Overview', 'Instructions', 'Tools', 'Knowledge'] as const
export type PanelTab = (typeof TABS)[number]
type Tab = PanelTab
/** The Category list's last line: a new one, made and the role put in it. */
const NEW_CATEGORY = '+new'

interface Props {
  role: Role
  teams: Team[]
  /** The categories it may be put in (slice 63b), and what makes a new one (answers its key). */
  categories: Category[]
  onNewCategory?: (name: string, colour: Colour) => Promise<string>
  /** The tab it opens on (a team's lead's links). */
  tab?: Tab
  onPatch: (roleId: string, change: RoleChange) => Promise<void>
  /** The Tools page, where a role is given a server: on that server, by its name. */
  onOpenTools?: (server?: string) => void
  /** KOLONİ's own tools switched off on the Tools page (slice 61): kept by the role, offered to no agent. */
  off?: string[]
  /** The MCP servers switched off on the Tools page: said on the role's chip; a skill that asks for one cannot run. */
  serversOff?: string[]
  /** The skills KOLONİ keeps (K-skill-uyum), to say which of the role's can run; the Tools page, where a role is given one: on that skill. */
  skills?: Skill[]
  onOpenSkills?: (skill?: string) => void
  /** The role's form, opened at this section; `done` once it is saved or put away. */
  editor: (at: Part, done: () => void) => ReactNode
  /** Where its agents run now, and what stands in their way there (who uses what). */
  runs?: RoleModel
  /** The providers set up: those it may be moved to, by name. */
  providers?: Provider[]
  /** Its Knowledge tab (K-bilgi): the folder open now, its knowledge, what gives a role one, and the Knowledge page. */
  knowledge?: { projectId: string | null; actions?: KnowledgeActions; items?: KnowledgeItem[]; onOpen?: () => void }
  onClose: () => void
}

function Row({ label, children, edit }: { label: string; children: ReactNode; edit?: () => void }) {
  return (
    <div className="role-kv">
      <span className="muted">{label}</span>
      <div>{children}</div>
      {edit ? (
        <button type="button" className="link-btn" aria-label={`Edit ${label.toLowerCase()}`} onClick={edit}>
          Edit
        </button>
      ) : (
        <span />
      )}
    </div>
  )
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** A role, opened from the chart: what it is, its rule, its instructions, tools and knowledge. Read first; Edit opens its form. */
export function RolePanel({ role, teams, categories, onNewCategory, tab: first = 'Overview', onPatch, onOpenTools, off = [], serversOff = [], skills = [], onOpenSkills, editor, runs, providers = [], knowledge, onClose }: Props) {
  const tabs = TABS.filter(one => one !== 'Knowledge' || knowledge)
  const [tab, setTab] = useState<Tab>(tabs.includes(first) ? first : 'Overview')
  const [editing, setEditing] = useState<Part | null>(null)
  const [newCategory, setNewCategory] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const patch = (change: RoleChange) => {
    setError(null)
    onPatch(role.id, change).catch(err => setError(errorText(err)))
  }
  // A tile saves at once (as the Models page's switches do): shown as clicked while it saves, as saved after a failure.
  // shortcut: a click made while an earlier one still saves is sent on top of it; were that one to fail, the later
  // save may still carry it. Hold the tiles while one saves if that is ever seen.
  const [tools, setTools] = useState<string[] | null>(null)
  const saving = useRef(0)
  useEffect(() => {
    if (saving.current) return
    setTools(null)
  }, [role.updated_at])
  const [said, setSaid] = useState<string | null>(null)
  useEffect(() => {
    if (!said) return
    const gone = setTimeout(() => setSaid(null), 4000)
    return () => clearTimeout(gone)
  }, [said])
  const has = tools ?? role.tools
  const observer = role.builtin && role.name === 'Observer'
  const saveAtOnce = (change: RoleChange, done: string, undo: () => void) => {
    setError(null)
    setSaid(null)
    saving.current += 1
    onPatch(role.id, change)
      .then(
        () => setSaid(done),
        err => {
          undo()
          setError(errorText(err))
        },
      )
      .finally(() => {
        saving.current -= 1
      })
  }
  const flip = (tool: RoleTool) => {
    const on = !has.includes(tool.name)
    // The role's own list, one changed: what no tile shows (assess_task) goes back as it was.
    const next = on ? [...has, tool.name] : has.filter(name => name !== tool.name)
    setTools(next)
    saveAtOnce({ tools: next }, `${tool.label}: ${on ? 'on' : 'off'}, saved.`, () => setTools(null))
  }
  // As its agents have them (app/skills.py `split`): ticked, on, and with every group of tools it asks for.
  const runnable = (skill: Skill) => !cannotRun(skill, { tools: has, mcp: role.mcp }, off, serversOff)
  const givenSkills = skills.filter(skill => role.skills.includes(skill.name) && runnable(skill))
  const done = () => setEditing(null)
  const choose = (one: Tab) => {
    setTab(one)
    setEditing(null)
  }
  // A team's lead (slice 63a): its team names it; its switch is its team's.
  const teamLead = teams.some(team => team.lead.id === role.id)
  const mine = teams.filter(team => role.teams.includes(team.id))
  const others = teams.filter(team => !role.teams.includes(team.id))
  const tabId = (one: Tab) => `role-tab-${one.toLowerCase()}`

  return (
    <aside className="role-panel" aria-label={`Role ${role.name}`}>
      <div className="role-panel-head">
        <div>
          <h2>
            <Avatar name={role.name} colour={kindColour(categories, role.kind)} />
            {role.name}
            {/* (A team's lead is on or off with its team: said on its team's row.) */}
            {!teamLead && <span className={`tag${role.enabled ? ' tag-ok' : ''}`}>{role.enabled ? 'on' : 'off'}</span>}
          </h2>
          {titleOf(role.name, teams) !== role.name && <span className="muted">— shown as {titleOf(role.name, teams)}</span>}
          <span className="muted">{role.description}</span>
          {role.created_by_agent && <span className="tag tag-accent">Created by an agent</span>}
        </div>
        {canSwitch(role) && !teamLead && <input type="checkbox" role="switch" className="model-agents" aria-label={`${role.name} on`} checked={role.enabled} onChange={e => patch({ enabled: e.target.checked })} />}
        <button type="button" className="icon-btn" aria-label="Close the role" onClick={onClose}>
          <X size={14} />
        </button>
      </div>
      {/* The arrow keys go from tab to tab, the chosen one alone in the Tab order (the tabs pattern). */}
      <div
        className="tabs"
        role="tablist"
        aria-label={`${role.name}'s parts`}
        onKeyDown={e => {
          const by = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
          if (!by) return
          const next = tabs[(tabs.indexOf(tab) + by + tabs.length) % tabs.length]
          choose(next)
          document.getElementById(tabId(next))?.focus()
        }}
      >
        {tabs.map(one => (
          <button
            key={one}
            id={tabId(one)}
            type="button"
            role="tab"
            className="tab"
            aria-selected={tab === one}
            tabIndex={tab === one ? 0 : -1}
            onClick={() => choose(one)}
          >
            {one}
          </button>
        ))}
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div role="tabpanel" aria-labelledby={tabId(tab)} className="role-tab">
        {editing ? (
          editor(editing, done)
        ) : tab === 'Overview' ? (
          <>
            {/* A team's lead is in no team and no category: it is its team's. */}
            {!teamLead && (
              <>
                <Row label="Category">
                  {newCategory ? (
                    <CategoryForm
                      button="Add"
                      onSave={(name, colour) => {
                        setError(null)
                        onNewCategory?.(name, colour)
                          .then(key => onPatch(role.id, { kind: key }))
                          .then(() => setNewCategory(false), err => setError(errorText(err)))
                      }}
                      onCancel={() => setNewCategory(false)}
                    />
                  ) : (
                    <select className="input role-category" aria-label={`${role.name}'s category`} value={role.kind} onChange={e => (e.target.value === NEW_CATEGORY ? setNewCategory(true) : patch({ kind: e.target.value }))}>
                      {/* (A kind no category has is shown as it is, until another is picked.) */}
                      {!categories.some(one => one.key === role.kind) && <option value={role.kind}>{role.kind}</option>}
                      {categories.map(one => (
                        <option key={one.key} value={one.key}>
                          {one.name}
                        </option>
                      ))}
                      {onNewCategory && <option value={NEW_CATEGORY}>+ New category…</option>}
                    </select>
                  )}
                </Row>
                <Row label="In teams">
                  <span className="role-inteams">
                    {mine.map(team => (
                      <span key={team.id} className="role-inteam">
                        <b>{team.name}</b>
                        <span className="muted"> · {team.stages.find(stage => stage.roles.includes(role.id))?.name}</span>
                        <button type="button" className="chip-x" aria-label={`Take ${role.name} out of ${team.name}`} onClick={() => patch({ teams: role.teams.filter(id => id !== team.id) })}>
                          <X size={10} />
                        </button>
                      </span>
                    ))}
                    {others.length > 0 && (
                      <select className="chip chip-add" aria-label={`Put ${role.name} in a team`} value="" onChange={e => e.target.value && patch({ teams: [...role.teams, e.target.value] })}>
                        <option value="">+ Add to a team…</option>
                        {others.map(team => (
                          <option key={team.id} value={team.id}>
                            {team.name}
                          </option>
                        ))}
                      </select>
                    )}
                    {mine.length === 0 && others.length === 0 && <span className="muted">No team yet</span>}
                  </span>
                </Row>
              </>
            )}
            <ModelAnswers role={role} runs={runs} providers={providers} teamLead={teamLead} onEdit={setEditing} />
            <Row label="May" edit={() => setEditing('tools')}>
              {mayDo(role.tools)}
            </Row>
          </>
        ) : tab === 'Knowledge' && knowledge ? (
          <KnowledgeTab role={role} teamLead={teamLead} projectId={knowledge.projectId} items={knowledge.items} onUse={knowledge.actions?.useKnowledge} onOpenKnowledge={knowledge.onOpen} />
        ) : tab === 'Instructions' ? (
          <>
            <p className="role-read role-read-long">{role.instructions || <span className="muted">No instructions.</span>}</p>
            <button type="button" className="btn btn-small" onClick={() => setEditing('what')}>
              Edit
            </button>
          </>
        ) : (
          <>
            <p className="muted tool-sum">
              <span>
                May use{' '}
                <b>
                  {ROLE_TOOLS.filter(tool => has.includes(tool.name)).length} of {ROLE_TOOLS.length}
                </b>{' '}
                tools · {plural(role.mcp.length, 'MCP server')} · {skills.length > 0 ? `${givenSkills.length} of ${skills.length} skills` : plural(role.skills.length, 'skill')}
              </span>{' '}
              <Hint doc={GUIDE.rolePanel}>“asks”: it waits for your yes first, as the conversation’s permission level says.</Hint>
            </p>
            {observer ? (
              // No agent is opened in it: what it is asked is one question, with no tools (the server refuses any).
              <p className="muted provider-note">
                Tools: none. Where a project has it on (Sub-agents’ work), KOLONİ asks this role’s model one question about
                each sub-agent’s report; no agent is opened in this role.
              </p>
            ) : (
              TOOL_GROUPS.map(group => {
                const all = ROLE_TOOLS.filter(tool => tool.group === group)
                return (
                  <div key={group} className="tool-block" style={{ '--c': `var(--tool-${group.toLowerCase()})` } as CSSProperties}>
                    <h4>
                      <span className="tool-mark" aria-hidden="true">
                        {group[0]}
                      </span>
                      {group}
                      <span className="muted">
                        {all.filter(tool => has.includes(tool.name)).length} of {all.length}
                      </span>
                    </h4>
                    <div className="tool-tiles">
                      {all.map(tool => {
                        const on = has.includes(tool.name)
                        // The server keeps a role with at least one tool: the last one stays on.
                        const keep = on && has.length === 1
                        return (
                          <button
                            key={tool.name}
                            type="button"
                            className={`tool-tile${on ? ' tool-tile-on' : ''}`}
                            aria-pressed={on}
                            aria-label={tool.label}
                            aria-describedby={`tool-${tool.name}-line`}
                            disabled={keep}
                            title={keep ? 'A role needs at least one tool: turn another on first' : `${tool.name}: ${tool.hint}`}
                            onClick={() => flip(tool)}
                          >
                            <span className="tool-tile-name">
                              {tool.label}
                              <span className="tool-tile-check" aria-hidden="true">
                                {on && <Check size={10} weight="bold" />}
                              </span>
                            </span>
                            <span id={`tool-${tool.name}-line`} className="tool-tile-line">
                              {tool.line}
                              {off.includes(tool.name) ? (
                                <span className="tool-tile-asks">off on the Tools page</span>
                              ) : (
                                on && tool.asks && <span className="tool-tile-asks">asks</span>
                              )}
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )
              })
            )}
            {/* 0.1.0-ui: a role is given a server or a skill on the Tools page; here it is listed, each a way there. */}
            <div className="tool-extra">
              <h4 className="tool-extra-head">
                Servers and skills
                {onOpenTools && (
                  <button type="button" className="link-btn" onClick={() => onOpenTools()}>
                    on Tools →
                  </button>
                )}
              </h4>
              <div className="chips">
                {role.mcp.length + role.skills.length === 0 && <span className="muted">none</span>}
                {role.mcp.map(name => {
                  // Switched off on the Tools page: kept by the role, given to no agent.
                  const isOff = serversOff.includes(name)
                  return (
                    <button
                      key={name}
                      type="button"
                      className="chip mono"
                      aria-label={`${name}${isOff ? ', off' : ''}, on the Tools page`}
                      disabled={!onOpenTools}
                      onClick={() => onOpenTools?.(name)}
                    >
                      {name}
                      {isOff && <span className="muted"> · off</span>}
                    </button>
                  )
                })}
                {role.skills.map(name => {
                  const skill = skills.find(one => one.name === name)
                  const why = skill && cannotRun(skill, { tools: has, mcp: role.mcp }, off, serversOff)
                  return (
                    <button
                      key={name}
                      type="button"
                      className="chip"
                      aria-label={`${name}${why ? `, cannot run here: ${why}` : ''}, on the Tools page`}
                      title={why ? `Cannot run here: ${why}` : undefined}
                      disabled={!onOpenSkills}
                      onClick={() => onOpenSkills?.(name)}
                    >
                      {why && <span className="warn" aria-hidden="true">⚠ </span>}
                      {name}
                    </button>
                  )
                })}
              </div>
            </div>
            <span role="status" className="muted provider-note">
              {said}
            </span>
          </>
        )}
      </div>
    </aside>
  )
}
