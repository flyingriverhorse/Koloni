import { type ReactNode, useEffect, useState } from 'react'
import type { Price, Run, Usage } from '../api/types'
import { keptNote, turnTeams } from '../agents/teamRun'
import { workOf, workText } from '../canvas/turns'
import { inScratch, isKept } from '../changes/copies'
import { partTokens, turnTokens } from '../shell/tokens'
import type { ConvState } from '../state/applyEvent'
import { totalCost } from '../usage/cost'

interface Props {
  state: ConvState
  run: Run
  onOpenChange: (changeId: string) => void
  /** What the turn's agents spent by model, with what is known of its cost; without it the cost is not known. */
  onUsage?: (runId: string) => Promise<Usage>
  prices?: Price[]
}

const n = (value: number | null) => (value === null ? '–' : value.toLocaleString('en-US'))

/** What of the turn is left for you, in words ('': nothing). */
const leftOpen = (merges: number, proposed: boolean, serving: boolean) =>
  [merges > 0 && 'changes to take in or discard', proposed && 'changes to approve', serving && 'a server running'].filter(Boolean).join(', ')

/**
 * The questions the turn's agents put to you ('': none). Not KOLONİ's own cards (leave for a tool, a recipe's Go on?),
 * which are asked as a command's are - not counted here either - nor those the Orchestrator answered for you: Decided
 * for you has those.
 */
function askedOf(state: ConvState, runId: string): string {
  const asked = state.questions.filter(q => q.run_id === runId && !q.leave && q.lead_why == null).length
  return asked === 0 ? '' : `${asked} question${asked === 1 ? '' : 's'}`
}

/** The turn's tokens: as its parts say them, else in and out - a dash where neither is known. */
const tokensSaid = (parts: ReturnType<typeof partTokens>, sent: number | null, wrote: number | null) =>
  parts ?? (sent === null && wrote === null ? '–' : `in ${n(sent)} · out ${n(wrote)}`)

/**
 * Under an answer whose message did work (slice 107): one quiet line - "2 agents · 3 files
 * changed · details ▸" - of what is known, and nothing at all under a plain answer. "details"
 * opens the summary: what it changed (with the way to Changes), the sub-agents, the tokens and
 * the cost as far as they are known, and what is left for you; there what is not known is a dash.
 * The cost is read only then: one request per message opened, not one per message of the chat.
 */
export function TurnSummary({ state, run, onOpenChange, onUsage, prices = [] }: Props) {
  const [spent, setSpent] = useState<Usage['by_model'] | null>(null)
  const [open, setOpen] = useState(false)
  // Read again when a price is written: the server prices what was spent (by what the prices say, not by the array).
  const priced = JSON.stringify(prices)
  useEffect(() => {
    if (!open) return
    let mine = true
    // A reading that fails leaves the cost unknown: a dash, as when nothing is priced.
    onUsage?.(run.id).then(
      usage => mine && setSpent(usage.by_model),
      () => {},
    )
    return () => {
      mine = false
    }
  }, [open, onUsage, run.id, priced])

  const changed = state.fileChanges.filter(f => f.run_id === run.id && (f.status === 'applied' || f.status === 'merged') && !inScratch(f.path))
  const work = workOf(state, [run.id])
  const { input_tokens: sent, output_tokens: wrote } = turnTokens(state, run)
  const merges = state.merges.filter(m => m.run_id === run.id && (m.status === 'pending' || isKept(m))).length
  const proposed = state.fileChanges.some(f => f.run_id === run.id && f.status === 'proposed')
  // (a server it started keeps running after it: slice 42b)
  const serving = state.commands.some(c => c.run_id === run.id && c.keep_running && c.status === 'running')
  const note = keptNote(turnTeams(state, run.id), state.fileChanges, run.id)
  const left = leftOpen(merges, proposed, serving)
  const line = [workText(work, true), askedOf(state, run.id), left].filter(Boolean).join(' · ')
  if (!line && !note) return null
  const rows: [string, ReactNode][] = [
    [
      'Files changed',
      <>
        {work.files}
        {work.files > 0 && (
          <>
            {' '}
            <button type="button" className="btn btn-small" onClick={() => onOpenChange(changed[0].id)}>
              View changes
            </button>
          </>
        )}
      </>,
    ],
    ['Sub-agents', work.agents],
    ['Tokens', tokensSaid(partTokens(state, run), sent, wrote)],
    ['Known cost', spent ? totalCost(spent, prices) : '–'],
    ['Left open', left || 'nothing'],
    // G1.3, B-84: its recipes' teams that ended before their end, and what Take in takes in with the kept copy.
    ...(note ? [['Teams', note] as [string, ReactNode]] : []),
  ]
  return (
    <section className="turn-summary" aria-label="What it did">
      <div className="turn-summary-line">
        {line && <span>{line}</span>}
        <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
          details {open ? '▾' : '▸'}
        </button>
      </div>
      {open && (
        <dl>
          {rows.map(([term, value]) => (
            <div key={term}>
              <dt>{term}</dt> <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  )
}
