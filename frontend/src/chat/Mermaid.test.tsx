import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import source from './Markdown.tsx?raw'
import { assistantMessage, convState, run, userMessage } from '../test-fixtures'
import { Markdown } from './Markdown'
import { MessageList } from './MessageList'

// Slice 68: a ```mermaid block is drawn. mermaid itself is mocked here; the real one draws in e2e/68-mermaid.
const mermaid = vi.hoisted(() => ({ initialize: vi.fn(), render: vi.fn() }))
vi.mock('mermaid', () => ({ default: mermaid }))

const FLOW = 'flowchart LR\n  A --> B\n'
const block = (text: string) => `Here:\n\n\`\`\`mermaid\n${text}\`\`\`\n\nDone.`
// (as mermaid draws it: its own role description, and a node's title deeper in - not the diagram's)
const svg = (inside = '') => `<svg id="d" aria-roledescription="flowchart-v2">${inside}<g><title>A node</title><text>A</text></g></svg>`

beforeEach(() => {
  mermaid.render.mockResolvedValue({ svg: svg(), diagramType: 'flowchart-v2' })
})
afterEach(() => {
  vi.clearAllMocks()
  document.documentElement.classList.remove('dark')
})

test('mermaid is fetched only for a diagram: not imported up front, not asked for by other code', async () => {
  expect(source).not.toMatch(/^import .*'mermaid'/m)
  const { container } = render(<Markdown>{'```python\nprint(1)\n```'}</Markdown>)
  await act(() => new Promise(done => setTimeout(done, 50)))
  expect(mermaid.render).not.toHaveBeenCalled()
  expect(container.querySelector('pre code')).toHaveTextContent('print(1)')
})

test('a closed block is drawn strictly, as an image named for its kind, with its source a press away', async () => {
  const { container } = render(<Markdown>{block(FLOW)}</Markdown>)
  const drawing = await screen.findByRole('img', { name: 'Diagram: flowchart' })
  expect(drawing.tagName.toLowerCase()).toBe('svg')
  expect(drawing).not.toHaveAttribute('aria-roledescription')
  expect(mermaid.initialize).toHaveBeenCalledWith(expect.objectContaining({ startOnLoad: false, securityLevel: 'strict', htmlLabels: false, theme: 'default' }))
  // ...and none of that, nor CSS of its own, may a diagram's own %%{init}%% change
  expect(mermaid.initialize.mock.calls[0][0].secure).toEqual(expect.arrayContaining(['secure', 'securityLevel', 'htmlLabels', 'theme', 'themeVariables', 'themeCSS']))
  expect(mermaid.render).toHaveBeenCalledWith(expect.stringMatching(/^mermaid-[\w-]+$/), FLOW)
  expect(container.querySelector('pre')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Show source' }))
  expect(container.querySelector('pre code')).toHaveTextContent('flowchart LR')
  await userEvent.click(screen.getByRole('button', { name: 'Hide source' }))
  expect(container.querySelector('pre')).toBeNull()
})

test('a diagram given a title is named by it', async () => {
  mermaid.render.mockResolvedValue({ svg: svg('<title>Sign-in steps</title>'), diagramType: 'sequence' })
  render(<Markdown>{block('sequenceDiagram\n  accTitle: Sign-in steps\n  A->>B: hi\n')}</Markdown>)
  expect(await screen.findByRole('img', { name: 'Sign-in steps' })).toBeInTheDocument()
})

test('a broken diagram stays code, with mermaid’s first error line under it', async () => {
  mermaid.render.mockRejectedValue(new Error('Parse error on line 2:\n...A -->\n---^\nExpecting something'))
  const { container } = render(<Markdown>{block('flowchart LR\n  A -->\n')}</Markdown>)
  expect(await screen.findByText('Could not draw this diagram: Parse error on line 2:')).toBeInTheDocument()
  expect(container.querySelector('pre code')).toHaveTextContent('A -->')
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Show source' })).toBeNull()
})

test('a block still being written is not drawn until its fence closes', async () => {
  const { container, rerender } = render(<Markdown>{'Here:\n\n```mermaid\nflowchart LR\n  A --> B'}</Markdown>)
  await act(() => new Promise(done => setTimeout(done, 50)))
  expect(mermaid.render).not.toHaveBeenCalled()
  expect(container.querySelector('pre code')).toHaveTextContent('A --> B')
  rerender(<Markdown>{block(FLOW)}</Markdown>)
  expect(await screen.findByRole('img')).toBeInTheDocument()
  expect(mermaid.render).toHaveBeenCalledTimes(1)
  expect(mermaid.render).toHaveBeenCalledWith(expect.any(String), FLOW)
})

test('in words written to their end - a file, a finished answer - a last block that never closes is drawn (K-68)', async () => {
  render(<Markdown written>{'Here:\n\n```mermaid\nflowchart LR\n  A --> B'}</Markdown>)
  expect(await screen.findByRole('img')).toBeInTheDocument()
  expect(mermaid.render).toHaveBeenCalledWith(expect.any(String), 'flowchart LR\n  A --> B\n')
})

test("an answer's last unclosed diagram is drawn once the answer is complete, not while it streams", async () => {
  const unclosed = 'Here:\n\n```mermaid\nflowchart LR\n  A --> B'
  const list = (status: 'streaming' | 'complete') => (
    <MessageList state={convState({ runs: [run('r', 'running')], messages: [userMessage('r', 'go'), assistantMessage('a', 'r', unclosed, status)] })} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={async () => {}} onDecideCommand={async () => {}} />
  )
  const { rerender } = render(list('streaming'))
  await act(() => new Promise(done => setTimeout(done, 50)))
  expect(mermaid.render).not.toHaveBeenCalled()
  rerender(list('complete'))
  expect(await screen.findByRole('img')).toBeInTheDocument()
})

test('it is drawn anew in the dark theme when the app switches to it', async () => {
  render(<Markdown>{block(FLOW)}</Markdown>)
  await screen.findByRole('img')
  act(() => document.documentElement.classList.add('dark'))
  await waitFor(() => expect(mermaid.render).toHaveBeenCalledTimes(2))
  expect(mermaid.initialize).toHaveBeenLastCalledWith(expect.objectContaining({ theme: 'dark' }))
})

test('switched to dark and straight back, the diagram is still shown: each drawing has an id of its own', async () => {
  // as mermaid does: the element with the id it is given is taken away first
  mermaid.render.mockImplementation(async (id: string) => {
    document.getElementById(id)?.remove()
    return { svg: `<svg id="${id}"><g><text>A</text></g></svg>`, diagramType: 'flowchart-v2' }
  })
  render(<Markdown>{block(FLOW)}</Markdown>)
  await screen.findByRole('img')
  act(() => document.documentElement.classList.add('dark'))
  await waitFor(() => expect(mermaid.render).toHaveBeenCalledTimes(2))
  act(() => document.documentElement.classList.remove('dark'))
  await waitFor(() => expect(mermaid.render).toHaveBeenCalledTimes(3))
  await act(() => new Promise(done => setTimeout(done, 50)))
  expect(screen.getByRole('img', { name: 'Diagram: flowchart' })).toBeInTheDocument()
  expect(new Set(mermaid.render.mock.calls.map(call => call[0])).size).toBe(3)
})

test('only a fence of the opening one’s kind, at least as long, closes a block', async () => {
  const { container } = render(
    <>
      <Markdown>{'````mermaid\nflowchart LR\n  A --> B\n```'}</Markdown>
      <Markdown>{'```mermaid\nflowchart LR\n  A --> B\n~~~'}</Markdown>
    </>,
  )
  await act(() => new Promise(done => setTimeout(done, 50)))
  expect(mermaid.render).not.toHaveBeenCalled()
  expect(container.querySelectorAll('pre code')).toHaveLength(2)
  render(<Markdown>{'~~~mermaid\nflowchart LR\n  A --> B\n~~~~'}</Markdown>)
  expect(await screen.findByRole('img')).toBeInTheDocument()
})

test('a diagram that asks for the ELK layout is laid out with dagre: ELK is not shipped, and the diagram cannot choose', async () => {
  const ELK = '---\nconfig:\n  layout: elk\n---\nflowchart LR\n  A --> B\n'
  render(<Markdown>{block(ELK)}</Markdown>)
  await screen.findByRole('img')
  const config = mermaid.initialize.mock.calls[0][0]
  expect(config).toEqual(expect.objectContaining({ layout: 'dagre', mindmap: { layout: 'cose-bilkent' }, swimlane: { layout: 'swimlane' } }))
  expect(config.secure).toContain('layout')
  expect(JSON.stringify(config)).not.toMatch(/elk/i)
  expect(mermaid.render).toHaveBeenCalledWith(expect.any(String), ELK)
})
