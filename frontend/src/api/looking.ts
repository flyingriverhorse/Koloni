import { useEffect } from 'react'
import { api } from './client'

/**
 * herdr's rule (28 Nov 2026): a desktop notice is shown only where nobody looks at the chat. This page says, for the
 * chat it has open, whether it is on screen now: its view shown (not another page of KOLONİ's over it), its tab seen,
 * its window not elsewhere - as its event stream opens (`openEvents`), and again on each change.
 */

/** This page's own id, for as long as it is open: its stream and its word go together. */
export const CLIENT = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

/** The chat shown on screen now, if any (`useLooking`). */
let shown: string | null = null

/** Whether the tab is seen and the window has the focus - a frame of the page's own holding it counts. */
const seen = () => typeof document === 'undefined' || (!document.hidden && document.hasFocus())

/** Whether this page has the chat `conversationId` on screen now. */
export const lookingAt = (conversationId: string) => shown === conversationId && seen()

function tell(conversationId: string, looking: boolean) {
  void api.post(`/conversations/${conversationId}/looking`, { client: CLIENT, looking }).catch(() => {})
}

/** As the chat's stream opens: said again, the server's own record of it is new. */
export function streamOpened(conversationId: string) {
  if (shown === conversationId) tell(conversationId, seen())
}

/** Says whether the chat shown (`conversationId`; null: none, another page is) is looked at, on each change. */
export function useLooking(conversationId: string | null) {
  useEffect(() => {
    shown = conversationId
    if (!conversationId) return
    let last: boolean | null = null
    const say = () => {
      const now = lookingAt(conversationId)
      if (now !== last) tell(conversationId, (last = now))
    }
    // (A blur may be the focus going into a frame of the page - the Workspace's preview: looked at again after it.)
    const later = () => setTimeout(say, 0)
    say()
    document.addEventListener('visibilitychange', say)
    window.addEventListener('focus', say)
    window.addEventListener('blur', later)
    return () => {
      document.removeEventListener('visibilitychange', say)
      window.removeEventListener('focus', say)
      window.removeEventListener('blur', later)
      if (shown === conversationId) shown = null
      if (last) tell(conversationId, false)
    }
  }, [conversationId])
}
