import { CaretDown, CaretRight, X } from '@phosphor-icons/react'
import { type ReactNode, useId, useState } from 'react'
import { api } from '../api/client'
import { EFFORTS, TIERS, type Availability, type Effort, type ModelInput, type Provider, type Tier } from '../api/types'
import { type LoadFacts, sourceOf, useModelFacts } from './levels'
import { InputIcons, inputsLine, MarkInputs, withMarks } from './inputs'
import { type ContextTier, isCli } from './ModelsPage'

/** Beside a model: usable now, not (and why), or not known. A glyph of its own for each, not only a colour
 *  (and not the row's remove cross). */
function Mark({ state, why }: Availability['models'][number]) {
  const [glyph, look, said] =
    state === 'usable'
      ? ['●', 'tag tag-ok', 'Usable now']
      : state === 'unusable'
        ? ['!', 'tag tag-del', `Cannot be used: ${why}`]
        : ['?', 'tag', `Not known if usable: ${why}`]
  return (
    <span className={look} role="img" aria-label={said} title={said}>
      {glyph}
    </span>
  )
}

export interface GuideRow {
  name: string
  note: string
  tier: Tier | null
  agents: boolean
  /** False: switched off. Left out (a new row, a catalogue's), what it has on the server is kept. */
  enabled?: boolean
  /** B-396: why KOLONİ switched it off (a CLI refused it); never sent back. */
  off_why?: string | null
  inputs?: ModelInput[] | null
  context?: ContextTier | null
}

/** A window in tokens, short: 200k, 1M. */
const tokens = (n: number) => (n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : `${Math.round(n / 1000)}k`)

/** A fact of a model in the table; "–" where nothing says it. Where it came from is said in the unfolded row. */
function Fact({ value }: { value: string | null }) {
  return value === null ? (
    <td className="muted" title="Not known">
      –
    </td>
  ) : (
    <td>{value}</td>
  )
}

/** A fact of a model unfolded, and where it came from. */
function Known({ name, value, from }: { name: string; value: ReactNode | null; from?: string }) {
  return (
    <div>
      <dt>{name}</dt>
      <dd>
        {value ?? '–'}
        {value !== null && from && <span className="src">{from}</span>}
      </dd>
    </div>
  )
}

/** The levels a model takes, from its lowest to its highest; "none" where it takes none. */
function levels(efforts: Effort[] | null | undefined): string | null {
  if (!efforts) return null
  if (!efforts.length) return 'none'
  const [low, high] = [EFFORTS[efforts[0]], EFFORTS[efforts[efforts.length - 1]]]
  return low === high ? low : `${low}–${high}`
}

/** Switched off, and why where KOLONİ did it (B-396). */
function Off({ why }: { why?: string | null }) {
  return (
    <>
      <span className="tag">off</span>
      {why && <span className="muted">{why}</span>}
    </>
  )
}

/** One model of the guide: its name and tier as you set them and what is known of it; unfolded, each fact with
 *  its source, its note for agents and what it was used for. */
export function ModelRow({
  row,
  provider,
  avail,
  used,
  onFacts,
  onTier,
  onAgents,
  onEnabled,
  onInputs,
  onContext,
  onNote,
  onNoteDone,
  onRemove,
}: {
  row: GuideRow
  provider: Provider | null
  /** Whether it can be used now: undefined before that is read, null where nothing was said of it. */
  avail?: Availability['models'][number] | null
  /** What it was used for in the last 30 days, in words; null where that is not known. */
  used: string | null
  onFacts?: LoadFacts
  onTier: (tier: Tier | null) => void
  onAgents: (agents: boolean) => void
  onEnabled: (enabled: boolean) => void
  onInputs: (inputs: ModelInput[]) => void
  onContext: (context: ContextTier) => void
  onNote: (note: string) => void
  /** The note is left: it is saved. */
  onNoteDone: () => void
  onRemove: () => void
}) {
  const name = row.name
  // Each time what was tried is taken away, or Find again is pressed, the facts are read again.
  const [forgot, setForgot] = useState(0)
  const facts = useModelFacts(onFacts, provider ? provider.id : null, name, forgot)
  const noteId = useId()
  const [open, setOpen] = useState(false)
  const efforts = facts?.efforts
  const price = facts?.price
  const from = (fact: string) => (facts?.sources[fact] ? sourceOf(facts, fact) : undefined)
  const said = (n: number | null | undefined) => (n ? `${n.toLocaleString('en-US')} tokens` : null)
  const plan = provider !== null && isCli(provider.kind) && !provider.base_url
  // K-copilot-baglam: GitHub's context tiers; on a model server of your own there are none.
  const tiered = provider?.kind === 'copilot_cli' && !provider.base_url
  const catalogued = facts?.context_window ? tokens(facts.context_window) : null
  const on = row.enabled !== false
  return (
    <>
    {/* Switched off: faded as a model with no tier is, and said. */}
    <tr className={!on ? 'model-untiered model-off' : row.tier ? undefined : 'model-untiered'}>
      <td>
        <span className="model-name">
          <button
            type="button"
            className="icon-btn"
            aria-expanded={open}
            aria-label={`What is known of ${name}`}
            onClick={() => setOpen(!open)}
          >
            {open ? <CaretDown size={12} /> : <CaretRight size={12} />}
          </button>
          {avail !== undefined && <span className="model-mark">{avail && <Mark {...avail} />}</span>}
          <span className="mono model-name-text">{name}</span>
          <InputIcons facts={withMarks(facts, row.inputs)} />
          {(avail?.retired || facts?.deprecated) && <span className="tag">being retired</span>}
          {!on && <Off why={row.off_why} />}
        </span>
      </td>
      <td>
        <select
          className="input"
          aria-label={`Tier of ${name}`}
          title="How strong this model is"
          value={row.tier ?? ''}
          onChange={e => onTier((e.target.value || null) as Tier | null)}
        >
          <option value="">no tier</option>
          {TIERS.map(tier => (
            <option key={tier} value={tier}>
              {tier}
            </option>
          ))}
        </select>
        {/* (One changed here and not saved yet is yours too: the facts are of the saved row.) */}
        {row.tier && facts && (facts.tier !== row.tier || facts.sources.tier === 'you') && (
          <span className="src" title="Set by you, not the catalogue’s">
            you
          </span>
        )}
      </td>
      {tiered ? (
        <td>
          <select
            className="input"
            aria-label={`Context of ${name}`}
            title="Copilot’s context window. Long costs more and holds only for the models Copilot offers it for."
            value={row.context ?? 'default'}
            onChange={e => onContext(e.target.value as ContextTier)}
          >
            <option value="default">Default</option>
            <option value="long_context">Long</option>
          </select>
          {/* shortcut: the catalogue has one window per model, which for Copilot may be the long tier's; the long
              tier's own size is not known, so none is shown for it. Show both once they are measured. */}
          {row.context !== 'long_context' && catalogued && (
            <span className="src" title="The catalogue’s context window">
              {catalogued}
            </span>
          )}
        </td>
      ) : (
        <Fact value={catalogued} />
      )}
      <Fact value={facts?.max_output ? tokens(facts.max_output) : null} />
      <Fact value={levels(efforts)} />
      <Fact value={plan ? 'plan' : price ? `${price.input} / ${price.output}` : null} />
      <td>
        <input
          type="checkbox"
          role="switch"
          className="model-agents"
          aria-label={`Agents may use ${name}`}
          checked={row.agents}
          onChange={e => onAgents(e.target.checked)}
        />
      </td>
      <td>
        <input
          type="checkbox"
          role="switch"
          className="switch"
          aria-label={`${name} on`}
          title="Off: nothing new starts on it - no chat, no agent, no learning. A turn already running goes on until it ends; Stop ends it now."
          checked={on}
          onChange={e => onEnabled(e.target.checked)}
        />
      </td>
      <td>
        <button type="button" className="icon-btn" aria-label={`Remove ${name}`} onClick={onRemove}>
          <X size={13} />
        </button>
      </td>
    </tr>
    {open && (
      <tr className="model-facts">
        <td colSpan={9}>
          {/* shortcut: what a model knows up to is not read from models.dev yet; add it when the catalogue's copy keeps it. */}
          <dl className="model-facts-grid">
            <Known name="Context window" value={said(facts?.context_window)} from={from('context_window')} />
            <Known name="Max output" value={said(facts?.max_output)} from={from('max_output')} />
            {provider && (provider.kind === 'openai_compat' || provider.kind === 'anthropic') && (
              <div>
                <dt>Changed on the server?</dt>
                <dd>
                  <button
                    type="button"
                    className="link-btn"
                    title="Asks the server, or Anthropic, again for its window and levels; no model is run"
                    onClick={() => void api.post(`/providers/${provider.id}/find-again`).then(() => setForgot(n => n + 1), () => {})}
                  >
                    Find again
                  </button>
                </dd>
              </div>
            )}
            <Known
              name="Thinking levels"
              value={efforts ? (efforts.length ? efforts.map(level => EFFORTS[level]).join(', ') : 'none') : null}
              from={from('efforts')}
            />
            <Known
              name={plan ? 'Price if paid per token (1M)' : 'Price in / out (1M)'}
              value={
                price
                  ? `${price.input} / ${price.output} ${price.currency}${price.cache_read != null ? `, cache read ${price.cache_read}` : ''}`
                  : null
              }
              from={from('price')}
            />
            <Known name="Known tier" value={facts?.tier ?? null} from={from('tier')} />
            <Known name="Takes besides text" value={inputsLine(withMarks(facts, row.inputs)?.inputs)} />
            <div>
              <dt>Mark by hand</dt>
              <dd>
                <MarkInputs name={name} marked={row.inputs} known={facts?.inputs} onChange={onInputs} />
                {provider && facts?.inputs?.some(said => said.source === 'tried') && (
                  // A refusal for another reason is not the model's word for good: the user takes it back.
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() =>
                      void api.delete(`/providers/${provider.id}/tried-inputs?model=${encodeURIComponent(name)}`).then(() => setForgot(n => n + 1), () => {})
                    }
                  >
                    Forget what was tried
                  </button>
                )}
              </dd>
            </div>
            <div>
              <dt>
                <label htmlFor={noteId}>Its note for agents</label>
              </dt>
              <dd>
                <input
                  id={noteId}
                  className="input"
                  aria-label={`Note of ${name}`}
                  value={row.note}
                  maxLength={120}
                  placeholder="Optional: what it is for"
                  onChange={e => onNote(e.target.value)}
                  onBlur={onNoteDone}
                />
              </dd>
            </div>
            {/* shortcut: which roles the Lead picked it for is not in the usage record; add it with Agents' history (81b). */}
            <Known name="Used in 30 days" value={used} />
          </dl>
        </td>
      </tr>
    )}
    </>
  )
}
