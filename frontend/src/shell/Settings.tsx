import { X } from '@phosphor-icons/react'
import { type ComponentProps, type FormEvent, Fragment, type ReactNode, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { AnswerLanguage, ExperimentalClis, Folders, Project, Storage } from '../api/types'
import { Backup } from './Backup'
import { DeleteProject } from './DeleteProject'
import { FoldersSection } from './Folders'
import { GUIDE } from './guide'
import { KeptCopies } from './KeptCopies'
import { LANGUAGES, ProjectSettings, Row, type Section } from './ProjectSettings'
import { JudgeModel } from './sections/JudgeModel'
import { experimentalChanged } from '../models/experimental'
import { VoiceSettings } from '../voice/VoiceControls'
import { ChatSheet } from '../chat/ChatSheet'
import { useApp } from '../state/store'

type Level = 'chat' | 'project' | 'app'

/** The app's sections, as This project's are listed. */
export type AppSection = 'app-agents' | 'voice' | 'data'
export const APP_SECTIONS: [AppSection, string][] = [
  ['app-agents', 'Agents'],
  ['voice', 'Voice'],
  ['data', 'Your data'],
]

/** Where Settings may be asked to open (Ctrl+K, a link): This chat, a section of This project's, or of the app's. */
export type SettingsPlace = 'chat' | Section | AppSection

const isApp = (place: SettingsPlace): place is AppSection => APP_SECTIONS.some(([key]) => key === place)

type Props = Omit<ComponentProps<typeof ProjectSettings>, 'project' | 'picked' | 'levels' | 'toApp' | 'children'> & {
  /** The open chat's folder; none for a plain chat: then only The app. */
  project: Project | null
  /** A place asked for, each time with a new count: Settings shows it. */
  picked?: { section: SettingsPlace; n: number }
  onClose: () => void
}

/**
 * Settings (sample A): one place, its levels in a fixed order - This chat › This project › The app - listed on the
 * left with their sections. Each setting is set at one level; a chat shows what it takes from above, read only. Every
 * level is kept while another is shown: what was typed in one is still there.
 */
export function Settings({ project, onClose, picked, ...rest }: Props) {
  const [level, setLevel] = useState<Level>(project ? 'project' : 'app')
  const [appSection, setAppSection] = useState<AppSection>('app-agents')
  // This project's section asked for, each time with a new count.
  const [projectAsk, setProjectAsk] = useState<{ section: Section; n: number } | undefined>(undefined)
  const go = (place: SettingsPlace) => {
    if (place === 'chat') setLevel('chat')
    else if (isApp(place)) {
      setLevel('app')
      setAppSection(place)
    } else {
      setLevel('project')
      setProjectAsk(asked => ({ section: place, n: (asked?.n ?? 0) + 1 }))
    }
  }
  const [asked, setAsked] = useState<number | undefined>(undefined)
  if (picked && picked.n !== asked) {
    setAsked(picked.n)
    go(picked.section)
  }
  const levels = useLevels(project)
  // (A level that is not there - no chat open, no folder - is not shown: the project's, else the app's.)
  const shown = levels.some(([one]) => one === level) ? level : project ? 'project' : 'app'
  useEffect(() => {
    // Shown from a button or link of another level's panel, now hidden: the focus goes to this level's own button,
    // where it would be lost with that panel.
    const at = document.activeElement
    if (at && at !== document.body && !at.closest('[hidden]')) return
    document.getElementById(`${shown}-level-button-${shown}`)?.focus()
  }, [shown])
  const list = (at: Level, sections: ReactNode) => (
    <Levels at={at} levels={levels} onLevel={setLevel}>
      {sections}
    </Levels>
  )

  return (
    <section className="settings-page" aria-label="Settings">
      <div className="settings-head">
        <h2>Settings</h2>
        <span className="muted settings-order">
          A chat takes what it does not set from its project, and the project from the app.
        </span>
        <button type="button" className="icon-btn" aria-label="Close settings" onClick={onClose}>
          <X size={14} />
        </button>
      </div>
      {levels[0][0] === 'chat' && (
        <div className="settings-panel" hidden={shown !== 'chat'}>
          <div className="agents-page">
            {list('chat', null)}
            <div className="role-editor">
              <h2>This chat</h2>
              <ChatSheet />
            </div>
          </div>
        </div>
      )}
      {project && (
        <div className="settings-panel settings-project" hidden={shown !== 'project'}>
          <ProjectSettings
            key={project.id}
            project={project}
            picked={projectAsk}
            levels={sections => list('project', sections)}
            toApp={() => go('app-agents')}
            {...rest}
          >
            <DeleteProject key={`delete-${project.id}`} project={project} />
          </ProjectSettings>
        </div>
      )}
      <div className="settings-panel" hidden={shown !== 'app'}>
        <div className="agents-page">
          {list(
            'app',
            APP_SECTIONS.map(([key, name]) => (
              <button
                key={key}
                type="button"
                className="conv-row agents-row"
                aria-current={appSection === key ? 'true' : undefined}
                onClick={() => setAppSection(key)}
              >
                <span className="conv-row-title">{name}</span>
              </button>
            )),
          )}
          <div className="role-editor">
            <div hidden={appSection !== 'app-agents'}>
              <AppSettings toLimits={project ? () => go('limits') : undefined} />
              <ExperimentalChoice />
              <JudgeModel />
            </div>
            {/* (Made when shown: it keeps nothing typed, each choice is kept as it is made.) */}
            {appSection === 'voice' && <VoiceSettings />}
            <div hidden={appSection !== 'data'}>
              <YourData shown={shown === 'app' && appSection === 'data'} />
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/** The levels there are, in their order, each with its name and what it covers. */
function useLevels(project: Project | null): [Level, string, string][] {
  const chat = useApp(s => s.conv?.conversation.title)
  return [
    ...(chat === undefined ? [] : [['chat', 'This chat', chat] as [Level, string, string]]),
    ...(project ? [['project', 'This project', `${project.name} · every chat of it`] as [Level, string, string]] : []),
    ['app', 'The app', 'every project'],
  ]
}

/** The levels, in their order, with the sections of the one shown under it. */
function Levels({
  at,
  levels,
  onLevel,
  children,
}: {
  at: Level
  levels: [Level, string, string][]
  onLevel: (level: Level) => void
  children: ReactNode
}) {
  return (
    <nav className="agents-list settings-levels" aria-label="Settings levels">
      {levels.map(([level, name, note]) => (
        <Fragment key={level}>
          <button
            type="button"
            id={`${at}-level-button-${level}`}
            className="settings-level"
            aria-current={level === at ? 'true' : undefined}
            aria-describedby={`${at}-level-${level}`}
            onClick={() => onLevel(level)}
          >
            {name}
          </button>
          <span id={`${at}-level-${level}`} className="muted settings-level-note">
            {note}
          </span>
          {level === at && children}
        </Fragment>
      ))}
    </nav>
  )
}

type WholeKey =
  'compact_at' | 'max_steps' | 'max_files' | 'max_mb' | 'stuck_minutes' | 'turn_hours' | 'runs_at_once' | 'workers'

/**
 * One whole-number setting of the app - `key` at `path`, from `low` to `high` - as the server keeps it (undefined
 * until read) and as typed: `at` is what is sent, undefined for anything else. `empty`: left empty it is null (none).
 */
function useWhole(
  path: string,
  key: WholeKey,
  low: number,
  high: number,
  failed: (why: string) => void,
  empty = false,
) {
  const [kept, setKept] = useState<number | null | undefined>(undefined)
  const [text, setText] = useState('')
  useEffect(() => {
    api.get<Record<string, number | null>>(path).then(
      read => {
        setKept(read[key])
        setText(read[key] === null ? '' : String(read[key]))
      },
      err => failed(errorText(err)),
    )
  }, [path, key, failed])
  const typed = text.trim()
  const value = Number(typed)
  const at = empty && typed === '' ? null : /^\d+$/.test(typed) && value >= low && value <= high ? value : undefined
  return {
    kept,
    text,
    setText,
    at,
    bad: kept !== undefined && at === undefined,
    changed: kept !== undefined && at !== kept,
    save: async () => setKept((await api.put<Record<string, number | null>>(path, { [key]: at }))[key]),
  }
}

/** A `useWhole` setting's line: its input, its why behind ⓘ, and what it takes where what is typed is not that. */
function WholeRow({
  id,
  label,
  why,
  setting,
  low,
  high,
  also,
  placeholder,
}: {
  id: string
  label: string
  why: string
  setting: ReturnType<typeof useWhole>
  low: number
  high: number
  also?: ReactNode
  placeholder?: string
}) {
  return (
    <Row
      label={label}
      htmlFor={id}
      whyId={`${id}-more`}
      doc={GUIDE.settingsApp}
      why={why}
      warn={
        <>
          {setting.bad && (
            <span className="choice-note">
              A whole number from {low} to {high}
              {placeholder && ', or empty'}.
            </span>
          )}
          {also}
        </>
      }
    >
      <input
        id={id}
        className="input mono set-short"
        inputMode="numeric"
        value={setting.text}
        placeholder={placeholder}
        disabled={setting.kept === undefined}
        aria-invalid={setting.bad || undefined}
        aria-describedby={`${id}-more`}
        onChange={e => setting.setText(e.target.value)}
      />
    </Row>
  )
}

const TREE_HINT =
  'For every project: knowledge from a repository or a folder stops before it reads more than this. A learning at work keeps what it started with.'

/** Where Continue's extra steps are set: each project's. */
function ContinueNote({ toLimits }: { toLimits?: () => void }) {
  return (
    <span className="choice-note">
      Continue’s extra steps are each project’s:{' '}
      {toLimits ? (
        <button type="button" className="link-btn" onClick={toLimits}>
          This project › Limits and money
        </button>
      ) : (
        'This project › Limits and money'
      )}
      .
    </span>
  )
}

/** "Answer in" as it is sent: spaces once between its words, "auto" in any case as ''. */
const tidied = (text: string) => (/^auto$/i.test(text.trim()) ? '' : text.trim().replace(/ +/g, ' '))
/** Auto (''), or a language's name: at most 40 letters, spaces and hyphens. */
const isLanguage = (sent: string) => sent === '' || (sent.length <= 40 && /^\p{L}+(?:[ -]\p{L}+)*$/u.test(sent))

/** Settings › The app › Agents: what holds in every project - the language agents write in, when a chat is compacted, how many steps an agent may take. */
function AppSettings({ toLimits }: { toLimits?: () => void }) {
  // As the server keeps them (undefined until read), and as typed. '' is Auto.
  const [language, setLanguage] = useState<string | undefined>(undefined)
  const [languageText, setLanguageText] = useState('')
  const [readError, setReadError] = useState<string | null>(null)
  const compaction = useWhole('/compaction', 'compact_at', 50, 95, setReadError)
  const steps = useWhole('/steps', 'max_steps', 5, 200, setReadError)
  // (app/away.py STUCK_RANGE, CEILING_RANGE: the source of truth)
  const stuck = useWhole('/unattended', 'stuck_minutes', 5, 1440, setReadError)
  const ceiling = useWhole('/unattended', 'turn_hours', 1, 72, setReadError, true)
  // (app/knowledge.py FILES_RANGE, MB_RANGE: the source of truth)
  const treeFiles = useWhole('/knowledge-limits', 'max_files', 100, 1_000_000, setReadError)
  const treeMb = useWhole('/knowledge-limits', 'max_mb', 1, 10_240, setReadError)
  // (app/proof.py TEST_RUNS_RANGE, TEST_WORKERS_RANGE: the source of truth)
  const testRuns = useWhole('/test-load', 'runs_at_once', 1, 4, setReadError)
  const testWorkers = useWhole('/test-load', 'workers', 1, 16, setReadError)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    api.get<AnswerLanguage>('/answer-in').then(
      read => {
        setLanguage(read.answer_in ?? '')
        setLanguageText(read.answer_in ?? '')
      },
      err => setReadError(errorText(err)),
    )
  }, [])
  // As the server tidies it; "Auto" is ''. A language's name only - it goes into every agent's brief.
  const languageSent = tidied(languageText)
  const languageValid = isLanguage(languageSent)
  const languageChanged = language !== undefined && languageSent !== language
  const wholes = [compaction, steps, stuck, ceiling, treeFiles, treeMb, testRuns, testWorkers]
  const valid = languageValid && wholes.every(one => !one.bad)
  const changed = languageChanged || wholes.some(one => one.changed)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      for (const one of wholes) if (one.changed) await one.save()
      if (languageChanged)
        setLanguage((await api.put<AnswerLanguage>('/answer-in', { answer_in: languageSent || null })).answer_in ?? '')
      setSaved(true)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="settings-app-form" aria-label="App settings" onSubmit={submit}>
      <h2>Agents</h2>
      {readError && (
        <p role="alert" className="alert">
          The app’s settings could not be read: {readError}
        </p>
      )}
      <Row
        label="Answer in"
        htmlFor="answer-in"
        whyId="answer-in-more"
        doc={GUIDE.settingsApp}
        why="The language the agents write in, in every project. Auto: the language you write in. KOLONİ’s own screens stay in English."
        warn={
          !languageValid && (
            <span className="choice-note">A language’s name: at most 40 letters, spaces and hyphens.</span>
          )
        }
      >
        <input
          id="answer-in"
          className="input"
          list="answer-in-languages"
          value={languageText}
          placeholder="Auto"
          disabled={language === undefined}
          aria-invalid={!languageValid || undefined}
          aria-describedby="answer-in-more"
          onChange={e => setLanguageText(e.target.value)}
        />
        <datalist id="answer-in-languages">
          {LANGUAGES.map(name => (
            <option key={name} value={name} />
          ))}
        </datalist>
      </Row>
      <WholeRow
        id="max-steps"
        label="Steps an agent may take"
        setting={steps}
        low={5}
        high={200}
        why="For every project: the most model steps one sub-agent takes on a job before it stops. A team’s coordinator gets more for its recipe’s steps; a role’s own limit, where lower, still holds. The Orchestrator counts no steps: it stops when it goes round in circles, or at the Lead role’s own limit if you set one."
        also={<ContinueNote toLimits={toLimits} />}
      />
      <WholeRow
        id="stuck-minutes"
        label="Stuck after this many minutes with no progress"
        setting={stuck}
        low={5}
        high={1440}
        why="For every project, in a To-do task’s turn and in a job while you’re away: the Orchestrator’s turn ends, its work kept, once nothing has moved for this long - no file of the turn changed, no agent finished its work, no failing command passed. A card waiting for you, a command or a model step under way, or an agent below it at work is not nothing."
      />
      <WholeRow
        id="turn-hours"
        label="An unattended turn runs at most (hours)"
        setting={ceiling}
        low={1}
        high={72}
        placeholder="No limit"
        why="For every project: a To-do task’s turn or a job while you’re away ends after this many hours however it goes, its work kept - a last resort. Empty: no limit - a turn that keeps working (changes, agents at work, messages between agents) can then run without end."
      />
      <WholeRow
        id="compact-at"
        label="Summarise a long context at (%)"
        setting={compaction}
        low={50}
        high={95}
        why="For every project: once an agent’s context passes this much of its model’s window, the older part is summarised before its next step."
      />
      <WholeRow
        id="tree-files"
        label="Knowledge reads at most (files)"
        setting={treeFiles}
        low={100}
        high={1_000_000}
        why={TREE_HINT}
      />
      <WholeRow
        id="tree-mb"
        label="Knowledge reads at most (MB)"
        setting={treeMb}
        low={1}
        high={10_240}
        why={TREE_HINT}
      />
      <WholeRow
        id="test-runs"
        label="KOLONİ’s test runs at once"
        setting={testRuns}
        low={1}
        high={4}
        why="For every project: how many of the test runs KOLONİ makes at a turn’s end go at the same time; the rest wait their turn. More finishes sooner and loads the machine more. Agents’ own commands are not counted."
      />
      <WholeRow
        id="test-workers"
        label="Test processes per run"
        setting={testWorkers}
        low={1}
        high={16}
        why="For every project: how many processes one of KOLONİ’s test runs may start, where its runner reads it (pytest-xdist’s -n auto). Agents’ own commands are not limited."
      />
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="role-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || !valid || !changed}>
          Save
        </button>
        <span role="status" className="muted">
          {saved && !changed ? 'Saved' : ''}
        </span>
      </div>
    </form>
  )
}

/** Settings › The app › Agents, under its Save: whether the Models page offers what is experimental (0.1.8: agy;
 *  0.1.10: a CLI run Native) - kept as it is changed. */
function ExperimentalChoice() {
  const [show, setShow] = useState<boolean | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    api.get<ExperimentalClis>('/experimental-clis').then(
      read => setShow(read.show),
      err => setError(errorText(err)),
    )
  }, [])
  async function change(on: boolean) {
    setError(null)
    try {
      const saved = (await api.put<ExperimentalClis>('/experimental-clis', { show: on })).show
      setShow(saved)
      experimentalChanged(saved)
    } catch (err) {
      setError(errorText(err))
    }
  }
  return (
    <div className="settings-app-form">
      <label className="choice">
        <input
          type="checkbox"
          checked={show ?? false}
          disabled={show === undefined}
          onChange={e => void change(e.target.checked)}
        />
        <span>
          Show experimental features
          <span className="choice-note">
            Kept as you change it. Offers agy, and Native (a CLI with its own tools), under Experimental on the Models
            page: they are less measured than the rest. A provider already set up so works either way, tagged
            Experimental.
          </span>
        </span>
      </label>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
    </div>
  )
}

/** Settings › The app › Your data: a backup, what KOLONİ's data takes on this machine, and the places no agent opens - read once shown. */
function YourData({ shown }: { shown: boolean }) {
  // What KOLONİ's own data takes on this machine (0.1.0-hijyen): counted each time it is shown.
  const [storage, setStorage] = useState<Storage | null>(null)
  const [shared, setShared] = useState<Folders | null>(null)
  const [sharedError, setSharedError] = useState<string | null>(null)
  const count = () => api.get<Storage>('/storage').then(setStorage, () => setStorage(null))
  useEffect(() => {
    if (!shown) return
    count()
    api.get<Folders>('/folders').then(setShared, err => setSharedError(errorText(err)))
  }, [shown])
  return (
    <>
      <h2>Your data</h2>
      <Backup />
      {storage && (
        <p className="choice-note">
          KOLONİ’s data: db {mb(storage.db_mb)} · backups {mb(storage.backups_mb)} · copies {mb(storage.copies_mb)} ·
          logs {mb(storage.logs_mb)}
        </p>
      )}
      {storage && <KeptCopies storage={storage} onChanged={count} />}
      <FoldersSection shared={shared} sharedError={sharedError} />
    </>
  )
}

/** A size the server counted; "–" where it did not count it in time. */
const mb = (value: number | null) => (value === null ? '–' : `${value} MB`)
