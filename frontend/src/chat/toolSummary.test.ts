import { expect, test } from 'vitest'
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
