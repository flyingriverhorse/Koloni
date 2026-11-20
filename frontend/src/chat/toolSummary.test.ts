import { expect, test } from 'vitest'
import type { ToolCall } from '../api/types'
import { toolCall } from '../test-fixtures'
import { toolName, toolSummary } from './toolSummary'

const tc = (name: string, args: string) => toolCall('1', 'r', name, 'succeeded', args)

test('summaries name the target and survive bad arguments', () => {
  expect(toolSummary(tc('read_file', '{"path":"src/a.py"}'))).toBe('read_file src/a.py')
  expect(toolSummary(tc('search', '{"pattern":"TODO"}'))).toBe('search "TODO"')
  expect(toolSummary(tc('list_dir', '{}'))).toBe('list_dir .')
  expect(toolSummary(tc('list_dir', '{"path":"src"}'))).toBe('list_dir src')
  expect(toolSummary(tc('edit_file', '{oops'))).toBe('edit_file')
  expect(toolSummary(tc('read_file', '[1]'))).toBe('read_file')
  expect(toolSummary(tc('read_file', '{"path":5}'))).toBe('read_file')
})

test('agent tools name the role they are about', () => {
  expect(toolSummary({ name: 'spawn_agent', arguments: '{"role":"Reviewer","task":"x"}' })).toBe('spawn_agent Reviewer')
  expect(toolSummary({ name: 'create_role', arguments: '{"name":"Documenter","tools":[]}' })).toBe('create_role Documenter')
})

test('the Lead’s pick of teams says each team and why, on one line (slice 84b)', () => {
  const picks = { teams: [{ team: 'Web app', recipe: 'Feature', why: 'new page' }, { team: 'Docs' }, { why: 'no team' }] }
  expect(toolSummary({ name: 'pick_teams', arguments: JSON.stringify(picks) })).toBe('pick_teams Web app: new page; Docs')
})

test('a question never put to you reads as what it wanted to ask, and that it was not asked', () => {
  const asked = (status: ToolCall['status'], args: unknown, name = 'ask_user') => toolSummary(toolCall('1', 'r', name, status, JSON.stringify(args)))
  // refused (your message waits, Take in's options, a team's lead in its recipe, nobody watching), or failed ("Ready for you", asked a third time)
  expect(asked('denied', { question: '  Which greeting?\nhello or hey', options: ['hello', 'hey'] })).toBe('Wanted to ask: Which greeting? · not asked')
  expect(asked('failed', { question: 'Ready for you: the work' })).toBe('Wanted to ask: Ready for you: the work · not asked')
  expect(asked('denied', { question: 5 })).toBe('Wanted to ask you · not asked')
  // one that was asked, waits or was stopped has its card or its row: named as before
  for (const status of ['running', 'succeeded', 'interrupted'] as const) expect(asked(status, { question: 'Which?' })).toBe('ask_user')
  expect(toolSummary({ name: 'ask_user', arguments: '{"question":"Which?"}' })).toBe('ask_user')
  // Codex's own way to ask, declined natively (what its request holds is not measured: not read)
  expect(asked('denied', { questions: [{ question: 'Strict?' }] }, 'codex__item_tool_requestUserInput')).toBe('Wanted to ask you with its own tool · not asked')
})

test('a deletion names the file', () => {
  expect(toolSummary({ name: 'delete_file', arguments: '{"path":"old.txt"}' })).toBe('delete_file old.txt')
})

test('a tool of an MCP server the user connected is shown as server · tool', () => {
  expect(toolName({ name: 'rea__analyze_binary' })).toBe('rea · analyze_binary')
  expect(toolSummary(tc('rea__analyze_binary', '{"path":"a.exe"}'))).toBe('rea · analyze_binary a.exe')
  expect(toolSummary(tc('rea__scan__all', '{oops'))).toBe('rea · scan__all')
  // a CLI's own tool has a name of the CLI's making, and KOLONİ's own tools have no server
  expect(toolName({ name: 'claude__Read', origin: 'cli' })).toBe('claude__Read')
  expect(toolName({ name: 'read_file' })).toBe('read_file')
  expect(toolName({ name: 'Not_A_Server__tool' })).toBe('Not_A_Server__tool')
})

test('what the agent did in its browser reads in words (slice 51)', () => {
  expect(toolSummary(tc('browser_open', '{"url":"http://127.0.0.1:5173/"}'))).toBe('opened http://127.0.0.1:5173/')
  expect(toolSummary(tc('browser_click', '{"text":"Start"}'))).toBe('clicked Start')
  expect(toolSummary(tc('browser_click', '{"selector":"#go"}'))).toBe('clicked #go')
  expect(toolSummary(tc('browser_click', '{"x":10,"y":20}'))).toBe('clicked at 10, 20')
  expect(toolSummary(tc('browser_type', '{"selector":"#name","text":"x"}'))).toBe('typed into #name')
  expect(toolSummary(tc('browser_type', '{"text":"x"}'))).toBe('typed')
  expect(toolSummary(tc('browser_key', '{"key":"Enter"}'))).toBe('pressed Enter')
  expect(toolSummary(tc('browser_scroll', '{"dy":300}'))).toBe('scrolled down 300')
  expect(toolSummary(tc('browser_scroll', '{"dy":-80}'))).toBe('scrolled up 80')
  expect(toolSummary(tc('browser_read', '{}'))).toBe('read the page')
  expect(toolSummary(tc('browser_screenshot', '{}'))).toBe('took a screenshot')
  expect(toolSummary(tc('browser_console', '{}'))).toBe('read the console')
})

test('the rest of the tools by their target, and a tool whose target is not as expected by what it has', () => {
  const said = (name: string, args: unknown) => toolSummary(tc(name, JSON.stringify(args)))
  expect(said('message_agent', { to: 'Coder', text: 'x' })).toBe('message_agent Coder')
  expect(said('recall', { query: 'tax' })).toBe('recall "tax"')
  expect(said('web_search', { query: 'vat rates' })).toBe('web_search "vat rates"')
  expect(said('http_request', { url: 'https://x.test/a', method: 'post' })).toBe('http_request POST https://x.test/a')
  expect(said('http_request', { url: 'https://x.test/a' })).toBe('http_request https://x.test/a')
  expect(said('notify', { message: 'done' })).toBe('notify "done"')
  expect(said('remember', { about: 'the tax rule', text: 'x' })).toBe('remember the tax rule')
  expect(said('remember', { about: '', path: 'a.md' })).toBe('remember')
  expect(said('remember', {})).toBe('remember')
  expect(said('pick_teams', { teams: [null, { team: 5 }, { team: 'Docs', why: 3 }] })).toBe('pick_teams Docs')
  expect(said('pick_teams', { teams: 'all', path: 'x' })).toBe('pick_teams x')
  // In its browser, with nothing said of where.
  expect(said('browser_open', {})).toBe('opened a page')
  expect(said('browser_click', {})).toBe('clicked')
  expect(said('browser_click', { x: 1 })).toBe('clicked')
  expect(said('browser_click', { text: 'Go', selector: '#go' })).toBe('clicked Go')
  expect(said('browser_key', {})).toBe('pressed a key')
  expect(said('browser_scroll', {})).toBe('scrolled')
  expect(said('browser_scroll', { dy: 0 })).toBe('scrolled up 0')
  expect(said('browser_read', { path: 'x' })).toBe('read the page')
  // Its target not a string: by its path where it has one, else by its name alone.
  for (const [name, args] of [['search', { pattern: 1 }], ['spawn_agent', { role: 1 }], ['message_agent', {}], ['create_role', {}], ['recall', {}], ['web_search', {}], ['http_request', { method: 'GET' }], ['notify', {}]] as const) {
    expect(said(name, args)).toBe(name)
    expect(said(name, { ...args, path: 'p.txt' })).toBe(`${name} p.txt`)
  }
  expect(said('list_dir', { path: null })).toBe('list_dir')
  expect(toolSummary(tc('read_file', ''))).toBe('read_file')
  expect(toolSummary(tc('read_file', 'null'))).toBe('read_file')
  expect(toolSummary(tc('list_dir', '"x"'))).toBe('list_dir')
})
