import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type Node, type NodeProps, ReactFlowProvider } from '@xyflow/react'
import { expect, test, vi } from 'vitest'
import type { View } from '../api/types'
import { useApp } from '../state/store'
import { agent, convState, run, userMessage } from '../test-fixtures'
import { deriveGraph } from './deriveGraph'
import { foldGraph } from './foldGraph'
import { layoutGraph } from './layout'
import { isOutput } from './outputs'
import type { SharedData } from './sharedColumn'
import { SharedNode } from './SharedNode'
import { ToggleGroup } from './toggleGroup'

// K-belge-ciktilari: what an agent made is a card joined to its box - its count, its first three, the rest unfolded in
// place - and a row opens the Workspace on that file's preview.

const view = (path: string, kind: View['kind'], over: Partial<View> = {}): View => ({
  id: path,
  path,
  kind,
  agent_id: 'r',
  status: 'applied',
  sha: 'abc',
  note: null,
  too_large: false,
  url: `/api/conversations/c/views/${path}/x`,
  at: '2026-11-03T10:00:00Z',
  ...over,
})

const made = [
  view('deck.html', 'html', { note: 'the pitch' }),
  view('report.pdf', 'pdf'),
  view('logo.svg', 'svg'),
  view('chart.png', 'image'),
  view('flow.drawio', 'drawio'),
]
const state = () => convState({ runs: [run('r', 'completed')], agents: [agent('r', 'completed', { name: 'Designer' })], messages: [userMessage('r', 'make a deck')] })

test('a note, the browser’s own screenshots and what no agent made are no outputs', () => {
  expect(made.every(isOutput)).toBe(true)
  expect(isOutput(view('notes.md', 'md'))).toBe(false)
  expect(isOutput(view('.koloni/tmp/browser/shots/a.png', 'image'))).toBe(false)
  expect(isOutput(view('.koloni/tmp/images/r-1/a.png', 'image'))).toBe(true)
  expect(isOutput(view('a.png', 'image', { agent_id: null }))).toBe(false)
})

test('one card an agent, joined to its box, folded to three and unfolded in place', () => {
  const g = deriveGraph(state(), [], [], made)
  const card = g.nodes.find(n => n.id === 'output:r:r')!
  const data = card.data as SharedData
  expect(data.who).toBe('Designer · 5 outputs')
  expect(data.rows.map(r => r.text)).toEqual(['deck.html', 'report.pdf', 'logo.svg', '+2 more outputs'])
  expect(data.rows[0]).toMatchObject({ kind: 'output', what: 'html', path: 'deck.html', title: 'deck.html · the pitch' })
  expect(g.edges.find(e => e.target === card.id)).toMatchObject({ source: 'agent:r', shared: { colour: 'var(--accent)' } })
  // Laid out as the shared cards are: right of the turn, its line from the box.
  const shut = foldGraph(g, {})
  const placed = layoutGraph(shut.nodes, shut.edges)
  expect(placed.positions[card.id]).toBeDefined()
  expect(placed.sizes[card.id].height).toBeGreaterThan(0)
  const open = foldGraph(g, { [card.id]: true })
  expect((open.nodes.find(n => n.id === card.id)!.data as SharedData).rows.map(r => r.text)).toEqual([
    'deck.html',
    'report.pdf',
    'logo.svg',
    'chart.png',
    'flow.drawio',
    'Fewer',
  ])
  // Another agent's, or none made: no card.
  expect(deriveGraph(state(), [], [], [view('a.png', 'image', { agent_id: 'other' })]).nodes.some(n => n.kind === 'shared')).toBe(false)
})

test('a row opens the Workspace on its preview; “+N more” unfolds the card', async () => {
  const toggle = vi.fn()
  const g = deriveGraph(state(), [], [], made)
  render(
    <ReactFlowProvider>
      <ToggleGroup.Provider value={toggle}>
        <SharedNode {...({ id: 'output:r:r', data: g.nodes.find(n => n.id === 'output:r:r')!.data, selected: false } as unknown as NodeProps<Node<SharedData & Record<string, unknown>>>)} />
      </ToggleGroup.Provider>
    </ReactFlowProvider>,
  )
  expect(screen.getByRole('region', { name: 'Designer · 5 outputs: what it made' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Preview report.pdf in the Workspace' }))
  expect(useApp.getState().filesAt.key).toBe('preview-of:report.pdf')
  await userEvent.click(screen.getByRole('button', { name: '+2 more outputs' }))
  expect(toggle).toHaveBeenCalledWith('output:r:r')
})
