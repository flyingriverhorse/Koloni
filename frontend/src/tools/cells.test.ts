import { expect, test } from 'vitest'
import type { McpRead, McpServer, McpTool } from '../api/types'
import { builtinRuns, mergedRead, serverRuns, takenBack, toolRuns } from './cells'

const tool = (mark: McpTool['mark'], over: Partial<McpTool> = {}): McpTool => ({
  name: mark,
  description: '',
  input_schema: {},
  mark,
  unusable: null,
  chars: 10,
  ...over,
})
const server = (over: Partial<McpServer> = {}): McpServer => ({
  id: 's1',
  name: 'rea',
  command: ['rea'],
  env_names: [],
  tools: [tool('ask'), tool('off')],
  read_at: '2026-11-26T10:00:00Z',
  read_error: null,
  trusted: true,
  enabled: true,
  ...over,
})

test('a tool is green only on a server that is on and trusted, usable and marked to run without asking', () => {
  expect(toolRuns(server(), tool('free'))[0]).toBe('free')
  // a server not trusted yet asks at every level, whatever the mark (outside_mixin: not trusted or mark != free)
  expect(toolRuns(server({ trusted: false }), tool('free'))).toEqual(['ask', 'asks you: the server is not trusted yet'])
  expect(toolRuns(server(), tool('ask'))[0]).toBe('ask')
  expect(toolRuns(server(), tool('off'))[0]).toBe('off')
  expect(toolRuns(server(), tool('free', { unusable: 'stale' }))[0]).toBe('off')
  expect(toolRuns(server({ enabled: false }), tool('free'))[0]).toBe('off')
})

test('a server by the most its tools may do without you; a reading that took its trust back is red-orange', () => {
  expect(serverRuns(server(), false)).toEqual(['ask', 'trusted: each of its tools asks you first'])
  expect(serverRuns(server({ tools: [tool('free')] }), false)[0]).toBe('free')
  expect(serverRuns(server({ tools: [tool('free')], trusted: false }), false)).toEqual([
    'ask',
    'watching: every call asks you',
  ])
  expect(serverRuns(server({ tools: [tool('off')] }), false)[0]).toBe('off')
  expect(serverRuns(server({ read_at: null, tools: [] }), false)[1]).toBe('not read yet: no agent is offered any')
  expect(serverRuns(server({ enabled: false }), false)[1]).toBe('off: given to no agent')
  expect(serverRuns(server({ trusted: false }), true)[0]).toBe('taken')
  const read = (over: Partial<McpRead> = {}): McpRead => ({ server: server(), new: [], changed: [], gone: [], ...over })
  expect(takenBack(server({ trusted: false }), read({ changed: ['scan'] }))).toBe(true)
  // trusted again since, or never read here: not taken back - an untrusted server alone is only watched
  expect(takenBack(server(), read({ changed: ['scan'] }))).toBe(false)
  expect(takenBack(server({ trusted: false }), undefined)).toBe(false)
  // another command or other variables since: watched for themselves, not for what that reading found
  expect(takenBack(server({ trusted: false, command: ['other'] }), read({ changed: ['scan'] }))).toBe(false)
  expect(takenBack(server({ trusted: false, env_names: ['TOKEN'] }), read({ changed: ['scan'] }))).toBe(false)
  // a later reading merged in list by list, nothing named twice; a clean one keeps what was found
  const merged = mergedRead(read({ new: ['a'], changed: ['b'] }), read({ new: ['a', 'c'], gone: ['d'] }))
  expect([merged.new, merged.changed, merged.gone]).toEqual([['a', 'c'], ['b'], ['d']])
  expect(mergedRead(merged, read()).new).toEqual(['a', 'c'])
  expect(mergedRead(undefined, read({ new: ['z'] })).new).toEqual(['z'])
})

test('one of KOLONİ’s own tools: off where switched off, else as its role tile says', () => {
  expect(builtinRuns(true, true)[0]).toBe('ask')
  expect(builtinRuns(false, true)[0]).toBe('free')
  expect(builtinRuns(true, false)[0]).toBe('off')
})
