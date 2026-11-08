import { useContext, useState } from 'react'
import { errorText } from '../api/client'
import type { Project } from '../api/types'
import { AllowList } from '../commands/AllowList'
import { LEAD_WORK, OPENING, WHEN_AWAY } from '../shell/sections/Agents'
import { CloseMore } from '../shell/usePanel'
import { useApp } from '../state/store'

const TEAMS = { lead: 'Orchestrator decides', manual: 'Manual', none: 'No teams' } as const
const LEVELS = { ask: 'Ask before changes', auto_edit: 'Auto-edit files', full_auto: 'Full auto' } as const

/** A panel of the chat's own, opened as its own button opens it (the Teams button over the canvas, the folder button). */
const press = (id: string) => document.getElementById(id)?.click()

const nameOf = <T extends string>(list: readonly (readonly [T, string, ...unknown[]])[], value: T) => list.find(([key]) => key === value)?.[1] ?? value

/** What a chat of the project takes from it, in short: one line each. */
function fromProject(project: Project): [string, string][] {
  const away = project.when_away === 'lead' ? `${nameOf(WHEN_AWAY, project.when_away)}, after ${project.away_minutes} min` : nameOf(WHEN_AWAY, project.when_away)
  return [
    ['Who changes the files', nameOf(LEAD_WORK, project.lead_work)],
    ['Opening a sub-agent', nameOf(OPENING, project.spawn_approval)],
    ['When you’re away', away],
    ['Agents', `${project.max_agents ? `at most ${project.max_agents} in the project` : 'no limit in the project'} · ${project.spawn_max_parallel} at once · ${project.spawn_max_depth} levels · ${project.spawn_max_agents} per request`],
    ['Money', money(project)],
    ['Commands run on', project.exec_location === 'docker' ? `a Docker container (${project.docker_image ?? 'no image'})` : 'this machine'],
  ]
}

function money(project: Project): string {
  const turn = project.turn_token_limit ? `a message stops over ${project.turn_token_limit} tokens` : 'no token limit per message'
  return `${turn} · ${project.monthly_budget == null ? 'no monthly budget' : `${project.monthly_budget} a month`}`
}

/**
 * This chat's own settings (sample C's sheet; sample A's This chat): its teams, its folders, its pages' scripts, what
 * runs without asking in it - and, read only, what it takes from its project and the app, each a link to where it is
 * set. Its level, Plan first and model stay under the message box. `sheet`: under ⚙ beside the box, with All settings.
 */
export function ChatSheet({ sheet = false }: { sheet?: boolean }) {
  const conv = useApp(s => s.conv)
  const project = useApp(s => s.projects.find(p => p.id === s.conv?.conversation.project_id)) ?? null
  const teams = useApp(s => s.teams)
  // (Under ⚙: what goes elsewhere closes it first.)
  const close = useContext(CloseMore)
  if (!conv) return null
  const chat = conv.conversation
  const ask = (place: Parameters<ReturnType<typeof useApp.getState>['askSettings']>[0]) => {
    close()
    useApp.getState().askSettings(place)
  }
  // In the sheet, the panel's own button is pressed (where it is there); on the page, where it is is said.
  const opens = (id: string) =>
    sheet && document.getElementById(id)
      ? () => {
          close()
          press(id)
        }
      : undefined
  return (
    <div className="chat-sheet">
      {!sheet && (
        <div className="set-row">
          <span className="set-name">Under the message box</span>
          <span className="set-value">
            {LEVELS[chat.permission_mode]} · Plan first {chat.plan_first ? 'on' : 'off'} · the model
          </span>
        </div>
      )}
      <Elsewhere label="Teams" value={teamsSaid(chat, teams)} button="Change teams…" where="Set with the Teams button over the canvas." open={opens('chat-teams-button')} />
      <Elsewhere label="Folders" value={foldersSaid(chat, project)} button="Change folders…" where="Set with the folder button." open={opens('folder-button')} />
      <PageScripts on={chat.page_scripts} />
      <Runs inProject={chat.project_id !== null} onRules={() => ask('rules')} />
      {project && <FromProject project={project} onOpen={() => ask('agents')} />}
      {chat.project_id === null && <p className="choice-note">No folder: sub-agents use KOLONİ’s defaults - ask when it matters, 2 at the same time, 2 levels, 6 per request. Nothing changes them yet.</p>}
      <p className="choice-note">
        The language agents answer in, the steps an agent may take and when a long context is summarised are the app’s.{' '}
        <button type="button" className="link-btn" onClick={() => ask('app-agents')}>
          Change in The app
        </button>
      </p>
      {sheet && (
        <button type="button" className="btn btn-small" onClick={() => ask('chat')}>
          All settings
        </button>
      )}
    </div>
  )
}

type Chat = NonNullable<ReturnType<typeof useApp.getState>['conv']>['conversation']

/** Who picks the chat's teams, and the ones picked. */
function teamsSaid(chat: Chat, teams: { id: string; name: string }[]): string {
  const picked = chat.teams.map(row => teams.find(team => team.id === row.team_id)?.name ?? 'a team deleted since')
  return `${TEAMS[chat.teams_mode]}${picked.length > 0 ? `: ${picked.join(', ')}` : ''}`
}

/** Where its agents work, and how many other folders it has. */
function foldersSaid(chat: Chat, project: Project | null): string {
  const more = chat.also_in.length + chat.read_in.length
  return `${project ? `${project.name} · ${chat.part ?? 'the whole project'}` : 'No folder'}${more > 0 ? ` · and ${more} more` : ''}`
}

/** A row set in a panel of the chat's own: in the sheet a button opens that panel; on the page, where it is is said. */
function Elsewhere({ label, value, button, where, open }: { label: string; value: string; button: string; where: string; open?: () => void }) {
  return (
    <div className="set-row">
      <span className="set-name">{label}</span>
      <span className="set-value">
        {value}
        {open ? (
          <button type="button" className="link-btn" onClick={open}>
            {button}
          </button>
        ) : (
          <span className="choice-note">{where}</span>
        )}
      </span>
    </div>
  )
}

/** "Always run in this chat", also offered over a page's preview. */
function PageScripts({ on }: { on: boolean }) {
  const [error, setError] = useState<string | null>(null)
  const choose = (always: boolean) => {
    setError(null)
    useApp.getState().setPageScripts(always).catch(err => setError(errorText(err)))
  }
  return (
    <div className="set-row">
      <label className="set-name" htmlFor="page-scripts">
        Page scripts
      </label>
      <span className="set-value">
        <select id="page-scripts" className="input" value={on ? 'always' : 'ask'} onChange={e => choose(e.target.value === 'always')}>
          <option value="ask">Ask each time</option>
          <option value="always">Always run in this chat</option>
        </select>
        <span className="choice-note">A page an agent shows in the Workspace. A page’s script can reach outside KOLONİ.</span>
        {error && (
          <span role="alert" className="alert">
            {error}
          </span>
        )}
      </span>
    </div>
  )
}

/** What runs without asking: a project's chat's are kept in This project; a plain chat keeps its own here. */
function Runs({ inProject, onRules }: { inProject: boolean; onRules: () => void }) {
  const conv = useApp(s => s.conv)
  if (!conv) return null
  const id = conv.conversation.id
  const store = useApp.getState()
  return (
    <div className="set-row">
      <span className="set-name">Runs without asking</span>
      <span className="set-value">
        {inProject ? (
          <button type="button" className="btn btn-small" onClick={onRules}>
            {conv.allowedCommands.length + conv.allowedWeb.length} run without asking →
          </button>
        ) : (
          // (A plain chat's own: it has no project to keep them in.)
          <AllowList
            rules={conv.allowedCommands}
            web={conv.allowedWeb}
            onRemove={ruleId => void store.removeRule(ruleId)}
            onRemoveWeb={ruleId => void store.removeWebRule(ruleId)}
            onAllowHost={host => store.allowHost(id, host)}
            onAskFirst={(ruleId, askFirst) => void store.setAskFirst(ruleId, askFirst)}
            onAllowSite={(host, askFirst) => store.allowSite(id, host, askFirst)}
          />
        )}
      </span>
    </div>
  )
}

/** What the chat takes from its project, read only, and the way to where it is set. */
function FromProject({ project, onOpen }: { project: Project; onOpen: () => void }) {
  return (
    <section aria-label={`From ${project.name}`} className="chat-sheet-from">
      <h3 className="kicker">From {project.name}</h3>
      <dl>
        {fromProject(project).map(([name, value]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <button type="button" className="link-btn" onClick={onOpen}>
        Change in This project
      </button>
    </section>
  )
}
