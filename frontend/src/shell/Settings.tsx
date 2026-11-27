import { X } from '@phosphor-icons/react'
import { type ComponentProps, Fragment, type ReactNode, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Folders, Project, Storage } from '../api/types'
import { Backup } from './Backup'
import { DeleteProject } from './DeleteProject'
import { FoldersSection } from './Folders'
import { KeptCopies } from './KeptCopies'
import { MOVED_PLACES, OLD_NAMES, ProjectSettings, type ProjectPlace, SECTIONS } from './ProjectSettings'
import { AppAgents } from './sections/AppAgents'
import { Said } from './sections/part'
import { dataSaid } from './sections/said'
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

/** Where Settings may be asked to open (Ctrl+K, a link): This chat, a place of This project's, or a section of the app's. */
export type SettingsPlace = 'chat' | ProjectPlace | AppSection

/** Ctrl+K's settings: each section by its name - the app's with "(the app)" after it - found by the name it had
 *  before 0.1.10 too; and each section folded into another then, by its old name after the one it is in now, opening
 *  it where it is (its More, or the rules). */
export const settingsPlaces = (project: boolean): { place: SettingsPlace; name: string; also?: string[] }[] => {
  const moved = new Set(MOVED_PLACES.map(([, , name]) => name))
  const named = (section: string) => SECTIONS.find(([key]) => key === section)?.[1]
  return [
    ...(project
      ? [
          ...SECTIONS.map(([place, name]) => ({
            place,
            name,
            also: OLD_NAMES[place]?.filter(old => !moved.has(old)),
          })),
          ...MOVED_PLACES.map(([place, section, old]) => ({ place, name: `${named(section)} › ${old}` })),
        ]
      : []),
    ...APP_SECTIONS.map(([place, name]) => ({ place, name: `${name} (the app)` })),
  ]
}

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
  // This project's place asked for, each time with a new count.
  const [projectAsk, setProjectAsk] = useState<{ section: ProjectPlace; n: number } | undefined>(undefined)
  // The app's More limits, asked open by the link from Continue's steps: each time with a new count.
  const [appMore, setAppMore] = useState<number | undefined>(undefined)
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
            toApp={() => {
              setAppMore(n => (n ?? 0) + 1)
              go('app-agents')
            }}
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
              <AppAgents toLimits={project ? () => go('more-limits') : undefined} moreAsked={appMore} />
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
      <Said title="Your data">{dataSaid(storage, shared ? shared.never.length : null)}</Said>
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
