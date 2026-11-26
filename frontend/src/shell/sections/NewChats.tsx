import { X } from '@phosphor-icons/react'
import { useState } from 'react'
import type { Project, TeamsMode } from '../../api/types'
import { useApp } from '../../state/store'
import { type FolderRow, GIVEN, listsOf, rowsOf } from '../Folders'
import { part, Row } from './part'

const MODES: [mode: TeamsMode, label: string][] = [
  ['lead', 'Orchestrator decides'],
  ['manual', 'Manual'],
  ['none', 'No teams'],
]

const same = (a: FolderRow[], b: FolderRow[]) =>
  a.length === b.length && a.every((row, at) => row.path === b[at].path && row.access === b[at].access)

/**
 * This project › New chats start with: the teams and the other folders a new chat of it starts with. A chat sets its own
 * teams and folders; "Use for new chats" and "Keep for this project" there
 * put them here too.
 */
export function useNewChats(project: Project) {
  const [mode, setMode] = useState<TeamsMode>(project.teams_mode)
  const kept = rowsOf(project.also_in, project.read_in)
  const [folders, setFolders] = useState(kept)
  const patch = {
    // (As a chat's "Use for new chats" sends it: the teams kept only with Manual.)
    ...(mode !== project.teams_mode && { teams_mode: mode, teams: mode === 'manual' ? project.teams : [] }),
    ...(!same(folders, kept) && listsOf(folders)),
  }
  return part(
    patch,
    true,
    <>
      <h2>New chats start with</h2>
      <p className="choice-note">A new chat of this project starts with these; each chat then sets its own.</p>
      <NewTeams mode={mode} setMode={setMode} project={project} />
      <Row label="Other folders">
        {folders.length === 0 && <span className="muted">None.</span>}
        <ul className="folder-rows" aria-label="New chats’ other folders">
          {folders.map(row => (
            <li key={row.path}>
              <span className="mono">{row.path}</span>{' '}
              <span className="muted">{row.access === 'read' ? 'read only' : 'read and write'}</span>
              <button
                type="button"
                className="icon-btn"
                aria-label={`Remove ${row.path} from new chats`}
                onClick={() => setFolders(folders.filter(one => one !== row))}
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
        <span className="choice-note">
          A folder is added from a chat’s folder button: “Keep for this project”. {GIVEN}
        </span>
      </Row>
    </>,
  )
}

/** Who picks a new chat's teams; with Manual, the teams a chat kept for it. */
function NewTeams({
  mode,
  setMode,
  project,
}: {
  mode: TeamsMode
  setMode: (mode: TeamsMode) => void
  project: Project
}) {
  const teams = useApp(s => s.teams)
  const names = project.teams.map(row => teams.find(team => team.id === row.team_id)?.name ?? 'a team deleted since')
  return (
    <Row
      label="New chats’ teams"
      htmlFor="new-teams"
      warn={
        mode === 'manual' && (
          <span className="choice-note">
            {names.length > 0
              ? `${names.join(', ')}: `
              : 'No team yet: the Orchestrator calls any role, as with No teams. '}
            the teams a chat keeps with “Use for new chats in this project”.
          </span>
        )
      }
    >
      <select id="new-teams" className="input" value={mode} onChange={e => setMode(e.target.value as TeamsMode)}>
        {MODES.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </Row>
  )
}
