/**
 * The conversation's views (slice 39): the files agents wrote, or put before the user with
 * `show`, previewed in the Workspace window (42c) and new there till opened. The list is read from
 * the server, and read again when a change is made or decided or a file is shown (a screenshot of the
 * agent's browser too, slice 51) - at most once
 * a second - and every 2 s while the window is open, for a shown file a command may have changed on disk.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Command, View } from '../api/types'
import { CHANGE_LABEL } from '../changes/changeLabel'
import type { ConvState } from '../state/applyEvent'

/** How a view's state reads: as its change's does (one word for one state), and a file only shown. */
export const STATUS_WORDS: Record<View['status'], string> = {
  proposed: CHANGE_LABEL.proposed[0],
  approved: CHANGE_LABEL.approved[0],
  in_copy: CHANGE_LABEL.in_copy[0],
  applied: CHANGE_LABEL.applied[0],
  shown: 'Shown',
}

export const fileName = (path: string) => path.split('/').at(-1) ?? path

/**
 * A file's key in the Workspace window (42c): its path, by '/' - and on Windows in one case, as the
 * system opens it (`Hello.py` is `hello.py`). shortcut: the browser's system is taken for the
 * server's (KOLONİ answers on loopback only); a folder written in two cases is still two folders.
 */
/** A folder asked for in the Workspace window - opened there, with the folders over it - not a file's key. */
export const FOLDER = 'folder:'
/** K-belge-ciktilari: a file asked for on its preview (an output on the canvas), not on its diff. */
export const PREVIEW_OF = 'preview-of:'

export function keyOf(path: string) {
  const key = path.replaceAll('\\', '/')
  return /Windows/.test(globalThis.navigator?.userAgent ?? '') ? key.toLowerCase() : key
}

/** How a file is previewed, by its name (as the server's `views.KINDS`); null: it is not. */
export function kindOf(path: string): View['kind'] | null {
  if (/\.(drawio\.xml|drawio|dio)$/i.test(path)) return 'drawio'
  const ending = path.split('.').at(-1)?.toLowerCase() ?? ''
  if (['html', 'htm', 'svg', 'md'].includes(ending)) return ending === 'htm' ? 'html' : (ending as View['kind'])
  if (['stl', 'obj', 'gltf', 'glb', '3mf'].includes(ending)) return 'model'
  if (['pdf', 'docx', 'xlsx', 'pptx'].includes(ending)) return ending as View['kind']
  return ['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ending) ? 'image' : null
}

/** A server an agent's command keeps running (slice 42b): its page, live, under Previews. */
export interface Served {
  id: string
  /** Its name in the tree and on its tab: its address's host and port, or its command till it says one. */
  path: string
  kind: 'server'
  command: Command
}
/** What the Workspace window previews: a file an agent wrote or showed, or a server it keeps running. */
export type Item = View | Served

/** The conversation's servers, once started, newest first. */
export const servedOf = (conv: ConvState): Served[] =>
  conv.commands
    .filter(c => c.keep_running && c.started_at !== null)
    .map(c => ({ id: c.id, path: c.preview_url ? new URL(c.preview_url).host : c.command.replaceAll('/', ' '), kind: 'server' as const, command: c }))
    .reverse()

/** What the list is read again for: a change made or decided, a file shown. */
export function viewsStamp(conv: ConvState): string {
  return [
    ...conv.fileChanges.map(f => f.id + f.status),
    ...conv.toolCalls.filter(c => ['show', 'browser_screenshot', 'view_image', 'diagram_image'].includes(c.name)).map(c => c.id + c.status),
    // (R161: what a command made is put there with no call of its own.)
    String(conv.shown),
  ].join(' ')
}

/** Where the frame, the picture or the note is loaded from: anew whenever what is there changed. */
export const srcOf = (view: View) => `${view.url}?v=${view.sha ?? 'none'}-${view.status}`

const AT_MOST = 1000
const POLL = 2000

/**
 * The views of the conversation on screen, its servers first, and which of them are new: come
 * since the list was first read, and not yet opened (`see`). `open`: the window is, and reads it
 * every 2 s.
 */
export function useViews(conv: ConvState | null, open: boolean) {
  const cid = conv?.conversation.id ?? null
  const stamp = conv ? viewsStamp(conv) : ''
  const [read, setRead] = useState<{ cid: string; views: View[]; seen: Set<string> } | null>(null)
  const last = useRef(0)
  const served = conv ? servedOf(conv) : []
  const servedNow = useRef(served)
  const cidNow = useRef(cid)
  useEffect(() => {
    servedNow.current = served
    cidNow.current = cid
  })
  const load = useCallback(async () => {
    if (!cid) return
    last.current = Date.now()
    try {
      const views = await api.get<View[]>(`/conversations/${cid}/views`)
      if (!Array.isArray(views)) return // (not a list: nothing is made of it)
      // (Another conversation opened meanwhile: this late list would replace its first one.)
      if (cidNow.current !== cid) return
      // (What was there when the list was first read is not new.)
      setRead(was => (was?.cid === cid ? { ...was, views } : { cid, views, seen: new Set([...views, ...servedNow.current].map(v => v.id)) }))
    } catch {
      // the list stays as it was; it is read again at the next change
    }
  }, [cid])
  // Another conversation is read at once: what is there as it opens is what is not new.
  useEffect(() => {
    last.current = 0
  }, [cid])
  useEffect(() => {
    if (!cid) return
    const timer = setTimeout(load, Math.max(0, last.current + AT_MOST - Date.now()))
    return () => clearTimeout(timer)
  }, [cid, stamp, load])
  useEffect(() => {
    if (!open || !cid) return
    const timer = setInterval(() => Date.now() - last.current >= AT_MOST && void load(), POLL)
    return () => clearInterval(timer)
  }, [open, cid, load])
  const listed = read?.cid === cid ? read.views : []
  const views: Item[] = [...served, ...listed]
  const fresh = read?.cid === cid ? views.filter(v => !read.seen.has(v.id)).map(v => v.id) : []
  /** These were seen: no longer new. */
  const see = useCallback((ids: string[]) => setRead(was => was && { ...was, seen: new Set([...was.seen, ...ids]) }), [])
  return { views, fresh, see }
}
