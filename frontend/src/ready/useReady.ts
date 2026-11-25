import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { Away, Waiting } from '../api/types'
import { useApp } from '../state/store'
import { readyItems } from './ready'

/** Each night's Waiting for you as the store last held the night, read once: the pill, the rail, the panel, the page and
 *  the chat's line share one read of it (the store reads the night again on each decision of it: a new object). */
const asked = new WeakMap<Away, Promise<Waiting[]>>()

/** What the project's night parked for you (§10): its rows, read again with the night; none of a plan or of no night. */
function useParked(away: Away | null): Waiting[] {
  const [found, setFound] = useState<{ id: string | null; rows: Waiting[] }>({ id: null, rows: [] })
  useEffect(() => {
    if (!away || away.status === 'planned') return
    let live = true
    let rows = asked.get(away)
    if (!rows) {
      rows = api.get<Waiting[]>(`/away/${away.id}/waiting`).then(
        read => (Array.isArray(read) ? read : []),
        () => [],
      )
      asked.set(away, rows)
    }
    void rows.then(read => live && setFound({ id: away.id, rows: read }))
    return () => {
      live = false
    }
  }, [away])
  // (Read again: the rows before stay meanwhile - of this night alone.)
  return away && away.status !== 'planned' && found.id === away.id ? found.rows : NONE
}

const NONE: Waiting[] = []

/** Ready for you's rows, from what the store holds: one list for the pill, the rail, the panel, the page and the chat's line. */
export function useReady() {
  const conv = useApp(s => s.conv)
  const chats = useApp(s => s.readyChats)
  const projectId = useApp(s => s.projectId)
  const backlog = useApp(s => s.backlog)
  const memory = useApp(s => s.memory)
  const away = useApp(s => s.away)
  const parked = useParked(away)
  return useMemo(
    () => readyItems({ conv, chats, projectId, backlog, memory, away, parked }),
    [conv, chats, projectId, backlog, memory, away, parked],
  )
}
