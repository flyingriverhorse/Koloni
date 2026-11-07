import { CaretDown, Warning } from '@phosphor-icons/react'
import { type KeyboardEvent, useLayoutEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { BuiltinTool, McpRead, McpServer, McpServerChange, NewMcpServer, Role, Skill } from '../api/types'
import { since } from '../board/columns'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { count, type Pasted } from './paste'
import { type SkillActions, SkillsSection } from './Skills'
import { AddMenu, AddServer, type Way } from './AddServer'
import { BuiltIn } from './BuiltIn'
import { ServerEditor } from './ServerEditor'

export interface Props {
  servers: McpServer[]
  /** Open on this one (from Ctrl+K) rather than the first. */
  picked?: string
  roles: Role[]
  onAdd: (values: NewMcpServer) => Promise<McpServer>
  onSave: (serverId: string, change: McpServerChange) => Promise<void>
  onDelete: (serverId: string) => Promise<void>
  /** Starts the server once and keeps the tools it lists; `osv`: osv.dev is asked first; `inProject`: the files from a
   * project the reading before named, which the user said to start anyway (97). */
  onRead: (serverId: string, osv: boolean, inProject?: Record<string, string | null>) => Promise<McpRead>
  onRoleServers: (roleId: string, mcp: string[]) => Promise<void>
  /** KOLONİ's own tools, each on or off for every agent (slice 61). */
  builtin?: BuiltinTool[]
  /** Throws ApiError. */
  onSwitchTool?: (name: string, on: boolean) => Promise<void>
  /** KOLONİ's store of skills (K-skill-uyum), its third part; `picked` "skills" or "skill:<name>" opens there. */
  skills?: Skill[]
  skillActions?: SkillActions
}

/** What a server is not held to, and where none of its tools is to be had (app/agent.py, `_mcp`). */
const NOTES = [
  'It is not held to the project folder, to working copies or to the permission level: it can read and write anywhere and reach the network. A sub-agent that works in its copy can change the real project through a server’s tool.',
  'It is started in an empty folder of KOLONİ’s own, never in a project or a working copy, so that no file of a project decides what is started. Its tools are given full paths: an agent that has a server is told so, and the full path of the folder it works in - the project, or its working copy once it has one.',
  'So every tool is asked about unless you say otherwise. “Runs without asking” is your word: KOLONİ cannot check that a tool only reads.',
  'What a tool changes on disk is not put on record as a change, as what a command changes is not; what it changes inside a working copy is found as a difference when the copy is taken into the project.',
  'Other programs on this machine can see the arguments of the command: put a secret in a variable.',
  'Only the servers added here are started by KOLONİ: a project’s .mcp.json is not read.',
  'No server’s tool is offered to a CLI that works with its own tools (native), for a trigger’s message, in a project that runs its commands in Docker, or when an agent works only to answer another agent’s message or to speak in a discussion.',
]

const KINDS = [
  ['builtin', 'Built-in'],
  ['servers', 'Servers'],
  ['skills', 'Skills'],
] as const
type Kind = (typeof KINDS)[number][0]

/** A server's state on its row: one that could not be read, one watched, one trusted. */
const tagOf = (server: McpServer) =>
  server.read_error ? ['could not be read', 'tag-del'] : server.trusted ? ['trusted', 'tag-ok'] : ['watching', 'tag-warn']

/** Its row's second line: how many tools and how they run, or why there are none. */
function subOf(server: McpServer) {
  const off = server.enabled ? '' : 'off: given to no agent · '
  if (server.read_error) return off + server.read_error
  if (server.read_at === null) return `${off}not read yet: no agent is offered any`
  const asks = server.tools.filter(tool => tool.mark === 'ask' && !tool.unusable).length
  const how = server.trusted ? `${asks} ${asks === 1 ? 'asks' : 'ask'} first` : 'every call asks until you trust it'
  return `${off}${count(server.tools.length, 'tool')} · ${how} · read ${since(server.read_at)} ago`
}

/** KOLONİ's tools in three tabs (0.1.0-ui, layout A): its own, the MCP servers the user added, and its skills. */
export function ToolsPage({ servers, picked, builtin = [], onSwitchTool, skills = [], skillActions, ...rest }: Props) {
  const toSkills = picked?.startsWith('skill') ? picked : undefined
  // shortcut: the tab chosen is kept while the page is open, not in the address; a page opened anew is on Servers
  // (or where `picked` says). Keep it in the address if the user is seen coming back to another tab.
  const kinds = KINDS.filter(([id]) => (id !== 'builtin' || onSwitchTool) && (id !== 'skills' || skillActions))
  const [kind, setKind] = useState<Kind>(toSkills && skillActions ? 'skills' : picked === 'builtin' && onSwitchTool ? 'builtin' : 'servers')
  const counts: Record<Kind, number> = { builtin: builtin.length, servers: servers.length, skills: skills.length }
  // The server open under its row (picked, or else the first); '' none; 'new' while one is being added.
  const [selected, setSelected] = useState<string | null>(toSkills ? null : (picked ?? null))
  const [addingSkill, setAddingSkill] = useState(false)
  // The way a server is added; what "by hand" is filled from, and how many times it was filled anew.
  const [adding, setAdding] = useState<{ way: Way; start?: Pasted; n: number }>({ way: 'ready', n: 0 })
  const [error, setError] = useState<string | null>(null)
  const open = selected === 'new' || selected === '' ? null : (servers.find(s => s.id === selected) ?? servers[0] ?? null)
  function start(way: Way, from?: Pasted) {
    // (Filled anew only from a card or a paste: another way and back keeps what was typed.)
    setAdding(was => ({ way, start: from, n: from ? was.n + 1 : was.n }))
    setSelected('new')
    setKind('servers')
  }
  // A row opened - clicked, or picked from Ctrl+K - is in sight, also when a tall form above it closes.
  const openId = open?.id
  useLayoutEffect(() => {
    if (openId) document.getElementById(`tools-row-${openId}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [openId])
  // The arrow keys, Home and End move along the tabs (WAI-ARIA tabs: one tab stop, chosen as it is reached).
  function onTabKey(event: KeyboardEvent<HTMLDivElement>) {
    const at = kinds.findIndex(([id]) => id === kind)
    const to = ({ ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: kinds.length - 1 } as Record<string, number>)[event.key]
    if (to === undefined) return
    event.preventDefault()
    const next = kinds[(to + kinds.length) % kinds.length][0]
    setKind(next)
    document.getElementById(`tools-tab-${next}`)?.focus()
  }
  const switchServer = (server: McpServer) => {
    setError(null)
    rest.onSave(server.id, { enabled: !server.enabled }).catch(err => setError(errorText(err)))
  }
  return (
    <div className="memory-page tools-page">
      <div className="conv-head">
        <h2>Tools</h2>
        <AddMenu
          onServer={way => start(way)}
          onSkill={
            skillActions &&
            (() => {
              setKind('skills')
              setAddingSkill(true)
            })
          }
        />
      </div>
      <div className="tabs tools-tabs" role="tablist" aria-label="Kinds of tools" onKeyDown={onTabKey}>
        {kinds.map(([id, label]) => (
          <button
            key={id}
            id={`tools-tab-${id}`}
            type="button"
            role="tab"
            className="tab"
            aria-selected={kind === id}
            aria-controls={`tools-panel-${id}`}
            tabIndex={kind === id ? 0 : -1}
            onClick={() => setKind(id)}
          >
            {label} <span className="muted tools-count">{counts[id]}</span>
          </button>
        ))}
      </div>
      {onSwitchTool && (
        <div id="tools-panel-builtin" role="tabpanel" aria-labelledby="tools-tab-builtin" className="tools-panel" hidden={kind !== 'builtin'}>
          <p className="muted provider-note tools-lead">
            KOLONİ’s own tools; one switched off is given to no agent.{' '}
            <Hint doc={GUIDE.builtInTools}>
              One you switch off is given to no agent, whatever its role lists. Claude Code’s and Codex’s own web tools, and
              Codex’s apps, switch off with them. While Search the web or Web requests is off, a command that reaches the
              internet (curl, git clone, an https address) asks you on a card at every level, Full auto too.
            </Hint>
          </p>
          <BuiltIn tools={builtin} onSwitch={onSwitchTool} />
        </div>
      )}
      <div id="tools-panel-servers" role="tabpanel" aria-labelledby="tools-tab-servers" className="tools-panel" hidden={kind !== 'servers'}>
        <p className="muted provider-note tools-lead">
          Programs that give agents more tools. A new one asks before every call until you trust it.{' '}
          <Hint doc={GUIDE.mcpTrust}>
            <span className="hint-para">
              Programs that give agents more tools (MCP). Each tool asks you before it runs, unless you say otherwise. A server
              you add is watched: every call asks, at every level, until you trust it.
            </span>
            <span className="hint-para">
              <Warning size={13} color="var(--warn)" aria-hidden="true" /> A server runs with your rights on this machine.
            </span>
            {NOTES.map(note => (
              <span key={note} className="hint-para">
                {note}
              </span>
            ))}
          </Hint>
        </p>
        {(selected === 'new' || servers.length === 0) && (
          <AddServer
            servers={servers}
            // Not being added (the last server deleted, say): the page with none, its common servers.
            way={selected === 'new' ? adding.way : 'ready'}
            n={adding.n}
            start={adding.start}
            focus={selected === 'new' && adding.start === undefined}
            onClose={servers.length > 0 ? () => setSelected('') : undefined}
            onFill={from => start('hand', from)}
            {...rest}
            onDone={id => {
              // Added: what the form was filled from is spent.
              setAdding(was => ({ ...was, start: undefined }))
              setSelected(id)
            }}
          />
        )}
        {servers.length > 0 && (
          <ul className="tools-servers" aria-label="Servers">
            {servers.map((server, at) => {
              const shown = open?.id === server.id
              const [tag, tone] = tagOf(server)
              const given = rest.roles.filter(role => role.mcp.includes(server.name))
              return (
                <li key={server.id}>
                  <div className="tools-row">
                    <input type="checkbox" role="switch" className="switch" aria-label={`${server.name} on`} checked={server.enabled} onChange={() => switchServer(server)} />
                    <button
                      id={`tools-row-${server.id}`}
                      type="button"
                      className="tools-row-open"
                      aria-expanded={shown}
                      aria-controls={`tools-server-${server.id}`}
                      onClick={() => setSelected(shown ? '' : server.id)}
                    >
                      <span className="tools-row-text">
                        <span className="tools-row-name">
                          {server.name} <span className={`tag ${tone}`}>{tag}</span>
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
                  <div id={`tools-server-${server.id}`} hidden={!shown}>
                    {shown && (
                      // Keyed by the server and what was saved of it, so a save or a switch reloads the form.
                      <ServerEditor
                        key={`${server.id}:${JSON.stringify([server.command, server.env_names])}`}
                        server={server}
                        {...rest}
                        onDone={() => {
                          // Deleted (nothing else ends the form): the next row is open and has the focus, not the
                          // page; with none left, the Add button has it.
                          const next = servers[at + 1] ?? servers[at - 1]
                          document.getElementById(next ? `tools-row-${next.id}` : 'tools-add')?.focus()
                          setSelected(next?.id ?? null)
                        }}
                      />
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
      </div>
      {skillActions && (
        <div id="tools-panel-skills" role="tabpanel" aria-labelledby="tools-tab-skills" className="tools-panel" hidden={kind !== 'skills'}>
          <SkillsSection
            skills={skills}
            roles={rest.roles}
            off={builtin.filter(tool => !tool.on).map(tool => tool.name)}
            serversOff={servers.filter(server => !server.enabled).map(server => server.name)}
            picked={toSkills}
            adding={addingSkill}
            onAdding={setAddingSkill}
            {...skillActions}
          />
        </div>
      )}
    </div>
  )
}
