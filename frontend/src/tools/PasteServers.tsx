import { CaretDown, Lock } from '@phosphor-icons/react'
import { type ClipboardEvent, useState } from 'react'
import { errorText } from '../api/client'
import type { McpServer, NewMcpServer } from '../api/types'
import { argumentKey, commandShown, count, downloadOf, isValue, MASK, masked, NAME, type Pasted, programOf, readPasted } from './paste'

/** A command as a glance reads it: npx … server-github. */
const short = ([program, ...args]: string[]) =>
  [programOf(program), ...(args.length > 1 ? ['…'] : []), ...args.slice(-1).map(arg => arg.split(/[\\/]/).pop())].join(' ')

interface Props {
  servers: McpServer[]
  onAdd: (values: NewMcpServer) => Promise<McpServer>
  onEdit: (server: Pasted) => void
  onDone: (serverId: string) => void
}

/**
 * A server's block from its README, pasted, and what KOLONİ read from it: each server a card to
 * tick. Adding starts nothing; its values are put away as soon as they are read (MASK).
 * (Maps, not objects, by a server's name: a server may be named constructor or __proto__.)
 */
export function PasteServers({ servers, onAdd, onEdit, onDone }: Props) {
  const [text, setText] = useState('')
  // The values read from the text, by server and variable: the text has MASK in their place.
  const [kept, setKept] = useState(new Map<string, string>())
  // By the name a server has in the text: the name it is given here, the boxes unticked, the cards opened or closed.
  const [names, setNames] = useState(new Map<string, string>())
  const [unticked, setUnticked] = useState<string[]>([])
  const [toggled, setToggled] = useState<string[]>([])
  const [failed, setFailed] = useState(new Map<string, string>())
  const [busy, setBusy] = useState(false)
  const read = text.trim() ? readPasted(text) : null
  const found = (read && 'servers' in read ? read.servers : []).map(server => {
    const env = Object.fromEntries(
      Object.entries(server.env).map(([variable, value]) => [variable, value === MASK ? (kept.get(`${server.name}\n${variable}`) ?? '') : value]),
    )
    // An argument with MASK in it is the key kept for it; the card shows `shown`, the request sends `command`.
    const command = server.command.map((part, at) => (part.includes(MASK) ? (kept.get(argumentKey(server.name, at)) ?? '') : part))
    const name = names.get(server.name) ?? server.name
    // Known from the servers as they are now: one added a moment ago is skipped, not added twice.
    const added = servers.some(one => one.name === name)
    const missing = [...Object.keys(env).filter(variable => !isValue(env[variable])), ...command.flatMap((part, at) => (part ? [] : [`argument ${at}`]))]
    const addable = !added && NAME.test(name) && missing.length === 0
    const shown = commandShown(server.command)
    return { key: server.name, name, command, shown, env, added, missing, addable, ticked: addable && !unticked.includes(server.name) }
  })
  const ticked = found.filter(server => server.ticked)
  // "Edit before adding": first one whose value is to be typed, then the first ticked, then any not added yet.
  const editable = found.find(server => !server.added && server.missing.length > 0) ?? ticked[0] ?? found.find(server => !server.added)

  function putAway(away: [string, string][]) {
    setKept(was => new Map([...was, ...away]))
  }

  // What is pasted is read on its own and goes into the box already masked: the token is never in
  // the box, and undo cannot bring it back.
  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const read = masked(event.clipboardData.getData('text'))
    if (!read) return
    event.preventDefault()
    const box = event.currentTarget
    setText(text.slice(0, box.selectionStart) + read.text + text.slice(box.selectionEnd))
    putAway(read.away)
  }

  async function add() {
    setBusy(true)
    setFailed(new Map())
    const why = new Map<string, string>()
    let first: string | null = null
    for (const server of ticked) {
      try {
        const made = await onAdd({ name: server.name, command: server.command, env: server.env })
        first ??= made.id
      } catch (err) {
        why.set(server.key, errorText(err))
      }
    }
    setBusy(false)
    if (why.size > 0) return setFailed(why)
    setText('')
    setKept(new Map())
    if (first) onDone(first)
  }

  const flip = (list: string[], key: string) => (list.includes(key) ? list.filter(one => one !== key) : [...list, key])
  const unsupported = read && 'servers' in read ? read.unsupported : []
  return (
    <div className="paste-two">
      <section className="paste-side" aria-labelledby="paste-text-label">
        <label id="paste-text-label" htmlFor="paste-text" className="kicker">
          1 · What you pasted
        </label>
        <textarea
          id="paste-text"
          className="input mono role-instructions"
          rows={14}
          spellCheck={false}
          autoComplete="off"
          value={text}
          aria-describedby="paste-text-note"
          placeholder={'{\n  "mcpServers": { … }\n}'}
          onPaste={onPaste}
          onChange={e => {
            if (!e.target.value.trim()) setKept(new Map())
            setText(e.target.value)
          }}
          // Typed rather than pasted: put away once the box is left.
          onBlur={() => {
            const read = masked(text)
            if (!read) return
            setText(read.text)
            putAway(read.away)
          }}
        />
        <p id="paste-text-note" className="muted provider-note">
          Copy the block from the server’s README. Also read: the same with or without the outer “mcpServers”, one server alone, VS
          Code’s “servers”, or a claude mcp add line.
        </p>
      </section>
      <section className="paste-side" aria-labelledby="paste-read-label">
        <h3 id="paste-read-label" className="kicker">
          2 · What KOLONİ read from it
        </h3>
        {read === null ? (
          <p className="muted provider-note">Nothing pasted yet.</p>
        ) : 'error' in read ? (
          <p role="status" className="alert">
            {read.error}
          </p>
        ) : (
          <>
            <ul className="paste-servers">
              {found.map((server, at) => {
                const open = (found.length === 1) !== toggled.includes(server.key)
                const [program, ...args] = server.shown
                const variables = Object.keys(server.env)
                const secret = variables.some(variable => isValue(server.env[variable]))
                const downloads = downloadOf(server.shown)
                const label = server.name || 'this server'
                return (
                  <li key={server.key} className="paste-server">
                    <div className="paste-server-head">
                      {/* A sibling of the button that opens the card: ticking it does not open it. */}
                      <input
                        type="checkbox"
                        aria-label={`Add ${label}`}
                        checked={server.ticked}
                        disabled={!server.addable || busy}
                        onChange={() => setUnticked(flip(unticked, server.key))}
                      />
                      <button
                        type="button"
                        className="paste-server-toggle"
                        aria-expanded={open}
                        aria-controls={`paste-server-${at}`}
                        onClick={() => setToggled(flip(toggled, server.key))}
                      >
                        <span className="paste-server-name mono">{server.name || 'no name yet'}</span>
                        <span className="muted mono paste-server-command">{short(server.shown)}</span>
                        <span className="paste-server-tags">
                          {server.added ? <span className="tag">already added — will be skipped</span> : <span className="tag tag-ok">new</span>}
                          {secret && (
                            <span className="tag">
                              <Lock size={11} aria-hidden="true" /> key kept secret
                            </span>
                          )}
                          {downloads && <span className="tag tag-warn">downloads on first read</span>}
                          {!server.added && server.missing.length > 0 && <span className="tag tag-warn">needs a value</span>}
                          {!server.added && !NAME.test(server.name) && <span className="tag tag-warn">needs a name</span>}
                        </span>
                        <CaretDown size={12} aria-hidden="true" className="paste-server-caret" />
                      </button>
                    </div>
                    {failed.has(server.key) && (
                      <div role="alert" className="alert">
                        {server.name} was not added: {failed.get(server.key)}
                      </div>
                    )}
                    <div id={`paste-server-${at}`} className="paste-server-body" hidden={!open}>
                      <div className="paste-server-grid">
                        <label htmlFor={`paste-name-${at}`}>Name of {label}</label>
                        <input
                          id={`paste-name-${at}`}
                          className="input mono"
                          value={server.name}
                          maxLength={16}
                          aria-invalid={!server.added && !NAME.test(server.name)}
                          aria-describedby={`paste-name-note-${at}`}
                          onChange={e => setNames(new Map(names).set(server.key, e.target.value))}
                        />
                        <span id={`paste-name-note-${at}`} className="muted provider-note paste-server-wide">
                          Starts with a letter; 1 to 16 of a-z, 0-9 and -.
                        </span>
                        <span>Command</span>
                        <span className="mono paste-field">{program}</span>
                        {args.length > 0 && (
                          <>
                            <span>Arguments</span>
                            <span className="mono paste-field">{args.join(' ')}</span>
                          </>
                        )}
                        {variables.length > 0 && (
                          <>
                            <span>Variables</span>
                            <span className="paste-vars">
                              {variables.map(variable => (
                                <span key={variable}>
                                  <span className="mono paste-field">{variable}</span>{' '}
                                  {isValue(server.env[variable]) ? (
                                    <span className="paste-secret">
                                      <Lock size={11} aria-hidden="true" /> kept secret
                                    </span>
                                  ) : (
                                    <span className="paste-missing">no value</span>
                                  )}
                                </span>
                              ))}
                            </span>
                          </>
                        )}
                      </div>
                      {secret && (
                        <p className="paste-note paste-note-ok">
                          <b>The token was in what you pasted:</b> it is moved to the secret field and never shown again. Clear your
                          clipboard if you like.
                        </p>
                      )}
                      {!server.added && server.missing.length > 0 && (
                        <p className="paste-note">
                          <b>
                            {server.missing.join(' and ')} {server.missing.length === 1 ? 'has' : 'have'} no value in what you pasted:
                          </b>{' '}
                          “Edit before adding” to type it.
                        </p>
                      )}
                      {downloads && (
                        <p className="paste-note">
                          <b>Downloads on first read:</b> {programOf(program)} fetches <span className="mono">{downloads}</span> from the
                          internet. You are asked before it runs.
                        </p>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
            {unsupported.length > 0 && (
              <p className="muted provider-note">
                Not added: {unsupported.map(name => name || 'this server').join(', ')} - reached over the network (url). Only servers
                started by a command can be added yet.
              </p>
            )}
          </>
        )}
        <div className="paste-foot">
          <span className="muted">{count(ticked.length, 'new server')}</span>
          <button
            type="button"
            className="btn"
            disabled={busy || !editable}
            onClick={() =>
              editable &&
              onEdit({
                name: editable.name,
                command: editable.command,
                env: Object.fromEntries(Object.entries(editable.env).map(([variable, value]) => [variable, isValue(value) ? value : ''])),
              })
            }
          >
            Edit before adding
          </button>
          <button type="button" className="btn btn-primary" disabled={busy || ticked.length === 0} onClick={() => void add()}>
            Add {count(ticked.length, 'server')}
          </button>
        </div>
      </section>
    </div>
  )
}
