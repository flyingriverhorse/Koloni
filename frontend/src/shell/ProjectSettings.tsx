import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import { ProjectRules } from '../commands/ProjectRules'
import { ProjectSites } from '../commands/Sites'
import type { Budget, OthersInstructions, Project } from '../api/types'
import { OwnCommands } from './OwnCommands'
import { ProjectMap } from './ProjectMap'
import { useAgents, useAsking } from './sections/Agents'
import { useChecks } from './sections/Checks'
import { useCommands } from './sections/Commands'
import { useLimits } from './sections/Limits'
import { useMemoryWeb } from './sections/MemoryWeb'
import { useNewChats } from './sections/NewChats'
import { useNotifications } from './sections/Notifications'
import { own, type Part, type Setter } from './sections/part'

export { Row } from './sections/part'
export { LEAD_WORK } from './sections/Agents'

export interface ProjectSettingsValues {
  /** Where commands run: the three are sent together, and only by the Commands section's Save. */
  exec_location?: Project['exec_location']
  docker_image?: string | null
  docker_network?: boolean
  /** Whether commands see secret files as denied or empty, and the secret variables they are given all the same: each sent only when changed, with the three above. */
  hide_secrets?: boolean
  pass_env?: string
  /** The most agents at work at once in all the project's conversations; null: no limit. Sent only when changed. */
  max_agents?: number | null
  /** K-devam-butce: the steps a stopped agent gets on top when told to go on with none left. Sent only when changed. */
  continue_steps?: number
  /** 101: whether each turn's commands get a planted test key that stops the turn if sent out. Sent only when changed. */
  canary?: boolean
  /** The web settings: each is sent only when it was changed. Empty: none. */
  search_url?: string
  search_order?: Project['search_order']
  search_agy?: boolean
  notify_url?: string
  notify_format?: Project['notify_format']
  notify_desktop?: boolean
  /** "HH:MM": when the day's summary is sent; null: it is not. Sent only when changed. */
  day_note_at?: string | null
  /** The most tokens a turn may report before it is stopped; null takes the limit away. Sent only when changed. */
  turn_token_limit?: number | null
  /** What a calendar month's turns may cost, in the prices' currency; null: no budget. Sent only when changed. */
  monthly_budget?: number | null
  /** The command that checks a sub-agent's work before it is taken; empty: none. Sent only when changed. */
  check_command?: string
  /** K-evrim: the command that scores a candidate's work - the last line of its output, 0–100; empty: none. Sent only when changed. */
  measure_command?: string
  /** 89m: whether a Claude Code agent that changed files finishes only once the tests pass; null: automatic again. Sent only when changed. */
  finish_tests?: boolean | null
  /** Whether what is taken from a sub-agent is offered for a commit. Sent only when changed. */
  git_commit?: boolean
  /** K-dal-takim D2: how a team's finished branch reaches yours - merged here, or as a pull request. Sent only when changed. */
  finish_way?: 'merge' | 'pull_request'
  /** Whether the Observer's model looks over each sub-agent's report. Sent only when changed. */
  observe_reports?: boolean
  /** Whether the Assistant PO suggests follow-up tasks after each turn, and from which tier. Sent only when changed. */
  suggest_tasks?: boolean
  suggest_tier?: Project['suggest_tier']
  /** tek-ev: every chat's sub-agent settings, the project's. Each sent only when changed. */
  lead_work?: Project['lead_work']
  when_away?: Project['when_away']
  away_minutes?: number
  spawn_approval?: Project['spawn_approval']
  spawn_max_depth?: number
  spawn_max_agents?: number
  spawn_max_parallel?: number
  /** null takes the limit away. */
  discussion_budget?: number | null
  room_posts?: number | null
  room_tokens?: number | null
  room_minutes?: number | null
  /** Whether a fast model notes what a finished turn found. Sent only when changed. */
  auto_notes?: boolean
  /** 22c: the other projects whose memory an agent's recall also looks in (ids): the whole list. Sent only when changed. */
  memory_links?: string[]
  /** 22c, from the Memory page: the provider whose server embeds for the search by meaning (null: off), and the model name. */
  embedding_provider_id?: string | null
  embedding_model?: string
  /** The extra folders a new chat in this folder starts with (slice 86b), to work and to read only in: each whole list. */
  also_in?: string[]
  read_in?: string[]
  /** The teams a new chat in this folder starts with (slice 84b), from "Teams for this chat". */
  teams_mode?: Project['teams_mode']
  teams?: Project['teams']
}

interface Props {
  project: Project
  dockerAvailable: boolean
  dockerError: string | null
  /** Whether this system can show a desktop notification at all. */
  desktopAvailable: boolean
  /** The shell commands on this machine run in (/health); not given or null until known. */
  shell?: string | null
  /** Why a PowerShell 7 that is there is not used (/health.shell_note); null when it is, or there is none. */
  shellNote?: string | null
  onSave: (values: ProjectSettingsValues) => Promise<void>
  /** The user's yes to what the folder's .koloni/settings.json asks for, as the card showed it; the project as it is then saved. */
  onUseKoloni?: (asks: Project['koloni']['asks']) => Promise<Project>
  /** A section asked for (Ctrl+K, a chat's "run without asking" link), each time with a new count: shown, and what is not saved elsewhere stays. */
  picked?: { section: Section; n: number }
  /** This month's spend against the budget, as last read: its currency, and whether the budget is enforced. */
  spend?: Budget | null
  /** The open chat of this project: listed under Runs without asking even with none. */
  chat?: { id: string; title: string }
  /** The list the sections stand in (Settings: under "This project", among the levels); alone, a list of its own. */
  levels?: (sections: ReactNode) => ReactNode
  /** The app's step limit, from Limits and money. */
  toApp?: () => void
  /** Under This folder, after the form: Delete project (it has a form of its own). */
  children?: ReactNode
}

/** "Answer in"'s short list; any other language is typed. Auto: the agents answer in the language you write in. */
export const LANGUAGES = ['Auto', 'English', 'Türkçe', 'Deutsch', 'Español', 'Français', 'Italiano', 'Português']

/** Said once, by the save that put a setting or the rules into the folder’s .koloni/ (slice 86c). */
export const KEPT_IN_FOLDER = 'Saved in .koloni/ in this folder (kept in git)'

/** What the folder’s .koloni/settings.json asks for that is not saved here, in words: “run commands in Docker image X, with network access”. */
function askedFor(asks: Project['koloni']['asks'], project: Project): string {
  const where = asks.exec_location ?? project.exec_location
  const image = 'docker_image' in asks ? asks.docker_image : project.docker_image
  const parts = [
    asks.exec_location || (where === 'docker' && 'docker_image' in asks)
      ? where === 'docker' ? `run commands in Docker image ${image}` : 'run commands on this machine'
      : 'docker_image' in asks && `use the Docker image ${image ?? 'none'}`,
    'docker_network' in asks && (asks.docker_network ? 'with network access' : 'without network access'),
    asks.search_order && (asks.search_order === 'cli' ? 'search with a CLI first' : 'search with the built-in search first'),
  ]
  return parts.filter(Boolean).join(', ')
}

export type Section = 'agents' | 'asking' | 'new-chats' | 'limits' | 'commands' | 'rules' | 'checks' | 'memory' | 'notifications' | 'own-commands' | 'folder'

/** This project's sections (sample A), in order. */
export const SECTIONS: [Section, string][] = [
  ['agents', 'Agents'],
  ['asking', 'Asking and away'],
  ['new-chats', 'New chats start with'],
  ['limits', 'Limits and money'],
  ['commands', 'Commands and secrets'],
  ['rules', 'Runs without asking'],
  ['checks', 'Checks and git'],
  ['memory', 'Memory and web'],
  ['notifications', 'Notifications'],
  // (Your own; "Commands and secrets" is where they run.)
  ['own-commands', 'Slash commands'],
  ['folder', 'This folder'],
]

const alone = (sections: ReactNode) => (
  <nav className="agents-list" aria-label="Project settings sections">
    {sections}
  </nav>
)

/** Settings › This project: the project's sections listed on the left, the chosen one on the right with a Save of its own. */
export function ProjectSettings({ project, dockerAvailable, dockerError, desktopAvailable, shell, shellNote, onSave, onUseKoloni, picked, spend = null, chat, levels = alone, toApp, children }: Props) {
  const [section, setSection] = useState<Section>(picked?.section ?? 'agents')
  const [asked, setAsked] = useState(picked?.n)
  if (picked && picked.n !== asked) {
    setAsked(picked.n)
    setSection(picked.section)
  }
  // (Every section's, each time: what is typed in one stays while another is shown.)
  const parts: Record<Section, Part> = {
    agents: useAgents(project),
    asking: useAsking(project),
    'new-chats': useNewChats(project),
    limits: useLimits(project, spend, toApp),
    commands: useCommands(project, { dockerAvailable, dockerError, shell, shellNote }),
    rules: own(<Rules projectId={project.id} chat={chat} />),
    checks: useChecks(project, section === 'checks'),
    memory: useMemoryWeb(project),
    notifications: useNotifications(project, desktopAvailable),
    // shortcut: a command half written here is dropped when another section is chosen (no "not saved" mark); keep it mounted if that bites.
    'own-commands': own(<OwnCommands projectId={project.id} />),
    folder: own(<ThisFolder project={project} />),
  }
  const shown = parts[section]
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ section: Section; text: string } | null>(null)
  // The section last saved, said under its Save until it is changed again.
  const [savedSection, setSaved] = useState<Section | null>(null)
  // Whether .koloni/settings.json was there before the last save: the save that put it there says so, once.
  const [keptBefore, setKeptBefore] = useState(true)
  // (A server older than the page has no .koloni/ to say anything of.)
  const koloni = project.koloni as Project['koloni'] | undefined

  async function submit(event: FormEvent) {
    event.preventDefault()
    // Their own controls save; Enter in their fields sends nothing.
    if (shown.own) return
    // (Another section may be chosen while this one is saved: what comes back stays with this one.)
    const saving = section
    setBusy(true)
    setError(null)
    setSaved(null)
    setKeptBefore(koloni?.settings_kept ?? true)
    try {
      await onSave(shown.patch)
      shown.saved?.()
      setSaved(saving)
    } catch (err) {
      setError({ section: saving, text: errorText(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <form className="agents-page project-settings" aria-label="Project settings" onSubmit={submit}>
        {levels(
          SECTIONS.map(([key, name]) => (
            <button
              key={key}
              type="button"
              className="conv-row agents-row"
              aria-current={section === key ? 'true' : undefined}
              // The mark describes the row rather than naming it: "not saved" in a name would be found as a "Save" button.
              aria-describedby={parts[key].changed ? `unsaved-${key}` : undefined}
              onClick={() => setSection(key)}
            >
              <span className="conv-row-title">{name}</span>
              {parts[key].changed && (
                <span id={`unsaved-${key}`} className="tag" aria-hidden="true">
                  not saved
                </span>
              )}
            </button>
          )),
        )}
        <div className="role-editor">
          <FolderNotes project={project} koloni={koloni} onUseKoloni={onUseKoloni} take={now => [parts.commands, parts.memory].forEach(one => one.take?.(now))} />
          {shown.view}
          {error?.section === section && (
            <div role="alert" className="alert">
              {error.text}
            </div>
          )}
          {!shown.own && (
            <div className="role-actions">
              <button type="submit" className="btn btn-primary" disabled={busy || !shown.valid || !shown.changed}>
                Save
              </button>
              <span role="status" className="muted">
                {savedSection === section && !shown.changed ? (!keptBefore && koloni?.settings_kept ? KEPT_IN_FOLDER : 'Saved') : ''}
              </span>
            </div>
          )}
        </div>
      </form>
      {section === 'folder' && children}
    </>
  )
}

/** Runs without asking: the project's sites, then each chat's commands and requests. */
function Rules({ projectId, chat }: { projectId: string; chat?: { id: string; title: string } }) {
  // The project's sites, counted into each chat's "run without asking" as the chat's own link counts them.
  const [siteCount, setSiteCount] = useState(0)
  return (
    <>
      <h2>Runs without asking</h2>
      <ProjectSites projectId={projectId} onCount={setSiteCount} />
      <ProjectRules projectId={projectId} chat={chat} sites={siteCount} />
    </>
  )
}

/** This folder: its map and its rules (and, after the form, Delete project). */
function ThisFolder({ project }: { project: Project }) {
  const rules = (project.koloni as Project['koloni'] | undefined)?.rules
  return (
    <>
      <ProjectMap project={project} />
      {rules && (
        <section aria-label="This folder’s rules" className="field">
          <h2>This folder’s rules</h2>
          <span className="choice-note">From .koloni/rules.md, kept in git: every agent working here is given them. You change them on the Memory page.</span>
          <div className="memory-lines">
            <pre>{rules}</pre>
          </div>
        </section>
      )}
    </>
  )
}

/** Over every section: another project's agent instructions found here, a .koloni/ file not read, and what .koloni/settings.json asks. */
function FolderNotes({ project, koloni, onUseKoloni, take }: { project: Project; koloni: Project['koloni'] | undefined; onUseKoloni?: Props['onUseKoloni']; take: (now: Project) => void }) {
  // What the folder's settings ask for, until "Not now": asked again when the page is opened again.
  // shortcut: asked only here, not when the folder is opened; show it in the chat if users miss it.
  const [notNow, setNotNow] = useState(false)
  const [useError, setUseError] = useState<string | null>(null)
  const asks = koloni && !notNow && Object.keys(koloni.asks).length > 0 ? askedFor(koloni.asks, project) : ''
  // Another project's CLAUDE.md, AGENTS.md, .claude/... below this folder (K-yabanci-talimat): looked for once the page opens.
  // shortcut: said only here, not in the chat when a CLI agent starts; add a note there if users miss it.
  const [others, setOthers] = useState<OthersInstructions | null>(null)
  useEffect(() => {
    // (Not looked for, or an older server: nothing to say.)
    api.get<OthersInstructions>(`/projects/${project.id}/others-instructions`).then(setOthers, () => {})
  }, [project.id])

  async function takeThem() {
    if (!onUseKoloni || !koloni) return
    setUseError(null)
    try {
      // The form shows what is saved now, with nothing of it left to save.
      take(await onUseKoloni(koloni.asks))
    } catch (err) {
      setUseError(errorText(err))
    }
  }

  return (
    <>
      {others && others.paths.length > 0 && (
        <p className="alert">
          Another project’s agent instructions are in this folder: {others.paths.join(', ')}
          {others.more > 0 && ` +${others.more} more`} (CLI agents load them by themselves){others.partial && '. Not every folder was looked in'}
        </p>
      )}
      {koloni?.broken.map(line => (
        <p key={line} className="alert">
          {line}
        </p>
      ))}
      {asks && <Asks asks={asks} takeThem={takeThem} setNotNow={setNotNow} useError={useError} />}
    </>
  )
}

function Asks({ asks, takeThem, setNotNow, useError }: { asks: string; takeThem: () => Promise<void>; setNotNow: Setter<boolean>; useError: string | null }) {
  return (
    <div role="group" aria-label="This folder’s settings" className="alert">
      <span>This folder’s settings ask to {asks} — use them?</span>
      <div className="role-actions">
        <button type="button" className="btn btn-small btn-primary" onClick={() => void takeThem()}>
          Use them
        </button>
        <button type="button" className="btn btn-small" onClick={() => setNotNow(true)}>
          Not now
        </button>
      </div>
      {useError && <span role="alert">{useError}</span>}
    </div>
  )
}
