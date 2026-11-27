import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Budget, OthersInstructions, Project } from '../api/types'
import { ProjectMap } from './ProjectMap'
import { useAgents } from './sections/Agents'
import { type AskedFor, useAsking } from './sections/Asked'
import { useChecks } from './sections/Checks'
import { useLimits } from './sections/Limits'
import { useMemoryWeb } from './sections/MemoryWeb'
import { useNotifications } from './sections/Notifications'
import { own, type Part, Said, SaveBar, type Setter } from './sections/part'
import { folderSaid } from './sections/said'
import { changes } from './sections/usual'

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
  /** 0.1.8: the longest a command (KOLONİ's own test runs too) may take, 10 to 60 minutes. Sent only when changed. */
  longest_command?: number
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
  notify_desktop?: boolean
  /** "HH:MM": when the day's summary is sent; null: it is not. Sent only when changed. */
  day_note_at?: string | null
  /** The most tokens a turn may report before it is stopped; null takes the limit away. Sent only when changed. */
  turn_token_limit?: number | null
  /** What a calendar month's turns may cost, in the prices' currency; null: no budget. Sent only when changed. */
  monthly_budget?: number | null
  /** K-evrim: the command that scores a candidate's work - the last line of its output, 0–100; empty: none. Sent only when changed. */
  measure_command?: string
  /** Kanıtlı bitiş: what KOLONİ checks after a turn that changed code - Test and review, Tests only or Nothing. Sent only when changed. */
  after_change?: Project['after_change']
  /** S11: the rounds spent and a test still failing, the next stronger tier tries. Sent only when changed. */
  stronger_model?: boolean
  /** S3: how often failing tests and the Reviewer's blocking findings go back - 1 to 10, or "until" it passes (k-canli-016). Sent only when changed. */
  fix_rounds?: number | 'until'
  /** S5a: Check by kind of work - the kinds switched, merged into the project's. Sent only when changed. */
  check_kinds?: Record<string, boolean>
  /** S1b: forget the test command KOLONİ found and saved, and its look; found again at the next change. */
  forget_tests_found?: boolean
  /** Whether what is taken from a sub-agent is offered for a commit. Sent only when changed. */
  git_commit?: boolean
  /** K-dal-takim D2: how a team's finished branch reaches yours - merged here, or as a pull request. Sent only when changed. */
  finish_way?: 'merge' | 'pull_request'
  /** Whether the Scout suggests follow-up tasks after each turn, and from which tier. Sent only when changed. */
  suggest_tasks?: boolean
  suggest_tier?: Project['suggest_tier']
  /** tek-ev: every chat's sub-agent settings, the project's. Each sent only when changed. */
  lead_work?: Project['lead_work']
  when_away?: Project['when_away']
  away_minutes?: number
  spawn_approval?: Project['spawn_approval']
  /** 0.1.9: whether Full auto's judge looks at each command the list does not stop. Sent only when changed. */
  full_auto_judge?: boolean
  /** §8: whether it also lets a harmful-looking command a line of yours names run. Sent only when changed. */
  judge_words?: boolean
  /** What it does with a command it finds risky: refused, its agent goes on, or a card. Sent only when changed. */
  judge_risky?: Project['judge_risky']
  /** Coordination §4: whether a delete KOLONİ checks is disposable goes without a card. Sent only when changed. */
  disposable_deletes?: boolean
  spawn_max_depth?: number
  spawn_max_agents?: number
  spawn_max_parallel?: number
  /** null takes the limit away. */
  discussion_budget?: number | null
  /** Whether a fast model notes what a finished turn found. Sent only when changed. */
  auto_notes?: boolean
  /** 22c: the other projects whose memory an agent's recall also looks in (ids): the whole list. Sent only when changed. */
  memory_links?: string[]
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
  /** A place asked for (Ctrl+K, a chat's "run without asking" link), each time with a new count: its section shown - and
   *  what it names in it, where that is folded - and what is not saved elsewhere stays. */
  picked?: { section: ProjectPlace; n: number }
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

/** Where it asks commands to run, or only the Docker image they use (false: neither is asked). */
function commandsAsked(asks: Project['koloni']['asks'], project: Project) {
  const where = asks.exec_location ?? project.exec_location
  const image = 'docker_image' in asks ? asks.docker_image : project.docker_image
  return asks.exec_location || (where === 'docker' && 'docker_image' in asks)
    ? where === 'docker'
      ? `run commands in Docker image ${image}`
      : 'run commands on this machine'
    : 'docker_image' in asks && `use the Docker image ${image ?? 'none'}`
}

/** What the folder’s .koloni/settings.json asks for that is not saved here, in words: “run commands in Docker image X, with network access”. */
function askedFor(asks: Project['koloni']['asks'], project: Project): string {
  const parts = [
    commandsAsked(asks, project),
    'docker_network' in asks && (asks.docker_network ? 'with network access' : 'without network access'),
    asks.search_order &&
      (asks.search_order === 'cli' ? 'search with a CLI first' : 'search with the built-in search first'),
  ]
  return parts.filter(Boolean).join(', ')
}

export type Section = 'agents' | 'asking' | 'checks' | 'limits' | 'memory' | 'notifications' | 'folder'

/** This project's sections (0.1.10: by job, and fewer), in order. */
export const SECTIONS: [Section, string][] = [
  ['agents', 'How agents work'],
  ['asking', 'When you’re asked'],
  ['checks', 'When the work is done'],
  ['limits', 'Limits and money'],
  ['memory', 'Memory and web'],
  ['notifications', 'Notifications'],
  ['folder', 'This folder'],
]

/**
 * The sections before 0.1.10 and what was folded into one now: the section that holds it, and what opens there - its
 * More, or the rules. A link, Ctrl+K and the old names still find them.
 */
const MOVED = {
  'new-chats': ['agents', 'more', 'New chats start with'],
  'own-commands': ['agents', 'more', 'Slash commands'],
  rules: ['asking', 'rules', 'Runs without asking'],
  commands: ['asking', 'more', 'Commands and secrets'],
  'more-limits': ['limits', 'more', ''],
} as const satisfies Record<string, [Section, AskedFor['what'], string]>

/** A place in This project a link or Ctrl+K may ask for. */
export type ProjectPlace = Section | keyof typeof MOVED

/** A section's names before 0.1.10, which Ctrl+K still finds it by. */
export const OLD_NAMES: Partial<Record<Section, string[]>> = {
  agents: ['Agents', MOVED['new-chats'][2], MOVED['own-commands'][2]],
  asking: ['Asking and away', MOVED.rules[2], MOVED.commands[2]],
  checks: ['Checks and git'],
}

/** A place asked for: its section, and what opens in it then (each time with a new count). */
function opened(picked: { section: ProjectPlace; n: number }): [Section, Opening | undefined] {
  if (!(picked.section in MOVED)) return [picked.section as Section, undefined]
  const [section, what] = MOVED[picked.section as keyof typeof MOVED]
  return [section, { section, what, n: picked.n }]
}
type Opening = AskedFor & { section: Section }

/** Under a section's Save, once it is saved and not changed since: that it is - and, by the save that put the settings into the folder, that. */
const savedSaid = (saved: boolean, keptBefore: boolean, koloni: Project['koloni'] | undefined) =>
  saved ? (!keptBefore && koloni?.settings_kept ? KEPT_IN_FOLDER : 'Saved') : ''

const alone = (sections: ReactNode) => (
  <nav className="agents-list" aria-label="Project settings sections">
    {sections}
  </nav>
)

/** Settings › This project: the project's sections listed on the left, the chosen one on the right with a Save of its own. */
export function ProjectSettings({
  project,
  dockerAvailable,
  dockerError,
  desktopAvailable,
  shell,
  shellNote,
  onSave,
  onUseKoloni,
  picked,
  spend = null,
  chat,
  levels = alone,
  toApp,
  children,
}: Props) {
  const [first, firstOpening] = picked ? opened(picked) : (['agents', undefined] as const)
  const [section, setSection] = useState<Section>(first)
  const [opening, setOpening] = useState<Opening | undefined>(firstOpening)
  const [asked, setAsked] = useState(picked?.n)
  if (picked && picked.n !== asked) {
    setAsked(picked.n)
    const [now, then] = opened(picked)
    setSection(now)
    setOpening(then)
  }
  // What a link asked to open in a section, each time with a new count.
  const opens = (at: Section, what: AskedFor['what']) =>
    opening?.section === at && opening.what === what ? opening.n : undefined
  // (Every section's, each time: what is typed in one stays while another is shown.)
  const parts: Record<Section, Part> = {
    agents: useAgents(project, opens('agents', 'more')),
    asking: useAsking(
      project,
      { dockerAvailable, dockerError, shell, shellNote },
      chat,
      opening?.section === 'asking' ? opening : undefined,
    ),
    checks: useChecks(project, section === 'checks'),
    limits: useLimits(project, spend, toApp, opens('limits', 'more')),
    memory: useMemoryWeb(project),
    notifications: useNotifications(project, desktopAvailable),
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
          <FolderNotes
            project={project}
            koloni={koloni}
            onUseKoloni={onUseKoloni}
            take={now => [parts.asking, parts.memory].forEach(one => one.take?.(now))}
          />
          {shown.view}
          {error?.section === section && (
            <div role="alert" className="alert">
              {error.text}
            </div>
          )}
          {!shown.own && (
            <SaveBar
              changed={shown.changed}
              valid={shown.valid}
              busy={busy}
              said={changes(project, shown.patch)}
              saved={savedSaid(savedSection === section && !shown.changed, keptBefore, koloni)}
            />
          )}
        </div>
      </form>
      {section === 'folder' && children}
    </>
  )
}

/** This folder: what of the project it keeps, its map and its rules (and, after the form, Delete project). */
function ThisFolder({ project }: { project: Project }) {
  const koloni = project.koloni as Project['koloni'] | undefined
  const rules = koloni?.rules
  return (
    <>
      <Said title="This folder">{folderSaid(koloni)}</Said>
      <ProjectMap project={project} />
      {rules && (
        <section aria-label="This folder’s rules" className="field">
          <h2>This folder’s rules</h2>
          <span className="choice-note">
            From .koloni/rules.md, kept in git: every agent working here is given them. You change them on the Memory
            page.
          </span>
          <div className="memory-lines">
            <pre>{rules}</pre>
          </div>
        </section>
      )}
    </>
  )
}

/** Over every section: another project's agent instructions found here, a .koloni/ file not read, and what .koloni/settings.json asks. */
function FolderNotes({
  project,
  koloni,
  onUseKoloni,
  take,
}: {
  project: Project
  koloni: Project['koloni'] | undefined
  onUseKoloni?: Props['onUseKoloni']
  take: (now: Project) => void
}) {
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
          {others.more > 0 && ` +${others.more} more`} (CLI agents load them by themselves)
          {others.partial && '. Not every folder was looked in'}
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

function Asks({
  asks,
  takeThem,
  setNotNow,
  useError,
}: {
  asks: string
  takeThem: () => Promise<void>
  setNotNow: Setter<boolean>
  useError: string | null
}) {
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
