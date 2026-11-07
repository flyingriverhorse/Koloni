import { Handle, type Node, type NodeProps, Position } from '@xyflow/react'
import { type CSSProperties, useContext, useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { SharedFile } from '../api/types'
import { noteId } from '../notes/notesText'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { FOLDER, PREVIEW_OF, keyOf } from '../views/views'
import type { SharedData, SharedRow } from './sharedColumn'
import { NodeActions, ToggleGroup } from './toggleGroup'

// The calls that may write the shared folder: an agent's own file, a request's contract, a room's decision.
// (A CLI's over KOLONİ's MCP server are on record by the same names.)
const WRITES: ReadonlySet<string> = new Set(['write_shared', 'request_work', 'open_room'])

/** K-ortak-klasor: the files of the project's `.koloni/shared/`, read again whenever a call that may write it ends. */
export function useSharedFiles(state: ConvState | null): SharedFile[] {
  const projectId = state?.conversation.project_id ?? null
  const writes = state?.toolCalls.filter(t => WRITES.has(t.name) && t.status !== 'running').length ?? 0
  // (Each project's own: another project's are never shown while its own are read.)
  const [read, setRead] = useState<{ projectId: string; files: SharedFile[] } | null>(null)
  useEffect(() => {
    if (!projectId) return
    let live = true
    api
      .get<SharedFile[]>(`/projects/${projectId}/shared`)
      .then(files => live && setRead({ projectId, files }))
      .catch(() => live && setRead({ projectId, files: [] }))
    return () => {
      live = false
    }
  }, [projectId, writes])
  return read && read.projectId === projectId ? read.files : NONE
}

// (One empty list: a new one each time would be a new graph each time - S2.)
const NONE: SharedFile[] = []

/**
 * What one team (or agent) shared, noted and remembered in the turn, a card by its frame: its files in the shared
 * folder - each read in the Workspace, or taken into the project -, its notes - in full on hover, the Notes tab at it on
 * a click -, and the memory it was given, looked up and wrote to - the Memory page on a click. Its name lights its team.
 * No fold, no close.
 */
export function SharedNode({ id, data }: NodeProps<Node<SharedData & Record<string, unknown>>>) {
  const { light, openMemory } = useContext(NodeActions)
  const toggle = useContext(ToggleGroup)
  // What became of a file's Take in: in the project, or why not.
  const [taken, setTaken] = useState<Record<string, string>>({})
  const take = (path: string) =>
    api
      .post<{ path: string }>(`/projects/${data.projectId}/shared/take`, { path })
      .then(done => setTaken(was => ({ ...was, [path]: `in the project as ${done.path}` })))
      .catch(error => setTaken(was => ({ ...was, [path]: errorText(error) })))
  const row = (one: SharedRow, at: number) => {
    const kind = <span className={`shared-kind shared-kind-${one.kind}`}>{one.kind}</span>
    if (one.kind === 'file' && one.path) {
      const path = one.path
      return (
        <div key={at} className="shared-row">
          {kind}
          {/* Read before it is taken in: in the Workspace window. */}
          <button type="button" className="link-btn nodrag shared-name" title={`Read .koloni/shared/${path} in the Workspace`} onClick={() => useApp.getState().openFiles(keyOf(`.koloni/shared/${path}`))}>
            {path}
          </button>
          {taken[path] ? (
            <span className="muted shared-taken" title={taken[path]}>
              {taken[path]}
            </span>
          ) : (
            data.projectId && (
              <button type="button" className="link-btn nodrag shared-take" aria-label={`Take ${path} into the project`} title={`Take into the project as ${path}`} onClick={() => void take(path)}>
                Take in
              </button>
            )
          )}
        </div>
      )
    }
    if (one.kind === 'notebook' && one.note) {
      const note = one.note
      return (
        <button key={at} type="button" className="shared-row nodrag" title={one.title} aria-label={`${one.text} - open it on the Notes tab`} onClick={() => useApp.getState().showChatTab('Notes', true, noteId(note))}>
          {kind}
          <span className="shared-said">{one.text}</span>
        </button>
      )
    }
    if (one.kind === 'folder')
      return (
        <button key={at} type="button" className="shared-row nodrag shared-all" onClick={() => useApp.getState().openFiles(`${FOLDER}${keyOf('.koloni/shared')}`)}>
          {one.text}
        </button>
      )
    // K-belge-ciktilari: a file an agent made - its preview in the Workspace; "+N more" / "Fewer" unfold its card.
    if (one.kind === 'output' && one.path) {
      const path = one.path
      return (
        <button key={at} type="button" className="shared-row nodrag" title={one.title} aria-label={`Preview ${path} in the Workspace`} onClick={() => useApp.getState().openFiles(`${PREVIEW_OF}${path}`)}>
          <span className="shared-kind shared-kind-output">{one.what}</span>
          <span className="shared-name">{one.text}</span>
        </button>
      )
    }
    if (one.kind === 'more' && data.all)
      return (
        <button key={at} type="button" className="shared-row nodrag shared-more" onClick={() => toggle(id)}>
          {one.text}
        </button>
      )
    if (one.kind === 'memory')
      return (
        <button key={at} type="button" className="shared-row nodrag" title={one.title} aria-label={`Memory: ${one.text} - open the Memory page`} onClick={() => openMemory?.()}>
          {kind}
          <span className="shared-said">{one.text}</span>
        </button>
      )
    return (
      <div key={at} className="shared-row shared-more muted">
        {one.text}
      </div>
    )
  }
  return (
    <section
      className="shared-block"
      style={{ '--k': data.colour } as CSSProperties}
      aria-label={data.rows[0]?.kind === 'output' ? `${data.who}: what it made` : data.who ? `${data.who}: shared, noted, remembered` : data.rows[0]?.kind === 'folder' ? 'All shared files' : 'A request’s contract'}
    >
      {data.who && (
        <button type="button" className="shared-who nodrag" aria-label={`Show ${data.who}’s line`} onClick={() => light?.(id)}>
          {data.who}
        </button>
      )}
      {data.rows.map(row)}
      {/* (Where its line ends, for React Flow: the line itself runs where the layout put it.) */}
      <Handle type="target" position={Position.Left} isConnectable={false} className="shared-handle" />
    </section>
  )
}
