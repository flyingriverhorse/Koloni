import { AGENT_STATUS, WAITS } from '../agents/agentStatus'
import type { Board, ListedConversation, Project } from '../api/types'
import { standingOf } from '../board/waiting'

/**
 * Where the tabs are remembered, in this browser: one per project (slice 86e) - its id, or 'none' for the chats
 * with no folder. 86d kept a tab per chat here, by the chat's id: `kept` reads each as its chat's folder.
 */
const KEY = 'koloni-open-chats'
/** The chat last opened in each tab's project, by the tab. */
const LAST = 'koloni-tab-chats'

/** The narrowest a tab gets (base.css .open-chat), the "+N" button beside them, and the "+" that is always there. */
export const TAB_MIN = 120
export const MORE_W = 56
export const ADD_W = 36

/** A chat's tab: its folder's, or 'none'. */
export const tabOf = (projectId: string | null) => projectId ?? 'none'

export function remembered(): string[] {
  try {
    const kept: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    return Array.isArray(kept) ? kept.filter(id => typeof id === 'string') : []
  } catch {
    return [] // storage is closed to the page, or what it holds is not a list: no tabs
  }
}

export function remember(tabs: string[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(tabs))
  } catch {
    // storage is closed to the page: remembered while it is open
  }
}

function lastChats(): Record<string, unknown> {
  try {
    const kept: unknown = JSON.parse(localStorage.getItem(LAST) ?? '{}')
    return kept && typeof kept === 'object' ? (kept as Record<string, unknown>) : {}
  } catch {
    return {} // storage is closed to the page, or what it holds is not one: each tab opens its newest chat
  }
}

/** The chat opened last in a tab's project. */
export function rememberChat(tab: string, id: string) {
  try {
    localStorage.setItem(LAST, JSON.stringify({ ...lastChats(), [tab]: id }))
  } catch {
    // storage is closed to the page: each tab opens its newest chat
  }
}

/** The chat a tab opens: the one opened last in its project, while it is there and not archived; else its newest (the list is the latest first); null: none, a new one is made. */
export function chatOf(tab: string, conversations: ListedConversation[]): string | null {
  const its = conversations.filter(c => !c.archived_at && tabOf(c.project_id) === tab)
  const last = lastChats()[tab]
  return (its.find(c => c.id === last) ?? its[0])?.id ?? null
}

/** A project's tab gets its place at the end; one that has a tab keeps its place. */
export const opened = (tabs: string[], tab: string) => (tabs.includes(tab) ? tabs : [...tabs, tab])

/** The tabs of folders that are still there, each once: an 86d tab (a chat's id) is its chat's folder's, and one of a chat gone goes. */
export function kept(tabs: string[], conversations: ListedConversation[], projects: Project[]): string[] {
  const tabFor = (id: string) => {
    const chat = conversations.find(c => c.id === id)
    if (chat) return tabOf(chat.project_id)
    return id === 'none' || projects.some(p => p.id === id) || conversations.some(c => c.project_id === id) ? id : null
  }
  return [...new Set(tabs.map(tabFor).filter(tab => tab !== null))]
}

/** Its tab closed: the tab to open in its place - its right neighbour, else its left - only when it was the open one. */
export function closing(tabs: string[], tab: string, openTab: string | null): { tabs: string[]; next: string | null } {
  const at = tabs.indexOf(tab)
  const left = tabs.filter(other => other !== tab)
  return { tabs: left, next: tab === openTab ? (tabs[at + 1] ?? tabs[at - 1] ?? null) : null }
}

/** A tab's dot, with its word: orange while a chat of its project waits for you, green while one works (§5b: not the amber of work, beside orange), else grey (none said). */
export function standingOfTab(tab: string, conversations: ListedConversation[], board: Board | null): readonly [label: string | null, color: string] {
  const ids = new Set(conversations.filter(c => tabOf(c.project_id) === tab).map(c => c.id))
  const standings = (board?.conversations ?? []).filter(c => ids.has(c.conversation_id)).map(standingOf)
  if (standings.includes('waits')) return [WAITS, AGENT_STATUS.waiting_approval[1]]
  if (standings.includes('working')) return [AGENT_STATUS.running[0], 'var(--ok)']
  return [null, 'var(--muted)']
}

/** The tabs that fit in `width` px and those that go into the "+N" list; the open tab is always one that is shown. */
export function split(tabs: string[], openTab: string | null, width: number): { shown: string[]; more: string[] } {
  const all = Math.floor(width / TAB_MIN)
  const fits = tabs.length <= all ? tabs.length : Math.max(1, Math.floor((width - MORE_W) / TAB_MIN))
  const shown = tabs.slice(0, fits)
  const at = openTab ? tabs.indexOf(openTab) : -1
  // (In the list it takes the last place shown; the one there goes into the list.)
  if (at >= fits) shown[fits - 1] = tabs[at]
  return { shown, more: tabs.filter(id => !shown.includes(id)) }
}
