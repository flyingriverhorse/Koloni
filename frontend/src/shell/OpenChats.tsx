import { Plus, X } from '@phosphor-icons/react'
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { WAITS } from '../agents/agentStatus'
import type { Board, FolderBrowse, ListedConversation, Project } from '../api/types'
import { FolderBrowser } from './FolderBrowser'
import { FolderChoices } from './FolderButton'
import { ADD_W, closing, split, standingOfTab, tabOf } from './openTabs'
import { usePanel } from './usePanel'

interface Props {
  /** The tabs in their order, of folders that are still there (openTabs.ts `kept`): a project's id, or 'none'. */
  tabs: string[]
  conversations: ListedConversation[]
  projects: Project[]
  /** How every folder's chats stand, as last read: each tab's dot. */
  board: Board | null
  /** The open chat's tab. */
  openTab: string | null
  /** Go to a project: its chat opened last, else its newest, else a new one in it. */
  onOpen: (tab: string) => void
  /** Close its tab; no chat goes. */
  onClose: (tab: string) => void
  /** A folder of the disk made a project. Throws ApiError with why not. */
  onOpenFolder: (path: string) => Promise<Project>
  onBrowse: (path: string | null) => Promise<FolderBrowse>
}

/**
 * The tabs over the canvas, one per project (slice 86e; 86d's were one per chat): its folder's name and a dot for how
 * its chats stand; those with no room in a "+N" list, and "+" to go to another folder.
 */
export function OpenChats({ tabs, conversations, projects, board, openTab, onOpen, onClose, onOpenFolder, onBrowse }: Props) {
  const row = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(Infinity)
  const any = tabs.length > 0
  useLayoutEffect(() => {
    const at = row.current
    if (!at || typeof ResizeObserver === 'undefined') return
    const watch = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    watch.observe(at)
    return () => watch.disconnect()
  }, [any])
  const { open, setOpen, close, button, panel } = usePanel()
  const { open: adding, setOpen: setAdding, close: closeAdding, button: addButton, panel: addPanel } = usePanel()
  // Where the folder browser opened (false: it is closed).
  const [browsing, setBrowsing] = useState<string | null | false>(false)
  // Closed, the browser gives the focus back to "+".
  const browsed = useRef(false)
  useEffect(() => {
    if (browsing === false && browsed.current) addButton.current?.focus()
    browsed.current = browsing !== false
  }, [browsing, addButton])
  // (The last tab closed leaves its chat open, and "+" with it.)
  if (tabs.length === 0 && openTab === null) return null

  const { shown, more } = split(tabs, openTab, width - ADD_W)
  const about = (tab: string) => {
    const name = tab === 'none' ? 'No folder' : (projects.find(p => p.id === tab)?.name ?? 'A folder')
    const [said, color] = standingOfTab(tab, conversations, board)
    return { name, waits: said === WAITS, color, label: [name, said].filter(Boolean).join(', ') }
  }
  const look = (tab: string) => {
    const { name, color } = about(tab)
    return (
      <>
        <span className="open-chat-dot" style={{ background: color }} aria-hidden />
        <span className="open-chat-title">{name}</span>
      </>
    )
  }
  // The one reached by Tab: the open one's, else the first.
  const first = openTab && shown.includes(openTab) ? openTab : shown[0]
  function closeTab(tab: string) {
    onClose(tab)
    // (the focus stays among the tabs: on the neighbour that opens in its place, else on the open one)
    const next = closing(shown, tab, openTab).next ?? openTab
    requestAnimationFrame(() => list.current?.querySelector<HTMLElement>(`[data-tab="${next}"]`)?.focus())
  }
  // Arrows, Home and End move the focus only; Enter opens (each opening reads a chat and draws its canvas anew).
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const all = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]'))
    const at = all.indexOf(event.target as HTMLElement)
    if (at < 0) return
    if (event.key === 'Delete') return closeTab(shown[at])
    const to = ({ ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: all.length - 1 } as Record<string, number>)[event.key]
    if (to === undefined) return
    event.preventDefault()
    all[(to + all.length) % all.length].focus()
  }
  return (
    <div ref={row} className="open-chats">
      <div ref={list} role="tablist" aria-label="Open projects" onKeyDown={onKeyDown}>
        {shown.map(tab => {
          const { name, waits, label } = about(tab)
          const selected = tab === openTab
          return (
            // (A tab and its ×, side by side: a button inside a button is not one.)
            <div key={tab} role="presentation" className={`open-chat${selected ? ' open-chat-open' : ''}${waits ? ' open-chat-waits' : ''}`}>
              <button
                type="button"
                role="tab"
                aria-selected={selected}
                aria-label={label}
                aria-keyshortcuts="Delete"
                data-tab={tab}
                tabIndex={tab === first ? 0 : -1}
                className="open-chat-tab"
                title={`${label} - Delete closes the tab (no chat goes)`}
                onClick={() => selected || onOpen(tab)}
              >
                {look(tab)}
              </button>
              <button type="button" className="open-chat-close" aria-label={`Close ${name}`} title="Close the tab (no chat goes)" tabIndex={tab === first ? 0 : -1} onClick={() => closeTab(tab)}>
                <X size={10} />
              </button>
            </div>
          )
        })}
      </div>
      {more.length > 0 && (
        <button
          ref={button}
          type="button"
          className={`btn btn-small open-chats-more${more.some(tab => about(tab).waits) ? ' open-chat-waits' : ''}`}
          aria-expanded={open}
          aria-label={`${more.length} more open projects`}
          onClick={() => (open ? close() : setOpen(true))}
        >
          +{more.length}
        </button>
      )}
      <button
        ref={addButton}
        type="button"
        className="icon-btn open-chats-add"
        aria-expanded={adding}
        aria-label="Go to another folder"
        title="Go to another folder: its tab"
        onClick={() => (adding ? closeAdding() : setAdding(true))}
      >
        <Plus size={14} />
      </button>
      {open && more.length > 0 && (
        <div ref={panel} tabIndex={-1} className="allow-list-panel" role="dialog" aria-label="More open projects">
          <ul className="open-chats-list">
            {more.map(tab => (
              <li key={tab} className={`open-chat${about(tab).waits ? ' open-chat-waits' : ''}`}>
                <button
                  type="button"
                  className="open-chat-tab"
                  aria-label={about(tab).label}
                  onClick={() => {
                    close()
                    onOpen(tab)
                  }}
                >
                  {look(tab)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {adding && (
        <div ref={addPanel} tabIndex={-1} className="allow-list-panel folder-panel" role="dialog" aria-label="Go to another folder">
          <FolderChoices
            projects={projects}
            conversations={conversations}
            except={openTab ?? undefined}
            onPick={to => {
              closeAdding()
              onOpen(tabOf(to?.id ?? null))
            }}
            onBrowse={start => {
              closeAdding()
              setBrowsing(start)
            }}
          />
        </div>
      )}
      {browsing !== false && (
        <FolderBrowser
          start={browsing}
          onBrowse={onBrowse}
          onCancel={() => setBrowsing(false)}
          onOpen={async path => {
            const to = await onOpenFolder(path)
            setBrowsing(false)
            onOpen(to.id)
          }}
        />
      )}
    </div>
  )
}
