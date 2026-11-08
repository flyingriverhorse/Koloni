import { useMemo } from 'react'
import { useApp } from '../state/store'
import { readyItems } from './ready'

/** Ready for you's rows, from what the store holds: one list for the pill, the rail, the panel, the page and the chat's line. */
export function useReady() {
  const conv = useApp(s => s.conv)
  const chats = useApp(s => s.readyChats)
  const projectId = useApp(s => s.projectId)
  const backlog = useApp(s => s.backlog)
  const memory = useApp(s => s.memory)
  const away = useApp(s => s.away)
  return useMemo(() => readyItems({ conv, chats, projectId, backlog, memory, away }), [conv, chats, projectId, backlog, memory, away])
}
