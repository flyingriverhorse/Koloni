import { render, screen, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { AgentSteps } from '../agents/AgentSteps'
import { EarlierWork } from '../agents/EarlierWork'
import { topicOf } from '../canvas/thread.fixtures'
import { AgentWindow } from '../agents/AgentWindow'
import { Inspector } from '../inspector/Inspector'
import { agent, assistantMessage, convState, openAgentFold, run, toolCall, userMessage } from '../test-fixtures'
import { Markdown } from './Markdown'
import { MessageList } from './MessageList'

// The colouring, watched: done once for a block's text, not again on each render (slice 85a).
const colour = vi.hoisted(() => ({ calls: 0 }))
vi.mock('../changes/highlight', async real => {
  const module = await real<typeof import('../changes/highlight')>()
  return { ...module, colour: (text: string, language: string) => (colour.calls++, module.colour(text, language)) }
})

// Slice 36: an image in a model's or an agent's words is never drawn - drawing it would fetch it.
const REMOTE = 'http://127.0.0.1:9/pixel.png?carried=secret'
const WORDS = `Here it is: ![the chart](${REMOTE}) and ![a dot](data:image/png;base64,iVBORw0KGgo=) <img src="${REMOTE}">`

/** What every surface must show of WORDS: no image at all, each one's alt text, the remote one's address as a link. */
function shownWithoutImages(root: HTMLElement) {
  expect(root.querySelectorAll('img')).toHaveLength(0)
  expect(root).toHaveTextContent('[the chart]')
  expect(root).toHaveTextContent('[a dot]')
  const link = within(root).getByRole('link', { name: REMOTE })
  expect(link).toHaveAttribute('href', REMOTE)
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noreferrer noopener')
  // the data: one has no address to open; raw HTML is text, not an element
  expect(within(root).getAllByRole('link')).toHaveLength(1)
  expect(root).toHaveTextContent('<img src=')
}

test('the shared Markdown draws no image: alt text, and the address of a remote one to open by a click', () => {
  const { container } = render(<Markdown>{WORDS}</Markdown>)
  shownWithoutImages(container)
})

test('in the chat', () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    messages: [userMessage('r', 'show me'), assistantMessage('a', 'r', WORDS)],
  })
  const { container } = render(
    <MessageList state={state} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={async () => {}} onDecideCommand={async () => {}} />,
  )
  shownWithoutImages(container)
})

test('in the raw steps of an agent’s window', async () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    messages: [userMessage('r', 'show me'), assistantMessage('a', 'r', WORDS)],
  })
  render(<AgentWindow state={state} agentId="r" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  shownWithoutImages(await openAgentFold('Every step as recorded'))
})

test('in an agent’s steps', () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed')],
    messages: [assistantMessage('a', 'r', WORDS)],
  })
  const { container } = render(<AgentSteps state={state} agent={state.agents[0]} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  shownWithoutImages(container)
})

test('in an earlier turn’s report', () => {
  const s = topicOf(2)
  const state = { ...s, agents: s.agents.map(a => (a.id === 'coder-t1' ? { ...a, report: WORDS } : a)) }
  // (opened: what it did then is drawn only while it is)
  const { container } = render(<EarlierWork state={state} agentId="coder-t2" open onToggle={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  shownWithoutImages(container)
})

test('in the last words of a CLI’s own sub-agent', () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed', { provider_name: 'Claude Code' })],
    messages: [userMessage('r', 'fix it'), assistantMessage('m1', 'r', 'I will ask a helper.')],
    toolCalls: [
      toolCall('2', 'r', 'claude__Agent', 'succeeded', '{"description":"Look around","prompt":"Look"}', {
        origin: 'cli',
        message_id: 'm1',
        result: WORDS,
      }),
    ],
  })
  render(<Inspector state={state} selectedId="subagent:2" onClose={() => {}} />)
  shownWithoutImages(screen.getByRole('complementary', { name: 'Inspector' }))
})

test('there is no sixth place: Markdown is rendered by the shared component alone', () => {
  const sources = import.meta.glob('../**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
  const rendering = Object.keys(sources).filter(path => /from 'react-markdown'|<img\b|dangerouslySetInnerHTML/.test(sources[path]))
  // (and the Files window's picture: a file of the project or the conversation, at the app's own address -
  // slices 39, 42c; and coloured code, a diff's or a file's: highlight.js's own output, which escapes the text - 42a;
  // and a picture the user attached, at the app's own address, typed by its bytes - 85b;
  // and a browser screenshot of the agent's call, at the app's own address, its name KOLONİ's own - 51;
  // and the rail's mark, the app's own fixed /favicon.svg - K-logo;
  // and the empty canvas's bee where motion is reduced, the app's own fixed /brand/ picture - K-logo)
  expect(rendering.sort()).toEqual(['../canvas/CanvasView.tsx', '../changes/DiffView.tsx', '../shell/Rail.tsx', '../views/FilesWindow.tsx', './Attach.tsx', './Markdown.tsx', './ToolRow.tsx'])
})

test('a fenced block of a known language is coloured once for its text, not again on each render', () => {
  const { container, rerender } = render(<Markdown>{'```python\ndef a():\n    pass\n```'}</Markdown>)
  expect(container.querySelector('pre code.language-python .hljs-keyword')).toHaveTextContent('def')
  const after = colour.calls
  rerender(<Markdown>{'```python\ndef a():\n    pass\n```'}</Markdown>)
  rerender(<Markdown>{'```python\ndef a():\n    pass\n```\nmore words'}</Markdown>)
  expect(colour.calls).toBe(after)
  // (a language not known here stays plain)
  rerender(<Markdown>{'```cobol\nDISPLAY 1.\n```'}</Markdown>)
  expect(container.querySelector('pre code')!.innerHTML).toBe('DISPLAY 1.\n')
})

test('an inline path and command are marked for their colours, bold kept; a fenced block is not (K-sohbet-renk)', () => {
  const { container } = render(
    <Markdown>{'**Done.** In `app/views.py`, ran `pytest tests/test_views.py`; `test_empty_title` failed.\n\n```\nnpm run build\n```\n\n```sh\nnpm run build\n```'}</Markdown>,
  )
  expect(container.querySelector('strong')).toHaveTextContent('Done.')
  expect(container.querySelector('p code.md-path')).toHaveTextContent('app/views.py')
  expect(container.querySelector('p code.md-command')).toHaveTextContent('pytest tests/test_views.py')
  expect(Array.from(container.querySelectorAll('p code')).map(code => code.className)).toEqual(['md-path', 'md-command', ''])
  const fenced = Array.from(container.querySelectorAll('pre code'))
  expect(fenced).toHaveLength(2)
  expect(fenced.map(code => code.className)).toEqual(['', 'language-sh'])
})

test('B-182: a link into an agent’s working copy is the file’s path in the project, as text; any other link stays', () => {
  const copy = 'C:/Users/u/koloni/runtime/copies/coder-1/tree/docs/notes.md'
  const web = 'https://github.com/x/copies/y/tree/main/README.md'
  const { container } = render(<Markdown>{`See [notes](${copy}), [${copy}](${copy}), [the site](https://example.com/a) and [its repo](${web}).`}</Markdown>)
  expect(container).not.toHaveTextContent('runtime/copies')
  const [named, bare] = Array.from(container.querySelectorAll('code.md-path'))
  expect([named.textContent, bare.textContent]).toEqual(['notes', 'docs/notes.md'])
  expect(named).toHaveAttribute('title', 'docs/notes.md, in the project')
  // (a web address with such a path is no copy: it stays a link)
  expect(within(container).getAllByRole('link').map(link => link.getAttribute('href'))).toEqual(['https://example.com/a', web])
  // a file:// one is this machine's: its path in the project too
  const { container: file } = render(<Markdown>{`[notes](file:///${copy})`}</Markdown>)
  expect(file.querySelector('code.md-path')).toHaveTextContent('notes')
  expect(within(file).queryByRole('link')).toBeNull()
})
