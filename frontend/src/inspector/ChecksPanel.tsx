import type { Message, Run } from '../api/types'
import { type Loop, type LoopRound, testRows } from '../canvas/checksLoop'
import { FixIt } from '../chat/CheckedSection'
import { fixOf } from '../chat/checked'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'

type Row = NonNullable<Message['checked']>[number]

const MARK: Partial<Record<Row['state'], string>> = { passed: '✓', failed: '✗', running: '…' }
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/**
 * The Checks node's panel (tuval-kontrol-dongusu F): the Checked section's test runs, then round by round who looked and what
 * each said, the first blocking finding and who fixed it after - each agent's name opens its window -, and why the last round
 * was the last. Fix it as under the answer (on the chat's latest turn), and the way to that section.
 */
export function ChecksPanel({ state, run, loop, openWindow }: { state: ConvState; run: Run; loop: Loop | null; openWindow: (agentId: string) => void }) {
  const rows = state.messages.find(m => m.run_id === run.id && m.role === 'checked')?.checked ?? []
  // (Work not taken in is answered in the Checked section itself: its Fix it asks the stronger model's question.)
  const fix = state.runs.at(-1)?.id === run.id && !rows.some(row => row.kind === 'not_taken') ? fixOf(rows) : null
  const tests = testRows(rows)
  return (
    <div className="insp-body checks-panel">
      <section aria-label="Tests">
        <div className="kicker">Tests</div>
        {tests.length === 0 && <p className="muted">None said yet.</p>}
        {tests.map((row, index) => (
          <p key={index} className="checks-panel-li" data-state={row.state}>
            {MARK[row.state] ?? '–'} {row.text}
          </p>
        ))}
      </section>
      {loop?.rounds.map(round => (
        <Round key={round.n} round={round} stop={round.n === loop.rounds.length ? loop.stop : null} openWindow={openWindow} />
      ))}
      <div className="checks-panel-actions">
        {fix && <FixIt asked={fix} />}
        <button type="button" className="btn btn-small" onClick={() => useApp.getState().showChatTab('Chat', true, `checked-${run.id}`)}>
          Open the Checked section
        </button>
      </div>
    </div>
  )
}

/** A round: its looks with their verdicts, the first blocking finding, then who fixed it - or what sent it back, or why it stopped. */
function Round({ round, stop, openWindow }: { round: LoopRound; stop: string | null; openWindow: (agentId: string) => void }) {
  const files = round.fixed.reduce((all, one) => all + one.files, 0)
  return (
    <section aria-label={`Round ${round.n}`}>
      <div className="kicker">Round {round.n}</div>
      {round.looks.map(look => (
        <p key={look.agentId} className="checks-panel-li">
          <Who id={look.agentId} name={look.name} openWindow={openWindow} />
          <span data-tone={look.verdict?.startsWith('HOLD') ? 'bad' : look.verdict === 'MERGE' ? 'ok' : undefined}>{look.verdict ?? 'no verdict read'}</span>
        </p>
      ))}
      {round.finding && <p className="checks-panel-find">• {round.finding}</p>}
      {round.fixed.length > 0 && (
        <p className="checks-panel-li">
          <span>
            → fixed by{' '}
            {round.fixed.map((one, index) => (
              <span key={one.agentId}>
                {index > 0 && ', '}
                <Who id={one.agentId} name={one.name} openWindow={openWindow} />
              </span>
            ))}
          </span>
          <span data-tone="note">{plural(files, 'file')}</span>
        </p>
      )}
      {round.fixed.length === 0 && round.why && <p className="muted">→ sent back: {round.why}</p>}
      {stop && <p className="muted">{stop}</p>}
    </section>
  )
}

/** An agent's name: its window. */
function Who({ id, name, openWindow }: { id: string; name: string; openWindow: (agentId: string) => void }) {
  return (
    <button type="button" className="link-btn" onClick={() => openWindow(id)}>
      {name}
    </button>
  )
}
