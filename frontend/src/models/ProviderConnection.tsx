import type { Availability, ModelFacts, Provider, ProviderTest, Suggestion } from '../api/types'
import { modelName } from '../shell/modelName'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { ModelNameInput } from './ModelNameInput'
import { factsText, levelsKnown, namedLevel, takesOf } from './levels'
import type { GuideRow } from './ModelRow'
import type { CopilotOptions, ListedModel, Mode, Props as PageProps, ProviderKind, SignIn } from './ModelsPage'
import { LogIn, RunIt } from './RunIt'

const MAX_NOTE = 300

const COMMAND: Partial<Record<ProviderKind, string>> = {
  claude_cli: 'claude',
  qoder_cli: 'qodercli',
  codex_cli: 'codex',
  copilot_cli: 'copilot',
  agy_cli: 'agy',
}
const MODE_LABEL: Record<Mode, string> = {
  session: "One session per agent, with KOLONİ's tools (recommended)",
  step: "One run per model step, with KOLONİ's tools",
  native: 'Native: its own tools, in the project',
  reads: 'Reads with its own tools; started without leave to write or run',
}
// What each CLI asks KOLONİ before, natively (89a Codex, 89b Claude Code, 89c Copilot; agy through its hook).
const NATIVE_ASKS: Partial<Record<ProviderKind, string>> = {
  claude_cli: 'asks before every tool it uses',
  agy_cli: 'asks before every tool it uses',
  codex_cli: 'asks before each command and patch, but not those its own rules count as safe',
  copilot_cli: 'asks before each command, write and read',
  qoder_cli: 'asks before every tool it uses (not yet measured)',
}
// KOLONİ's tools in either way, from the agy version they were measured to reach (app/model_agy.py BRIDGE_FROM).
const AGY_TOOLS =
  'From agy 1.4.9 on, KOLONİ’s tools reach it through KOLONİ’s tool server in its home, so it can open sub-agents, ask you questions, write notes and use the project’s memory. An older agy runs the old way, without them: it takes a task, works and reports.'
// Said of every way of running in which the CLI works with tools of its own (app/providers.py, OWN_TOOLS).
// Since slice 19b: where a native sub-agent works.
const NATIVE_COPY =
  'A sub-agent works in a copy of the project of its own, and what it changed is taken into the project when it is done; the Orchestrator works in the project folder itself.'
const NOT_BY_TRIGGER = 'It is not started by a trigger: with nobody watching, only an agent that works with KOLONİ’s tools runs.'
const modeLabel = (kind: ProviderKind, mode: Mode) =>
  mode !== 'native' || !NATIVE_ASKS[kind] ? MODE_LABEL[mode] : `${MODE_LABEL.native}; ${NATIVE_ASKS[kind]}`

type Setter<T> = (value: T) => void

/** How to install the CLI, or sign in to it, where the last check found it is not. */
export function CliHelp({ avail, kind, onCheck }: { avail?: Availability | null; kind: ProviderKind; onCheck?: () => void }) {
  return (
    <>
      {avail?.installed === false && avail.install && (
        <RunIt
          label={`How to install ${COMMAND[kind]}`}
          text={`The ${COMMAND[kind]} command was not found on this machine. Install it in your own terminal (KOLONİ does not), then press Check on the Models tab:`}
          link="Install docs"
          told={avail.install}
        />
      )}
      {avail?.login ? (
        <LogIn kind={kind} told={avail.login} onCheck={onCheck} />
      ) : avail?.signed_in === false && avail.sign_in && (
        <RunIt
          label={`How to sign in to ${COMMAND[kind]}`}
          text={`${COMMAND[kind]} is not signed in. Sign in in your own terminal (KOLONİ does not), then press Check on the Models tab:`}
          link="Sign-in docs"
          told={avail.sign_in}
        />
      )}
    </>
  )
}

interface CliProps extends CopilotProps {
  kind: ProviderKind
  executable: string
  setExecutable: Setter<string>
  modes: Mode[]
  runs: Mode | null
  setMode: Setter<Mode>
  signs: boolean
  signIn: SignIn
  setSignIn: Setter<SignIn>
  savedSignIn: SignIn
  claudeNative: boolean
  ownSetup: boolean
  setOwnSetup: Setter<boolean>
  ownServer: boolean
  copilot: boolean
  agy: boolean
}

/** A CLI's connection: its command, how it runs, whose sign-in, and what each way of running does. */
export function CliFields(props: CliProps) {
  const { kind, provider, executable, setExecutable, modes, runs, setMode, signs, claudeNative, ownSetup, setOwnSetup, ownServer, address, setAddress, copilot } = props
  return (
    <>
      <div className="field">
        <label htmlFor="provider-executable">Path to the command</label>
        <input
          id="provider-executable"
          className="input mono"
          value={executable}
          placeholder={`Leave empty to find "${COMMAND[kind]}" on PATH`}
          onChange={e => setExecutable(e.target.value)}
        />
      </div>
      {modes.length > 1 && (
        <div className="field">
          <label htmlFor="provider-mode">How it runs</label>
          <select
            id="provider-mode"
            className="input"
            value={runs ?? ''}
            onChange={e => setMode(e.target.value as Mode)}
          >
            {modes.map(value => (
              <option key={value} value={value}>
                {modeLabel(kind, value)}
              </option>
            ))}
          </select>
        </div>
      )}
      {signs && <SignInField {...props} />}
      {claudeNative && (
        <label className="choice" htmlFor="claude-own-setup">
          <input
            id="claude-own-setup"
            type="checkbox"
            aria-label="Use my own Claude Code setup"
            checked={ownSetup}
            onChange={e => setOwnSetup(e.target.checked)}
          />
          <span>
            Use my own Claude Code setup
            <span className="choice-note">
              Off: only the project's own .claude settings are loaded — none of your personal skills,
              plugins, hooks or MCP servers. On: the agent starts with your own setup, which KOLONİ neither
              shows nor approves.
            </span>
          </span>
        </label>
      )}
      {ownServer && (
        // Open while it holds an address (one typed for another kind too): never saved unseen.
        <details className="more provider-server" open={!!provider?.base_url || !!address.trim() || undefined}>
          <summary>Use a model server of your own instead (optional)</summary>
          <div className="muted provider-note">
            With the address of your model server (llama-server) on this machine or your local network, it runs on
            that server&rsquo;s model: your sign-in and keys are not used and nothing counts against your plan.
            Start the server first: while it does not answer, a run is refused.
          </div>
          <div className="field">
            <label htmlFor="cli-server-address">Model server address</label>
            <input
              id="cli-server-address"
              className="input mono"
              value={address}
              placeholder="http://127.0.0.1:8080/v1"
              onChange={e => setAddress(e.target.value)}
            />
          </div>
        </details>
      )}
      {copilot && <CopilotFields {...props} />}
      <CliNotes {...props} />
    </>
  )
}

function SignInField({ kind, signIn, setSignIn, savedSignIn }: CliProps) {
  return (
    <div className="field">
      <label htmlFor="provider-sign-in">Sign-in</label>
      <select id="provider-sign-in" className="input" value={signIn} onChange={e => setSignIn(e.target.value as SignIn)}>
        <option value="own">My own ({kind === 'claude_cli' ? '~\\.claude' : '~\\.codex'})</option>
        <option value="koloni">Its own for KOLONİ</option>
      </select>
      <Hint doc={GUIDE.cliSignIn}>
        Its own: a sign-in folder for this provider alone, so several {COMMAND[kind]} accounts can run side by side, each
        its own provider, without switching accounts. You log in to it once from your own terminal.
      </Hint>
      {signIn === 'koloni' && savedSignIn !== 'koloni' && (
        // (R125: said before it is saved - the command to log in comes once its folder is made)
        <div role="status" className="provider-note">
          Not signed in yet: save, then “Log in to {kind === 'claude_cli' ? 'Claude' : 'Codex'} for this provider” above
          gives the command for your own terminal.
        </div>
      )}
      {signIn === 'koloni' && (
        <div className="muted provider-note">
          The other {kind === 'claude_cli' ? 'Claude Code' : 'Codex'} providers are other accounts: not used for a
          limit. When this one reaches its limit, KOLONİ never moves its work to one of them.
        </div>
      )}
    </div>
  )
}

interface CopilotProps {
  provider: Provider | null
  apiKey: string
  setKey: Setter<string>
  address: string
  setAddress: Setter<string>
  serverType: CopilotOptions['provider_type']
  setServerType: Setter<CopilotOptions['provider_type']>
  maxPrompt: string
  setMaxPrompt: Setter<string>
  maxOutput: string
  setMaxOutput: Setter<string>
  offline: boolean
  setOffline: Setter<boolean>
}

function CopilotFields({ provider, apiKey: key, setKey, address, setAddress, serverType, setServerType, maxPrompt, setMaxPrompt, maxOutput, setMaxOutput, offline, setOffline }: CopilotProps) {
  return (
    <>
      <div className="field">
        <label htmlFor="copilot-key">API key</label>
        <input
          id="copilot-key"
          className="input mono"
          type="password"
          autoComplete="off"
          value={key}
          placeholder={provider?.has_key ? 'Type a new one to replace the saved one' : 'Optional'}
          onChange={e => setKey(e.target.value)}
        />
        <span className="muted provider-note">
          Leave empty to use your own GitHub sign-in (gh). Or a fine-grained GitHub token with the Copilot
          Requests permission; with a model server of your own, that server&rsquo;s key, if it needs one.{' '}
          <Hint doc={GUIDE.copilot}>
            A token has not been tried on a real account yet. Either way Copilot starts with a home of its own,
            so your Copilot settings and plugins stay out; without a token it signs in through gh.
          </Hint>
        </span>
      </div>
      {/* Open where one is set: what is saved is never folded away. */}
      <details className="more provider-server" open={!!provider?.base_url || undefined}>
        <summary>Use a model server of your own instead (optional)</summary>
        <div className="muted provider-note">
          With the address of a model server of your own (llama.cpp, Ollama, any OpenAI-compatible address)
          Copilot runs on that model: no GitHub sign-in is needed and nothing counts against a plan.
        </div>
        <div className="field">
          <label htmlFor="copilot-address">Model server address</label>
          <input
            id="copilot-address"
            className="input mono"
            value={address}
            placeholder="http://localhost:8080/v1"
            onChange={e => setAddress(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="copilot-type">Server type</label>
          <select
            id="copilot-type"
            className="input"
            value={serverType}
            onChange={e => setServerType(e.target.value as CopilotOptions['provider_type'])}
          >
            <option value="openai">OpenAI-compatible</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="copilot-prompt">Most prompt tokens</label>
          <input
            id="copilot-prompt"
            className="input mono"
            inputMode="numeric"
            value={maxPrompt}
            placeholder="e.g. 70000: what your model's context can take"
            onChange={e => setMaxPrompt(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="copilot-output">Most output tokens</label>
          <input
            id="copilot-output"
            className="input mono"
            inputMode="numeric"
            value={maxOutput}
            placeholder="e.g. 8000"
            onChange={e => setMaxOutput(e.target.value)}
          />
        </div>
        <label className="choice" htmlFor="copilot-offline">
          <input
            id="copilot-offline"
            type="checkbox"
            checked={offline}
            onChange={e => setOffline(e.target.checked)}
          />
          <span>
            Never connect to GitHub
            <span className="choice-note">No sign-in, telemetry or update check; web tools are off.</span>
          </span>
        </label>
      </details>
    </>
  )
}

/** What running it this way does: a line for every CLI, and a warning for each native way. */
function CliNotes({ kind, copilot, ownServer, address, signs, signIn, runs, agy }: CliProps) {
  return (
    <>
      <div className="muted provider-note">
        {copilot
          ? 'Runs the copilot command on this machine, with a home of its own: your Copilot settings, MCP servers and plugins stay out of it. '
          : ownServer && address.trim()
            ? `Runs the ${COMMAND[kind]} command on this machine, on your model server. `
            : signs && signIn === 'koloni'
              ? `Runs the ${COMMAND[kind]} command on this machine with this provider's own sign-in; no key is needed, and its use counts against that account's plan. `
              : `Uses the ${COMMAND[kind]} command you are signed in to on this machine; no key is needed, and its use counts against your plan. `}
        {/* (A session or a run a step: the ways of running that have more to say.) */}
        {runs !== 'native' && runs !== 'reads' && (
          <Hint doc={GUIDE.cliRuns}>
            Its own tools are switched off: every tool it uses is KOLONİ's, so approvals, records and Stop work as
            with any other model.{' '}
            {runs === 'session' &&
              "It keeps its own loop for the whole of an agent's work and reaches KOLONİ's tools as they are needed, so it is quick and you see its text piece by piece as it works."}
            {runs === 'step' &&
              'Each model step is a separate run of the CLI, so it is slower and the answer arrives all at once.'}
            {kind === 'codex_cli' &&
              runs === 'session' &&
              " Codex's own patch tool cannot be switched off, so KOLONİ refuses every patch it asks to make and it writes with KOLONİ's write_file and edit_file instead. Unlike Native, it runs wherever the other sessions run: triggers, To-do, While you're away, recipe steps and comparisons. Tried on short work so far."}
            {kind === 'qoder_cli' &&
              " A model name has to be set below if Qoder's own default model does not answer."}
          </Hint>
        )}
      </div>
      {runs === 'native' && kind === 'claude_cli' && (
        <p role="note" className="composer-warning provider-note">
          Native: Claude Code works with its own file and shell tools, its own sub-agents and the project's own .claude
          settings. Skills, commands, your personal plugins, hooks and MCP servers come in only with “Use my own Claude
          Code setup” on. It asks KOLONİ before every tool
          of its own, its reads too. A change shows as a diff to approve and a command as a command to approve, as the
          permission level says. A secret file is asked about at every level; an ordinary read in the project is not. A
          read-only role stays read-only. {NATIVE_COPY} {NOT_BY_TRIGGER}
        </p>
      )}
      {agy && runs === 'reads' && (
        <p role="note" className="composer-warning provider-note">
          Reads only: agy works in the project folder with its own reading tools. It is started without leave to do
          more, so agy itself refuses to write a file or run a command; KOLONİ records such a step as refused, and its
          reads as its own tools. With nothing to ask, it runs at every permission level and for every role; a role’s
          write and command tools do not apply here. KOLONİ does not enforce this itself: permission rules in your own
          agy settings can allow more. {NOT_BY_TRIGGER} {AGY_TOOLS}
        </p>
      )}
      {agy && runs === 'native' && (
        <p role="note" className="composer-warning provider-note">
          Native: agy works with all its own tools, in a home of KOLONİ&apos;s, so your own agy settings, hooks and MCP
          servers stay out. It is started with --dangerously-skip-permissions, and a hook of KOLONİ&apos;s asks KOLONİ
          before each tool it uses: a change shows as a change to approve and a command as a command to approve, at any
          permission level, by KOLONİ&apos;s own rules. A read-only role stays read-only. If agy does not load that hook,
          or uses a tool without it, the run is stopped. As a sub-agent it works in its own copy of the project, without
          the project&apos;s dependency folders (node_modules, .venv), so what needs them does not run there; what it
          changed is taken into the project when it is done. {AGY_TOOLS} {NOT_BY_TRIGGER}
        </p>
      )}
      {runs === 'native' && kind === 'codex_cli' && (
        <p role="note" className="composer-warning provider-note">
          Native: Codex works with its own shell and patch tool; your own Codex skills and MCP servers are switched
          off. {NATIVE_COPY} It asks KOLONİ before each command it runs and each patch it makes, at any permission
          level, by KOLONİ&apos;s own rules: a new file shows as a diff to approve, an edit of an existing file as a
          sentence with its diff, and a command as a command to approve. It reads files by running commands, so its role
          has to be allowed to write and run them. What its own Codex rules let it do unasked is marked so on the record.
          It can open sub-agents and ask you questions through KOLONİ. {NOT_BY_TRIGGER}
        </p>
      )}
      {runs === 'native' && kind === 'qoder_cli' && (
        <p role="note" className="composer-warning provider-note">
          Native, not yet measured: Qoder works in the project folder with its own file and shell tools, and is
          asked, as Claude Code is, to ask KOLONİ before every tool of its own: a change shows as a diff to approve and
          a command as a command to approve, as the permission level says. Whether Qoder really does is not measured
          yet: a tool of its own seen running without KOLONİ being asked stops the run, after that one tool has run. A
          tool KOLONİ does not know by name is asked about at every level. It does not run natively in a project with
          Qoder settings of its own (.qoder). {NATIVE_COPY} {NOT_BY_TRIGGER}
        </p>
      )}
      {runs === 'native' && kind === 'copilot_cli' && (
        <p role="note" className="composer-warning provider-note">
          Native: Copilot works in the project folder with its own file and shell tools. It starts with a home of its
          own, so your Copilot plugins and MCP servers stay out. It asks KOLONİ before each command it runs, each file it
          writes and each file it reads, at any permission level, by KOLONİ&apos;s own rules: a new file shows as a diff
          to approve, an edit of an existing file as a sentence with its diff, a command as a command to approve and a
          secret file as a read to approve. Anything else it asks for, such as a web page, is refused. What it does
          unasked is marked so on the record. Where this machine can, its commands run in Copilot’s sandbox, denied the
          project’s secret files (Settings › This project › Commands and secrets); where it cannot, the run says so. It can open sub-agents
          and ask you questions through KOLONİ. Copilot (native) runs its sub-agents one at a time here; session mode
          runs them at once. Copilot’s own sandbox cannot start Python here (measured): tests run only through a
          sub-agent or in session mode. {NOT_BY_TRIGGER}
        </p>
      )}
    </>
  )
}

interface ServiceProps {
  kind: ProviderKind
  provider: Provider | null
  address: string
  setAddress: Setter<string>
  setAsked: Setter<string>
  suggested: Suggestion | null
  listId: string
  apiKey: string
  setKey: Setter<string>
  anthropic: boolean
  workspace: string
  setWorkspace: Setter<string>
}

/** An API's connection: its address, key and, for Anthropic, workspace. */
export function ServiceFields({ kind, provider, address, setAddress, setAsked, suggested, listId, apiKey: key, setKey, anthropic, workspace, setWorkspace }: ServiceProps) {
  return (
    <>
      <div className="field">
        <label htmlFor="provider-address">Address</label>
        <input
          id="provider-address"
          className="input mono"
          value={address}
          placeholder={kind === 'anthropic' ? 'https://api.anthropic.com' : 'http://127.0.0.1:8080/v1'}
          list={suggested?.addresses.length ? `${listId}-addresses` : undefined}
          onChange={e => setAddress(e.target.value)}
          onBlur={() => setAsked(address.trim())}
        />
        {!!suggested?.addresses.length && (
          <datalist id={`${listId}-addresses`}>
            {suggested.addresses.map(known => (
              <option key={known.api} value={known.api} label={known.name} />
            ))}
          </datalist>
        )}
      </div>
      <div className="field">
        <label htmlFor="provider-key">API key</label>
        <input
          id="provider-key"
          className="input mono"
          type="password"
          autoComplete="off"
          value={key}
          placeholder={provider?.has_key ? 'Type a new key to replace the saved one' : suggested?.env?.[0] ? `Your ${suggested.env[0]}` : 'None'}
          onChange={e => setKey(e.target.value)}
        />
        <span className="muted provider-note">
          {provider?.has_key && 'A key is saved and is never shown again. '}
          {!provider && suggested?.service && suggested.env?.length ? `${suggested.service} calls its key ${suggested.env.join(' or ')}. ` : null}
          Keys are kept in plain text in KOLONİ's local database on this machine.
        </span>
        {keyMisfit(key, address) && (
          <p role="note" className="composer-warning provider-note">
            {keyMisfit(key, address)}
          </p>
        )}
      </div>
      {anthropic && (
        <div className="field">
          <label htmlFor="provider-workspace">Workspace ID</label>
          <input
            id="provider-workspace"
            className="input mono"
            autoComplete="off"
            value={workspace}
            maxLength={100}
            placeholder="Optional, e.g. wrkspc_…"
            onChange={e => setWorkspace(e.target.value)}
          />
          <span className="muted provider-note">
            Only needed for a key that is not scoped to a workspace. Copy it from the Anthropic console.
          </span>
        </div>
      )}
    </>
  )
}

interface ModelFieldProps extends Pick<PageProps, 'onModels' | 'onFacts'> {
  kind: ProviderKind
  cli: boolean
  provider: Provider | null
  model: string
  setModel: Setter<string>
  listId: string
  suggested: Suggestion | null
  down: boolean
  facts: ModelFacts | null | undefined
}

export function DefaultModelField({ kind, cli, provider, model, setModel, listId, suggested, down, facts, onModels, onFacts }: ModelFieldProps) {
  return (
    <div className="field">
      <label htmlFor="provider-model">Default model</label>
      <ModelNameInput
        id="provider-model"
        value={model}
        placeholder={cli ? "The CLI's own default" : kind === 'anthropic' ? 'Needed, e.g. claude-sonnet-5-5' : 'First model the server lists'}
        providerId={provider?.id ?? null}
        loadModels={onModels}
        listId={listId}
        more={suggested?.models}
        quiet={down}
        onChange={setModel}
      />
      {provider && onFacts && (
        <span className="muted provider-note">
          {facts === undefined
            ? 'Looking up the model…'
            : down
              ? `${provider.name} isn’t answering: its models and levels show once it does.`
              : `${levelsKnown(takesOf(facts), namedLevel(facts))} ${factsText(facts)}`}
        </span>
      )}
      <span className="muted provider-note">
        Offered here: your own list, then the catalogue’s models, then the provider’s own list.{' '}
        <Hint doc={GUIDE.providerModels}>
          The provider is asked only after it is saved: Anthropic and hosted services with your key, so the list is
          what that key’s account can use; a server on this machine lists the model it has loaded.
        </Hint>
      </span>
    </div>
  )
}

interface AtOnceProps {
  kind: ProviderKind
  atOnce: string
  setAtOnce: Setter<string>
  usualAtOnce: number
  most: number | null | undefined
  onThisMachine: boolean
}

export function AtOnceField({ kind, atOnce, setAtOnce, usualAtOnce, most, onThisMachine }: AtOnceProps) {
  return (
    <div className="field">
      <label htmlFor="provider-at-once">At most this many agents at once</label>
      <input
        id="provider-at-once"
        className="input mono"
        inputMode="numeric"
        value={atOnce}
        placeholder={`Default: ${usualAtOnce}`}
        aria-invalid={most === undefined || undefined}
        aria-describedby="provider-at-once-note"
        onChange={e => setAtOnce(e.target.value)}
      />
      <span id="provider-at-once-note" className="muted provider-note">
        {most === undefined ? 'A whole number from 1 to 1000, or empty for the default: as written, it is not saved. ' : ''}
        How many agents may work on this provider at the same time, across all projects. One more waits in line, and
        its node says so. Empty:{' '}
        {kind.endsWith('_cli')
          ? '3, the default for a CLI: each agent on it spends your subscription.'
          : onThisMachine
            ? 'a llama-server’s slots, read from its /props when its first agent starts (1 if it does not say them); 8 until then.'
            : '8, the default for a service.'}
      </span>
    </div>
  )
}

interface GuideProps {
  rows: GuideRow[]
  forAgents: boolean
  setForAgents: Setter<boolean>
  note: string
  setNote: Setter<string>
  listed: ListedModel[]
  only: boolean
  setOnlyListed: Setter<boolean>
}

/** What agents are told of the provider as a whole, beside its models. */
export function ProviderGuide({ rows, forAgents, setForAgents, note, setNote, listed, only, setOnlyListed }: GuideProps) {
  return (
    <>
      {/* With models listed, each says it in its row; with none, the provider itself. */}
      {rows.length === 0 && (
        <label className="choice" htmlFor="provider-for-agents">
          <input
            id="provider-for-agents"
            type="checkbox"
            role="switch"
            aria-label="Agents may use this provider"
            checked={forAgents}
            onChange={e => setForAgents(e.target.checked)}
          />
          <span>
            Agents may use this provider
            <span className="choice-note">
              With its default model, as it has no list of models. An agent can then open a sub-agent on it by itself;
              you are still asked first unless sub-agent approval is set to never ask.
            </span>
          </span>
        </label>
      )}
      <div className="field">
        <label htmlFor="provider-note">What it is good for</label>
        <input
          id="provider-note"
          className="input"
          value={note}
          maxLength={MAX_NOTE}
          placeholder="e.g. Strongest; for hard debugging and design. Spends the plan."
          onChange={e => setNote(e.target.value)}
        />
        <span className="muted provider-note">
          <span className="mono">
            {note.length} / {MAX_NOTE}
          </span>{' '}
          · Agents read your line as you wrote it when they choose; KOLONİ adds nothing to it.
        </span>
      </div>
      <label className={`choice${listed.length === 0 ? ' choice-disabled' : ''}`} htmlFor="provider-only-listed">
        <input
          id="provider-only-listed"
          type="checkbox"
          aria-label="Never run a model that is not on this list"
          checked={only}
          disabled={listed.length === 0}
          onChange={e => setOnlyListed(e.target.checked)}
        />
        <span>
          Never run a model that is not on this list{' '}
          <Hint doc={GUIDE.providerModels}>
            Even a model you pick by hand has to be on the list. So a model your plan does not cover is never sent to a
            pay-as-you-go line.
          </Hint>
          <span className="choice-note">
            Then this provider runs only the models listed: never another one, or none, for a conversation, a role or an
            agent's pick. The default model has to be on the list too.
          </span>
        </span>
      </label>
    </>
  )
}

interface TestedProps {
  tested: ProviderTest
  kind: ProviderKind
  cli: boolean
  provider: Provider | null
  ownServer: boolean
  canAdd: boolean
  onAdd: () => void
}

/** What a Test or a real run found. */
export function TestResult({ tested, kind, cli, provider, ownServer, canAdd, onAdd }: TestedProps) {
  return tested.ok ? (
    <div role="status" className="provider-ok">
      {cli && tested.reply !== null && tested.reply !== undefined ? (
        <>
          It answered "{tested.reply}" · model {modelName(tested.model_id)}
          {tested.model_from === 'settings' && " (from Codex's settings)"}
          {canAdd && (
            <>
              {' '}
              <button
                type="button"
                className="btn btn-small"
                onClick={onAdd}
              >
                Add it to the list
              </button>
            </>
          )}
        </>
      ) : cli ? (
        // Finding the command is all a check may do: running it would use up the plan. Copilot on a GitHub
        // account is asked besides whether it is signed in (no turn; "not known" passes too).
        kind === 'copilot_cli' && !provider?.base_url ? (
          <>The copilot command was found, and Copilot did not say it is signed out. It was not run.</>
        ) : ownServer && provider?.base_url ? (
          <>The {COMMAND[kind]} command was found, and your model server answered. It was not run.</>
        ) : (
          <>The {COMMAND[kind]} command was found. It was not run, so sign-in is not checked.</>
        )
      ) : (
        <>
          Reachable · {tested.model_id}
          {tested.tools_supported === false && ' · this model does not take tools'}
        </>
      )}
    </div>
  ) : (
    <div role="alert" className="alert">
      {tested.error}
    </div>
  )
}

interface ActionsProps extends Pick<PageProps, 'onSave' | 'onDelete' | 'onTest' | 'onMakeDefault'> {
  provider: Provider
  cli: boolean
  busy: boolean
  canSave: boolean
  isDefault: boolean
  onlyOne: boolean
  run: (action: () => Promise<void>) => Promise<void>
  setTested: Setter<ProviderTest | null>
}

/** A saved provider's buttons: Save, the checks, and what is done to it. */
export function ProviderActions({ provider, cli, busy, canSave, isDefault, onlyOne, run, setTested, onSave, onDelete, onTest, onMakeDefault }: ActionsProps) {
  return (
    <>
      <button type="submit" className="btn btn-primary" disabled={busy || !canSave}>
        Save
      </button>
      <button
        type="button"
        className="btn"
        disabled={busy}
        onClick={() =>
          void run(async () => {
            setTested(null)
            setTested(await onTest(provider.id))
          })
        }
      >
        Test
      </button>
      {cli && (
        <button
          type="button"
          className="btn"
          disabled={busy}
          title="Runs the CLI once on a one-word question"
          onClick={() =>
            void run(async () => {
              setTested(null)
              setTested(await onTest(provider.id, true))
            })
          }
        >
          Try a real run
        </button>
      )}
      {!isDefault && onMakeDefault && (
        <button type="button" className="btn" disabled={busy} onClick={() => void run(() => onMakeDefault(provider.id))}>
          Make default
        </button>
      )}
      {provider.has_key && (
        <button type="button" className="btn" disabled={busy} onClick={() => void run(() => onSave(provider.id, { api_key: '' }))}>
          Remove key
        </button>
      )}
      <button
        type="button"
        className="btn btn-danger"
        disabled={busy || onlyOne}
        title={onlyOne ? 'At least one provider is needed' : undefined}
        onClick={() => void run(() => onDelete(provider.id))}
      >
        Delete provider
      </button>
    </>
  )
}

/** Why a key typed will not work at this address, by Alibaba's two kinds of key: a plan's (`sk-sp-`) only at its plan's
 *  address, and the Token Plan's address only with one; null where nothing is known against it.
 *  shortcut: Beijing's Token Plan address is not offered (its address was not confirmed) and a Coding Plan's key form
 *  is not checked; add both once read in Alibaba's own docs. */
function keyMisfit(key: string, address: string): string | null {
  let host: string
  try {
    host = new URL(address.trim()).hostname
  } catch {
    return null // no address yet, or not one
  }
  const plan = key.startsWith('sk-sp-')
  if (plan && /^dashscope(-intl)?\.aliyuncs\.com$/.test(host))
    return 'This key starts with sk-sp-: a plan’s key, which works only at its plan’s address (Token Plan or Coding Plan), not at DashScope’s pay-as-you-go one.'
  if (!plan && key.startsWith('sk-') && /^token-plan\..+\.aliyuncs\.com$/.test(host))
    return 'The Token Plan’s address takes the plan’s own key, which starts with sk-sp-: this key will not work here.'
  return null
}
