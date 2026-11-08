import { X } from '@phosphor-icons/react'
import { useState } from 'react'
import type { Project, TeamsMode } from '../../api/types'
import { useApp } from '../../state/store'
import { type FolderRow, GIVEN, listsOf, rowsOf } from '../Folders'
import { GUIDE } from '../guide'
import { limitOf, part, Row, sent, typed } from './part'

const MODES: [mode: TeamsMode, label: string][] = [
  ['lead', 'Orchestrator decides'],
  ['manual', 'Manual'],
  ['none', 'No teams'],
]

const same = (a: FolderRow[], b: FolderRow[]) => a.length === b.length && a.every((row, at) => row.path === b[at].path && row.access === b[at].access)

/**
 * This project › New chats start with: the teams and the other folders a new chat of it starts with, and what a room
 * opened in it may spend. A chat sets its own teams and folders; "Use for new chats" and "Keep for this project" there
 * put them here too.
 */
export function useNewChats(project: Project) {
  const [mode, setMode] = useState<TeamsMode>(project.teams_mode)
  const kept = rowsOf(project.also_in, project.read_in)
  const [folders, setFolders] = useState(kept)
  const rooms = useRoomLimits(project)
  const patch = {
    // (As a chat's "Use for new chats" sends it: the teams kept only with Manual.)
    ...(mode !== project.teams_mode && { teams_mode: mode, teams: mode === 'manual' ? project.teams : [] }),
    ...(!same(folders, kept) && listsOf(folders)),
    ...rooms.patch,
  }
  return part(
    patch,
    rooms.valid,
    <>
      <h2>New chats start with</h2>
      <p className="choice-note">A new chat of this project starts with these; each chat then sets its own.</p>
      <NewTeams mode={mode} setMode={setMode} project={project} />
      <Row label="Other folders">
        {folders.length === 0 && <span className="muted">None.</span>}
        <ul className="folder-rows" aria-label="New chats’ other folders">
          {folders.map(row => (
            <li key={row.path}>
              <span className="mono">{row.path}</span> <span className="muted">{row.access === 'read' ? 'read only' : 'read and write'}</span>
              <button type="button" className="icon-btn" aria-label={`Remove ${row.path} from new chats`} onClick={() => setFolders(folders.filter(one => one !== row))}>
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
        <span className="choice-note">A folder is added from a chat’s folder button: “Keep for this project”. {GIVEN}</span>
      </Row>
      {rooms.view}
    </>,
  )
}

/** What a room opened in any chat of the project may spend, unless it is set as it opens; empty: no limit. */
function useRoomLimits(project: Project) {
  const [postsText, setPostsText] = useState(typed(project.room_posts))
  const [tokensText, setTokensText] = useState(typed(project.room_tokens))
  const [minutesText, setMinutesText] = useState(typed(project.room_minutes))
  const [leastText, setLeastText] = useState(typed(project.room_min_tokens))
  const posts = limitOf(postsText, 1000)
  const tokens = limitOf(tokensText, 100_000_000)
  const minutes = limitOf(minutesText, 1440)
  const least = limitOf(leastText, 100_000_000)
  return {
    valid: posts !== undefined && tokens !== undefined && minutes !== undefined && least !== undefined,
    patch: {
      ...sent('room_posts', posts, project.room_posts ?? null),
      ...sent('room_tokens', tokens, project.room_tokens ?? null),
      ...sent('room_minutes', minutes, project.room_minutes ?? null),
      ...sent('room_min_tokens', least, project.room_min_tokens ?? null),
    },
    view: (
      <>
        <h3 className="kicker">A room’s limits</h3>
        <p className="choice-note">What a room opened in any chat of this project may spend, unless you say otherwise as you open it. Empty: no limit.</p>
        <Row label="Posts, at most" htmlFor="room-posts" warn={posts === undefined && <span className="choice-note">1 to 1000, or empty.</span>}>
          <input id="room-posts" className="input mono set-short" inputMode="numeric" placeholder="No limit" value={postsText} aria-invalid={posts === undefined || undefined} onChange={e => setPostsText(e.target.value)} />
        </Row>
        <Row label="Minutes, at most" htmlFor="room-minutes" warn={minutes === undefined && <span className="choice-note">1 to 1440, or empty.</span>}>
          <input id="room-minutes" className="input mono set-short" inputMode="numeric" placeholder="No limit" value={minutesText} aria-invalid={minutes === undefined || undefined} onChange={e => setMinutesText(e.target.value)} />
        </Row>
        <RoomTokens text={tokensText} setText={setTokensText} tokens={tokens} />
        <Row
          label="Tokens, at least"
          htmlFor="room-min-tokens"
          why="A room an agent asks for with fewer is given this many: one member’s step, with what it rereads, takes some 8,000 to 9,000."
          warn={
            <span className="choice-note">
              {least === undefined ? 'A whole number from 1 to 100,000,000, or empty. ' : ''}
              {least != null && tokens != null && least > tokens ? `Above the most: a room gets ${tokens.toLocaleString('en-US')}, the most wins. ` : ''}
              Empty: an agent’s room gets what it asks for.
            </span>
          }
        >
          <input id="room-min-tokens" className="input mono" inputMode="numeric" placeholder="None" value={leastText} aria-invalid={least === undefined || undefined} onChange={e => setLeastText(e.target.value)} />
        </Row>
      </>
    ),
  }
}

function RoomTokens({ text, setText, tokens }: { text: string; setText: (text: string) => void; tokens: number | null | undefined }) {
  return (
    <Row
      label="Tokens, at most"
      htmlFor="room-tokens"
      doc={GUIDE.settingsNewChats} why="By default none: a room ends on its posts or minutes, or on the message’s and the project’s own limits."
      warn={
        <span className="choice-note">
          {tokens === undefined ? 'A whole number from 1 to 100,000,000, or empty. ' : ''}
          Sent and written by its members’ models, as billed; a model that reports no tokens is not limited.
        </span>
      }
    >
      <input id="room-tokens" className="input mono" inputMode="numeric" placeholder="No limit" value={text} aria-invalid={tokens === undefined || undefined} onChange={e => setText(e.target.value)} />
    </Row>
  )
}

/** Who picks a new chat's teams; with Manual, the teams a chat kept for it. */
function NewTeams({ mode, setMode, project }: { mode: TeamsMode; setMode: (mode: TeamsMode) => void; project: Project }) {
  const teams = useApp(s => s.teams)
  const names = project.teams.map(row => teams.find(team => team.id === row.team_id)?.name ?? 'a team deleted since')
  return (
    <Row
      label="New chats’ teams"
      htmlFor="new-teams"
      warn={
        mode === 'manual' && (
          <span className="choice-note">
            {names.length > 0 ? `${names.join(', ')}: ` : 'No team yet: the Orchestrator calls any role, as with No teams. '}
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
