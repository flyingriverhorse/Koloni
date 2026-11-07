import { Plus, X } from '@phosphor-icons/react'
import { type FormEvent, useRef, useState } from 'react'
import { errorText } from '../api/client'
import type { McpRead, McpServer, McpTool } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { PackageLook } from './PackageLook'
import { commandShown, count, downloadOf, packageOf, type Pasted } from './paste'
import type { Props } from './ToolsPage'

/** How many of a server's tools its table shows before "+ N more", with nothing typed in its search. */
const FIRST_TOOLS = 8

const MARKS: [mark: McpTool['mark'], label: string][] = [
  ['ask', 'Ask'],
  ['free', 'Runs without asking'],
  ['off', 'Off'],
]

const linesOf = (text: string) => text.split('\n').map(line => line.trim()).filter(Boolean)

/** What a reading found against the one before, in words; nothing that is not there is named. */
function foundIn(read: McpRead): string {
  const parts = [
    read.new.length > 0 && `New: ${read.new.join(', ')}.`,
    read.changed.length > 0 && `Changed: ${read.changed.join(', ')} - one that ran without asking is asked about again.`,
    read.gone.length > 0 && `Gone: ${read.gone.join(', ')}.`,
  ].filter(Boolean)
  return parts.length > 0 ? parts.join(' ') : 'Nothing is new, changed or gone since the reading before.'
}

export interface EditorProps extends Omit<Props, 'servers'> {
  server: McpServer | null
  /** What a new server's form is filled from: a card (its variables with no value), or what was pasted. */
  start?: Pasted
  onDone: (serverId: string | null) => void
}

/**
 * A secret's field is written through its property only: React would write a controlled value
 * into the input's value attribute too, where the page's markup has it.
 */
const secretRef = (value: string) => (field: HTMLInputElement | null) => {
  if (field && field.value !== value) field.value = value
}

/** A path with what does not show in it written out, as an agent's card has it (`mcp_client.visible`): the yes is to what is seen. */
const visible = (text: string) =>
  text.replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/gu, ch => `\\u${ch.codePointAt(0)!.toString(16).padStart(4, '0')}`)

/** What a server runs from a project, as an agent's card says it (`mcp_client.runs`): the first few, and why it is asked every time.
 * shortcut: 2000 files and 50 MB are mcp_client.MAX_TREE_FILES and MAX_TREE_BYTES written again; change both together. */
function runsShown(files: Record<string, string | null>) {
  const paths = Object.keys(files)
  const more = paths.length > 3 ? ` and ${paths.length - 3} more` : ''
  const always = Object.values(files).includes(null)
    ? ' (a folder of it holds more than 2000 files or 50 MB, or what could not be read: you are asked every time it starts)'
    : ''
  return paths.slice(0, 3).map(visible).join(', ') + more + always
}

export function ServerEditor({ server, start, roles, onAdd, onSave, onDelete, onRead, onRoleServers, onDone }: EditorProps) {
  const [name, setName] = useState(server?.name ?? start?.name ?? '')
  // A key in an argument is never in the box: a saved server's comes masked, a pasted one is masked
  // here, and a line left as it was shown is sent as it was given.
  const given = server?.command ?? start?.command ?? []
  const givenShown = commandShown(given)
  const [command, setCommand] = useState(givenShown.join('\n'))
  // The saved variables are known by name only: a value typed here replaces the saved one,
  // null takes the variable away, and one not touched stays as it is.
  const [kept, setKept] = useState<Record<string, string | null>>({})
  const [rows, setRows] = useState<{ name: string; value: string }[]>(Object.entries(start?.env ?? {}).map(([name, value]) => ({ name, value })))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [read, setRead] = useState<McpRead | null>(null)
  // A command that may download what it runs is asked about before each reading starts it.
  const [asking, setAsking] = useState(false)
  // Its package looked for in osv.dev's known-malware records first (slice 92, A6): on unless taken off.
  const [osv, setOsv] = useState(true)
  // A server that runs files from a project, which agents can change, is not started until this is answered (97).
  const [inProject, setInProject] = useState<Record<string, string | null> | null>(null)
  const readButton = useRef<HTMLButtonElement>(null)
  const saved = server ? packageOf(server.command) : null
  // npx's name@version, uvx's name==version or name@version; none, or @latest, takes the newest each start.
  const unpinned = saved !== null && !/.@(?!latest$)|==/.test(saved)
  const readNow = (startFrom: Record<string, string | null> | null) => {
    if (!server) return
    const check = osv && saved !== null
    void run(async () => {
      const got = await (startFrom ? onRead(server.id, check, startFrom) : onRead(server.id, check))
      if (got.in_project) setInProject(got.in_project)
      else setRead(got)
    })
  }
  // Answered either way, the focus goes back to the button that asked.
  const answer = (yes: boolean) => {
    setAsking(false)
    readButton.current?.focus()
    if (yes) readNow(null)
  }
  const answerProject = (yes: boolean) => {
    setInProject(null)
    readButton.current?.focus()
    if (yes) readNow(inProject)
  }
  const lines = linesOf(command).map((line, at) => (line === givenShown[at] ? given[at] : line))
  const spec = packageOf(lines)
  const added = Object.fromEntries(rows.filter(row => row.name.trim()).map(row => [row.name.trim(), row.value]))
  // A variable it came with no value for is what its server needs to start (a token): it is not added without it.
  const missing = Object.entries(start?.env ?? {})
    .filter(([variable, value]) => value === '' && !rows.some(row => row.name.trim() === variable && row.value))
    .map(([variable]) => variable)

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
    if (!server) {
      void run(async () => onDone((await onAdd({ name: name.trim(), command: lines, env: added })).id))
      return
    }
    const env = { ...Object.fromEntries(Object.entries(kept).filter(([, value]) => value !== '')), ...added }
    void run(async () => {
      await onSave(server.id, {
        ...(JSON.stringify(lines) !== JSON.stringify(server.command) ? { command: lines } : {}),
        ...(Object.keys(env).length > 0 ? { env } : {}),
      })
      // Saved: no value stays in the form.
      setKept({})
      setRows([])
    })
  }

  const on = server?.tools.filter(tool => tool.mark !== 'off' && tool.chars !== null) ?? []
  const chars = on.reduce((sum, tool) => sum + (tool.chars ?? 0), 0).toLocaleString('en-US')
  // A server can have hundreds of tools: the table lists the ones whose name or description has what is typed.
  const [find, setFind] = useState('')
  const wanted = find.trim().toLowerCase()
  const found = server?.tools.filter(tool => `${tool.name}\n${tool.description}`.toLowerCase().includes(wanted)) ?? []
  // With nothing typed, the first few and "+ N more"; typed, every one found.
  const [more, setMore] = useState(false)
  const listed = wanted || more ? found : found.slice(0, FIRST_TOOLS)
  // A saved server's name, command and variables are behind Edit; a new one's form is all there is.
  const [editing, setEditing] = useState(server === null)
  // Every tool that can be offered, given one mark in one request. Never "Runs without asking": that is said tool by tool.
  const offerable = server?.tools.filter(tool => !tool.unusable) ?? []
  function setAll(mark: 'ask' | 'off') {
    if (server) void run(() => onSave(server.id, { marks: Object.fromEntries(offerable.map(tool => [tool.name, mark])) }))
  }
  return (
    <form className="role-editor tools-editor" onSubmit={submit}>
      {server && (
        <div className="tools-bar">
          <span className="mono tools-command" title={givenShown.join(' ')}>
            {givenShown.join(' ')}
          </span>
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            title="Starts the server once, in an empty folder, asks it for its tools and ends it"
            ref={readButton}
            onClick={() => (downloadOf(server.command) ? setAsking(true) : answer(true))}
          >
            Read its tools
          </button>
          <button type="button" className="btn btn-small" aria-expanded={editing} onClick={() => setEditing(!editing)}>
            Edit
          </button>
          <button
            type="button"
            className="btn btn-small btn-danger"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await onDelete(server.id)
                onDone(null)
              })
            }
          >
            Delete server
          </button>
        </div>
      )}
      {editing && (
      <>
      <div className="field">
        <label htmlFor="mcp-name">Name</label>
        <input
          id="mcp-name"
          className="input mono"
          value={name}
          readOnly={server !== null}
          maxLength={16}
          aria-describedby="mcp-name-note"
          onChange={e => setName(e.target.value)}
        />
        <span id="mcp-name-note" className="muted provider-note">
          1 to 16 of a-z, 0-9 and -, starting with a letter. It cannot be changed later: agents see its tools as
          name__tool.
        </span>
      </div>
      <div className="field">
        <label htmlFor="mcp-command">Command</label>
        <textarea
          id="mcp-command"
          className="input mono role-instructions"
          rows={4}
          // Filled from a card: the line left to the user is here, or its variable's value is.
          autoFocus={start !== undefined && Object.keys(start.env).length === 0}
          value={command}
          aria-describedby="mcp-command-note mcp-command-more"
          placeholder={'The program on the first line, then one argument a line'}
          onChange={e => setCommand(e.target.value)}
        />
        <span className="muted provider-note">
          {/* What saving refuses stays in sight; why is behind ⓘ. */}
          <span id="mcp-command-note">
            The program, then each argument on a line of its own (at most 20). For a .cmd or .bat program (npx on Windows
            is one), saving refuses % ! ^ &amp; | &lt; &gt; in its path and its arguments.
          </span>{' '}
          <Hint doc={GUIDE.mcpAdding} id="mcp-command-more">
            A bare name is looked for on PATH; otherwise give the full path. It starts as written: no shell reads the line,
            so quotes, pipes and variables do nothing. A .cmd or .bat file is the exception: the Windows command
            interpreter runs it and would act on those characters.
          </Hint>
        </span>
      </div>
      <fieldset className="provider-server">
        <legend>Variables</legend>
        {server?.env_names.map(variable => {
          const removed = kept[variable] === null
          return (
            <div key={variable} className="model-row">
              <span className="mono">{variable}</span>
              <input
                className="input mono"
                type="password"
                autoComplete="off"
                aria-label={`New value of ${variable}`}
                ref={secretRef(kept[variable] ?? '')}
                disabled={removed}
                placeholder={removed ? 'Taken away when you save' : 'Saved. Type a new value to replace it'}
                onChange={e => setKept({ ...kept, [variable]: e.target.value })}
              />
              <button
                type="button"
                className="icon-btn"
                aria-label={`Remove ${variable}`}
                aria-pressed={removed}
                onClick={() => setKept({ ...kept, [variable]: removed ? '' : null })}
              >
                <X size={13} />
              </button>
            </div>
          )
        })}
        {rows.map((row, index) => (
          <div key={index} className="model-row">
            <input
              className="input mono"
              aria-label={`Variable ${index + 1}`}
              value={row.name}
              placeholder="NAME"
              onChange={e => setRows(rows.map((one, at) => (at === index ? { ...one, name: e.target.value } : one)))}
            />
            <input
              className="input mono"
              type="password"
              autoComplete="off"
              aria-label={`Value ${index + 1}`}
              autoFocus={start !== undefined && index === 0}
              ref={secretRef(row.value)}
              placeholder="Its value"
              onChange={e => setRows(rows.map((one, at) => (at === index ? { ...one, value: e.target.value } : one)))}
            />
            <button
              type="button"
              className="icon-btn"
              aria-label={`Remove variable ${index + 1}`}
              onClick={() => setRows(rows.filter((_, at) => at !== index))}
            >
              <X size={13} />
            </button>
          </div>
        ))}
        <button type="button" className="btn btn-small" onClick={() => setRows([...rows, { name: '', value: '' }])}>
          <Plus size={13} />
          Add a variable
        </button>
        <span className="muted provider-note">
          Added to the server’s environment, on top of this machine’s own (KOLONİ’s own settings are left out). A value
          is kept in plain text in KOLONİ’s local database and never shown again. In what the server’s tools return, a
          value of 8 characters or more shows as ***.
        </span>
      </fieldset>
      {/* Keyed by the command: another package's findings are not shown under this one's. (A saved server's: under Checks.) */}
      {!server && spec && <PackageLook key={lines.join('\n')} spec={spec} command={lines} />}
      <div className="role-actions">
        {server ? (
          <button type="submit" className="btn btn-primary" disabled={busy || lines.length === 0}>
            Save
          </button>
        ) : (
          <>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={busy || !name.trim() || lines.length === 0 || missing.length > 0}
              aria-describedby={missing.length > 0 ? 'mcp-missing' : undefined}
            >
              Add server
            </button>
            {missing.length > 0 && (
              <span id="mcp-missing" className="muted provider-note">
                Type the value of {missing.join(' and ')} first: the server cannot start without it.
              </span>
            )}
          </>
        )}
      </div>
      </>
      )}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {server && asking && (
        <section className="cmd-approval" aria-label="Read its tools?">
          <div className="kicker cmd-approval-kicker">Read its tools?</div>
          <p className="cmd-approval-note">
            It may download {downloadOf(server.command)} from the internet before it starts. The server runs on this
            machine with your rights.
          </p>
          {saved && (
            <label className="choice" htmlFor="mcp-osv">
              <input
                id="mcp-osv"
                type="checkbox"
                aria-label="First look for it in osv.dev’s known-malware records"
                aria-describedby="mcp-osv-note"
                checked={osv}
                onChange={e => setOsv(e.target.checked)}
              />
              <span>
                First look for it in osv.dev’s known-malware records
                <span id="mcp-osv-note" className="choice-note">
                  Sends the name {saved} to osv.dev. A package it lists is not started. If osv.dev cannot be reached, it starts
                  anyway and you are told. Its dependencies are not checked.
                </span>
              </span>
            </label>
          )}
          <div className="change-actions">
            {/* (Asked, the question takes the focus, as the undo card's does.) */}
            <button type="button" className="btn btn-small btn-primary" autoFocus onClick={() => answer(true)}>
              Download and read
            </button>
            <button type="button" className="btn btn-small" onClick={() => answer(false)}>
              Cancel
            </button>
          </div>
        </section>
      )}
      {server && inProject && (
        <section className="cmd-approval" aria-label="Start it anyway?">
          <div className="kicker cmd-approval-kicker">Start it anyway?</div>
          <p className="cmd-approval-note">
            This server runs {runsShown(inProject)} from your project, which agents can change. It runs on
            this machine with your rights, outside every agent’s card. You are asked again if its code changes.
          </p>
          <div className="change-actions">
            <button type="button" className="btn btn-small btn-primary" autoFocus onClick={() => answerProject(true)}>
              Start it anyway
            </button>
            <button type="button" className="btn btn-small" onClick={() => answerProject(false)}>
              Cancel
            </button>
          </div>
        </section>
      )}
      {server && (
        <>
          {/* Slice 92: a server added is watched until you trust it (one added before is trusted). */}
          {!server.trusted && (
            <>
              <div className="tools-bar">
                <span className="tag tag-warn">Watching: every call asks</span>
                {/* Trust is in the tools read: none before the first reading. */}
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={busy || server.read_at === null}
                  aria-describedby={unpinned ? 'mcp-trust-note' : undefined}
                  onClick={() => void run(() => onSave(server.id, { trusted: true }))}
                >
                  Trust this server
                </button>
                {unpinned && (
                  <span id="mcp-trust-note" className="muted provider-note">
                    <span className="mono">{saved}</span> updates itself: trust covers future versions
                  </span>
                )}
              </div>
              {/* What it runs stays in sight; why, and what watches it again, behind ⓘ. */}
              <p className="muted provider-note">
                Every call asks until you trust it.{' '}
                <Hint doc={GUIDE.mcpTrust}>
                  Until you trust it, every call of its tools asks you on a card with what the server says of the tool, at every
                  level, Full auto too, and “Runs without asking” waits. Read its tools and what they say first. Another command,
                  another variable, or a reading that finds a new or changed tool watches it again.
                </Hint>
              </p>
            </>
          )}
          {/* What the package says of itself and what the last reading found: only what is on record. */}
          <h4 className="kicker">Checks</h4>
          {spec && <PackageLook key={lines.join('\n')} spec={spec} command={lines} />}
          {server.read_error ? (
            <div role="alert" className="alert">
              Its tools could not be read. {server.read_error}
              {server.tools.length > 0 && ' What is listed below is from the reading before.'}
            </div>
          ) : read ? (
            <div role="status" className="provider-ok">
              {count(read.server.tools.length, 'tool')} read. {foundIn(read)}
              {read.malware &&
                (read.malware.error
                  ? ` osv.dev could not be asked (${read.malware.error}): it was started without that check.`
                  : ` osv.dev lists no known-malware record for ${read.malware.package}.`)}
            </div>
          ) : server.read_at === null ? (
            <p className="muted provider-note">
              Its tools have not been read yet: no agent is offered any. “Read its tools” starts the server once in an
              empty folder, asks for its tools and stops it. Agents get the tools as read, until you read them again.
            </p>
          ) : (
            <p className="muted provider-note">Its tools were last read {new Date(server.read_at).toLocaleString()}.</p>
          )}
          {server.tools.length > 0 && (
            <>
              <div className="tools-bar">
                <input
                  type="search"
                  className="input"
                  aria-label="Find a tool"
                  placeholder="Find a tool by its name or description…"
                  value={find}
                  onChange={e => setFind(e.target.value)}
                />
                <button type="button" className="btn btn-small" disabled={busy || offerable.length === 0} onClick={() => setAll('ask')}>
                  Set all to Ask
                </button>
                <button type="button" className="btn btn-small" disabled={busy || offerable.length === 0} onClick={() => setAll('off')}>
                  Set all to Off
                </button>
                <Hint doc={GUIDE.mcpTools}>
                  Each sets every one of this server’s {count(offerable.length, 'tool')} that can be offered - the ones you
                  set by hand too{wanted ? `, and not only the ${found.length} shown` : ''}. It cannot be undone.
                </Hint>
              </div>
              {/* What the line under the table says in full, in sight before the table is read to its end. */}
              <p className="muted provider-note">
                {on.length} of {count(server.tools.length, 'tool')} on · about {chars} characters added to every model step
                {wanted && ` · ${found.length} shown`}
              </p>
              {found.length === 0 ? (
                <p className="muted provider-note">No tool has “{find.trim()}” in its name or description.</p>
              ) : (
                // However many tools, the table is no taller than the window: it scrolls under its heading.
                <div className="tools-table">
                  <table className="usage-table usage-limits" aria-label={`Tools of ${server.name}`}>
                    <thead>
                      <tr>
                        <th scope="col">Tool</th>
                        <th scope="col">The server’s own description and inputs</th>
                        <th scope="col">Adds to every step</th>
                        <th scope="col">When an agent calls it</th>
                      </tr>
                    </thead>
                    <tbody>
                      {listed.map(tool => (
                        <tr key={tool.name}>
                          <th scope="row" className="mono">
                            {tool.name}
                          </th>
                          <td>
                            {tool.description ? `“${tool.description}”` : <span className="muted">none given</span>}
                            {/* The model is told its inputs too, and "Runs without asking" is said of both. */}
                            {!tool.unusable && (
                              <details className="tool-inputs">
                                <summary>Its inputs, as an agent is given them</summary>
                                <pre className="mono">{JSON.stringify(tool.input_schema, null, 2)}</pre>
                              </details>
                            )}
                          </td>
                          <td className="mono">{tool.chars === null ? '' : `about ${tool.chars.toLocaleString('en-US')} characters`}</td>
                          <td>
                            {tool.unusable ? (
                              <span className="choice-note">Not offered: {tool.unusable}.</span>
                            ) : (
                              <select
                                className="input"
                                aria-label={`When an agent calls ${tool.name}`}
                                value={tool.mark}
                                disabled={busy}
                                onChange={e =>
                                  void run(() => onSave(server.id, { marks: { [tool.name]: e.target.value as McpTool['mark'] } }))
                                }
                              >
                                {MARKS.map(([mark, label]) => (
                                  <option key={mark} value={mark}>
                                    {label}
                                  </option>
                                ))}
                              </select>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {listed.length < found.length && (
                    <button type="button" className="link-btn" onClick={() => setMore(true)}>
                      + {found.length - listed.length} more
                    </button>
                  )}
                </div>
              )}
              <p className="muted provider-note">
                {count(on.length, 'tool')} on: about {chars}{' '}
                characters added to every model step of an agent with this server. A small local model’s context has to
                carry them.
              </p>
            </>
          )}
          {/* R191: an MCP server is given only to the roles that list it (`Role.mcp`). */}
          <p className="muted provider-note">Agents use it only in the roles you tick here.</p>
          <fieldset className="role-tools">
            <legend>Roles that may use it</legend>
            {roles.map(role => {
              const has = role.mcp.includes(server.name)
              return (
                <label key={role.id} className="choice" htmlFor={`mcp-role-${role.id}`}>
                  <input
                    id={`mcp-role-${role.id}`}
                    type="checkbox"
                    checked={has}
                    disabled={busy}
                    onChange={() =>
                      void run(() => onRoleServers(role.id, has ? role.mcp.filter(n => n !== server.name) : [...role.mcp, server.name]))
                    }
                  />
                  <span>{role.name}</span>
                </label>
              )
            })}
          </fieldset>
          <p className="muted provider-note">
            A sub-agent never gets a server the agent that opened it does not have: for a sub-agent to use this one, the
            Orchestrator needs it too.
          </p>
        </>
      )}
    </form>
  )
}
