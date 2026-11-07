import { expect, test } from 'vitest'
import type { Attachment } from '../api/types'
import { agent, convState, run, userMessage } from '../test-fixtures'
import { deriveGraph, type AttachmentData } from './deriveGraph'
import { foldGraph } from './foldGraph'
import { FILE_H, layoutGraph, NODE_H, ROW_GAP } from './layout'

function file(id: string, over: Partial<Attachment> = {}): Attachment {
  return {
    id, conversation_id: 'c', message_id: 'u-r', frame_of: null, name: `${id}.ts`, kind: 'text',
    mime: 'text/plain', size: 10, summary: '1 line', given_to: [], shown_to: {}, keep_in_project: false,
    created_at: '2026-10-05T10:00:00Z', ...over,
  }
}

const withFiles = (files: Attachment[]) =>
  convState({
    runs: [run('r')],
    messages: [userMessage('r', 'see these')],
    agents: [agent('r', 'running', { depth: 0 }), agent('k', 'running', { id: 'k', run_id: 'r', parent_agent_id: 'r', depth: 1 })],
    attachments: files,
  })

test('a file of the message is a small node under its request, with a dashed line to whom it was handed', () => {
  const shot = file('shot', { kind: 'image', mime: 'image/png', name: 'shot.png', shown_to: { r: 'shown to sonnet on Claude Code' } })
  const g = deriveGraph(withFiles([file('cart', { given_to: ['k'] }), shot, file('f', { frame_of: 'x' })]))
  const files = g.nodes.filter(n => n.kind === 'attachment')
  expect(files.map(n => (n.data as AttachmentData).name)).toEqual(['cart.ts', 'shot.png']) // (not a frame)
  expect((files[1].data as AttachmentData).label).toBe('PNG')
  // The card says whose model was shown it, as the server recorded it (slice 85c).
  expect((files[1].data as AttachmentData).meta).toBe('image · 10 B · shown to sonnet on Claude Code')
  expect(g.edges.filter(e => e.handed).map(e => [e.source, e.target])).toEqual([['attachment:cart', 'agent:k']])
  const { positions } = layoutGraph(g.nodes, g.edges)
  expect(positions['attachment:cart']).toEqual({ x: 0, y: NODE_H + ROW_GAP })
  expect(positions['attachment:shot'].y).toBe(NODE_H + ROW_GAP + FILE_H + 14)
})

test('more than four fold into one "N files" box, opened by the user', () => {
  const g = deriveGraph(withFiles(Array.from({ length: 6 }, (_, at) => file(`f${at}`, { given_to: ['k'] }))))
  const folded = foldGraph(g, {})
  expect(folded.nodes.filter(n => n.kind === 'files').map(n => (n.data as { summary: string }).summary)).toEqual(['6 files'])
  expect(folded.nodes.some(n => n.kind === 'attachment')).toBe(false)
  expect(folded.edges.some(e => e.handed)).toBe(false)
  const opened = foldGraph(g, { 'files:r': true })
  expect(opened.nodes.filter(n => n.kind === 'attachment')).toHaveLength(6)
  expect(opened.edges.filter(e => e.handed)).toHaveLength(6)
})

test('a message with no files has no file node', () => {
  expect(deriveGraph(withFiles([])).nodes.some(n => n.kind === 'attachment' || n.kind === 'files')).toBe(false)
})
