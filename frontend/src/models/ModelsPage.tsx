import { Plus, X } from '@phosphor-icons/react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import type { Availability, ClaudeSessionSetup, CatalogueDraft, CatalogueFill, CatalogueUpdate, FillAll, FilledProvider, Limits, LocalServer, LocalServerConfig, ModelInput, Price, Provider, ProviderTest, Suggestion, Tier, TierOrder, Tiers, Usage } from '../api/types'
import { useConfirm } from '../shell/Confirm'
import { limitUnkept } from '../usage/cost'
import { since } from '../usage/period'
import { OFF_MEANS, paidOf, ProviderCard, readingOf } from './cards'
import { FillTiers } from './FillTiers'
import type { LimitsChange } from './LimitsTab'
import type { ServerAction } from './LocalServerTab'
import type { LoadModels } from './ModelNameInput'
import { dayOf, type LoadFacts } from './levels'
import { ProviderEditor, type Tab } from './ProviderEditor'
import { TierSlots } from './TierSlots'

export type ProviderKind = Provider['kind']
export type Mode = NonNullable<Provider['mode']>
export type SignIn = 'own' | 'koloni'

/** Whose sign-in a provider runs on (K-claude-hesap): a folder of its own for KOLONİ, or the user's own. */
export const signInOf = (provider: Provider | null | undefined): SignIn =>
  (provider?.options as { sign_in?: string } | null)?.sign_in === 'koloni' ? 'koloni' : 'own'

/** What is sent when a provider is added. */
export interface NewProvider {
  name: string
  kind: ProviderKind
  base_url?: string
  api_key?: string
  default_model: string
  executable?: string
  mode?: Mode
  /** Copilot: how its own model server is spoken to. Anthropic: the workspace of its key.
   *  Native Claude Code: whether it starts with your own setup; Claude Code and Codex: whose sign-in. */
  options?: CopilotOptions | AnthropicOptions | { own_setup?: boolean; sign_in?: SignIn }
  /** The team guide: agents may choose it, what it is good for, its selectable models. */
  for_agents?: boolean
  note?: string
  models?: ListedModel[]
  /** Never run with a model outside the list, nor with none. */
  only_listed?: boolean
  /** The most agents at work on it at once, in the whole app; null: its kind's default. */
  max_running?: number | null
  /** False: switched off - nobody uses it; its key and settings stay. */
  enabled?: boolean
}

export interface ListedModel {
  name: string
  note: string | null
  /** null: in no automatic choice - it is only ever picked by name. */
  tier: Tier | null
  /** Whether agents may pick it; the user still can, by hand. */
  agents: boolean
  /** False: switched off - nobody uses it, you neither; left out, what it had is kept. */
  enabled?: boolean
  /** What the user marked it to take besides text (slice 85b); left out, what it had is kept. */
  inputs?: ModelInput[] | null
  /** Copilot on your GitHub account: its context window tier; left out, what it had is kept. */
  context?: ContextTier | null
}

export type ContextTier = NonNullable<Provider['models'][number]['context']>

export interface CopilotOptions {
  provider_type: 'openai' | 'anthropic'
  max_prompt_tokens: number | null
  max_output_tokens: number | null
  /** Never go to GitHub: no sign-in, telemetry or update check. */
  offline: boolean
}

export interface AnthropicOptions {
  /** The workspace the key belongs to; null when the key says it itself. */
  workspace_id: string | null
}

/** What is sent when one is changed: only the fields that apply to its kind. */
export type ProviderChange = Partial<Omit<NewProvider, 'kind'>> & LimitsChange

export interface Props {
  providers: Provider[]
  /** Open on this one (from Ctrl+K) rather than the first. */
  picked?: string
  onCreate: (values: NewProvider) => Promise<void>
  onSave: (providerId: string, values: ProviderChange) => Promise<void>
  onDelete: (providerId: string) => Promise<void>
  /** With `run`, a CLI is really run once; that spends the plan and is never done unasked. */
  onTest: (providerId: string, run?: boolean) => Promise<ProviderTest>
  onModels?: LoadModels
  onMakeDefault?: (providerId: string) => Promise<void>
  /** A team guide proposed from the catalogue; nothing is saved. */
  onFill?: (providerId: string) => Promise<CatalogueFill>
  /** The same for a provider not added yet, from its kind and address. */
  onFillNew?: (draft: CatalogueDraft) => Promise<CatalogueFill>
  /** Whether each model can be used now; runs no model. */
  onAvailability?: (providerId: string, free?: boolean) => Promise<Availability>
  /** What is known of the default model being typed: its levels, window, price, tier. */
  onFacts?: LoadFacts
  /** For a provider not added yet: the catalogue's names, a service's address and key name. */
  onSuggest?: (kind: string, baseUrl: string | null) => Promise<Suggestion>
  /** Downloads models.dev's list and keeps it as the catalogue: only on the user's click. */
  onUpdateCatalogue?: () => Promise<CatalogueUpdate>
  /** Which catalogue is read: its date and counts. */
  onCatalogue?: () => Promise<CatalogueUpdate>
  /** "Keep the catalogue fresh": downloaded again at the start once a week old. */
  onKeepFresh?: (on: boolean) => Promise<CatalogueUpdate>
  /** Every provider's tiers from the catalogue, previewed, then saved in one go. */
  onFillAll?: () => Promise<FillAll>
  onSaveFillAll?: (providers: FilledProvider[]) => Promise<void>
  /** Each tier's models in the order they are tried, and that order saved. */
  onTiers?: () => Promise<Tiers>
  onSaveTiers?: (order: TierOrder) => Promise<Tiers>
  /** What a CLI last said of its plan; with `afresh` only on the user's Read now, which starts Codex or one short Claude Code turn. */
  onLimits?: (providerId: string, afresh: boolean) => Promise<Limits>
  /** The status line command that keeps Claude Code's reading fresh from the user's own sessions; nothing is written. */
  onClaudeSetup?: () => Promise<ClaudeSessionSetup>
  /** What the agents' models used from a moment on, in every project. */
  onUsage?: (since: string) => Promise<Usage>
  /** The model server on this machine, and the user's Start / Stop / Restart of it (with the form's program and arguments). */
  onLocalServer?: () => Promise<LocalServer>
  onRunLocalServer?: (action: ServerAction, config?: LocalServerConfig) => Promise<LocalServer>
  /** The user's prices: whether a limit of spend can be kept is read from their currencies (81c). */
  prices?: Price[]
}

/** A CLI on this machine, not an API: on a plan, so it has no price for a token. */
export const isCli = (kind: ProviderKind) => kind !== 'openai_compat' && kind !== 'anthropic'
/** The CLIs whose plan the server can read afresh (`Limits.read`). */
export const READ_NOW: ProviderKind[] = ['codex_cli', 'claude_cli', 'agy_cli', 'copilot_cli']

/** A provider's state in a word or two, and how it looks: from what was last read of it (no model is run). */
export function stateOf(provider: Provider, avail: Availability | null | undefined): [look: 'ok' | 'bad' | 'off', said: string] {
  if (provider.kind === 'anthropic' && !provider.has_key) return ['off', 'no key yet']
  if (avail === undefined) return ['off', 'looking…']
  if (avail === null) return ['off', 'not known']
  if (avail.installed === false) return ['bad', 'not installed']
  if (avail.signed_in === false) return ['bad', 'not signed in']
  if (avail.signed_in) return ['ok', avail.plan ? `signed in · ${avail.plan}` : 'signed in']
  if (avail.installed) return ['ok', 'installed']
  if (avail.models.some(m => m.state === 'usable')) return ['ok', 'running']
  const why = avail.models.find(m => m.why)?.why ?? ''
  if (/\b(401|403)\b|unauthori[sz]ed|invalid.{0,20}key|api key/i.test(why)) return ['bad', 'key refused · check it']
  if (/unreachable|timed? ?out|refused/i.test(why)) return ['bad', 'not answering']
  // shortcut: a server with no model in its guide or catalogue gets no row to say why its list failed, so
  // one that does not answer reads "not known" here; have availability say that itself if it matters.
  return ['off', 'not known']
}

/**
 * Where model steps can be sent: a card for each provider with what it has left, each tier's models in the
 * order they are tried, and a provider's models, connection and limits in a window of its own.
 */
export function ModelsPage({
  providers,
  picked,
  onUpdateCatalogue,
  onCatalogue,
  onKeepFresh,
  onFillAll,
  onSaveFillAll,
  onTiers,
  onSaveTiers,
  onLimits,
  onUsage,
  prices = [],
  ...handlers
}: Props) {
  const unkept = limitUnkept(prices)
  // The provider whose window is open (picked from Ctrl+K, or clicked); 'new' while one is added.
  const [opened, setOpened] = useState<string | null>(picked ?? null)
  const current = providers.find(p => p.id === opened) ?? null
  const creating = opened === 'new'
  const shown = creating || current !== null
  // The catalogue read, as the app says it, and as the last "Update catalogue" kept it; or why that failed.
  const [catalogue, setCatalogue] = useState<CatalogueUpdate | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [updating, setUpdating] = useState(false)
  useEffect(() => {
    let current = true
    onCatalogue?.().then(told => current && setCatalogue(told), () => {})
    return () => {
      current = false
    }
  }, [onCatalogue])
  async function update() {
    if (!onUpdateCatalogue) return
    setUpdating(true)
    setFailed(null)
    try {
      setCatalogue(await onUpdateCatalogue())
    } catch (err) {
      setFailed(errorText(err))
    } finally {
      setUpdating(false)
    }
  }
  async function keepFresh(on: boolean) {
    if (!onKeepFresh) return
    setFailed(null)
    try {
      setCatalogue(await onKeepFresh(on))
    } catch (err) {
      setFailed(errorText(err))
    }
  }
  // What is known of each provider: read in full (a CLI's sign-in, the provider's own list) for the one open, on
  // Check and for a server on this machine (only its list is asked: no model is run); the others from what costs
  // nothing (a CLI's command on this machine, a key) or their last full reading.
  const { onAvailability, ...editing } = handlers
  // A provider switched on or off from its card or its window's head; which one failed, and why, if one did.
  const [switchError, setSwitchError] = useState<{ id: string; text: string } | null>(null)
  async function switchOn(id: string, enabled: boolean) {
    setSwitchError(null)
    try {
      await editing.onSave(id, { enabled })
    } catch (err) {
      setSwitchError({ id, text: errorText(err) })
    }
  }
  const [full, setFull] = useState<Record<string, Availability | null>>({})
  const [free, setFree] = useState<Record<string, Availability | null>>({})
  const check = useCallback(
    async (id: string) => {
      if (!onAvailability) return
      try {
        const told = await onAvailability(id)
        setFull(was => ({ ...was, [id]: told }))
      } catch (err) {
        setFull(was => ({ ...was, [id]: null }))
        throw err
      }
    },
    [onAvailability],
  )
  const openId = current?.id ?? null
  const openStamp = current?.updated_at ?? null
  useEffect(() => {
    if (openId) check(openId).catch(() => {}) // said as "not known" beside it
  }, [openId, openStamp, check])
  const read = useRef<Record<string, string>>({})
  useEffect(() => {
    for (const p of providers)
      if (p.id !== openId && read.current[p.id] !== p.updated_at) {
        read.current[p.id] = p.updated_at
        const local = paidOf(p) === 'this machine'
        const keep = local ? setFull : setFree
        onAvailability?.(p.id, !local).then(
          told => keep(was => ({ ...was, [p.id]: told })),
          () => keep(was => ({ ...was, [p.id]: null })),
        )
      }
  }, [providers, openId, onAvailability])
  const availOf = (id: string) => full[id] ?? free[id]
  // What each CLI last said of its plan, and when a plan key's quota was last seen used up: read as it is, nothing
  // is started.
  const [limits, setLimits] = useState<Record<string, Limits | null>>({})
  const clis = providers
    .filter(p => paidOf(p) === 'subscription' || (paidOf(p) === 'API key' && p.plan))
    .map(p => p.id)
    .join(' ')
  useEffect(() => {
    let live = true
    for (const id of clis.split(' ').filter(Boolean))
      onLimits?.(id, false).then(
        told => live && setLimits(was => ({ ...was, [id]: told })),
        () => live && setLimits(was => ({ ...was, [id]: null })),
      )
    return () => {
      live = false
    }
  }, [clis, onLimits])
  // A plan read afresh on its card's Read now: Codex's app-server, agy's /quota and Copilot's getQuota (on GitHub's
  // plan, not a model server of its own) run no model (as the Usage page's "Check now" has it); Claude Code runs one
  // short turn.
  // Each card's own: one ending leaves another's going, and a second click on one going starts nothing (Claude
  // Code's would be a second paid turn).
  const running = useRef(new Set<string>())
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set())
  async function busyWith(id: string, work: () => Promise<void>) {
    if (running.current.has(id)) return
    running.current.add(id)
    setBusy(new Set(running.current))
    try {
      await work()
    } finally {
      running.current.delete(id)
      setBusy(new Set(running.current))
    }
  }
  const readNow = (id: string) =>
    busyWith(id, async () => {
      try {
        const told = await onLimits!(id, true)
        setLimits(was => ({ ...was, [id]: told }))
      } catch (err) {
        // The last reading stays, with why this one failed beside it.
        setLimits(was => ({ ...was, [id]: { ...(was[id] ?? { windows: [] }), failed: errorText(err) } }))
      }
    })
  // Check on a card with no plan to read: what the window's Check reads (no model is run).
  const checkNow = (id: string) => busyWith(id, () => check(id).catch(() => {})) // said as "not known" on its card
  // What the record says was used today (an API key's spend) and in the last 30 days (a model's row).
  const [today, setToday] = useState<Usage['by_model'] | null>()
  const [month, setMonth] = useState<Usage['by_model'] | null>()
  useEffect(() => {
    if (!onUsage) return
    let live = true
    onUsage(since('today')!).then(told => live && setToday(told.by_model), () => live && setToday(null))
    onUsage(since('30')!).then(told => live && setMonth(told.by_model), () => live && setMonth(null))
    return () => {
      live = false
    }
  }, [onUsage])
  // Each tier's order, read again whenever a provider changes (a model's tier is set on it) and after an order
  // was refused; or why it could not be read.
  const [tiers, setTiers] = useState<Tiers | string | null>(null)
  const [reread, setReread] = useState(0)
  const stamps = providers.map(p => `${p.id}:${p.updated_at}`).join(' ')
  useEffect(() => {
    if (!onTiers) return
    let live = true
    onTiers().then(
      told => live && setTiers(told),
      err => live && setTiers(errorText(err)),
    )
    return () => {
      live = false
    }
  }, [stamps, onTiers, reread])
  // How a provider looked when this page read it, where that stands in its way; null where it did not.
  const down = (id: string) => {
    const provider = providers.find(p => p.id === id)
    if (!provider) return null
    const [look, said] = stateOf(provider, availOf(id))
    return look === 'bad' || said === 'no key yet' ? said : null
  }
  const reading = (p: Provider) =>
    readingOf(p, { limits: onLimits ? limits[p.id] : null, today: onUsage ? today : null, avail: onAvailability ? availOf(p.id) : null, unkept })
  // The window takes the keyboard when it opens and gives it back to what opened it when it closes.
  const back = useRef<HTMLElement | null>(null)
  const dialog = useRef<HTMLDivElement>(null)
  const [tab, setTab] = useState<Tab>('models')
  const open = (id: string) => {
    back.current = document.activeElement as HTMLElement | null
    setTab('models')
    setOpened(id)
  }
  useEffect(() => {
    if (shown) dialog.current?.focus()
    else back.current?.focus()
  }, [shown])
  // Closed by its ✕ or Esc; what is typed and not saved is not thrown away without asking.
  const dirty = useRef(false)
  const setDirty = useCallback((now: boolean) => {
    dirty.current = now
  }, [])
  const confirm = useConfirm()
  const close = () => {
    if (!dirty.current) setOpened(null)
    else confirm.ask('Close without saving what you typed?', 'Close without saving')
  }
  const closeNow = useRef(close)
  useLayoutEffect(() => {
    closeNow.current = close
  })
  // Esc closes it wherever the focus is - also when a button it was on went away (a save takes it).
  useEffect(() => {
    if (!shown) return
    const onKey = (event: globalThis.KeyboardEvent) => {
      // (The question's own Esc is its no: it marks the key taken.)
      if (event.key !== 'Escape' || event.defaultPrevented) return
      closeNow.current()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [shown])
  const look = current && stateOf(current, availOf(current.id))[0]
  return (
    <div className="paged">
      {/* (While a provider's window is open, nothing behind it is reached.) */}
      <div className="models-body" inert={shown}>
        <div className="page-head">
          <h2>Models</h2>
          <span className="muted">What each provider has left; a click opens its models</span>
          <div className="page-head-right">
            {/* The user's own catalogue, where it could not be read: nothing of it counts until it is fixed. */}
            {catalogue?.local && (
              <span role="alert" className="muted">
                {catalogue.local}
              </span>
            )}
            {onUpdateCatalogue && (
              <>
                <span role={failed ? 'alert' : 'status'} className="muted">
                  {failed ??
                    `Catalogue: models.dev${catalogue?.updated_at ? `, ${dayOf(catalogue.updated_at)}` : ''}${catalogue ? ` · ${catalogue.providers} services` : ''}`}
                </span>
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={updating}
                  title="Model names, levels, windows and prices come from a copy of models.dev (MIT), the one shipped with KOLONİ until it is updated. This downloads models.dev's list (about 6 MB) and keeps what KOLONİ reads of it."
                  onClick={() => void update()}
                >
                  {updating ? 'Updating…' : 'Update catalogue'}
                </button>
                {onKeepFresh && catalogue && (
                  <label className="muted" title="When KOLONİ starts, a catalogue more than a week old is downloaded again, as Update catalogue does; without the network the old one stays.">
                    <input type="checkbox" checked={catalogue.keep_fresh} onChange={e => void keepFresh(e.target.checked)} /> Keep the catalogue fresh
                  </label>
                )}
              </>
            )}
            <FillTiers providers={providers} onFillAll={onFillAll} onSaveFillAll={onSaveFillAll} button />
          </div>
        </div>
        <div className="provider-cards">
          {providers.map((provider, index) => (
            <ProviderCard
              key={provider.id}
              provider={provider}
              isDefault={index === 0}
              state={stateOf(provider, availOf(provider.id))}
              reading={reading(provider)}
              open={opened === provider.id}
              onOpen={() => open(provider.id)}
              onSwitch={on => void switchOn(provider.id, on)}
              onRead={
                // (a CLI not installed has nothing to read it with)
                onLimits && provider.enabled !== false && READ_NOW.includes(provider.kind) && !provider.base_url && availOf(provider.id)?.installed !== false
                  ? () => void readNow(provider.id)
                  : undefined
              }
              onCheck={onAvailability && provider.enabled !== false ? () => void checkNow(provider.id) : undefined}
              busy={busy.has(provider.id)}
              readAt={onLimits ? limits[provider.id]?.read_at : null}
            />
          ))}
          <button type="button" className="provider-card provider-add" onClick={() => open('new')}>
            <span className="provider-add-name">
              <Plus size={14} /> Add a provider
            </span>
            <span className="muted">A CLI with your subscription, an API key, or a server of your own</span>
          </button>
        </div>
        {switchError && !shown && (
          <p role="alert" className="muted tier-read-failed">
            {providers.find(p => p.id === switchError.id)?.name} could not be switched: {switchError.text}
          </p>
        )}
        {onTiers &&
          onSaveTiers &&
          (typeof tiers === 'string' ? (
            <p role="alert" className="muted tier-read-failed">
              The tiers could not be read: {tiers}
            </p>
          ) : (
            <TierSlots tiers={tiers} down={down} onSave={onSaveTiers} onRefused={() => setReread(n => n + 1)} />
          ))}
      </div>
      {shown && (
        <div className="dialog-back">
          <div
            ref={dialog}
            tabIndex={-1}
            className="provider-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="provider-dialog-title"          >
            <div className="provider-dialog-head">
              {look && <span className={`state-dot state-${look}`} aria-hidden="true" />}
              <h3 id="provider-dialog-title">{current ? current.name : 'Add a provider'}</h3>
              {/* (What its plan has left is on its card: said once.) */}
              {current && (
                <span className="muted">
                  {paidOf(current)}
                  {current.id === providers[0]?.id && ' · default'}
                </span>
              )}
              {current && (
                // Off: nothing new starts on it; its key and settings stay for later. (Its card has the same switch.)
                <label className="choice" title={OFF_MEANS}>
                  <input
                    type="checkbox"
                    role="switch"
                    className="switch"
                    aria-label={`${current.name} on`}
                    checked={current.enabled !== false}
                    onChange={e => void switchOn(current.id, e.target.checked)}
                  />
                  <span>{current.enabled === false ? 'off' : 'on'}</span>
                </label>
              )}
              {switchError && switchError.id === current?.id && (
                <span role="alert" className="muted">
                  {switchError.text}
                </span>
              )}
              <button type="button" className="icon-btn provider-dialog-close" aria-label="Close" onClick={close}>
                <X size={14} />
              </button>
            </div>
            <ProviderEditor
              // (Not drawn anew by a save: a change the Models tab saved leaves what is typed on Connection.)
              key={creating ? 'new' : current!.id}
              provider={current}
              onlyOne={providers.length <= 1}
              isDefault={!creating && current!.id === providers[0]?.id}
              avail={current ? full[current.id] : undefined}
              onCheck={!current || !onAvailability ? undefined : () => check(current.id)}
              used={onUsage ? month : null}
              tab={tab}
              onTab={setTab}
              onDirty={setDirty}
              unkept={unkept}
              {...editing}
              onDone={() => setOpened(null)}
            />
            {confirm.shown(() => setOpened(null))}
          </div>
        </div>
      )}
    </div>
  )
}
