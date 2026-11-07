import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Run, View } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { fileName, viewsStamp } from '../views/views'
import type { AgentData, GraphEdge, GraphNode } from './deriveGraph'
import type { SharedData, SharedRow } from './sharedColumn'

/** K-belge-ciktilari: the kinds of view that read as something an agent made - not a note (.md), written all the time. */
const MADE: ReadonlySet<View['kind']> = new Set(['html', 'svg', 'image', 'pdf', 'docx', 'xlsx', 'pptx', 'model', 'drawio'])
/** An output card shows so many, folded; the rest behind "+N more". */
export const FOLDED = 3

/** What the agents made: the conversation's views (`app.views`) of a made kind - not the agent's own browser's screenshots, its looks. */
export const isOutput = (view: View) => view.agent_id !== null && MADE.has(view.kind) && !view.path.startsWith('.koloni/tmp/browser/')

/**
 * The conversation's outputs, read again as the Workspace's list is (`useViews`): when a change is made or decided, or a file shown.
 * shortcut: a second reader of the same list, beside the chat's; share one if the two GETs a change are felt.
 */
export function useOutputs(state: ConvState | null): View[] {
  const cid = state?.conversation.id ?? null
  const folder = Boolean(state?.conversation.project_id)
  const stamp = state ? viewsStamp(state) : ''
  const [read, setRead] = useState<{ cid: string; views: View[] } | null>(null)
  useEffect(() => {
    if (!cid || !folder) return // (a chat with no folder has no file to show)
    let live = true
    api
      .get<View[]>(`/conversations/${cid}/views`)
      .then(views => live && Array.isArray(views) && setRead({ cid, views: views.filter(isOutput) }))
      .catch(() => {}) // (as it was; read again at the next change)
    return () => {
      live = false
    }
  }, [cid, folder, stamp])
  return read?.cid === cid ? read.views : NONE
}

// (One empty list: a new one each time would be a new graph each time.)
const NONE: View[] = []

/**
 * Each agent of the turn that made something: one card, joined to its box, with its count and its first outputs (newest first),
 * the rest behind "+N more" - unfolded in place (`foldGraph`). A row opens the Workspace on its preview.
 */
export function outputCards(state: ConvState, run: Run, nodes: GraphNode[], outputs: View[]): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const added: GraphNode[] = []
  const lines: GraphEdge[] = []
  for (const node of nodes.filter(n => n.runId === run.id && n.kind === 'agent')) {
    const made = outputs.filter(v => v.agent_id === node.agentId)
    if (!made.length) continue
    const rows: SharedRow[] = made.map(v => ({ kind: 'output', text: fileName(v.path), path: v.path, what: v.kind, title: v.note ? `${v.path} · ${v.note}` : v.path }))
    const id = `output:${run.id}:${node.agentId}`
    const data: SharedData = {
      who: `${(node.data as AgentData).name} · ${made.length} output${made.length === 1 ? '' : 's'}`,
      colour: 'var(--accent)',
      projectId: state.conversation.project_id,
      runId: run.id,
      rows: rows.length > FOLDED ? [...rows.slice(0, FOLDED), { kind: 'more', text: `+${rows.length - FOLDED} more output${rows.length - FOLDED === 1 ? '' : 's'}` }] : rows,
      ...(rows.length > FOLDED && { all: [...rows, { kind: 'more' as const, text: 'Fewer' }] }),
    }
    added.push({ id, kind: 'shared', runId: run.id, refId: run.id, data })
    lines.push({ id: `shared:${id}`, source: node.id, target: id, active: false, shared: { colour: 'var(--accent)' } })
  }
  return { nodes: added, edges: lines }
}
