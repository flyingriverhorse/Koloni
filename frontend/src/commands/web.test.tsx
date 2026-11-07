import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { AllowedWeb, Role, WebRequest } from '../api/types'
import { toolSummary, webNote } from '../chat/toolSummary'
import { ToolRow } from '../chat/ToolRow'
import { MessageList } from '../chat/MessageList'
import { agent, assistantMessage, convState, run, toolCall, userMessage } from '../test-fixtures'
import { AllowList } from './AllowList'
import { WebApproval } from './WebApproval'

const asked = (over: Partial<WebRequest> = {}): WebRequest => ({
  id: 'w',
  run_id: 'r',
  agent_id: 'r',
  tool_call_id: 't',
  kind: 'search',
  method: null,
  target: 'python docs',
  host: null,
  headers: [],
  body_chars: null,
  status: 'proposed',
  created_at: 't',
  decided_at: null,
  ...over,
})
const rule = (id: string, kind: AllowedWeb['kind'], host = '', ask_first = false): AllowedWeb => ({ id, conversation_id: 'c', project_id: null, kind, host, ask_first, created_at: 't' })

test('a search is asked about with its query, and each answer is sent', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<WebApproval request={asked()} onDecide={onDecide} />)
  expect(screen.getByText('Search the web?')).toBeInTheDocument()
  expect(screen.getByText('python docs')).toBeInTheDocument()
  expect(screen.getByText('The query leaves this machine.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Search once' }))
  await userEvent.click(screen.getByRole('button', { name: 'Always allow searching in this conversation' }))
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide.mock.calls.map(c => c[0])).toEqual(['once', 'always', 'reject'])
})

test('a request is asked about with its method, address, hidden headers and the size of its body', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const get = asked({ kind: 'http', method: 'GET', target: 'https://example.com/api?x=1', host: 'example.com', headers: ['Authorization', 'X-Key'] })
  const { unmount } = render(<WebApproval request={get} onDecide={onDecide} />)
  expect(screen.getByText('Make this request?')).toBeInTheDocument()
  expect(screen.getByText('GET https://example.com/api?x=1')).toBeInTheDocument()
  expect(screen.getByText('Authorization: ***')).toBeInTheDocument()
  expect(screen.getByText('X-Key: ***')).toBeInTheDocument()
  expect(screen.queryByText(/with a body of/)).not.toBeInTheDocument()
  expect(screen.queryByLabelText('The body it sends')).not.toBeInTheDocument()
  expect(screen.getByText('Anything written in the address or the body is sent as it is, and kept in the record, except values of fields named like a secret.')).toBeInTheDocument()
  // no rule covers a GET that carries headers (or a body) of the agent's own: none is offered
  expect(screen.queryByRole('button', { name: /Always allow/ })).not.toBeInTheDocument()
  expect(screen.getByText('A GET with a body or headers of its own is asked every time.')).toBeInTheDocument()
  unmount()
  const bare = render(<WebApproval request={{ ...get, headers: [] }} onDecide={onDecide} />)
  // what "always" would be for is said: that scheme, host and port
  expect(screen.getByText('“Always” is for GET to https://example.com only: this scheme, host and port.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Always allow GET to example.com' }))
  expect(onDecide).toHaveBeenCalledWith('always')
  bare.unmount()
  const sends = render(<WebApproval request={{ ...get, headers: [], body_chars: 0 }} onDecide={onDecide} />)
  expect(screen.queryByRole('button', { name: /Always allow/ })).not.toBeInTheDocument()
  sends.unmount()
  const plain = render(<WebApproval request={asked({ kind: 'http', method: 'GET', target: 'http://example.com:9999/b', host: 'http://example.com:9999' })} onDecide={onDecide} />)
  expect(screen.getByRole('button', { name: 'Always allow GET to http://example.com:9999' })).toBeInTheDocument()
  expect(screen.getByText('“Always” is for GET to http://example.com:9999 only: this scheme, host and port.')).toBeInTheDocument()
  plain.unmount()
  // only a GET can be allowed for good: anything else is asked every time, and says so
  const call = toolCall('t', 'r', 'http_request', 'running', JSON.stringify({ method: 'POST', url: 'https://example.com/c', headers: { 'X-Key': '***' }, body: 'a=1&token=abc' }))
  render(<WebApproval request={asked({ kind: 'http', method: 'POST', target: 'https://example.com/c', host: 'example.com', headers: ['X-Key'], body_chars: 3 })} call={call} onDecide={onDecide} />)
  // the body that would leave is shown as it is; a header's value never
  expect(screen.getByLabelText('The body it sends')).toHaveTextContent('a=1&token=abc')
  expect(screen.getByText('X-Key: ***')).toBeInTheDocument()
  expect(screen.getByText('with a body of 3 characters')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Send once' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Always allow/ })).not.toBeInTheDocument()
  expect(screen.getByText('A POST is asked every time.')).toBeInTheDocument()
})

test('a decision the server refuses is said on the card', async () => {
  render(<WebApproval request={asked()} onDecide={vi.fn().mockRejectedValue({ detail: 'this request is no longer waiting for a decision' })} />)
  await userEvent.click(screen.getByRole('button', { name: 'Search once' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('no longer waiting')
})

test('the allow list holds what goes out without asking beside the commands, and each can be taken back', async () => {
  const onRemove = vi.fn()
  const onRemoveWeb = vi.fn()
  const rules = [{ id: 'c1', conversation_id: 'c', prefix: 'pytest', danger: '', created_at: 't' }]
  render(<AllowList rules={rules} web={[rule('w1', 'search'), rule('w2', 'host', 'example.com')]} onRemove={onRemove} onRemoveWeb={onRemoveWeb} />)
  await userEvent.click(screen.getByRole('button', { name: '3 rules' }))
  expect(screen.getByText('pytest')).toBeInTheDocument()
  expect(screen.getByText('search the web')).toBeInTheDocument()
  expect(screen.getByText('GET example.com')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Remove rule GET example.com' }))
  await userEvent.click(screen.getByRole('button', { name: 'Remove rule search the web' }))
  expect(onRemoveWeb.mock.calls.map(c => c[0])).toEqual(['w2', 'w1'])
  expect(onRemove).not.toHaveBeenCalled()
})

test('K-tarayici-disari: a site the agent would open is asked about with This time, Allow this site and Reject', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<WebApproval request={asked({ kind: 'page', method: 'GET', target: 'https://example.com/docs', host: 'example.com' })} onDecide={onDecide} />)
  expect(screen.getByText('Open this site?')).toBeInTheDocument()
  expect(screen.getByText('https://example.com/docs')).toBeInTheDocument()
  expect(screen.getByText('example.com')).toBeInTheDocument()
  expect(screen.queryByText(/Always allow GET/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'This time' }))
  await userEvent.click(screen.getByRole('button', { name: 'Allow this site' }))
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide.mock.calls.map(c => c[0])).toEqual(['once', 'always', 'reject'])
})

test('K-tarayici-disari A2: a password, a form or a sign-in on a site is asked once, never always', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const { unmount } = render(<WebApproval request={asked({ kind: 'password', target: 'type into a password field', host: 'site.test' })} onDecide={onDecide} />)
  expect(screen.getByText('Type into a password field?')).toBeInTheDocument()
  expect(screen.getByText('type into a password field')).toBeInTheDocument()
  expect(screen.getByText('site.test')).toHaveClass('tag')  // (the site apart from the page's words)
  expect(screen.queryByRole('button', { name: /Always|Allow this site/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Yes, this once' }))
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecide.mock.calls.map(c => c[0])).toEqual(['once', 'reject'])
  unmount()
  render(<WebApproval request={asked({ kind: 'form', target: "send a form - the page's own words on it: 'Sign in'", host: 'site.test' })} onDecide={onDecide} />)
  expect(screen.getByText('Send this form?')).toBeInTheDocument()
})

test('K-tarayici-disari: a site on the list reads as one and has its Ask first mark there', async () => {
  const onAskFirst = vi.fn()
  render(<AllowList rules={[]} web={[rule('w1', 'host', 'api.example.com'), rule('w2', 'page', 'example.com', true)]} onRemove={vi.fn()} onRemoveWeb={vi.fn()} onAskFirst={onAskFirst} />)
  await userEvent.click(screen.getByRole('button', { name: '2 rules' }))
  expect(screen.getByText('GET api.example.com')).toBeInTheDocument()
  expect(screen.getByText('open example.com')).toBeInTheDocument()
  // (a GET rule has no mark: only a site does)
  const mark = screen.getByRole('checkbox', { name: 'Ask first' })
  expect(mark).toBeChecked()
  await userEvent.click(mark)
  expect(onAskFirst).toHaveBeenCalledWith('w2', false)
})

test('with web rules alone the list is still there', () => {
  const { rerender } = render(<AllowList rules={[]} web={[rule('w1', 'search')]} onRemove={vi.fn()} onRemoveWeb={vi.fn()} />)
  expect(screen.getByRole('button', { name: '1 rule' })).toBeInTheDocument()
  rerender(<AllowList rules={[]} web={[]} onRemove={vi.fn()} onRemoveWeb={vi.fn()} />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test('a host is allowed by hand from the list, which is there for that while it is still empty', async () => {
  const onAllowHost = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce({ detail: 'not reachable from here: localhost is on this machine' })
  render(<AllowList rules={[]} web={[]} onRemove={vi.fn()} onAllowHost={onAllowHost} />)
  await userEvent.click(screen.getByRole('button', { name: '0 rules' }))
  const host = screen.getByLabelText('Allow GET to a host')
  expect(host).toHaveAttribute('placeholder', 'Allow GET to a host…')
  expect(screen.getByRole('button', { name: 'Allow' })).toBeDisabled()
  await userEvent.type(host, ' example.com {Enter}')
  expect(onAllowHost).toHaveBeenCalledWith('example.com')
  expect(host).toHaveValue('')
  // one the server refuses stays written, with the reason
  await userEvent.type(host, 'localhost')
  await userEvent.click(screen.getByRole('button', { name: 'Allow' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('localhost is on this machine')
  expect(host).toHaveValue('localhost')
})

test('the chat asks about a search under its call, and about a sub-agent’s with who asks', async () => {
  const onDecideWeb = vi.fn().mockResolvedValue(undefined)
  const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn(), onDecideWeb }
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'waiting'), agent('r', 'running', { id: 'scout', parent_agent_id: 'r', tool_call_id: '2', role_name: 'Researcher', task: 'look it up', depth: 1 })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [
      toolCall('1', 'r', 'web_search', 'running', '{"query":"python docs"}', { message_id: 'm' }),
      toolCall('2', 'r', 'spawn_agent', 'running', '{"role":"Researcher"}', { message_id: 'm' }),
    ],
    webRequests: [
      asked({ id: 'w1', tool_call_id: '1' }),
      asked({ id: 'w2', agent_id: 'scout', tool_call_id: '9', kind: 'http', method: 'GET', target: 'https://example.com/a', host: 'example.com' }),
      asked({ id: 'w3', tool_call_id: '8', target: 'decided already', status: 'approved' }),
    ],
  })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByText('Researcher asks')).toBeInTheDocument()
  expect(screen.queryByText('decided already')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Search once' }))
  await userEvent.click(screen.getByRole('button', { name: 'Always allow GET to example.com' }))
  expect(onDecideWeb.mock.calls).toEqual([['w1', 'once'], ['w2', 'always']])
})

const SEARCHED ='Web search for "python docs": answered by DuckDuckGo. SearXNG did not answer — DuckDuckGo was used.\n[content from the web]\n1. Python docs'
const FETCHED = 'GET https://example.com/long: HTTP 200, text/html; 500000 characters of text, cut at 200000\n[content from the web]\nTitle'

test('a web call is named by what was asked', () => {
  expect(toolSummary({ name: 'web_search', arguments: '{"query":"python docs"}' })).toBe('web_search "python docs"')
  expect(toolSummary({ name: 'http_request', arguments: '{"method":"get","url":"https://example.com/a","headers":{"A":"***"}}' })).toBe('http_request GET https://example.com/a')
  expect(toolSummary({ name: 'http_request', arguments: '{"unreadable":"***"}' })).toBe('http_request')
  expect(toolSummary({ name: 'notify', arguments: '{"message":"the tests pass"}' })).toBe('notify "the tests pass"')
})

test('a web call says which way answered, and when the search fell back', () => {
  const call = (name: string, result: string | null, status: 'succeeded' | 'failed' = 'succeeded') => toolCall('1', 'r', name, status, '{}', { result })
  expect(webNote(call('web_search', SEARCHED))).toBe('answered by DuckDuckGo. SearXNG did not answer — DuckDuckGo was used.')
  expect(webNote(call('web_search', 'Web search for "q": answered by SearXNG.\n…'))).toBe('answered by SearXNG.')
  expect(webNote(call('http_request', FETCHED))).toBe('HTTP 200, text/html; 500000 characters of text, cut at 200000')
  // what is not known is not said
  expect(webNote(call('web_search', null))).toBeNull()
  expect(webNote(call('web_search', 'error: search could not be made: DuckDuckGo did not answer (HTTP 202)', 'failed'))).toBeNull()
  expect(webNote(call('read_file', SEARCHED))).toBeNull()
})

test('the row of a search shows the way it was answered without being opened', () => {
  render(<ToolRow call={toolCall('1', 'r', 'web_search', 'succeeded', '{"query":"python docs"}', { result: SEARCHED })} />)
  expect(screen.getByText('web_search "python docs"')).toBeInTheDocument()
  expect(screen.getByText('answered by DuckDuckGo. SearXNG did not answer — DuckDuckGo was used.')).toBeInTheDocument()
})

test('B-134: an expert’s search offers no rule for the conversation - its every search is asked', () => {
  render(<WebApproval request={asked()} expert onDecide={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Search once' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Always allow searching in this conversation' })).toBeNull()
  expect(screen.getByText('An expert’s search is asked every time.')).toBeInTheDocument()
})

test('B-134: the chat offers no rule on an expert’s search', () => {
  const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn(), onDecideWeb: vi.fn() }
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'waiting'), agent('r', 'running', { id: 'pay', parent_agent_id: 'r', tool_call_id: '2', role_name: 'Pay expert', task: 'refunds?', depth: 1 })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('2', 'r', 'spawn_agent', 'running', '{"role":"Pay expert"}', { message_id: 'm' })],
    webRequests: [asked({ id: 'w1', agent_id: 'pay', tool_call_id: '9' })],
  })
  const roles = [{ name: 'Pay expert', knows: [{ knowledge_id: 'k', mode: 'full', topic: 'Pay', project_id: null }] }] as unknown as Role[]
  render(<MessageList {...handlers} state={state} roles={roles} />)
  expect(screen.getByRole('button', { name: 'Search once' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Always allow searching in this conversation' })).toBeNull()
})

test('K-bilgi: a role is an expert only where its knowledge is - this project or every project', () => {
  const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn(), onDecideWeb: vi.fn() }
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'waiting'), agent('r', 'running', { id: 'pay', parent_agent_id: 'r', tool_call_id: '2', role_name: 'Pay expert', task: 'refunds?', depth: 1 })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('2', 'r', 'spawn_agent', 'running', '{"role":"Pay expert"}', { message_id: 'm' })],
    webRequests: [asked({ id: 'w1', agent_id: 'pay', tool_call_id: '9' })],
  })
  // (In full in another project only: a plain role here, its search ruled as any.)
  const roles = [{ name: 'Pay expert', knows: [{ knowledge_id: 'k', mode: 'full', topic: 'Pay', project_id: 'elsewhere' }] }] as unknown as Role[]
  render(<MessageList {...handlers} state={state} roles={roles} />)
  expect(screen.getByRole('button', { name: 'Always allow searching in this conversation' })).toBeInTheDocument()
})
