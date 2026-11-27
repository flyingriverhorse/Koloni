import { CaretDown } from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import type { McpRead, McpServer, Role } from '../api/types'
import { since } from '../board/columns'
import { Cell } from '../shell/Cell'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { runsCell, serverRuns, takenBack } from './cells'
import { commandShown, count, packageOf } from './paste'
import { foundIn } from './ServerEditor'

/** A server's state beside its name, in its cell's colour: trust a reading took back, could not be read, watched, trusted. */
const tagOf = (server: McpServer, taken: boolean) =>
  taken
    ? ['trust taken back', 'tag-warn']
    : server.read_error
      ? ['could not be read', 'tag-del']
      : server.trusted
        ? ['trusted', 'tag-ok']
        : ['watching', 'tag-accent']

/** Its card's line under the command: how many tools and how they run, or why there are none. */
function subOf(server: McpServer) {
  const off = server.enabled ? '' : 'off: given to no agent · '
  if (server.read_error) return off + server.read_error
  if (server.read_at === null) return `${off}not read yet: no agent is offered any`
  const asks = server.tools.filter(tool => tool.mark === 'ask' && !tool.unusable).length
  const how = server.trusted ? `${asks} ${asks === 1 ? 'asks' : 'ask'} first` : 'every call asks until you trust it'
  return `${off}${count(server.tools.length, 'tool')} · ${how} · read ${since(server.read_at)} ago`
}

/** npx's name@version, uvx's name==version or name@version; none, or @latest, takes the newest each start. */
const unpinnedOf = (command: string[]) => {
  const saved = packageOf(command)
  return saved !== null && !/.@(?!latest$)|==/.test(saved) ? saved : null
}

interface Props {
  server: McpServer
  /** Its editor is open under its head. */
  shown: boolean
  /** The roles that list it. */
  given: Role[]
  /** The reading on this page that took its trust back, if one did (`ToolsPage`). */
  read?: McpRead
  onOpen: () => void
  onSwitch: () => void
  /** Throws ApiError: the page says it. */
  onTrust: () => Promise<void>
  /** Its editor, while it is open. */
  children: ReactNode
}

/**
 * A server's card (0.1.10): its head - its switch, its cell, its name, command and state, the roles that list it - and,
 * while it is not trusted, its trust in sight; open, its editor under it.
 */
export function ServerCard({ server, shown, given, read, onOpen, onSwitch, onTrust, children }: Props) {
  const taken = takenBack(server, read)
  const [tag, tone] = tagOf(server, taken)
  const command = commandShown(server.command).join(' ')
  return (
    <li className={`tools-server${shown ? ' tools-open' : ''}`}>
      <div className="tools-row">
        <input
          type="checkbox"
          role="switch"
          className="switch"
          aria-label={`${server.name} on`}
          checked={server.enabled}
          onChange={onSwitch}
        />
        <Cell {...runsCell(serverRuns(server, taken))} big />
        <button
          id={`tools-row-${server.id}`}
          type="button"
          className="tools-row-open"
          aria-expanded={shown}
          aria-controls={`tools-server-${server.id}`}
          onClick={onOpen}
        >
          <span className="tools-row-text">
            <span className="tools-row-name">
              {server.name} <span className={`tag ${tone}`}>{tag}</span>
            </span>
            <span className="mono muted tools-command" title={command}>
              {command}
            </span>
            <span className="muted tools-row-sub">{subOf(server)}</span>
          </span>
          <span className="chips">
            {given.length === 0 ? (
              <span className="muted">no role: no agent uses it</span>
            ) : (
              given.map(role => (
                <span key={role.id} className="chip">
                  {role.name}
                </span>
              ))
            )}
          </span>
          <CaretDown size={13} aria-hidden className="tools-row-caret" />
        </button>
      </div>
      {/* Slice 92: a server added is watched until you trust it (one added before is trusted) - said on its card. */}
      {!server.trusted && <Trust server={server} read={taken ? read : undefined} onTrust={onTrust} />}
      <div id={`tools-server-${server.id}`} hidden={!shown}>
        {shown && children}
      </div>
    </li>
  )
}

/** A server not trusted: Trust this server - or, a reading having taken its trust back, the difference and Trust it again. */
function Trust({ server, read, onTrust }: { server: McpServer; read?: McpRead; onTrust: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [seeing, setSeeing] = useState(false)
  const unpinned = unpinnedOf(server.command)
  const trust = () => {
    setBusy(true)
    onTrust().finally(() => setBusy(false))
  }
  return (
    <>
      <div className="tools-bar tools-trust">
        {read && (
          <button
            type="button"
            className="btn btn-small btn-primary"
            aria-expanded={seeing}
            aria-controls={`tools-found-${server.id}`}
            onClick={() => setSeeing(!seeing)}
          >
            See the difference
          </button>
        )}
        {/* Trust is in the tools read: none before the first reading. */}
        <button
          type="button"
          className={`btn btn-small${read ? '' : ' btn-primary'}`}
          disabled={busy || server.read_at === null}
          aria-describedby={unpinned ? `mcp-trust-note-${server.id}` : undefined}
          onClick={trust}
        >
          {read ? 'Trust it again' : 'Trust this server'}
        </button>
        {unpinned && (
          <span id={`mcp-trust-note-${server.id}`} className="muted provider-note">
            <span className="mono">{unpinned}</span> updates itself: trust covers future versions
          </span>
        )}
        {/* That every call asks is on its head; why, and what watches it again, behind ⓘ. */}
        <Hint doc={GUIDE.mcpTrust}>
          Until you trust it, every call of its tools asks you on a card with what the server says of the tool, at every
          level, Full auto too, and “Runs without asking” waits. Read its tools and what they say first. Another
          command, another variable, or a reading that finds a new or changed tool watches it again.
        </Hint>
      </div>
      {/* What the reading found against the one before: names only - a tool's words before are not kept. */}
      {read && (
        <p id={`tools-found-${server.id}`} className="muted provider-note tools-found" hidden={!seeing}>
          {foundIn(read)}
        </p>
      )}
    </>
  )
}
