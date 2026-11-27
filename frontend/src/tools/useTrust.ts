import { useState } from 'react'
import { errorText } from '../api/client'
import type { McpRead, McpServer, McpServerChange } from '../api/types'
import { mergedRead } from './cells'
import type { Props } from './ToolsPage'

/**
 * What the Servers tab keeps of the trust it shows (0.1.10): the readings on this page that took a server's trust back
 * (each later reading of it merged in, list by list, until it is trusted again), and the servers at work - a reading of
 * their tools, a save from their editor -, whose Trust waits so that nothing not seen yet is trusted.
 * shortcut: a reading that took trust back is known only from its answer (no field says it): the page keeps it until
 * you leave it, and opened anew such a server shows as watched. Keep it on the server if that is seen to matter.
 */
export function useTrust(
  servers: McpServer[],
  { onRead, onSave }: Pick<Props, 'onRead' | 'onSave'>,
  setError: (error: string | null) => void,
) {
  const [reads, setReads] = useState<Record<string, McpRead>>({})
  // How many jobs each server has at work: a count, as two saves of one server may overlap.
  const [working, setWorking] = useState<Record<string, number>>({})
  const at = (id: string, by: number) => setWorking(was => ({ ...was, [id]: (was[id] ?? 0) + by }))
  const busyWith = <T>(id: string, job: () => Promise<T>) => {
    at(id, 1)
    return job().finally(() => at(id, -1))
  }
  const read: Props['onRead'] = (serverId, osv, inProject) =>
    busyWith(serverId, async () => {
      const was = servers.find(server => server.id === serverId)?.trusted
      const got = await (inProject ? onRead(serverId, osv, inProject) : onRead(serverId, osv))
      // (Asked first, nothing was read: nothing to keep.)
      if (!got.in_project && !got.server.trusted)
        setReads(kept => (was || kept[serverId] ? { ...kept, [serverId]: mergedRead(kept[serverId], got) } : kept))
      return got
    })
  const save = (serverId: string, change: McpServerChange) => busyWith(serverId, () => onSave(serverId, change))
  /** Trusted again: the reading kept is spent - trust taken back later (another command, say) is not its. */
  const trust = (server: McpServer) => {
    setError(null)
    return busyWith(server.id, () => onSave(server.id, { trusted: true })).then(
      () => setReads(kept => Object.fromEntries(Object.entries(kept).filter(([id]) => id !== server.id))),
      err => setError(errorText(err)),
    )
  }
  return { reads, busy: (id: string) => (working[id] ?? 0) > 0, read, save, trust }
}
