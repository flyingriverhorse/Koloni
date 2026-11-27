import { Warning } from '@phosphor-icons/react'
import { type KeyboardEvent, useLayoutEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { BuiltinTool, McpRead, McpServer, McpServerChange, NewMcpServer, Role, Skill } from '../api/types'
import { Cell } from '../shell/Cell'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { RUNS_CELL, RUNS_WORD, type Runs } from './cells'
import type { Pasted } from './paste'
import { type SkillActions, SkillsSection } from './Skills'
import { AddMenu, AddServer, type Way } from './AddServer'
import { BuiltIn } from './BuiltIn'
import { ServerCard } from './ServerCard'
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
  'No server’s tool is offered to a CLI that works with its own tools (native), in a project that runs its commands in Docker, or when an agent works only to answer another agent’s message or to speak in a discussion.',
]

const KINDS = [
  ['builtin', 'KOLONİ’s tools'],
  ['servers', 'Servers'],
  ['skills', 'Skills'],
] as const
type Kind = (typeof KINDS)[number][0]

/** What the cells say, once, under the heading: each cell with its word - the word is what a screen reader says. */
function ToolsKey() {
  return (
    <div className="cell-legend tools-key" role="group" aria-label="What the cells say">
      {(Object.keys(RUNS_WORD) as Runs[]).map(runs => (
        <span key={runs}>
          <Cell {...RUNS_CELL[runs]} label={RUNS_WORD[runs]} hidden /> {RUNS_WORD[runs]}
        </span>
      ))}
    </div>
  )
}

/** The tab a page opened anew is on: Skills or Built-in where `picked` says so and that tab is there, else Servers. */
const firstKind = (
  toSkills: string | undefined,
  skillActions: SkillActions | undefined,
  picked: string | undefined,
  onSwitchTool: Props['onSwitchTool'],
): Kind => (toSkills && skillActions ? 'skills' : picked === 'builtin' && onSwitchTool ? 'builtin' : 'servers')

/** The server open under its row: the one selected, or else the first; none while one is added ('new') or all are closed (''). */
const openOf = (servers: McpServer[], selected: string | null) =>
  selected === 'new' || selected === '' ? null : (servers.find(s => s.id === selected) ?? servers[0] ?? null)

/** KOLONİ's tools in three tabs (0.1.0-ui, layout A): its own, the MCP servers the user added, and its skills. */
export function ToolsPage({ servers, picked, builtin = [], onSwitchTool, skills = [], skillActions, ...rest }: Props) {
  const toSkills = picked?.startsWith('skill') ? picked : undefined
  // shortcut: the tab chosen is kept while the page is open, not in the address; a page opened anew is on Servers
  // (or where `picked` says). Keep it in the address if the user is seen coming back to another tab.
  const kinds = KINDS.filter(([id]) => (id !== 'builtin' || onSwitchTool) && (id !== 'skills' || skillActions))
  const [kind, setKind] = useState<Kind>(firstKind(toSkills, skillActions, picked, onSwitchTool))
  // What waits on a tab, beside its name: the servers watched.
  const watched = servers.filter(server => !server.trusted).length
  const badges: Record<Kind, string> = { builtin: '', servers: watched ? `${watched} watching` : '', skills: '' }
  // shortcut: a reading that took a server's trust back is known only from its answer, kept while the page is open
  // (no field says it): opened anew, such a server shows as watched. Keep it on the server if that is seen to matter.
  const [reads, setReads] = useState<Record<string, McpRead>>({})
  const onRead: Props['onRead'] = async (serverId, osv, inProject) => {
    const was = servers.find(server => server.id === serverId)?.trusted
    const got = await (inProject ? rest.onRead(serverId, osv, inProject) : rest.onRead(serverId, osv))
    if (was && !got.server.trusted) setReads(kept => ({ ...kept, [serverId]: got }))
    return got
  }
  // The server open under its row (picked, or else the first); '' none; 'new' while one is being added.
  const [selected, setSelected] = useState<string | null>(toSkills ? null : (picked ?? null))
  const [addingSkill, setAddingSkill] = useState(false)
  // The way a server is added; what "by hand" is filled from, and how many times it was filled anew.
  const [adding, setAdding] = useState<{ way: Way; start?: Pasted; n: number }>({ way: 'ready', n: 0 })
  const [error, setError] = useState<string | null>(null)
  const open = openOf(servers, selected)
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
    const to = ({ ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: kinds.length - 1 } as Record<string, number>)[
      event.key
    ]
    if (to === undefined) return
    event.preventDefault()
    const next = kinds[(to + kinds.length) % kinds.length][0]
    setKind(next)
    document.getElementById(`tools-tab-${next}`)?.focus()
  }
  /** A change made from a server's card head - its switch, its trust: a refusal says why under the list. */
  const saveServer = (server: McpServer, change: McpServerChange) => {
    setError(null)
    return rest.onSave(server.id, change).catch(err => setError(errorText(err)))
  }
  /** The form that adds a server: while one is being added, and as the page while there is none. */
  const addServer = () =>
    (selected === 'new' || servers.length === 0) && (
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
    )
  return (
    <div className="memory-page tools-page">
      <div className="conv-head">
        <div>
          <h2>Tools</h2>
          <p className="muted tools-sub">
            What agents can do. Which role has which is on that role’s Tools tab; here, the tool itself.
          </p>
        </div>
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
      <ToolsKey />
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
            {label} {badges[id] && <span className="tools-badge">{badges[id]}</span>}
          </button>
        ))}
      </div>
      {onSwitchTool && (
        <div
          id="tools-panel-builtin"
          role="tabpanel"
          aria-labelledby="tools-tab-builtin"
          className="tools-panel"
          hidden={kind !== 'builtin'}
        >
          <p className="muted provider-note tools-lead">
            KOLONİ’s own tools, grouped as a role’s Tools tab has them: one “by role” is given there; one with a switch,
            switched off here, is given to no agent.{' '}
            <Hint doc={GUIDE.builtInTools}>
              One you switch off is given to no agent, whatever its role lists. Claude Code’s and Codex’s own web tools,
              and Codex’s apps, switch off with them. While Search the web or Web requests is off, a command that
              reaches the internet (curl, git clone, an https address) asks you on a card at every level, Full auto too.
            </Hint>
          </p>
          <BuiltIn tools={builtin} onSwitch={onSwitchTool} />
        </div>
      )}
      <div
        id="tools-panel-servers"
        role="tabpanel"
        aria-labelledby="tools-tab-servers"
        className="tools-panel"
        hidden={kind !== 'servers'}
      >
        <p className="muted provider-note tools-lead">
          Programs that give agents more tools. A new one asks before every call until you trust it.{' '}
          <Hint doc={GUIDE.mcpTrust}>
            <span className="hint-para">
              Programs that give agents more tools (MCP). Each tool asks you before it runs, unless you say otherwise. A
              server you add is watched: every call asks, at every level, until you trust it.
            </span>
            <span className="hint-para">
              <Warning size={13} color="var(--warn)" aria-hidden="true" /> A server runs with your rights on this
              machine.
            </span>
            {NOTES.map(note => (
              <span key={note} className="hint-para">
                {note}
              </span>
            ))}
          </Hint>
        </p>
        {addServer()}
        {servers.length > 0 && (
          <ul className="tools-servers" aria-label="Servers">
            {servers.map((server, at) => {
              const shown = open?.id === server.id
              return (
                <ServerCard
                  key={server.id}
                  server={server}
                  shown={shown}
                  given={rest.roles.filter(role => role.mcp.includes(server.name))}
                  read={reads[server.id]}
                  onOpen={() => setSelected(shown ? '' : server.id)}
                  onSwitch={() => void saveServer(server, { enabled: !server.enabled })}
                  onTrust={() => saveServer(server, { trusted: true })}
                >
                  {/* Keyed by the server and what was saved of it, so a save or a switch reloads the form. */}
                  <ServerEditor
                    key={`${server.id}:${JSON.stringify([server.command, server.env_names])}`}
                    server={server}
                    {...rest}
                    onRead={onRead}
                    onDone={() => {
                      // Deleted (nothing else ends the form): the next row is open and has the focus, not the
                      // page; with none left, the Add button has it.
                      const next = servers[at + 1] ?? servers[at - 1]
                      document.getElementById(next ? `tools-row-${next.id}` : 'tools-add')?.focus()
                      setSelected(next?.id ?? null)
                    }}
                  />
                </ServerCard>
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
        <div
          id="tools-panel-skills"
          role="tabpanel"
          aria-labelledby="tools-tab-skills"
          className="tools-panel"
          hidden={kind !== 'skills'}
        >
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
