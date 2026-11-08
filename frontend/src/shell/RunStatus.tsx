import { CompactNow } from '../agents/AgentDetails'
import { WAITS } from '../agents/agentStatus'
import type { Run } from '../api/types'
import { pendingMerge } from '../changes/copies'
import { TERMINAL, activeRun, type ConvState } from '../state/applyEvent'
import { contextFull, partTokens, percentFull, tokens, turnTokens } from './tokens'
import { usePanel } from './usePanel'

// The words the agents and the turn list say these in, in capitals. (A turn queued behind another is
// QUEUED, as its message says in the chat: it waits for that turn, not for a slot.)
const LABEL: Record<Run['status'], [text: string, tag: string]> = {
  queued: ['QUEUED', 'tag'],
  running: ['WORKING', 'tag tag-accent'],
  waiting_approval: [WAITS.toUpperCase(), 'tag tag-warn'],
  completed: ['DONE', 'tag tag-ok'],
  failed: ['FAILED', 'tag tag-del'],
  cancelled: ['STOPPED', 'tag'],
  interrupted: ['INTERRUPTED', 'tag tag-warn'],
}

/** The run the top bar reports on: the active one, else the latest that actually ran. */
function shownRun(conv: ConvState): Run | null {
  const active = activeRun(conv)
  if (active) return active
  const ran = conv.runs.filter(r => TERMINAL.has(r.status) && r.started_at)
  return ran[ran.length - 1] ?? null
}

export function RunStatus({ conv, connection }: { conv: ConvState | null; connection: 'open' | 'reconnecting' }) {
  const run = conv && shownRun(conv)
  // While a sub-agent is the one at work, say which.
  const worker =
    conv && run && !TERMINAL.has(run.status)
      ? conv.agents.findLast(a => a.run_id === run.id && a.depth > 0 && a.status === 'running')
      : undefined
  // Several may be at work at the same time.
  const atWork =
    conv && run && !TERMINAL.has(run.status)
      ? conv.agents.filter(a => a.run_id === run.id && a.status === 'running').length
      : 0
  // The turn waits for your word on what an agent changed in its working copy: that agent
  // is done, and is the one to name - not whoever else is still at work.
  const decides =
    conv && run?.status === 'waiting_approval'
      ? conv.agents.find(a => a.run_id === run.id && pendingMerge(conv, a.id) !== null)
      : undefined
  const named = decides ?? (atWork > 1 ? undefined : worker)
  // How full its lead's context is, as its window shows it; where the window is not known, what its last step sent -
  // not for a CLI, whose count is not what it holds. "–" where nothing was measured: the button is there all the same,
  // for its panel (Compact now, each agent's context).
  // shortcut: after a summary it still says what its last step sent, until a next step measures it again; say
  // "before its summary" there if that misleads.
  const lead = conv && run ? conv.agents.find(a => a.run_id === run.id && a.depth === 0 && a.started_at) : undefined
  const full = lead && (contextFull(lead.input_tokens, lead.context_window) ?? (lead.provider_mode || lead.input_tokens === null ? 'context –' : `context ${lead.input_tokens.toLocaleString('en-US')} tokens`))
  return (
    <>
      {connection === 'reconnecting' && <span className="tag tag-warn">Reconnecting…</span>}
      {run && (
        <>
          <span className={LABEL[run.status][1]} data-run={run.status}>
            <span className="dot" />
            {/* (Waiting: the dot and whom - how many wait, and the way there, is the Ready pill beside it: tek-ev §1.) */}
            {run.status === 'waiting_approval' ? named && (named.name || named.role_name) : LABEL[run.status][0]}
            {run.status !== 'waiting_approval' && (named ? ` · ${named.name || named.role_name}` : atWork > 1 && ` · ${atWork} agents`)}
          </span>
          <span className="mono muted topbar-tokens">{partTokens(conv, run) ?? tokens(turnTokens(conv, run))}</span>
          {full && <Contexts conv={conv} run={run} label={full} />}
        </>
      )}
    </>
  )
}

const count = (n: number | null) => (n === null ? '–' : n.toLocaleString('en-US'))
// A CLI run step by step: each step is a CLI started anew, sent a trimmed history (the API's 409 says the same).
const STEP_TRIMMED = 'each step is sent a trimmed history; not compacted'

/**
 * The lead's context, as a button: it opens what each agent of the turn holds - its last step's input, of its model's
 * window - with Compact now for a lead KOLONİ compacts (`CompactNow` keeps to those), a CLI's too where it starts each
 * turn anew. Only a CLI that keeps what it is sent itself (`compacts_itself`: its session goes on) compacts itself.
 */
function Contexts({ conv, run, label }: { conv: ConvState; run: Run; label: string }) {
  const { open, setOpen, close, button, panel } = usePanel()
  return (
    <>
      <button ref={button} type="button" className="mono muted topbar-context" aria-expanded={open} onClick={() => (open ? close() : setOpen(true))}>
        {label}
      </button>
      {open && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel" role="dialog" aria-label="Each agent’s context">
          <div className="kicker">Each agent’s context</div>
          <p className="muted context-note">Its last step’s input, of its model’s window: after Compact now, until its next step.</p>
          <ul className="context-list">
            {/* (Not one that never started: proposed, rejected, or stopped before it began.) */}
            {conv.agents
              .filter(a => a.run_id === run.id && a.started_at)
              .map(a => (
                <li key={a.id}>
                  <div className="context-row">
                    <span className="context-name">{a.name || a.role_name}</span>
                    <span className="mono">{percentFull(a.input_tokens, a.context_window) ?? '–'}</span>
                    <span className="mono muted">
                      {/* A CLI's count without a window is not what it holds (its cache counted in): not said, as in the bar. */}
                      {count(a.provider_mode && !a.context_window ? null : a.input_tokens)} / {count(a.context_window)}
                    </span>
                  </div>
                  {a.compacts_itself ? (
                    <span className="muted context-note">{a.provider_mode === 'step' ? STEP_TRIMMED : 'compacts itself'}</span>
                  ) : (
                    // (The agent window's Edit is not locked meanwhile: the server refuses its Save while this compacts.)
                    <CompactNow agent={a} goesOn={conv.agents.some(b => b.continues_id === a.id)} onBusy={() => {}} />
                  )}
                </li>
              ))}
          </ul>
        </div>
      )}
    </>
  )
}
