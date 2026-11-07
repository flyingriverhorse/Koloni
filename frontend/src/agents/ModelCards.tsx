import { type CSSProperties, type Dispatch, type ReactNode, type SetStateAction, useEffect, useState } from 'react'
import { api } from '../api/client'
import { EFFORTS, type Effort, type ModelFacts, type Provider, type Role, type RoleModel, TIERS, type Tier } from '../api/types'
import { type LoadFacts, levelsKnown, type Named, NAMED_WHY, namedLevel, namedOf, sourceOf, takesOf, type Takes, useModelFacts } from '../models/levels'
import { type LoadModels, ModelNameInput, ProviderOptions } from '../models/ModelNameInput'
import { modelName } from '../shell/modelName'
import type { RoleValues } from './AgentsPage'
import { cannotOf, ruleText } from './chart'
import { Cannot } from './roleParts'
import type { Part } from './RolePanel'

// K-rol-model (tasarim/specs/2026-11-06-rol-model-b.md): a role's Model part as question cards, and its read view as
// a grid of their answers.

type SetValues = (patch: Partial<RoleValues>) => void

/** Which model a role's agents use, as one choice over its fields (slice 81b). */
export type Uses = 'pick' | 'tier' | 'model' | 'conversation'
export function usesOf(values: Pick<RoleValues, 'provider_id' | 'tier'>, isLead: boolean): Uses {
  if (values.provider_id) return 'model'
  if (values.tier === 'conversation' || (!values.tier && isLead)) return 'conversation'
  return values.tier ? 'tier' : 'pick'
}
/** The fields a choice sets: the others' are cleared, so no leftover decides where an agent runs. */
export const NONE = { provider_id: null, model_id: null, tier: null, tier_min: null, tier_max: null }
export const USES: Record<Uses, (isLead: boolean, providers: Provider[]) => Partial<RoleValues>> = {
  pick: () => NONE,
  tier: () => ({ ...NONE, tier: 'balanced' }),
  model: (_lead, providers) => ({ ...NONE, provider_id: providers[0]?.id ?? null }),
  // (The Lead's own "none" is the conversation's model.)
  conversation: isLead => ({ ...NONE, tier: isLead ? null : 'conversation' }),
}

const LEVELS = Object.keys(EFFORTS) as Effort[]
const at = (level: Effort) => LEVELS.indexOf(level)
/** Auto's most where the user set none (app/agent/spawn_mixin.py `AUTO_MOST`). */
const AUTO_MOST: Effort = 'high'

/** The Lead: nobody opens it, so nobody picks its level - its most means nothing; the chat's level goes first. */
const leadRole = (role: Role) => role.builtin && role.name === 'Lead'

/** A role's thinking in a few words: its card's header, and where it runs. */
function thinkingShort(effort: Effort | null, most: Effort | null, lead: boolean): string {
  if (lead) return effort ? EFFORTS[effort] : 'Auto'
  if (!effort) return `Auto · up to ${EFFORTS[most ?? AUTO_MOST]}`
  return most ? `${EFFORTS[effort]}, up to ${EFFORTS[most]}` : `Always ${EFFORTS[effort]}`
}

/** A role's thinking as its read view says it: one line, with a second only where the model or the Lead needs it. */
function thinkingSaid(effort: Effort | null, most: Effort | null, takes: Takes, lead: boolean, named: Named = false): [string, string?] {
  if (Array.isArray(takes) && takes.length === 0) return ['The model’s own', `${named ? NAMED_WHY[named] : 'its levels aren’t known'}: none is sent`]
  if (lead) return effort ? [EFFORTS[effort], 'unless the chat sets a level'] : ['Auto', 'the chat’s level, or the model’s own']
  return [thinkingShort(effort, most, false)]
}

/** One question card: its header reachable by keyboard (a <summary>), open while the role is edited. */
function Card({ title, now, id, children }: { title: string; now: ReactNode; id?: string; children: ReactNode }) {
  return (
    <details id={id} className="role-q" open>
      <summary>
        <h4>{title}</h4>
        <span className="role-q-now">{now}</span>
      </summary>
      <div className="role-q-body">{children}</div>
    </details>
  )
}

/** What one line under a setting leaves out, folded. */
function LearnMore({ children }: { children: ReactNode }) {
  return (
    <details className="more">
      <summary>Learn more</summary>
      <div className="role-learn">{children}</div>
    </details>
  )
}

const ownModel = (row: RoleModel) => row.source === 'role' || row.source === 'tier'

/** Where a role's agents run now with no tier given for the job, how hard they think, and why there. */
function RunsOn({ role, row }: { role: Role; row: RoleModel }) {
  // Why a tier's pick is not its first model, or why none of the tier was had (B-314): the agent's card says the same.
  const why =
    row.moved ??
    (row.source === 'role'
      ? 'its own model, set by you'
      : row.source === 'tier'
        ? `the first ${row.tier} model of your team guide, where the Orchestrator names no tier`
        : row.tier
          ? `no model in your team guide that may be picked for it has the ${row.tier} tier`
          : 'it has no model of its own')
  return (
    <p className="role-runs">
      Runs on <b>{ownModel(row) ? `${row.provider_name} · ${row.model_id ? modelName(row.model_id) : 'its default'}` : 'the conversation’s model'}</b>
      , thinking <b>{thinkingShort(role.effort, role.max_effort, leadRole(role))}</b> — {why}.
      {row.cannot_run && <span className="role-runs-not"> It would not run there now: {row.cannot_run}</span>}
    </p>
  )
}

export interface CardsProps {
  role: Role | null
  /** Where the role was copied from, or itself: its "Only these" list as kept. */
  from: Role | undefined
  values: RoleValues
  set: SetValues
  uses: Uses
  pick: (one: Uses) => void
  isLead: boolean
  observer: boolean
  teamLead: boolean
  providers: Provider[]
  onModels?: LoadModels
  onFacts?: LoadFacts
  runs?: RoleModel
  /** The levels its saved model takes, and its window as found (see `RoleEditor`). */
  savedTakes?: Takes
  savedFound?: { window: number | null; from: string } | null
  windowText: string
  setWindowText: (text: string) => void
  contextWindow: number | null | undefined
  at?: Part
}

/** The provider and model whose levels and window the cards show: the one picked here, where the role has its own;
 *  else the one its agents run on now (who uses what, as saved). */
function factsModel(own: Provider | undefined, ran: Provider | undefined, values: RoleValues, runs: RoleModel | undefined): [string | null, string] {
  if (own) return [own.id, (values.model_id ?? '').trim() || (own.default_model ?? '')]
  return [ran?.id ?? null, runs?.model_id ?? ran?.default_model ?? '']
}

const foundIn = (facts: ModelFacts | null | undefined) => facts && { window: facts.context_window, from: facts.context_window ? sourceOf(facts, 'context_window') : '' }

/** What the cards say of its model: its levels and window, as looked up here or as saved. */
function useCardFacts({ role, values, providers, onFacts, runs, savedTakes, savedFound }: CardsProps) {
  const own = onFacts ? providers.find(p => p.id === values.provider_id) : undefined
  const ran = own ? undefined : runs && providers.find(p => p.name === runs.provider_name)
  const which = factsModel(own, ran, values, runs)
  const facts = useModelFacts(onFacts, ...which)
  return {
    takes: own ? takesOf(facts) : savedTakes,
    found: own ? foundIn(facts) : savedFound,
    levelsFrom: facts?.efforts?.length ? ` Levels ${sourceOf(facts, 'efforts')}.` : '',
    named: own ? namedLevel(facts) : namedOf(runs?.level_named, which[1]),
    // Before its first save nothing is looked up.
    known: !!(role || own),
    retiring: !!(own && facts?.deprecated),
  }
}

/** The Model part of a role's form: where it runs now, then a card for each question. */
export function ModelCards(props: CardsProps) {
  const { role, values, providers, runs } = props
  const { takes, found, levelsFrom, named, known, retiring } = useCardFacts(props)
  return (
    <>
      {role && runs && <RunsOn role={role} row={runs} />}
      <WhichModel {...props} />
      {/* Not for the Observer: its one question is asked with no level. */}
      {!props.observer && <ThinkingCard lead={props.isLead} values={values} set={props.set} takes={takes} known={known} levelsFrom={levelsFrom} named={named} retiring={retiring} />}
      <WindowCard known={known} found={found} windowText={props.windowText} setWindowText={props.setWindowText} contextWindow={props.contextWindow} at={props.at} />
      {providers.length > 0 && <PicksCard values={values} set={props.set} from={props.from} providers={providers} />}
      {/* 89g: not for the Lead, the Observer or a team's lead - none is opened by a Lead. */}
      {!props.isLead && !props.observer && !props.teamLead && <InsideCard values={values} set={props.set} />}
    </>
  )
}

/** Which model: who picks it, then only what that choice needs, and the models tried first. */
function WhichModel({ values, set, uses, pick, isLead, providers, onModels }: CardsProps) {
  // K-rol-model-sirasi: the pair being added to the preferred list - from the team guide, where agents may run.
  const guided = providers.filter(p => p.for_agents && p.enabled !== false)
  const [adding, setAdding] = useState({ provider_id: guided[0]?.id ?? '', model_id: '' })
  return (
    <Card title="Which model" now={ruleText(values, providers, isLead)}>
      <WhoPicks uses={uses} isLead={isLead} providers={providers} pick={pick} />
      {uses === 'pick' && <TierRange values={values} set={set} />}
      {uses === 'tier' && <OneTier values={values} set={set} />}
      {uses === 'model' && <OneModel values={values} set={set} providers={providers} onModels={onModels} />}
      <span id="role-uses-note" className="choice-note">
        {USES_NOTE[uses]}
      </span>
      {guided.length > 0 && <PreferredModels providers={providers} guided={guided} listed={values.models ?? []} set={set} adding={adding} setAdding={setAdding} onModels={onModels} />}
      <LearnMore>
        <p>A tier runs on its first model, in the order on the Models page - the chat’s own provider is not preferred.</p>
        <p>If the Orchestrator names no tier, it gets balanced, or the nearest end of the range. If no model it may use has that tier, it runs on the chat’s model.</p>
        <p>
          If a provider fails before it says a word (down, or queued too long), the sub-agent moves once: to its next preferred model, then the tier’s next model.
          You approve that on a card, unless the chat’s spawn approval is “never”, and only while you watch the turn.
        </p>
      </LearnMore>
    </Card>
  )
}

const USES_NOTE: Record<Uses, string> = {
  pick: 'It picks a tier for each job, inside this range, and says why.',
  conversation: 'Whatever the chat’s model picker says.',
  tier: 'Always this tier. The Orchestrator can’t change it.',
  model: 'Always this model, whatever the job.',
}

/** Who picks the model: four choices (the Lead, whom nobody opens, has no Orchestrator). */
const WHO: [Uses, string][] = [
  ['pick', 'Orchestrator'],
  ['conversation', 'As the chat'],
  ['tier', 'One tier'],
  ['model', 'One model'],
]

/** The first question: who picks the model. */
function WhoPicks({ uses, isLead, providers, pick }: Pick<CardsProps, 'uses' | 'isLead' | 'providers' | 'pick'>) {
  return (
    <>
      <span id="role-who" className="q">
        Who picks it?
      </span>
      <div role="radiogroup" aria-labelledby="role-who" aria-describedby="role-uses-note" className="role-seg">
        {WHO.filter(([one]) => one !== 'pick' || !isLead).map(([one, title]) => (
          <Rung key={one} name="role-model" label={title} checked={uses === one} disabled={one === 'model' && providers.length === 0} onPick={() => pick(one)} />
        ))}
      </div>
    </>
  )
}

/** One tier, always: Fast, Balanced or Strongest. */
function OneTier({ values, set }: { values: RoleValues; set: SetValues }) {
  return (
    <div role="radiogroup" aria-label="Tier" className="role-seg">
      {TIERS.map(tier => (
        <Rung key={tier} name="role-tier" label={`${tier[0].toUpperCase()}${tier.slice(1)}`} checked={values.tier === tier} disabled={false} onPick={() => set({ ...NONE, tier })} />
      ))}
    </div>
  )
}

/** One model, always: its provider and its name (empty: the provider's default). */
function OneModel({ values, set, providers, onModels }: Pick<CardsProps, 'values' | 'set' | 'providers' | 'onModels'>) {
  return (
    <span className="role-tier-range">
      <select id="role-provider" aria-label="Provider" className="input" value={values.provider_id ?? ''} onChange={e => set({ provider_id: e.target.value, model_id: null })}>
        <ProviderOptions providers={providers} />
      </select>
      <ModelNameInput
        label="Model name"
        value={values.model_id ?? ''}
        placeholder={providers.find(p => p.id === values.provider_id)?.default_model ?? 'its default'}
        providerId={values.provider_id ?? ''}
        loadModels={onModels}
        onChange={value => set({ model_id: value || null })}
      />
    </span>
  )
}

/** The tiers the Orchestrator may pick from. */
function TierRange({ values, set }: { values: RoleValues; set: SetValues }) {
  return (
    <span className="role-tier-range">
      {(
        [
          ['tier_min', 'From', TIERS[0]],
          ['tier_max', 'To', TIERS[TIERS.length - 1]],
        ] as const
      ).map(([key, label, end]) => (
        <label key={key} htmlFor={`role-${key}`}>
          {label}{' '}
          <select id={`role-${key}`} className="input" value={values[key] ?? end} onChange={e => set({ [key]: e.target.value === end ? null : (e.target.value as Tier) })}>
            {TIERS.map(tier => (
              <option key={tier} value={tier}>
                {tier}
              </option>
            ))}
          </select>
        </label>
      ))}
    </span>
  )
}

/** The preferred model being added: its provider and name. */
type Adding = { provider_id: string; model_id: string }

/** The models tried first, in order (K-rol-model-sirasi): "Try first", and "+ Add a model" to add one. */
function PreferredModels({ providers, guided, listed, set, adding, setAdding, onModels }: {
  providers: Provider[]
  guided: Provider[]
  listed: NonNullable<RoleValues['models']>
  set: SetValues
  adding: Adding
  setAdding: Dispatch<SetStateAction<Adding>>
  onModels: LoadModels | undefined
}) {
  const [open, setOpen] = useState(false)
  const move = (from: number, by: number) => {
    const next = [...listed]
    next.splice(from + by, 0, ...next.splice(from, 1))
    set({ models: next })
  }
  return (
    <div className="field">
      <span className="role-tier-range">
        <span className="q">Try first:</span>
        {listed.length === 0 && <span className="muted">none</span>}
        {listed.length < 5 && !open && (
          <button type="button" className="btn btn-small" onClick={() => setOpen(true)}>
            + Add a model
          </button>
        )}
      </span>
      {listed.length > 0 && (
        <ol className="role-picks" aria-label="Preferred models, in order">
          {listed.map((one, i) => (
            <li key={`${one.provider_id} ${one.model_id}`}>
              {i + 1}. {providers.find(p => p.id === one.provider_id)?.name ?? 'a provider no longer set up'} · {modelName(one.model_id)}{' '}
              <button type="button" className="btn btn-small" disabled={i === 0} aria-label={`Move ${modelName(one.model_id)} up`} onClick={() => move(i, -1)}>
                ↑
              </button>{' '}
              <button type="button" className="btn btn-small" disabled={i === listed.length - 1} aria-label={`Move ${modelName(one.model_id)} down`} onClick={() => move(i, 1)}>
                ↓
              </button>{' '}
              <button type="button" className="btn btn-small" aria-label={`Remove ${modelName(one.model_id)}`} onClick={() => set({ models: listed.filter((_, j) => j !== i) })}>
                ×
              </button>
            </li>
          ))}
        </ol>
      )}
      {listed.length < 5 && open && <AddPreferred guided={guided} listed={listed} set={set} adding={adding} setAdding={setAdding} onModels={onModels} onCancel={() => setOpen(false)} />}
      <span className="choice-note">Up to 5 from the team guide, tried in order before the choice above.</span>
    </div>
  )
}

/** The row that adds a preferred model: a provider of the team guide and a model name. */
function AddPreferred({ guided, listed, set, adding, setAdding, onModels, onCancel }: Omit<Parameters<typeof PreferredModels>[0], 'providers'> & { onCancel: () => void }) {
  return (
    <span className="role-tier-range">
      <select id="role-prefer-provider" aria-label="Preferred models" className="input" value={adding.provider_id} onChange={e => setAdding({ provider_id: e.target.value, model_id: '' })}>
        {guided.map(p => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <ModelNameInput label="Preferred model name" value={adding.model_id} placeholder="Model name" providerId={adding.provider_id} loadModels={onModels} onChange={model_id => setAdding(a => ({ ...a, model_id }))} />
      <button
        type="button"
        className="btn btn-small"
        disabled={!adding.model_id.trim() || listed.some(one => one.provider_id === adding.provider_id && one.model_id === adding.model_id.trim())}
        onClick={() => {
          set({ models: [...listed, { provider_id: adding.provider_id, model_id: adding.model_id.trim() }] })
          setAdding(a => ({ ...a, model_id: '' }))
        }}
      >
        Add
      </button>
      <button
        type="button"
        className="btn btn-small"
        aria-label="Cancel adding a model"
        onClick={() => {
          setAdding(a => ({ ...a, model_id: '' }))
          onCancel()
        }}
      >
        Cancel
      </button>
    </span>
  )
}

type Thinking = Pick<RoleValues, 'effort' | 'max_effort'>

/** A fixed level, keeping a most set earlier only above it: the API refuses a most below the level. */
const startAt = (level: Effort, most: Effort | null): Thinking => ({ effort: level, max_effort: most && at(most) > at(level) ? most : null })

/** Back to Auto: a most of Off, or one its model is known not to take, is taken away (Auto never picks Off). An empty
 *  list of levels means they are not known: the most stays. */
const autoOf = (most: Effort | null, takes: Takes): Thinking => ({ effort: null, max_effort: most && most !== 'off' && (!takes?.length || takes.includes(most)) ? most : null })

/** One fixed level starts at Medium, or the nearest lower level its model takes, or the lowest it takes. */
const fixedStart = (taken: Effort[]): Effort | undefined => taken.filter(level => at(level) <= at('medium')).at(-1) ?? taken[0]

/** Auto's most where none is set, as shown: High, or the nearest lower level its model takes - the one sent then.
 *  (Shown only: nothing is saved until a level is clicked.) */
const autoMost = (taken: Effort[]): Effort => taken.filter(level => level !== 'off' && at(level) <= at(AUTO_MOST)).at(-1) ?? AUTO_MOST

/** The most Auto's ladder marks: the one set, else `autoMost`; a most of Off set earlier on the lowest level it takes
 *  (Off itself is never picked by Auto). */
function shownMost(most: Effort | null, taken: Effort[]): Effort | undefined {
  if (most === 'off') return taken.find(level => level !== 'off')
  return most ?? autoMost(taken)
}

/** A most set earlier that the ladder doesn't choose: above a fixed level, or Off under Auto. */
const setEarlier = ({ effort, max_effort: most }: Thinking) => (effort ? startAt(effort, most).max_effort : most === 'off' ? most : null)

/** The one line under the ladder: what it means now, and what a click does. */
function ladderNote(values: Thinking, lead: boolean, taken: Effort[]): string {
  const { effort, max_effort: most } = values
  if (lead) return effort ? `It runs at ${EFFORTS[effort]}, unless the chat’s model picker sets a level.` : 'Auto: no level is sent; the chat’s level, or the model’s own, applies.'
  if (!effort) return most === 'off' ? 'Auto picks a level for each task.' : `Auto picks a level for each task, from Low up to ${EFFORTS[most ?? autoMost(taken)]}. Click a level to move “most”.`
  return `Every task gets ${EFFORTS[effort]}.${setEarlier(values) ? '' : ' The Orchestrator doesn’t change it.'} Click another level to change it.`
}

/** Of a saved level its model does not take: what goes instead. */
function unsentNote(saved: (Effort | null)[], takes: Effort[]): string {
  const unsent = [...new Set(saved.filter((level): level is Effort => !!level && !takes.includes(level)))]
  return unsent.length && takes.length ? ` ${unsent.map(level => EFFORTS[level]).join(', ')} as saved: the nearest lower level it takes is sent, or none.` : ''
}

/** What its model takes, and - in so many words - the levels struck on the ladder. */
function levelsNote(known: boolean, takes: Takes, levelsFrom: string, named: Named): string {
  if (!known) return 'Its model’s levels are looked up once the role is saved.'
  const struck = LEVELS.filter(level => !takes?.includes(level))
  return `${levelsKnown(takes, named)}${takes?.length ? `${levelsFrom} ${struck.map(level => EFFORTS[level]).join(', ')}: not taken by this model.` : ''}`
}

/** One choice of a segmented row: a radio with its name. */
function Rung({ name, label, checked, disabled, onPick }: { name: string; label: string; checked: boolean; disabled: boolean; onPick: () => void }) {
  return (
    <label className="role-seg-one">
      <input type="radio" name={name} checked={checked} disabled={disabled} onChange={onPick} />
      {label}
    </label>
  )
}

type ThinkingProps = { lead: boolean; values: RoleValues; set: SetValues; takes: Takes; known: boolean; levelsFrom: string; named: Named; retiring: boolean }

/** How hard it thinks: Auto or one fixed level, and one ladder of the levels - Auto's most, or the fixed level. */
function ThinkingCard({ lead, values, set, takes, known, levelsFrom, named, retiring }: ThinkingProps) {
  const { effort, max_effort: most } = values
  const taken = takes ?? []
  const fixed = fixedStart(taken)
  return (
    <Card id="role-part-thinking" title="How hard it thinks" now={thinkingShort(effort, most, lead)}>
      <div role="radiogroup" aria-label="Thinking" className="role-seg">
        <Rung name="role-thinking" label="Auto" checked={!effort} disabled={false} onPick={() => set(autoOf(most, takes))} />
        <Rung name="role-thinking" label="One fixed level" checked={!!effort} disabled={!effort && !fixed} onPick={() => fixed && set(startAt(fixed, most))} />
      </div>
      <Ladder lead={lead} values={values} set={set} taken={taken} />
      <span id="role-ladder-note" className="choice-note">
        {ladderNote(values, lead, taken)}
      </span>
      {!lead && <SetEarlier values={values} set={set} />}
      {!effort && !lead && <span className="choice-note">It picks Low for reading or summarizing, Medium for normal code, High for hard bugs or design.</span>}
      <span className="choice-note">
        {levelsNote(known, takes, levelsFrom, named)}
        {unsentNote([effort, most], taken)}
        {retiring && ' Its model is being retired: it still runs.'}
      </span>
      <LearnMore>
        {!lead && (
          <>
            <p>Auto never goes above High unless you move “most” to XHigh or Max. Move it down to keep every task cheaper.</p>
            <p>If the Orchestrator picks no level, the fixed level runs; with Auto, Medium (or the most, where that is lower).</p>
            <p>Auto never picks Off: only you set Off, as a fixed level.</p>
          </>
        )}
        <p>On a model without the level, the nearest lower level it takes is sent - never down to Off.</p>
        <p>The agent’s window shows the level it got{lead ? '' : ', and the Orchestrator’s reason where it picked one'}.</p>
      </LearnMore>
    </Card>
  )
}

/** A most set earlier, which the ladder no longer chooses, said with its Remove. */
function SetEarlier({ values, set }: { values: RoleValues; set: SetValues }) {
  const most = setEarlier(values)
  if (!most) return null
  return (
    <span className="choice-note">
      {values.effort ? `The Orchestrator may also go up to ${EFFORTS[most]} (set earlier).` : 'Up to Off (set earlier).'}{' '}
      <button type="button" className="link-btn" aria-label={`Remove the most of ${EFFORTS[most]}`} onClick={() => set({ max_effort: null })}>
        Remove
      </button>
    </span>
  )
}

/** Why a level can't be picked: its model does not take it, or Auto never picks Off. */
function whyNot(level: Effort, taken: Effort[], auto: boolean): string | undefined {
  if (!taken.includes(level)) return 'Not taken by this model'
  return auto && level === 'off' ? 'Auto never picks Off' : undefined
}

/** The ladder, Off to Max, as radios: in Auto the most it may pick (the band up to it shaded), else the fixed level.
 *  Levels its model does not take are struck. (Nobody opens the Lead: a click sets its level, never a most.) */
function Ladder({ lead, values, set, taken }: { lead: boolean; values: RoleValues; set: SetValues; taken: Effort[] }) {
  const { effort, max_effort: most } = values
  const auto = !effort && !lead
  const cap = auto ? shownMost(most, taken) : undefined
  return (
    <div role="radiogroup" aria-label={auto ? 'Most the Orchestrator may pick' : 'Fixed level'} aria-describedby="role-ladder-note" className="role-ladder">
      {LEVELS.map(level => {
        const why = whyNot(level, taken, auto)
        const band = cap && level !== 'off' && taken.includes(level) && at(level) <= at(cap)
        return (
          <label key={level} className={`role-ladder-one${band ? ' role-ladder-in' : ''}${taken.includes(level) ? '' : ' role-ladder-no'}`} title={why}>
            <input type="radio" name="role-ladder" checked={level === (auto ? cap : effort)} disabled={!!why} onChange={() => set(auto ? { max_effort: level } : startAt(level, most))} />
            {EFFORTS[level]}
            {/* (Decorative: the group's name says what is checked.) */}
            {level === cap && (
              <span className="role-ladder-most" aria-hidden="true">
                most
              </span>
            )}
          </label>
        )
      })}
    </div>
  )
}

/** The window line: as found, unknown, or not looked up (yet). */
function foundText(known: boolean, found: CardsProps['savedFound']): string {
  if (found === undefined) return known ? 'Looking up the model’s window…' : 'Its model’s window is looked up once the role is saved.'
  if (found === null) return 'Could not look up the model’s window.'
  return found.window ? `Found automatically: ${found.window.toLocaleString('en-US')} tokens (${found.from}).` : 'Found automatically: unknown.'
}

/** The app's "Summarise a long context at (%)" (Settings › The app), where the window card's bar marks it. */
function useCompactAt(): number {
  // shortcut: 75 (app/agent/summary.py COMPACT_AT) until it is read, or where it can't be; pass it down if that shows.
  const [at, setAt] = useState(75)
  useEffect(() => {
    let live = true
    api.get<{ compact_at: number }>('/compaction').then(
      read => live && setAt(read.compact_at),
      () => {},
    )
    return () => {
      live = false
    }
  }, [])
  return at
}

/** The bar under the window (decorative: the note says it in words): where KOLONİ summarizes, or striped where the
 *  window is unknown. No fill - a role has no fullness of its own. */
function WindowBar({ known }: { known: boolean }) {
  const at = useCompactAt()
  if (!known) return <div className="role-meter role-meter-unknown" aria-hidden="true" />
  return (
    <div className="role-meter" aria-hidden="true" style={{ '--at': `${at}%` } as CSSProperties}>
      <b />
      <span>summarized past {at}%</span>
    </div>
  )
}

/** How much it reads: the window found, and one set by hand under its fold. */
function WindowCard({ known, found, windowText, setWindowText, contextWindow, at: part }: Pick<CardsProps, 'windowText' | 'setWindowText' | 'contextWindow' | 'at'> & { known: boolean; found: CardsProps['savedFound'] }) {
  // Opened once where one is set (or its Edit was clicked); then as the user leaves it, so it never shuts while typed in.
  const [byHand] = useState(windowText !== '' || part === 'window')
  const win = contextWindow || found?.window
  return (
    <Card id="role-part-window" title="How much it reads" now={win ? `${win.toLocaleString('en-US')} tokens` : 'Unknown'}>
      <span className="choice-note">{foundText(known, found)}</span>
      <WindowBar known={!!win} />
      <span className="choice-note">
        {win
          ? 'Past the % in Settings › The app (“Summarise a long context at (%)”), KOLONİ summarizes the older part - unless its CLI keeps its own session and does that itself.'
          : 'No fullness meter, and KOLONİ doesn’t summarize it early.'}
      </span>
      <details className="more" open={byHand}>
        <summary>Set by hand</summary>
        <div className="field">
          <label htmlFor="role-window">Context window</label>
          <input
            id="role-window"
            className="input mono"
            inputMode="numeric"
            value={windowText}
            placeholder={found?.window ? String(found.window) : 'Unknown'}
            aria-invalid={contextWindow === undefined || undefined}
            aria-describedby="role-window-note"
            onChange={e => setWindowText(e.target.value)}
          />
          <span id="role-window-note" className="choice-note">
            {contextWindow === undefined && 'A whole number above zero, or empty for the one found. '}
            {contextWindow ? 'Set by you; empty it to use the one found. ' : ''}
            Use it where the window is unknown (say, a CLI with no fixed model), or to summarize earlier. The model’s server refuses a
            window bigger than the model’s own.
          </span>
        </div>
      </details>
      <LearnMore>
        <p>KOLONİ also keeps what it sends under a fixed size, dropping the oldest tool output first.</p>
        <p>A model reached over an API that says it’s full gets its older part summarized then. A CLI that keeps its own session summarizes itself.</p>
      </LearnMore>
    </Card>
  )
}

type Picks = 'all' | 'some' | 'none'
const PICKS: [Picks, string][] = [
  ['all', 'Any provider in the team guide'],
  ['some', 'Only these'],
  ['none', 'No one'],
]

/** Who may move it: the providers an agent may put a sub-agent of this role on instead. */
function PicksCard({ values, set, from, providers }: Pick<CardsProps, 'values' | 'set' | 'from' | 'providers'>) {
  // "Only these" with none ticked yet is still that choice, though it is sent as none.
  const [some, setSome] = useState((from?.pick_from?.length ?? 0) > 0)
  const picks = values.pick_from ?? []
  const choice: Picks = values.pick_from === null ? 'all' : some ? 'some' : 'none'
  const choose = (one: Picks) => {
    setSome(one === 'some')
    set({ pick_from: one === 'all' ? null : one === 'some' ? picks : [] })
  }
  return (
    <Card id="role-part-picks" title="Who may move it" now={choice === 'all' ? 'Any in the team guide' : picksNames(providers, picks)}>
      <span className="q">An agent that opens it may move it to another provider. It must say why; the card shows the reason.</span>
      <div role="radiogroup" aria-label="May be picked for this role" className="role-opts">
        {PICKS.map(([one, title]) => (
          <label key={one} className="choice">
            <input type="radio" name="role-picks" checked={choice === one} onChange={() => choose(one)} />
            <span>
              {title}
              {one === 'none' && <span className="choice-note">It stays on the model chosen above.</span>}
            </span>
          </label>
        ))}
      </div>
      {choice === 'some' && <PickList values={values} set={set} providers={providers} />}
      <LearnMore>
        <p>Only a provider in the team guide (Models page, “Agents may choose this”) can ever be picked.</p>
      </LearnMore>
    </Card>
  )
}

/** "Only these": the team guide's providers - and what the list holds that is not in the guide now. */
function PickList({ values, set, providers }: Pick<CardsProps, 'values' | 'set' | 'providers'>) {
  const picks = values.pick_from ?? []
  const pickable = providers.filter(p => (p.for_agents && p.enabled !== false) || picks.includes(p.id))
  const toggle = (id: string) => {
    const next = picks.includes(id) ? picks.filter(one => one !== id) : [...picks, id]
    set({ pick_from: providers.map(p => p.id).filter(one => next.includes(one)) })
  }
  if (pickable.length === 0) return <span className="choice-note">No provider is in the team guide: tick “Agents may choose this” for one on the Models page.</span>
  return (
    <div className="role-pick-list">
      {pickable.map(p => (
        <label key={p.id} className="choice" htmlFor={`pick-${p.id}`}>
          <input id={`pick-${p.id}`} type="checkbox" checked={picks.includes(p.id)} onChange={() => toggle(p.id)} />
          <span>
            {p.name}
            {!p.for_agents && <span className="choice-note">not in the team guide now: it cannot be picked until it is</span>}
          </span>
        </label>
      ))}
    </div>
  )
}

const picksNames = (providers: Provider[], picks: string[]) => providers.filter(p => picks.includes(p.id)).map(p => p.name).join(', ') || 'No one'

/** 89g: run inside the CLI of the agent that opens it, where that is Claude Code. */
function InsideCard({ values, set }: Pick<CardsProps, 'values' | 'set'>) {
  return (
    <Card id="role-part-inside" title="Run inside the CLI" now={values.inside_cli ? 'On' : 'Off'}>
      <label className="choice" htmlFor="role-inside-cli">
        <input id="role-inside-cli" type="checkbox" checked={values.inside_cli} onChange={e => set({ inside_cli: e.target.checked })} />
        <span>Run inside the CLI of the agent that opens it</span>
      </label>
      <span className="choice-note">Only when the agent opening it runs in Claude Code.</span>
      <div className="role-pros">
        <div>
          <b>Good</b>
          <ul>
            <li>cheaper</li>
            <li>counts toward no turn or role limit</li>
          </ul>
        </div>
        <div>
          <b>Keep in mind</b>
          <ul>
            <li>not its own agent on the canvas</li>
            <li>stops when the agent that opened it stops</li>
            <li>never used while you're away or for a trigger</li>
          </ul>
        </div>
      </div>
      <LearnMore>
        <p>Its own model is used only where it is on the same provider as the agent opening it; otherwise it runs on that agent’s model.</p>
        <p>Not offered when the chat asks you before every sub-agent, or when Claude Code is installed as an npm .cmd and the instructions hold any of % &amp; | &lt; &gt; !</p>
      </LearnMore>
    </Card>
  )
}

/** One answer of the read view: a question, its answer and a line under it; a click opens the form at its card. */
function Answer({ question, answer, line, wide, onOpen }: { question: string; answer: ReactNode; line?: string; wide?: boolean; onOpen: () => void }) {
  return (
    <button type="button" className={`role-answer${wide ? ' role-answer-wide' : ''}`} onClick={onOpen}>
      <span className="kicker">{question}</span>
      <span className="role-answer-v">{answer}</span>
      {line && <span className="role-answer-s">{line}</span>}
    </button>
  )
}

/** The window as its read view says it. */
function windowSaid(role: Role, runs: RoleModel | undefined): [string, string] {
  if (role.context_window) return [`${role.context_window.toLocaleString('en-US')} tokens`, 'set by you']
  if (runs?.context_window) return [`${runs.context_window.toLocaleString('en-US')} tokens`, 'found automatically']
  return ['Unknown', 'no fullness meter']
}

/** Who may move it, as its read view says it. */
function picksSaid(role: Role, providers: Provider[]): [string, string] {
  if (role.pick_from === null) return ['Any provider', 'in the team guide, with a reason']
  if (role.pick_from.length === 0) return ['No one', 'stays on its own model']
  return [picksNames(providers, role.pick_from), 'only these, with a reason']
}

/** The read view of a role's Model part: a 2 × 2 grid of answers (K-rol-model). */
export function ModelAnswers({ role, runs, providers, teamLead, onEdit }: { role: Role; runs?: RoleModel; providers: Provider[]; teamLead: boolean; onEdit: (part: Part) => void }) {
  const observer = role.builtin && role.name === 'Observer'
  const inside = !teamLead && !observer && !leadRole(role)
  const [think, thinkLine] = thinkingSaid(role.effort, role.max_effort, runs?.efforts, leadRole(role),
    namedOf(runs?.level_named, runs?.model_id ?? providers.find(p => p.name === runs?.provider_name)?.default_model))
  const [win, winLine] = windowSaid(role, runs)
  const [picks, picksLine] = picksSaid(role, providers)
  return (
    <section className="role-model" aria-label="Model">
      <div className="role-model-head">
        <span className="kicker">Model</span>
        <button type="button" className="link-btn" aria-label="Edit model" onClick={() => onEdit('model')}>
          Edit
        </button>
      </div>
      <div className="role-answers">
        <Answer
          question="Which model"
          answer={
            <>
              {/* K-rol-model-sirasi: its preferred models first, then its rule. */}
              {role.models && role.models.length > 0 && <>First {role.models.map(one => modelName(one.model_id)).join(', then ')} — then </>}
              {ruleText(role, providers, leadRole(role))}
            </>
          }
          line={runs?.provider_name && `now on ${runs.provider_name}${runs.model_id ? ` · ${modelName(runs.model_id)}` : ''}`}
          onOpen={() => onEdit('model')}
        />
        {!observer && <Answer question="How hard it thinks" answer={think} line={thinkLine} onOpen={() => onEdit('thinking')} />}
        <Answer question="How much it reads" answer={win} line={winLine} onOpen={() => onEdit('window')} />
        <Answer question="Who may move it" answer={picks} line={picksLine} onOpen={() => onEdit('picks')} />
        {inside && <Answer wide question="Runs as" answer={role.inside_cli ? 'a helper inside the CLI of the agent that opens it' : 'its own agent'} onOpen={() => onEdit('inside')} />}
      </div>
      <Cannot said={cannotOf(runs, 'step', 'room')} />
    </section>
  )
}
