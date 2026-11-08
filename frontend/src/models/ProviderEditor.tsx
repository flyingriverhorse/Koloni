import { type FormEvent, type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react'
import { errorText } from '../api/client'
import type { Availability, Provider, ProviderTest, Suggestion, Usage } from '../api/types'
import { paidOf } from './cards'
import { LimitsTab } from './LimitsTab'
import { LocalServerTab } from './LocalServerTab'
import { useModelFacts } from './levels'
import type { GuideRow } from './ModelRow'
import { type AnthropicOptions, type CopilotOptions, isCli, type ListedModel, type Mode, type NewProvider, type Props, type ProviderChange, type ProviderKind, signInOf } from './ModelsPage'
import { AtOnceField, CliFields, CliHelp, DefaultModelField, ProviderActions, ProviderGuide, ServiceFields, TestResult } from './ProviderConnection'
import { MAX_MODELS, ProviderModels } from './ProviderModels'
import { KeepFresh } from './RunIt'

const KINDS: [kind: ProviderKind, label: string][] = [
  ['openai_compat', 'OpenAI-compatible server'],
  ['anthropic', 'Anthropic API'],
  ['claude_cli', 'Claude Code (CLI)'],
  ['qoder_cli', 'Qoder (CLI)'],
  ['codex_cli', 'Codex (CLI)'],
  ['copilot_cli', 'GitHub Copilot CLI'],
  // By its command's name: what the product is called was not measured.
  ['agy_cli', 'agy (CLI)'],
]
const limit = (text: string) => (/^\d+$/.test(text.trim()) ? Number(text) : null)
/** How each CLI can be run; the first is its default. */
const MODES: Partial<Record<ProviderKind, Mode[]>> = {
  claude_cli: ['session', 'step', 'native'],
  qoder_cli: ['session', 'native'],
  codex_cli: ['session', 'step', 'native'],
  copilot_cli: ['session', 'native'],
  agy_cli: ['reads', 'native'],
}
// shortcut: Codex on a model server of the user's starts as a step, its session there not measured
// (app/api/providers.py `_mode`); drop this once it is.
const firstMode = (kind: ProviderKind, server: string): Mode | null =>
  kind === 'codex_cli' && server.trim() ? 'step' : (MODES[kind]?.[0] ?? null)

export type Tab = 'models' | 'connection' | 'limits' | 'server'
const TABS: [Tab, string][] = [
  ['models', 'Models'],
  ['connection', 'Connection'],
  ['limits', 'Limits'],
]

interface EditorProps extends Omit<Props, 'providers' | 'onAvailability' | 'prices'> {
  provider: Provider | null
  /** Why no limit of spend can be kept now (`limitUnkept`); null: it can. */
  unkept?: string | null
  /** Whether each of its models can be used now, as the page read it: undefined while it is read, null where that failed. */
  avail?: Availability | null
  /** Reads that again; runs no model. */
  onCheck?: () => Promise<void>
  /** What each model was used for in the last 30 days, every provider's; undefined while read, null where that failed. */
  used?: Usage['by_model'] | null
  onlyOne: boolean
  isDefault: boolean
  /** The tab open: kept by the page, so a Save (which draws the form anew) stays on it. */
  tab: Tab
  onTab: (tab: Tab) => void
  /** Whether something typed on Connection (or a model's name being added) is not saved yet, as it changes. */
  onDirty?: (dirty: boolean) => void
  onDone: () => void
}

export function ProviderEditor({
  provider,
  onlyOne,
  isDefault,
  tab,
  onTab: setTab,
  onDirty,
  onCreate,
  onSave,
  onDelete,
  onTest,
  onModels,
  onMakeDefault,
  onFill,
  onFillNew,
  avail,
  onCheck,
  used,
  onFacts,
  onSuggest,
  onDone,
  onClaudeSetup,
  onLocalServer,
  onRunLocalServer,
  unkept = null,
}: EditorProps) {
  const [name, setName] = useState(provider?.name ?? '')
  const [kind, setKind] = useState<ProviderKind>(provider?.kind ?? 'openai_compat')
  const [address, setAddress] = useState(provider?.base_url ?? '')
  const [key, setKey] = useState('')
  const [model, setModel] = useState(provider?.default_model ?? '')
  // The default model and the guide's rows offer the same names.
  const listId = useId()
  const facts = useModelFacts(onFacts, provider?.id ?? null, model.trim())
  // A model server that does not answer is said once, not once by each lookup that failed.
  const down = provider?.kind === 'openai_compat' && !!facts?.failed && facts.efforts === null
  // A provider not added yet: the catalogue's names for its kind, and the address it was given
  // (asked when the address is left), with a models.dev service's own address and key name.
  const [asked, setAsked] = useState(address.trim())
  const [suggested, setSuggested] = useState<Suggestion | null>(null)
  useEffect(() => {
    setSuggested(null)
    if (provider || !onSuggest) return
    let current = true
    onSuggest(kind, asked || null).then(
      told => {
        if (!current) return
        setSuggested(told)
        // Only an address that names the service and no more is completed: never one typed out.
        if (told.api && asked && told.api !== asked && told.api.startsWith(asked.replace(/\/+$/, '') + '/')) setAddress(told.api)
      },
      () => {},
    )
    return () => {
      current = false
    }
  }, [provider, onSuggest, kind, asked])
  const [executable, setExecutable] = useState(provider?.executable ?? '')
  const [mode, setMode] = useState<Mode | null>(provider?.mode ?? null)
  const saved = (provider?.options ?? {}) as Partial<CopilotOptions>
  const [serverType, setServerType] = useState<CopilotOptions['provider_type']>(saved.provider_type ?? 'openai')
  const [maxPrompt, setMaxPrompt] = useState(saved.max_prompt_tokens ? String(saved.max_prompt_tokens) : '')
  const [maxOutput, setMaxOutput] = useState(saved.max_output_tokens ? String(saved.max_output_tokens) : '')
  const [offline, setOffline] = useState(saved.offline ?? true)
  const savedWorkspace = (provider?.options as Partial<AnthropicOptions> | null)?.workspace_id ?? ''
  const [workspace, setWorkspace] = useState(savedWorkspace)
  const anthropic = kind === 'anthropic'
  // Said only when it is not what is saved: options left out stay as they are.
  const scoped: Pick<NewProvider, 'options'> =
    anthropic && workspace.trim() !== savedWorkspace ? { options: { workspace_id: workspace.trim() || null } } : {}
  const savedOwnSetup = (provider?.options as { own_setup?: boolean } | null)?.own_setup ?? false
  const [ownSetup, setOwnSetup] = useState(savedOwnSetup)
  // K-claude-hesap: signed in with the user's own Claude Code or Codex, or with a folder of its own.
  const savedSignIn = signInOf(provider)
  const [signIn, setSignIn] = useState(savedSignIn)
  const copilot = kind === 'copilot_cli'
  // Claude Code and Codex on a model server of the user's: only its address (K-cli-llama).
  const ownServer = kind === 'claude_cli' || kind === 'codex_cli'
  const agy = kind === 'agy_cli'
  // What Copilot is told about a model server of your own; the server fills in the rest.
  const served = {
    base_url: address.trim(),
    options: {
      provider_type: serverType,
      max_prompt_tokens: limit(maxPrompt),
      max_output_tokens: limit(maxOutput),
      offline,
    },
  }
  const [note, setNote] = useState(provider?.note ?? '')
  // Agents may use a model when it says so and its provider is one they may choose (from before 81a, a provider
  // not ticked had its models on): the first change saved says it of each model, and the provider follows.
  const latest = useRef(provider)
  latest.current = provider
  const savedRows = (from = latest.current): GuideRow[] =>
    (from?.models ?? []).map(m => ({ name: m.name, note: m.note ?? '', tier: m.tier ?? null, agents: from!.for_agents && m.agents, ...(m.enabled === false && { enabled: false, off_why: m.off_why }), inputs: m.inputs ?? null, ...(m.context && { context: m.context }) }))
  const [rows, setRows] = useState(() => savedRows())
  // A provider with no list says it of itself (a CLI or a server on its default model): on Connection.
  const [forAgents, setForAgents] = useState(provider?.for_agents ?? false)
  // A model added joins the provider's way: agents may use it when they may use one of the others already (or,
  // with none listed yet, the provider itself).
  const usual = rows.length ? rows.some(row => row.agents) : (provider?.for_agents ?? false)
  const [onlyListed, setOnlyListed] = useState(provider?.only_listed ?? false)
  // How many a catalogue fill left out, while what it proposed is not saved yet (null: no such proposal).
  const [leftOut, setLeftOut] = useState<number | null>(null)
  const listedOf = (list: GuideRow[]): ListedModel[] =>
    list.map(row => ({ name: row.name, note: row.note.trim() || null, tier: row.tier, agents: row.agents, ...(row.enabled !== undefined && { enabled: row.enabled }), ...(row.inputs != null && { inputs: row.inputs }), ...(row.context !== undefined && { context: row.context }) }))
  const listed = listedOf(rows)
  // The Models tab saves each change at once (a tier, a note, a model added or removed), as the tiers' order does;
  // only a catalogue's proposal waits for its own Save. Nothing of the Connection tab is sent with it.
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  useEffect(() => {
    if (!toast) return
    const gone = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(gone)
  }, [toast])
  async function persist(next: GuideRow[], said: string) {
    setRows(next)
    if (!provider || leftOut !== null) return
    setModelsError(null)
    try {
      await onSave(provider.id, { models: listedOf(next) })
      setToast(said)
    } catch (err) {
      setModelsError(errorText(err))
      setFailedAt(n => n + 1)
    }
  }
  // What is shown follows the provider as last saved - also after a save that failed, and never back over a later
  // one. A catalogue's proposal stays until it is saved or not. shortcut: a note being typed when another change's
  // save lands is put back as saved; keep the row being typed if that is ever missed.
  const stamp = provider?.updated_at
  const [failedAt, setFailedAt] = useState(0)
  useEffect(() => {
    if (latest.current && leftOut === null) setRows(savedRows())
  }, [stamp, failedAt, leftOut])
  // A model's name is given once, when it is added. shortcut: renaming one is removing it and adding it again,
  // which loses its note and its place in its tier's order; add a rename if that is missed.
  const [adding, setAdding] = useState<string | null>(null)
  function add() {
    const named = (adding ?? '').trim()
    if (!named) return setModelsError('A model needs its name, as the provider knows it.')
    if (rows.some(row => row.name === named)) return setModelsError(`${named} is on the list already.`)
    setAdding(null)
    void persist([...rows, { name: named, note: '', tier: null, agents: usual }], `${named} added.`)
  }
  // "Never run a model that is not on this list" means something only while there is a list.
  const only = onlyListed && listed.length > 0
  // A provider not added yet is filled over the rows typed so far; its catalogue is found by
  // its kind, and an OpenAI-compatible server's by its address.
  const draft = `${kind} ${address.trim()}`
  const propose =
    provider && onFill
      ? () => onFill(provider.id)
      : !provider && onFillNew && (kind !== 'openai_compat' || address.trim())
        ? () => onFillNew({ kind, base_url: address.trim() || null, models: listed })
        : null
  // The kind and address a fill found no catalogue for.
  const [noCatalogue, setNoCatalogue] = useState<string | null>(null)
  const [atOnce, setAtOnce] = useState(provider?.max_running ? String(provider.max_running) : '')
  // What is typed and not saved yet: closing the window asks before it is thrown away.
  const draftOf = (typedKey: string) =>
    JSON.stringify([name, kind, address, typedKey, model, executable, mode, serverType, maxPrompt, maxOutput, offline,
      workspace, ownSetup, signIn, note, onlyListed, atOnce, forAgents, adding ?? ''])
  const [clean, setClean] = useState(() => draftOf(''))
  const dirty = draftOf(key) !== clean
  useEffect(() => {
    onDirty?.(dirty)
    return () => onDirty?.(false)
  }, [dirty, onDirty])
  // Empty: its kind's default (`most_at_once`). Anything else has to be a whole number from 1 to 1000 - nothing else is sent.
  // What an empty field holds: the server's word for a saved provider as it is (`most_at_once`: a llama-server's
  // slots once read), else its kind's.
  const onThisMachine = kind === 'openai_compat' && /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])([:/]|$)/i.test(address.trim())
  const asSaved = provider && provider.max_running == null && provider.kind === kind && (provider.base_url ?? '') === address.trim()
  const usualAtOnce = (asSaved && provider.most_at_once) || (kind.endsWith('_cli') ? 3 : 8)
  const most = atOnce.trim() === '' ? null : /^[1-9]\d{0,3}$/.test(atOnce.trim()) && Number(atOnce) <= 1000 ? Number(atOnce) : undefined
  /** What changed in the guide and the limit; what was not touched is left out and stays as it is. */
  // (A saved provider's models are not in it: its Models tab saves them itself.)
  function guide(): Pick<NewProvider, 'for_agents' | 'note' | 'models' | 'only_listed' | 'max_running'> {
    return {
      ...(most !== undefined && most !== (provider?.max_running ?? null) ? { max_running: most } : {}),
      ...(!rows.length && forAgents !== (provider?.for_agents ?? false) ? { for_agents: forAgents } : {}),
      ...(note.trim() !== (provider?.note ?? '') ? { note: note.trim() } : {}),
      ...(!provider && listed.length ? { models: listed } : {}),
      ...(only !== (provider?.only_listed ?? false) ? { only_listed: only } : {}),
    }
  }
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tested, setTested] = useState<ProviderTest | null>(null)
  // The model a real run named, when it is a name and not yet on the list.
  const reported =
    tested?.ok && tested.reply != null && tested.model_id && !/ default$/.test(tested.model_id) ? tested.model_id : null
  const canAdd = reported !== null && !listed.some(m => m.name === reported) && rows.length < MAX_MODELS
  const cli = isCli(kind)
  const modes = MODES[kind] ?? []
  // A kind runs in its default way unless another of its ways was chosen.
  const runs = mode && modes.includes(mode) ? mode : firstMode(kind, address)
  const claudeNative = kind === 'claude_cli' && runs === 'native'
  // Whose sign-in it runs on: not asked on a model server of the user's, where nothing is signed in to.
  const signs = ownServer && !address.trim()
  const signing = signs ? signIn : 'own' // (a provider moved to a model server leaves its own sign-in)
  // Like the workspace: said only when it is not what is saved - both together, as the server keeps what is sent whole.
  const setup: Pick<NewProvider, 'options'> =
    (claudeNative && ownSetup !== savedOwnSetup) || (ownServer && signing !== savedSignIn)
      ? { options: { ...(kind === 'claude_cli' ? { own_setup: ownSetup } : {}), ...(signing === 'koloni' ? { sign_in: 'koloni' } : {}) } }
      : {}

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    setTested(null)
    if (!provider) {
      const values: NewProvider = cli
        ? {
            name: name.trim(),
            kind,
            default_model: model.trim(),
            executable: executable.trim(),
            ...(modes.length > 1 && runs ? { mode: runs } : {}),
            ...(copilot ? { base_url: served.base_url, api_key: key, options: served.options } : {}),
            ...(ownServer && address.trim() ? { base_url: address.trim() } : {}),
            ...setup,
            ...guide(),
          }
        : { name: name.trim(), kind, base_url: address.trim(), api_key: key, default_model: model.trim(), ...scoped, ...guide() }
      void run(async () => {
        await onCreate(values)
        onDone()
      })
      return
    }
    const values: ProviderChange = cli
      ? {
          name: name.trim(),
          default_model: model.trim(),
          executable: executable.trim(),
          ...(modes.length > 1 && runs ? { mode: runs } : {}),
          ...(copilot ? served : {}),
          ...(ownServer && address.trim() !== (provider.base_url ?? '') ? { base_url: address.trim() } : {}),
          ...setup,
          ...guide(),
        }
      : { name: name.trim(), base_url: address.trim(), default_model: model.trim(), ...scoped, ...guide() }
    // An empty key field means "leave the saved key alone".
    if ((!cli || copilot) && key) values.api_key = key
    void run(async () => {
      await onSave(provider.id, values)
      setKey('')
      setClean(draftOf(''))
    })
  }

  // The models agents and you can pick here, and how strong each is: read first, each change saved at once.
  const modelsPart = (
    <ProviderModels
      provider={provider}
      rows={rows}
      setRows={setRows}
      savedRows={savedRows}
      listed={listed}
      usual={usual}
      avail={avail}
      used={used}
      onFacts={onFacts}
      onSave={onSave}
      onCheck={onCheck}
      persist={persist}
      adding={adding}
      setAdding={setAdding}
      add={add}
      listId={listId}
      propose={propose}
      busy={busy}
      run={run}
      draft={draft}
      noCatalogue={noCatalogue}
      setNoCatalogue={setNoCatalogue}
      leftOut={leftOut}
      setLeftOut={setLeftOut}
      modelsError={modelsError}
      setModelsError={setModelsError}
      toast={toast}
      setToast={setToast}
    />
  )

  // The provider itself: how it is reached and run, what agents are told of it, and what is done to it.
  const form = (
    <form className="role-editor" onSubmit={submit}>
      {/* Slice 64: the card of the server on this machine (Start / Stop / Restart, its model file and
          settings) goes here, above the rest. Nothing of it is built yet. */}
      <CliHelp avail={avail} kind={kind} onCheck={onCheck && (() => void run(onCheck))} />
      <div className="field">
        <label htmlFor="provider-name">Name</label>
        <input id="provider-name" className="input" value={name} onChange={e => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="provider-kind">Kind</label>
        <select
          id="provider-kind"
          className="input"
          value={kind}
          disabled={provider !== null}
          onChange={e => setKind(e.target.value as ProviderKind)}
        >
          {KINDS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {cli ? (
        <CliFields
          kind={kind}
          provider={provider}
          executable={executable}
          setExecutable={setExecutable}
          modes={modes}
          runs={runs}
          setMode={setMode}
          signs={signs}
          signIn={signIn}
          setSignIn={setSignIn}
          savedSignIn={savedSignIn}
          claudeNative={claudeNative}
          ownSetup={ownSetup}
          setOwnSetup={setOwnSetup}
          ownServer={ownServer}
          copilot={copilot}
          agy={agy}
          apiKey={key}
          setKey={setKey}
          address={address}
          setAddress={setAddress}
          serverType={serverType}
          setServerType={setServerType}
          maxPrompt={maxPrompt}
          setMaxPrompt={setMaxPrompt}
          maxOutput={maxOutput}
          setMaxOutput={setMaxOutput}
          offline={offline}
          setOffline={setOffline}
        />
      ) : (
        <ServiceFields
          kind={kind}
          provider={provider}
          address={address}
          setAddress={setAddress}
          setAsked={setAsked}
          suggested={suggested}
          listId={listId}
          apiKey={key}
          setKey={setKey}
          anthropic={anthropic}
          workspace={workspace}
          setWorkspace={setWorkspace}
        />
      )}
      <DefaultModelField
        kind={kind}
        cli={cli}
        provider={provider}
        model={model}
        setModel={setModel}
        listId={listId}
        suggested={suggested}
        down={down}
        facts={facts}
        onModels={onModels}
        onFacts={onFacts}
      />
      <AtOnceField kind={kind} atOnce={atOnce} setAtOnce={setAtOnce} usualAtOnce={usualAtOnce} most={most} onThisMachine={onThisMachine} />
      {/* What agents are told of the provider as a whole, beside its models. */}
      <ProviderGuide
        rows={rows}
        forAgents={forAgents}
        setForAgents={setForAgents}
        note={note}
        setNote={setNote}
        listed={listed}
        only={only}
        setOnlyListed={setOnlyListed}
      />
      {!provider && modelsPart}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {tested && (
        <TestResult
          tested={tested}
          kind={kind}
          cli={cli}
          provider={provider}
          ownServer={ownServer}
          canAdd={canAdd}
          onAdd={() => reported && void persist([...rows, { name: reported, note: '', tier: null, agents: usual }], `${reported} added.`)}
        />
      )}
      {provider && cli && (
        <p className="muted provider-note">
          {agy
            ? 'Try a real run: One short run of the CLI, reading only, in an empty folder; it counts against your plan. It shows which model answered.'
            : 'Try a real run: One short run of the CLI; it counts against your plan (not when it runs on a model server of your own). It shows which model answered.'}
        </p>
      )}
      <div className="role-actions">
        {provider ? (
          <ProviderActions
            provider={provider}
            cli={cli}
            busy={busy}
            canSave={!!name.trim()}
            isDefault={isDefault}
            onlyOne={onlyOne}
            run={run}
            setTested={setTested}
            onSave={onSave}
            onDelete={onDelete}
            onTest={onTest}
            onMakeDefault={onMakeDefault}
          />
        ) : (
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
            Add provider
          </button>
        )}
      </div>
    </form>
  )
  if (!provider) return form
  return (
    <ProviderTabs
      provider={provider}
      tab={tab}
      onTab={setTab}
      unkept={unkept}
      onSave={onSave}
      onClaudeSetup={onClaudeSetup}
      onLocalServer={onLocalServer}
      onRunLocalServer={onRunLocalServer}
      modelsPart={modelsPart}
      form={form}
    />
  )
}

interface TabsProps extends Pick<EditorProps, 'tab' | 'onTab' | 'unkept' | 'onSave' | 'onClaudeSetup' | 'onLocalServer' | 'onRunLocalServer'> {
  provider: Provider
  modelsPart: ReactNode
  form: ReactNode
}

/** A saved provider's tabs: its models, its connection, its limits and, for a server on this machine, the server. */
function ProviderTabs({ provider, tab, onTab: setTab, unkept, onSave, onClaudeSetup, onLocalServer, onRunLocalServer, modelsPart, form }: TabsProps) {
  // A server on this machine has a tab that starts and stops it (slice 64).
  const tabs: [Tab, string][] =
    provider.kind === 'openai_compat' && paidOf(provider) === 'this machine' && onLocalServer && onRunLocalServer ? [...TABS, ['server', 'Server']] : TABS
  // The arrow keys, Home and End move along the tabs (WAI-ARIA tabs: one tab stop, chosen as it is reached).
  function onTabKey(event: KeyboardEvent<HTMLDivElement>) {
    const at = tabs.findIndex(([id]) => id === tab)
    const to = ({ ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 } as Record<string, number>)[event.key]
    if (to === undefined) return
    event.preventDefault()
    const next = tabs[(to + tabs.length) % tabs.length][0]
    setTab(next)
    event.currentTarget.querySelector<HTMLElement>(`#provider-tab-${next}`)?.focus()
  }
  return (
    <div className="role-editor">
      <div className="tabs provider-tabs" role="tablist" aria-label={provider.name} onKeyDown={onTabKey}>
        {tabs.map(([id, label]) => (
          <button
            key={id}
            id={`provider-tab-${id}`}
            type="button"
            role="tab"
            className="tab"
            aria-selected={tab === id}
            aria-controls={`provider-panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {/* Each is kept while another tab is open: what was typed in one is still there when you come back. */}
      <div id="provider-panel-models" role="tabpanel" aria-labelledby="provider-tab-models" className="provider-panel" hidden={tab !== 'models'}>
        {modelsPart}
      </div>
      <div id="provider-panel-connection" role="tabpanel" aria-labelledby="provider-tab-connection" className="provider-panel" hidden={tab !== 'connection'}>
        {form}
      </div>
      <div id="provider-panel-limits" role="tabpanel" aria-labelledby="provider-tab-limits" className="provider-panel" hidden={tab !== 'limits'}>
        {/* Its own Save, apart from Connection's. */}
        <LimitsTab provider={provider} unkept={unkept} onSave={values => onSave(provider.id, values)} />
        {/* Only the default command's: a session of the user's is started by that. */}
        {/* Nor one with a sign-in folder of its own: the user's sessions are not on its account. */}
        {provider.kind === 'claude_cli' && !provider.executable && signInOf(provider) === 'own' && onClaudeSetup && (
          <KeepFresh onSetup={onClaudeSetup} />
        )}
      </div>
      {tabs.length > TABS.length && (
        <div id="provider-panel-server" role="tabpanel" aria-labelledby="provider-tab-server" className="provider-panel" hidden={tab !== 'server'}>
          <LocalServerTab active={tab === 'server'} onRead={onLocalServer!} onRun={onRunLocalServer!} />
        </div>
      )}
    </div>
  )
}
