import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Agent, ProjectMemory, Provider } from '../api/types'
import { AgentMemory } from '../memory/AgentMemory'
import { useAsk } from '../memory/useAsk'
import { autoModel, autoNothing, autoPicked } from '../shell/modelName'
import { cached, percentFull, spent } from '../shell/tokens'
import type { AgentLive, ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { AT_WORK, titleOf } from './agentStatus'
import { AgentSteps, stepsOf } from './AgentSteps'
import { Fold, many } from './agentParts'
import { CopyRaw } from './CopyRaw'
import { LET_THROUGH, letThrough } from './ownWork'
import { ToolChips } from './SpawnApproval'

/** A time on record, as the user's clock reads it; "—" where there is none. */
export function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

interface Props {
  state: ConvState
  agent: Agent
  memory?: ProjectMemory | null
  providers: Provider[]
  open: boolean
  onToggle: (open: boolean) => void
  onOpenChange: (changeId: string) => void
  onSelectAgent: (agentId: string) => void
}

/**
 * Details, folded at the bottom of its window: everything raw - its model and times, its context and steps, its
 * working state, its tools, its raw stream, and every step as recorded (the raw list the story above is told from).
 */
export function AgentDetails({ state, agent, memory, providers, open, onToggle, onOpenChange, onSelectAgent }: Props) {
  const [steps, setSteps] = useState(false)
  // The agent whose Compact now is at work: its working state is not corrected meanwhile (the summary would replace it).
  const [compacting, setCompacting] = useState(false)
  const goesOn = state.agents.some(a => a.continues_id === agent.id)
  const stepped = stepsOf(state, agent.id, agent.report)
  return (
    <Fold title="Details" count="model, usage, tools, raw steps" open={open} onToggle={onToggle} className="agent-details">
      {/* The level its opener picked and why; or its service refused the level it was sent (the step went again without one);
          or why Copilot's auto picked its model. */}
      {agent.effort_note && <p className="muted provider-note">{agent.effort_note}</p>}
      {/* A step was asked again, with the same model, after a short failure of its provider. */}
      {agent.retry_note && <p className="muted provider-note">{agent.retry_note}</p>}
      <ModelFacts state={state} agent={agent} providers={providers} />
      <div className="agent-compact">
        <CompactNow agent={agent} goesOn={goesOn} onBusy={setCompacting} />
      </div>
      <Summarised agent={agent} goesOn={goesOn} compacting={compacting} />
      <div className="kicker">Tools</div>
      <ToolChips tools={agent.tools} />
      {/* The servers its role gave it, as its record has them: where none of their tools is offered is said on the Tools page. */}
      {agent.mcp.length > 0 && (
        <p className="muted provider-note">
          MCP servers: <span className="mono">{agent.mcp.join(', ')}</span>
        </p>
      )}
      {agent.provider_mode === 'reads' && (
        <p role="note" className="muted provider-note">
          Reads only{letThrough(state, agent.id) && LET_THROUGH}: on this provider it works with the CLI’s own tools, and the CLI
          was started without leave to write or run; your own agy settings can allow more. The tools of its role, listed above, do
          not apply.
        </p>
      )}
      <div className="kicker">Raw stream</div>
      <CopyRaw agentId={agent.id} />
      <Fold title="Every step as recorded" count={stepped.steps.length ? many(stepped.steps.length, 'step') : 'none'} open={steps} onToggle={setSteps} className="agent-steps">
        <AgentMemory state={state} agent={agent} memory={memory} />
        <AgentSteps state={state} agent={agent} of={stepped} onOpenChange={onOpenChange} onSelectAgent={onSelectAgent} empty="Nothing yet." />
      </Fold>
    </Fold>
  )
}

/** Its model and how it was chosen, its provider, depth and times, cache, context and model steps. */
function ModelFacts({ state, agent, providers }: { state: ConvState; agent: Agent; providers: Provider[] }) {
  const run = state.runs.find(r => r.id === agent.run_id)
  const lead = agent.depth === 0
  const modelId = agent.model_id ?? (lead ? run?.model_id : null)
  const provider = providers.find(p => p.name === agent.provider_name)
  // R166: its model row's Copilot context tier, which KOLONİ passes as `--context long_context` (K-copilot-baglam).
  // shortcut: the row as it is now, not as it was when the agent ran; keep the tier on the agent if that is ever misleading.
  const longContext = !provider?.base_url && provider?.models.find(m => m.name === modelId)?.context === 'long_context'
  const cache = cached(agent)
  return (
    <dl className="facts">
      <dt>Model</dt>
      <dd className="mono">
        {autoPicked(agent.model_from)}
        {modelId ?? 'unknown'}
        {agent.model_from === 'settings' && " (from Codex's settings)"}
        {longContext && ' · context: long'}
        <ChosenBy state={state} agent={agent} />
      </dd>
      <dt>Provider</dt>
      <dd className="mono">{agent.provider_name ?? 'unknown'}</dd>
      <dt>Id</dt>
      <dd className="mono">{agent.id}</dd>
      <dt>Depth</dt>
      <dd className="mono">{agent.depth}</dd>
      <dt>Started</dt>
      <dd className="mono">{when(agent.started_at)}</dd>
      <dt>Ended</dt>
      <dd className="mono">{when(agent.ended_at ?? (lead ? (run?.ended_at ?? null) : null))}</dd>
      {/* Of all it sent: what its provider said was read again from the cache and written to it. */}
      {cache && (
        <>
          <dt>Cache</dt>
          <dd className="mono">{cache}</dd>
        </>
      )}
      <Usage state={state} agent={agent} />
    </dl>
  )
}

/** Who chose its model, and why. */
function ChosenBy({ state, agent }: { state: ConvState; agent: Agent }) {
  const opener = state.agents.find(a => a.id === agent.parent_agent_id)
  return (
    <>
      {agent.chosen && ` · chosen by ${titleOf(opener?.name ?? '') || 'the agent that opened it'}`}
      {/* A lead whose model followed the message: nobody chose it, and the reason is a model's guess; a
          sub-agent the Lead gave a tier: why (B-76). */}
      {!agent.chosen && agent.chosen_why && ` · ${agent.depth > 0 ? 'why this tier' : autoModel(agent.asked_how_hard)}`}
      {/* Why, in that agent's own words. */}
      {agent.chosen_why && `: “${agent.chosen_why}”`}
      {/* Somebody was asked and nothing came of it. */}
      {!agent.chosen && !agent.chosen_why && agent.asked_how_hard && ` · ${autoNothing(agent.asked_how_hard)}`}
    </>
  )
}

/** How full its context is, and its model steps against its limit. */
function Usage({ state, agent }: { state: ConvState; agent: Agent }) {
  // (Its role's step limit as it stands now; the app's 25 holds each job in any case.)
  const roleSteps = useApp(s => s.roles.find(r => r.name === agent.role_name)?.max_steps)
  // What its last step sent, of its model's window, where both are known - or what its CLI says it holds while it works (89j).
  const said = state.live[agent.id]?.context ?? null
  const tokensKnown = agent.input_tokens !== null || agent.output_tokens !== null
  return (
    <>
      {(tokensKnown || said) && (
        <>
          <dt>Context</dt>
          <ContextLine agent={agent} said={said} tokensKnown={tokensKnown} />
        </>
      )}
      {agent.steps_given > 0 && (
        // K-devam-butce: its model steps so far, over the limit it had and what it was given on top. The app's limit
        // is in no payload: 25, its default, here.
        // shortcut: a limit changed in Settings › The app, or a coordinator's extra steps, is not shown; send it if missed.
        // shortcut: a go on after a stop at the app's 25 (no role limit) runs on a fresh 25 that is not counted in
        // steps_given (B-83's rule); put it on the record if the sum is seen to mislead.
        <>
          <dt>Steps</dt>
          <dd>{`${state.messages.filter(m => m.agent_id === agent.id && m.role === 'assistant' && !m.discussion_id).length} / ${Math.min(25, roleSteps ?? 25)} + ${agent.steps_given}`}</dd>
        </>
      )}
    </>
  )
}

/** How full its context is, its tokens in and out, and Copilot's own unit: AI credits or premium requests. */
function ContextLine({ agent, said, tokensKnown }: { agent: Agent; said: AgentLive['context'] | null; tokensKnown: boolean }) {
  const [used, window] = said ? [said.used, said.window] : [agent.input_tokens, agent.context_window]
  const full = percentFull(used, window)
  const show = (n: number | null) => (n === null ? 'unknown' : n.toLocaleString('en-US'))
  const units = spent(agent)
  return (
    <dd>
      {full && (tokensKnown ? `${full} · ` : `${full} full`)}
      {tokensKnown && `${show(agent.input_tokens)} in / ${show(agent.output_tokens)} out`}
      {tokensKnown && units && ` · ${units}`}
      {full && <meter className="agent-meter" aria-label="Context used" min={0} max={window!} value={Math.min(used!, window!)} />}
    </dd>
  )
}

/**
 * Beside its context line: the user's Compact now, for an agent KOLONİ compacts - a lead whose CLI, if any, does not
 * keep what it is sent itself (`compacts_itself`; a sub-agent is compacted at its steps, and nothing goes on from
 * it). Its older part is summarised now, as after a turn, and
 * what came of it is said here. Not while it is at work (it is compacted at its steps then), nor where a later
 * agent goes on from it: the button says why. Also in the top bar's panel of each agent's context (`RunStatus`).
 */
export function CompactNow({ agent, goesOn, onBusy }: { agent: Agent; goesOn: boolean; onBusy: (on: boolean) => void }) {
  const { busy, error, ask } = useAsk()
  const [said, setSaid] = useState<string | null>(null)
  if (agent.compacts_itself || agent.depth > 0) return null
  const why = AT_WORK.has(agent.status)
    ? 'It is at work: it is compacted at its next step past the threshold in Settings › The app (“Summarise a long context at (%)”). Compact it once its work is over.'
    : goesOn
      ? 'A later agent goes on from this one: compact that one.'
      : null
  return (
    <>
      <button
        type="button"
        className="btn btn-small"
        // (Not disabled: a disabled button is never focused, and its reason never read.)
        aria-disabled={busy || why !== null || undefined}
        title={why ?? 'Summarise the older part of what its model is sent, now'}
        onClick={() => {
          if (why) setSaid(why)
          else if (!busy)
            void ask(async () => {
              setSaid(null)
              onBusy(true)
              try {
                const after = await api.post<Agent>(`/agents/${agent.id}/compact`)
                const more = after.summarised - agent.summarised
                // A summary made clears why an earlier one could not be: a note left is this one's.
                setSaid(
                  more !== 0
                    ? `Compacted: ${more} message${more === 1 ? '' : 's'} more summarised.`
                    : after.summary_note
                      ? `Not compacted: ${after.summary_note}`
                      : 'Nothing older to summarise yet.',
                )
              } finally {
                onBusy(false)
              }
            })
        }}
      >
        {busy ? 'Compacting…' : 'Compact now'}
      </button>
      {/* (On the page before it says anything: a live region that comes already filled is not read out.) */}
      <span role="status" className="muted changes-summary" title={said ?? undefined}>
        {said}
      </span>
      {error && (
        <span role="alert" className="changes-summary" style={{ color: 'var(--del)' }} title={error}>
          {error}
        </span>
      )}
    </>
  )
}

/**
 * Under its context line: how much of its history its model is sent summarised, with the working
 * state to read and - where a model is still to read it (`summary_correctable`, and no later
 * agent goes on from it: `goesOn`) - correct; or why none could be made. The record below is whole.
 */
function Summarised({ agent, goesOn, compacting }: { agent: Agent; goesOn: boolean; compacting: boolean }) {
  const { busy, error, ask } = useAsk()
  const [draft, setDraft] = useState<string | null>(null)
  const edit = useRef<HTMLButtonElement>(null)
  const back = useRef(false)
  // Its summarised count when Edit was pressed: a summary made since is not written over (the server refuses).
  const began = useRef(0)
  useEffect(() => {
    if (draft === null && back.current) {
      back.current = false
      edit.current?.focus()
    }
  }, [draft])
  if (agent.summarised === 0 && agent.summary_note === null) return null
  const close = () => {
    back.current = true
    setDraft(null)
  }
  const most = mostChars(agent.context_window)
  return (
    <div className="muted provider-note working-state">
      {agent.summary_note && <p>{agent.summary_note}</p>}
      {agent.summarised > 0 && (
        <details className="more">
          <summary>
            {many(agent.summarised, 'message')} summarised for its model
          </summary>
          {draft === null ? (
            <>
              <div className="summary-text" role="region" aria-label="Working state" tabIndex={0}>
                {agent.summary}
              </div>
              {agent.summary_correctable && !goesOn && (
                <button
                  ref={edit}
                  type="button"
                  className="btn btn-small"
                  aria-label="Edit working state"
                  disabled={compacting}
                  onClick={() => {
                    began.current = agent.summarised
                    setDraft(agent.summary ?? '')
                  }}
                >
                  Edit
                </button>
              )}
            </>
          ) : (
            <>
              <textarea
                aria-label="Working state"
                className="input"
                rows={8}
                maxLength={most}
                value={draft}
                onChange={e => setDraft(e.target.value)}
              />
              <p>
                {AT_WORK.has(agent.status)
                  ? 'Its model is sent your words from its next step on.'
                  : 'The Orchestrator of your next message goes on from your words.'}{' '}
                The record is not changed.
              </p>
              <div className="memory-actions">
                <button
                  type="button"
                  className="btn btn-small btn-primary"
                  disabled={busy || compacting || !draft.trim()}
                  onClick={() =>
                    void ask(async () => {
                      await api.patch<Agent>(`/agents/${agent.id}/summary`, { summary: draft, summarised: began.current })
                      close()
                    })
                  }
                >
                  Save
                </button>
                <button type="button" className="btn btn-small" disabled={busy} onClick={close}>
                  Cancel
                </button>
              </div>
            </>
          )}
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
        </details>
      )}
    </div>
  )
}

/** As the server holds a working state: a quarter of its window, at three characters a token, never past 40 000. */
const mostChars = (window: number | null) => Math.min(window ? Math.floor((window * 3) / 4) : 40000, 40000)
