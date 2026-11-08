import { CaretDown, Plus, X } from '@phosphor-icons/react'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import type { McpServer } from '../api/types'
import type { Pasted } from './paste'
import { PasteServers } from './PasteServers'
import { type EditorProps, ServerEditor } from './ServerEditor'

interface Card {
  title: string
  what: string
  name: string
  command: string[]
  /** Its variables: '' is a value the user types (a token), and it is not added without it. */
  env: Record<string, string>
  /** What its command may download when it starts. */
  downloads?: string
  /** As its registry lists it, checked when the card was written. */
  licence?: string
  source?: string
}

/**
 * Common servers, their commands as their makers document them. A card only fills the form:
 * nothing is started or downloaded until the server is added and its tools are read.
 */
const CARDS: Card[] = [
  {
    title: 'Filesystem',
    what: 'Reads and writes in the folders you name: put a folder’s full path on the last line',
    name: 'filesystem',
    command: ['npx', '-y', '@modelcontextprotocol/server-filesystem', 'FULL-PATH-OF-A-FOLDER'],
    env: {},
    downloads: '@modelcontextprotocol/server-filesystem',
  },
  {
    title: 'GitHub',
    what: 'Issues and pull requests; needs Docker and a GitHub token',
    name: 'github',
    command: ['docker', 'run', '-i', '--rm', '-e', 'GITHUB_PERSONAL_ACCESS_TOKEN', 'ghcr.io/github/github-mcp-server'],
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: '' },
    downloads: 'ghcr.io/github/github-mcp-server',
  },
  {
    title: 'Browser (Playwright)',
    what: 'Opens and tries pages in a browser',
    name: 'playwright',
    command: ['npx', '-y', '@playwright/mcp'],
    env: {},
    downloads: '@playwright/mcp',
  },
  {
    title: 'Fetch',
    what: 'Reads web pages as text',
    name: 'fetch',
    command: ['uvx', 'mcp-server-fetch'],
    env: {},
    downloads: 'mcp-server-fetch',
  },
  // (Pinned: a card starts the version whose licence was checked, 26 October 2026.)
  {
    title: 'REA (reverse engineering)',
    what: 'Looks into programs, apps and web pages without running them; about 170 tools, so turn off the ones you do not need',
    name: 'rea',
    command: ['npx', '-y', 'rea-agents@6.8.0', 'mcp'],
    // Its tools' inputs shorter, so that they cost each model step less (its documented profile).
    env: { REA_MCP_INPUT_SCHEMA_PROFILE: 'compact' },
    downloads: 'rea-agents@6.8.0',
    licence: 'MIT',
    source: 'https://github.com/morluto/rea',
  },
  {
    title: 'Context7',
    what: 'Up-to-date documentation and examples of libraries, for an agent to look up',
    name: 'context7',
    command: ['npx', '-y', '@upstash/context7-mcp@4.4.4'],
    env: {},
    downloads: '@upstash/context7-mcp@4.4.4',
    licence: 'MIT',
    source: 'https://github.com/upstash/context7',
  },
  {
    title: 'Chrome DevTools',
    what: 'Drives and inspects Chrome: pages, the console, network requests and performance',
    name: 'chrome-devtools',
    command: ['npx', '-y', 'chrome-devtools-mcp@1.12.0'],
    env: {},
    downloads: 'chrome-devtools-mcp@1.12.0',
    licence: 'Apache-2.0',
    source: 'https://github.com/ChromeDevTools/chrome-devtools-mcp',
  },
  {
    title: 'Git',
    what: 'Reads and changes a git repository: put the project folder’s full path on the last line',
    name: 'git',
    command: ['uvx', 'mcp-server-git@2026.10.19', '--repository', 'FULL-PATH-OF-THE-PROJECT'],
    env: {},
    downloads: 'mcp-server-git@2026.10.19',
    licence: 'MIT',
    source: 'https://github.com/modelcontextprotocol/servers/tree/main/src/git',
  },
]

const fromCard = (card: Card): Pasted => ({ name: card.name, command: card.command, env: card.env })

/** The common servers: each fills a new server's form. (Your own is "Fill by hand".) */
function Cards({ onPick }: { onPick: (card: Card) => void }) {
  return (
    <section className="tools-cards" aria-label="Start from a common server">
      <h3 className="kicker">Start from a common server</h3>
      <div className="tools-cards-grid">
        {CARDS.map(card => (
          // (The link beside the card's button: a link inside a button is not one.)
          <div key={card.title} className="tools-card-cell">
            <button type="button" className="tools-card" onClick={() => onPick(card)}>
              <span className="tools-card-title">{card.title}</span>
              <span className="muted tools-card-what">{card.what}</span>
              {card.downloads && <span className="muted mono tools-card-note">May download {card.downloads} when it starts</span>}
              {card.licence && <span className="tag mono">{card.licence}</span>}
            </button>
            {card.source && (
              <a className="muted tools-card-note" href={card.source} target="_blank" rel="noreferrer noopener">
                Its source: {card.source.replace('https://', '')}
              </a>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

/** The three ways to add a server, as the Add menu names them. */
const WAYS = [
  ['ready', 'A server, ready-made', 'from KOLONİ’s list'],
  ['paste', 'A server, from its page', 'paste its setup text'],
  ['hand', 'A server, by hand', ''],
] as const
export type Way = (typeof WAYS)[number][0]

/** "＋ Add ▾": a server three ways, or a skill. A menu button: the arrow keys, Home and End move, Esc closes. */
export function AddMenu({ onServer, onSkill }: { onServer: (way: Way) => void; onSkill?: () => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [open])
  // (The item goes with the menu: the focus is the button's until what was picked takes it.)
  const pick = (act: () => void) => {
    setOpen(false)
    button.current?.focus()
    act()
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
      button.current?.focus()
      return
    }
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'))
    const at = items.indexOf(document.activeElement as HTMLElement)
    const to = ({ ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: items.length - 1 } as Record<string, number>)[event.key]
    if (to === undefined) return
    event.preventDefault()
    items[(to + items.length) % items.length].focus()
  }
  return (
    <div
      className="att-menu-box"
      ref={box}
      // (Tabbed out of: closed, as a click elsewhere closes it.)
      onBlur={event => {
        if (!box.current?.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}
    >
      <button
        ref={button}
        id="tools-add"
        type="button"
        className="btn btn-primary btn-small"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? 'tools-add-menu' : undefined}
        onClick={() => setOpen(!open)}
      >
        <Plus size={13} />
        Add
        <CaretDown size={11} aria-hidden />
      </button>
      {open && (
        <div id="tools-add-menu" role="menu" aria-label="Add" className="att-menu tools-add-menu" onKeyDown={onKeyDown}>
          {WAYS.map(([way, label, note], at) => (
            <button key={way} type="button" role="menuitem" tabIndex={-1} autoFocus={at === 0} onClick={() => pick(() => onServer(way))}>
              <span>
                {label}
                {note && <span className="muted"> · {note}</span>}
              </span>
            </button>
          ))}
          {onSkill && (
            <button type="button" role="menuitem" tabIndex={-1} className="tools-add-skill" onClick={() => pick(onSkill)}>
              <span>
                A skill<span className="muted"> · from a folder or GitHub</span>
              </span>
            </button>
          )}
        </div>
      )}
    </div>
  )
}

interface AddProps extends Omit<EditorProps, 'server'> {
  servers: McpServer[]
  way: Way
  /** How many times the form was asked for: each fills it anew. */
  n: number
  /** Chosen from the menu: its heading takes the focus. */
  focus: boolean
  /** None while there is no server: the common servers are the page. */
  onClose?: () => void
  /** By hand, filled from a card or from what was pasted. */
  onFill: (from: Pasted) => void
}

/** A server added one of three ways, none of which runs anything: a common one, one pasted from its page, one by hand. */
export function AddServer({ servers, way, n, focus, onClose, onFill, start, ...rest }: AddProps) {
  const head = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (focus) head.current?.focus()
  }, [n, way, focus])
  return (
    <section className="role-editor tools-editor" aria-labelledby="tools-adding-head">
      <div className="tools-bar">
        <h3 id="tools-adding-head" ref={head} tabIndex={-1} className="kicker">
          {WAYS.find(([id]) => id === way)?.[1]}
        </h3>
        {onClose && (
          <button type="button" className="icon-btn" aria-label="Stop adding a server" onClick={onClose}>
            <X size={13} />
          </button>
        )}
      </div>
      <div hidden={way !== 'ready'}>
        <Cards onPick={card => onFill(fromCard(card))} />
      </div>
      {/* Each is kept while another way is open, so that what was pasted or typed is still there. */}
      <div hidden={way !== 'paste'}>
        <PasteServers servers={servers} onAdd={rest.onAdd} onEdit={onFill} onDone={rest.onDone} />
      </div>
      <div hidden={way !== 'hand'}>
        <ServerEditor key={n} server={null} start={start} {...rest} />
      </div>
    </section>
  )
}
