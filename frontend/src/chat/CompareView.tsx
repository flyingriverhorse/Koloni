import { useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { Compare, CompareSide, Provider } from '../api/types'
import type { SpawnDecision } from '../agents/SpawnApproval'
import { isKept } from '../changes/copies'
import { DiffView } from '../changes/DiffView'
import { type Choices, MergeCard, type Shown } from '../changes/MergeCard'
import { UndoCard } from '../changes/UndoCard'
import { modelName } from '../shell/modelName'
import type { ConvState } from '../state/applyEvent'
import { money } from '../usage/cost'
import { Markdown } from './Markdown'

interface Props {
  compareId: string
  state: ConvState
  providers: Provider[]
  onLoad: (compareId: string) => Promise<Compare>
  /** Take one side's work into the project (its turn), or throw both away (null). */
  onDecide: (compareId: string, runId: string | null) => Promise<Compare>
  /** The chosen side's card, where files of it clash with the project as it is now. */
  onDecideMerge: (mergeId: string, decision: SpawnDecision, choices?: Choices, shown?: Shown) => Promise<void>
  onCheckMerge: (mergeId: string, choices: Choices) => Promise<void>
  onCommitMerge: (mergeId: string, message: string, hooks?: 'with' | 'without') => Promise<void>
}

const WAITING: Record<string, string> = {
  queued: 'Queued: starts when the other side is done.',
  running: 'Working…',
  waiting_approval: 'Waits for you below.',
  failed: 'Failed.',
  cancelled: 'Stopped.',
  interrupted: 'Interrupted by a restart.',
  completed: 'Done, with no answer written.',
}
const n = (value: number | null) => (value === null ? '–' : value.toLocaleString('en-US'))

/**
 * One message sent to two models (slice 54), side by side under it: each one's answer, the files
 * it changed in its own copy (with their diffs), its time, tokens and cost. Nothing of either is in
 * the project until you pick one; the other's work is thrown away.
 */
export function CompareView({ compareId, state, providers, onLoad, onDecide, onDecideMerge, onCheckMerge, onCommitMerge }: Props) {
  const [compare, setCompare] = useState<Compare | null>(null)
  const [busy, setBusy] = useState(false)
  const [undoing, setUndoing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const runs = state.runs.filter(r => r.compare_id === compareId)
  const merges = state.merges.filter(m => runs.some(r => r.id === m.run_id))
  // Read again whenever a side moves on, or its changes are decided.
  const stamp = [...runs.map(r => r.status), ...merges.map(m => `${m.status} ${m.files.length}`)].join(' ')
  useEffect(() => {
    let mine = true
    onLoad(compareId).then(
      found => mine && setCompare(found),
      err => mine && setError(errorText(err)),
    )
    return () => {
      mine = false
    }
  }, [compareId, stamp, onLoad])

  if (!compare) return error ? <div role="alert" className="alert">{error}</div> : null
  const provider = (side: CompareSide) => providers.find(p => p.id === side.provider_id)?.name ?? 'A provider'
  const full = (side: CompareSide) => `${provider(side)}${side.model_id ? ` · ${modelName(side.model_id)}` : ''}`
  // What its buttons call it: the provider, unless both sides are of one.
  const [a, b] = compare.sides
  const short = (side: CompareSide) => (a && b && provider(a) === provider(b) ? full(side) : provider(side))
  const chosen = compare.sides.find(side => side.run_id === compare.chosen_run_id)
  // Not all of the chosen side's work could be taken (a file clashes with the project as it is now,
  // or moved since): its card stays, for the user to decide as any kept copy's.
  const left = chosen?.kept ? merges.find(m => m.run_id === chosen.run_id && isKept(m)) : undefined

  async function decide(runId: string | null) {
    setBusy(true)
    setError(null)
    try {
      setCompare(await onDecide(compareId, runId))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cmd-approval compare" role="group" aria-label="Two models compared">
      <div className="compare-sides">
        {compare.sides.map(side => {
          const merge = merges.find(m => m.run_id === side.run_id)
          return (
            <section key={side.run_id} className="compare-side" aria-label={full(side)}>
              <div className="compare-head">
                <strong>{full(side)}</strong>
                {side.run_id === compare.chosen_run_id && <span className="tag tag-accent">Chosen</span>}
              </div>
              {side.answer ? (
                <div className="markdown compare-answer">
                  <Markdown>{side.answer}</Markdown>
                </div>
              ) : (
                <div className="msg-status mono">{WAITING[side.status]}</div>
              )}
              {side.error && (
                <div className="muted cmd-approval-note">
                  Why it failed: {side.error}
                  {side.changed_files.length > 0 && ' What it changed before that is still yours to pick.'}
                </div>
              )}
              {side.changed_files.length > 0 && (
                <ul className="compare-files" aria-label={`Files ${full(side)} changed`}>
                  {side.changed_files.map(path => {
                    const diff = merge?.files.find(f => f.path === path)?.diff
                    return (
                      <li key={path}>
                        <span className="mono">{path}</span>
                        {diff != null && (
                          <details className="merge-file">
                            <summary>View diff</summary>
                            <div className="merge-file-diff">
                              <DiffView diff={diff} />
                            </div>
                          </details>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
              <dl className="compare-meta">
                <div>
                  <dt>Time</dt> <dd>{side.seconds === null ? '–' : `${Math.round(side.seconds)} s`}</dd>
                </div>
                <div>
                  <dt>Tokens</dt>
                  <dd>{side.input_tokens === null && side.output_tokens === null ? '–' : `in ${n(side.input_tokens)} · out ${n(side.output_tokens)}`}</dd>
                </div>
                <div>
                  {/* (A sum for each currency, as the turn's summary says it: one is never added to another.) */}
                  <dt>Cost</dt> <dd>{side.cost ? side.cost.map(money).join(' + ') : '–'}</dd>
                </div>
              </dl>
              {/* (Not a side that left nothing: choosing it would take nothing.) */}
              {compare.status === 'ready' && (side.answer || side.changed_files.length > 0) && (
                <>
                  <button type="button" className="btn btn-small btn-primary" disabled={busy} onClick={() => void decide(side.run_id)}>
                    Use {short(side)}’s work
                  </button>
                  {side.changed_files.length === 0 && <div className="muted cmd-approval-note">It changed no files: its answer goes on as the conversation’s.</div>}
                </>
              )}
            </section>
          )
        })}
      </div>
      {/* (While they work too: a side at work, or queued, is stopped and keeps nothing.) */}
      {(compare.status === 'ready' || compare.status === 'running') && (
        <div className="change-actions">
          <button type="button" className="btn btn-small btn-danger" disabled={busy} onClick={() => void decide(null)}>
            Discard both
          </button>
        </div>
      )}
      {compare.status === 'running' && <div className="muted cmd-approval-note">Files they write stay in their own copies until you pick one.</div>}
      {chosen && !left && (
        <div role="status" className="muted cmd-approval-note">
          {chosen.changed_files.length > 0 ? `${short(chosen)}’s work was taken` : `${short(chosen)}’s answer goes on; it changed no files`}; the other’s was thrown away.
        </div>
      )}
      {/* The pick undone: what the chosen side's work changed in the project is taken back, as a message's is.
          shortcut: once undone and closed, the button comes back (its card then says "Nothing to take back"); hide it if that confuses. */}
      {chosen && !left && chosen.changed_files.length > 0 && !undoing && (
        <div className="change-actions">
          <button type="button" className="btn btn-small" onClick={() => setUndoing(true)}>
            Undo these changes
          </button>
        </div>
      )}
      {chosen && undoing && (
        <UndoCard path={`/runs/${chosen.run_id}/undo`} title="Undo these changes" confirm="Undo" onClose={() => setUndoing(false)} />
      )}
      {compare.status === 'discarded' && <div role="status" className="muted cmd-approval-note">Both were thrown away: nothing reached the project.</div>}
      {chosen && left && (
        <>
          <div role="status" className="muted cmd-approval-note">
            {left.files.some(f => f.state === 'conflict')
              ? 'The project changed meanwhile: say whose side is taken where they clash.'
              : 'Not all of it could be taken yet: decide on its card.'}
          </div>
          <MergeCard
            merge={left}
            name={short(chosen)}
            onDecide={(decision, choices, shown) => onDecideMerge(left.id, decision, choices, shown)}
            onCheck={choices => onCheckMerge(left.id, choices)}
            onCommit={(message, hooks) => onCommitMerge(left.id, message, hooks)}
          />
        </>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </div>
  )
}
