import { chatColours } from '../agents/teamRun'
import type { BoardPost } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { noteId, readLine, writerOf } from './notesText'

/**
 * The notes of one turn's notebook, in the order they were written. A turn with teams (K-not-oda) has a notebook per
 * team: the whole turn's first (yours, the Lead's, KOLONİ's), then each team's, in its colour.
 */
export function NoteList({ state, runId }: { state: ConvState; runId: string }) {
  const notes = state.boardPosts.filter(p => p.run_id === runId).sort((a, b) => a.seq - b.seq)
  const teams = [...new Map(notes.flatMap(n => (n.team_id === null ? [] : [[n.team_id, n.team ?? 'Team'] as const]))).entries()]
  if (!teams.length) return <>{notes.map(note => <Note key={note.id} state={state} note={note} />)}</>
  const colours = chatColours(state)
  const whole = notes.filter(n => n.team_id === null)
  return (
    <>
      {whole.length > 0 && (
        <section className="note-team" aria-label="For every team">
          <div className="note-team-head mono">For every team</div>
          {whole.map(note => <Note key={note.id} state={state} note={note} />)}
        </section>
      )}
      {teams.map(([id, name]) => (
        <section key={id} className="note-team" aria-label={`${name} notes`}>
          <div className="note-team-head mono">
            <span className="team-dot" style={{ background: colours.get(id) }} aria-hidden="true" />
            {name}
          </div>
          {notes.filter(n => n.team_id === id).map(note => <Note key={note.id} state={state} note={note} />)}
        </section>
      ))}
    </>
  )
}

function Note({ state, note }: { state: ConvState; note: BoardPost }) {
  return (
    <div id={noteId(note.id)} className={`channel-message${note.koloni ? ' note-koloni' : ''}`}>
      <div className="channel-head">
        <span className="mono">
          {writerOf(state, note)}
          {note.everyone && <span className="tag tag-accent note-everyone">for every team</span>}
        </span>
        <span className="mono muted">
          {new Date(note.created_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>
      <div className="channel-body">{note.content}</div>
      <div className="mono muted note-read">{readLine(state, note)}</div>
    </div>
  )
}
