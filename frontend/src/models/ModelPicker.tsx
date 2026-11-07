import { Cpu } from '@phosphor-icons/react'
import { type FormEvent, useState } from 'react'
import { errorText } from '../api/client'
import { type Effort, type Provider, type Tier, TIERS } from '../api/types'
import { modelName } from '../shell/modelName'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { useConfirm } from '../shell/Confirm'
import { usePanel } from '../shell/usePanel'
import { type LoadFacts, LevelOptions, levelsDisabled, levelsKnown, namedLevel, takesOf, useModelFacts } from './levels'
import { type LoadModels, ModelNameInput, ProviderOptions } from './ModelNameInput'

export interface ModelChoice {
  provider_id: string | null
  model_id: string | null
  /** The lead's model follows how hard the message is; left out where that was not changed. */
  lead_auto?: boolean
  /** The Lead's reasoning level here, null for its role's; left out where that was not changed. */
  lead_effort?: Effort | null
}

interface Props {
  providers: Provider[]
  /** The conversation's choice; null means the default provider. */
  providerId: string | null
  modelId: string | null
  /** The lead's model is chosen each turn by how hard a fast model says the message is. */
  leadAuto?: boolean
  /** The Lead's reasoning level in this conversation; null: its role's. */
  leadEffort?: Effort | null
  onSave: (choice: ModelChoice) => Promise<void>
  onModels?: LoadModels
  /** What is known of the model being picked: its levels, and whether it is being retired. */
  onFacts?: LoadFacts
  /** The Lead role's own model, where it has one: the Lead runs on it whatever is picked here. */
  lead?: { provider_id: string | null; model_id: string | null } | null
  /** The chat has had a turn: a model picked now starts with no cache of it. */
  hasHistory?: boolean
}

/**
 * What "Lead model: automatic" costs, and the rest of its note, which is folded under it.
 * Who is asked is the server's to say (the Lead role's own limits count too): not guessed here.
 */
const AUTO_COSTS = 'One more request for each message you send: a fast model of your team guide is sent your message and asked how hard it is.'
/** In sight too: the one thing "A role with its own model keeps it", above it, does not hold for. */
const AUTO_OVERRIDES = 'It overrides the Orchestrator role’s own model and tier. A trigger’s message does not use it.'
const AUTO_REST =
  'The Orchestrator then runs on your first fast, balanced or strongest model, and shows the answer as that model’s guess. With no answer to go by, or no model of that tier, the Orchestrator runs where it otherwise would: its role’s model, else its tier, else the model above.'

/**
 * 89k: every turn is a new Claude Code given the whole chat; the cache of its prompt is the
 * model's own, so the first turn on another model writes all of it again.
 * shortcut: how much more is not measured here (a live session's switch cost 0.117 $ for one
 * word, 27 Oct); Claude Code only: Codex's cost of a switch is not measured, say it once it is.
 */
export const SWITCH_COSTS =
  'Another model has no cache of this chat yet: its next turn writes everything it is sent to the cache again, so it costs more.'

/**
 * B-193: the model a provider runs on where nothing names one: its default, else for a CLI the one KOLONİ names
 * (app/providers.py `stand_in`, the same rule) - of what its list lets agents use, the first of the tier nearest
 * balanced, fast before strongest, else the first. Null: an HTTP provider's own, or a CLI's own default, model unknown.
 */
export function runsOn(p: Provider | undefined): string | null {
  if (!p || p.default_model || p.kind === 'openai_compat' || p.kind === 'anthropic') return p?.default_model ?? null
  const mine = p.models.filter(m => m.agents !== false && m.enabled !== false)
  const far = (tier: Tier) => Math.abs(TIERS.indexOf(tier) - 1) * 10 + TIERS.indexOf(tier)
  const tiered = mine.filter(m => m.tier).sort((a, b) => far(a.tier!) - far(b.tier!))
  return (tiered[0] ?? mine[0])?.name ?? null
}

/**
 * The button's words, the model first: a narrow chat's "…" cuts the least of it, and the provider and the lead give way
 * (sample C, base.css). `rest`: the name without the lead, where there is no model to put first.
 */
function ButtonLabel({ provider, model, rest, leadAuto }: { provider?: string; model: string | null; rest: string; leadAuto: boolean }) {
  return (
    <span className="model-picker-label">
      {provider && model ? (
        <>
          {modelName(model)}
          <span className="model-picker-provider"> · {provider}</span>
        </>
      ) : (
        rest
      )}
      {leadAuto && <span className="model-picker-lead"> · Orchestrator: automatic</span>}
    </span>
  )
}

/** Which model this conversation's agents use, unless their role has its own. */
export function ModelPicker({ providers, providerId, modelId, leadAuto = false, leadEffort = null, onSave, onModels, onFacts, lead, hasHistory = false }: Props) {
  const [provider, setProvider] = useState(providerId ?? '')
  const [model, setModel] = useState(modelId ?? '')
  const [auto, setAuto] = useState(leadAuto)
  const [effort, setEffort] = useState(leadEffort)
  // K-31: a pick not saved is not thrown away by a click elsewhere unasked (as Sub-agents, B-75).
  const changed = provider !== (providerId ?? '') || model.trim() !== (modelId ?? '') || auto !== leadAuto || effort !== leadEffort
  const confirm = useConfirm()
  const mayClose = () => {
    // (Esc or a click elsewhere while it asks: back to the panel, as Keep editing.)
    if (confirm.asking) confirm.cancel()
    else if (changed) confirm.ask('Close without saving what you changed?', 'Close without saving')
    return !changed && !confirm.asking
  }
  const { open, setOpen, close, button, panel } = usePanel<HTMLFormElement>(mayClose)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // What a turn would use right now: the choice, or the first provider.
  const used = providers.find(p => p.id === providerId) ?? providers[0]
  const usedModel = (providerId && modelId) || runsOn(used)
  // "Lead: automatic" first: it is what the Lead's model goes by, whatever the rest names. A CLI's own default is said (B-193).
  const cliOwn = used && !usedModel && used.kind !== 'openai_compat' && used.kind !== 'anthropic'
  const rest = used ? `${used.name}${usedModel ? ` · ${modelName(usedModel)}` : cliOwn ? '’s own default (unknown model)' : ''}` : 'no provider'
  const label = (leadAuto ? 'Orchestrator: automatic · ' : '') + rest
  const picked = providers.find(p => p.id === provider) ?? providers[0]
  // The levels are those of the model the Lead runs on: its role's own, else the one picked here.
  // shortcut: with "Lead model: automatic" the turn's own pick is not known here; it shows the picked one.
  const own = lead?.provider_id ? providers.find(p => p.id === lead.provider_id) : undefined
  const facts = useModelFacts(
    open ? onFacts : undefined,
    (own ?? picked)?.id ?? null,
    own ? (lead?.model_id ?? runsOn(own) ?? '') : model.trim() || (runsOn(picked) ?? ''),
  )
  const takes = takesOf(facts)
  // From Claude Code to Claude Code only: from elsewhere there is no cache of it to lose.
  // shortcut: hasHistory counts turns on any provider, so a chat just moved onto Claude Code says it too; count its turns there if that confuses.
  const switching =
    hasHistory &&
    used?.kind === 'claude_cli' &&
    picked?.kind === 'claude_cli' &&
    (picked.id !== used?.id || (model.trim() || runsOn(picked) || '') !== (usedModel || ''))

  function toggle() {
    if (open) {
      if (mayClose()) close()
      return
    }
    setProvider(providerId ?? '')
    setModel(modelId ?? '')
    setAuto(leadAuto)
    setEffort(leadEffort)
    setError(null)
    setOpen(true)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSave({
        ...(provider ? { provider_id: provider, model_id: model.trim() || null } : { provider_id: null, model_id: null }),
        ...(auto !== leadAuto ? { lead_auto: auto } : {}),
        ...(effort !== leadEffort ? { lead_effort: effort } : {}),
      })
      close()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="allow-list model-picker">
      <button
        ref={button}
        type="button"
        className="btn btn-small model-picker-button"
        aria-expanded={open}
        aria-label={`Model: ${label}`}
        title={`${label}: the model this conversation's agents use${leadAuto ? '; the Orchestrator’s is chosen for each message by how hard it is' : ''}`}
        onClick={toggle}
      >
        <Cpu size={13} />
        <ButtonLabel provider={used?.name} model={usedModel} rest={rest} leadAuto={leadAuto} />
      </button>
      {open && (
        <form ref={panel} tabIndex={-1} className="allow-list-panel" aria-label="Model for this conversation" onSubmit={submit}>
          <div className="kicker">Model for this conversation</div>
          {/* (The button may cut it: here it is whole.) */}
          <div className="muted cmd-approval-note">Now: {label}</div>
          <div className="field">
            <label htmlFor="pick-provider">Provider</label>
            <select
              id="pick-provider"
              className="input"
              value={provider}
              onChange={e => {
                setProvider(e.target.value)
                setModel('')
              }}
            >
              <option value="">Default ({providers[0]?.name ?? 'none'})</option>
              <ProviderOptions providers={providers} />
            </select>
          </div>
          {provider && (
            <div className="field">
              <label htmlFor="pick-model">Model name</label>
              <ModelNameInput
                id="pick-model"
                value={model}
                // (The Anthropic API has no default of its own: with none set, a run is refused.)
                placeholder={runsOn(picked) ?? (picked?.kind === 'anthropic' ? 'Needed: this provider has no default model' : "The provider's default")}
                providerId={provider}
                loadModels={onModels}
                onChange={setModel}
              />
            </div>
          )}
          <div className="muted cmd-approval-note">
            Applies from the next turn. A role with its own model keeps it.
          </div>
          {switching && <div className="muted cmd-approval-note">{SWITCH_COSTS}</div>}
          <label className="choice" htmlFor="pick-lead-auto">
            {/* Named as it was, by all of its note: a browser leaves a closed hint out of a name, and would add its button’s name to it. */}
            <input
              id="pick-lead-auto"
              type="checkbox"
              aria-label={`Orchestrator model: automatic ${AUTO_COSTS} ${AUTO_OVERRIDES} ${AUTO_REST}`}
              checked={auto}
              onChange={e => setAuto(e.target.checked)}
            />
            <span>
              Orchestrator model: automatic
              <span className="choice-note">
                {AUTO_COSTS} {AUTO_OVERRIDES} <Hint doc={GUIDE.autoModel}>{AUTO_REST}</Hint>
              </span>
            </span>
          </label>
          <div className="field">
            <label htmlFor="pick-lead-effort">Thinking</label>
            <select
              id="pick-lead-effort"
              className="input"
              aria-describedby="pick-lead-effort-note"
              disabled={levelsDisabled(takes, effort)}
              value={effort ?? ''}
              onChange={e => setEffort((e.target.value || null) as Effort | null)}
            >
              <LevelOptions takes={takes} value={effort} />
            </select>
            <span id="pick-lead-effort-note" className="choice-note">
              {levelsKnown(takes, namedLevel(facts))} {own ? 'Of the Orchestrator role’s own model. ' : ''}
              {facts?.deprecated ? 'Its model is being retired: it still runs. ' : ''}The Orchestrator’s level here. Default: the Orchestrator role’s.
            </span>
          </div>
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
          <button type="submit" className="btn btn-small btn-primary" disabled={busy}>
            Use this model
          </button>
          {confirm.shown(close)}
        </form>
      )}
    </div>
  )
}
