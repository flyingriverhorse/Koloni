import { expect, test } from 'vitest'
import { convState, toolCall } from '../test-fixtures'
import { innerCalls, isOwnSubAgent, ownSubAgentTask, ownTool, subAgentIds } from './ownWork'

const own = (id: string, name: string, over = {}) => toolCall(id, 'r', name, 'succeeded', '{}', { origin: 'cli', ...over })

test('a tool of the CLI itself and a tool of an MCP server are told apart by the recorded name', () => {
  expect(ownTool('claude__Read')).toEqual({ server: null, tool: 'Read' })
  expect(ownTool('copilot__view')).toEqual({ server: null, tool: 'view' })
  // Claude Code names an MCP server's tool mcp__<server>__<tool>; Codex names the server itself
  expect(ownTool('claude__mcp__sonarqube__scan')).toEqual({ server: 'sonarqube', tool: 'scan' })
  expect(ownTool('sonarqube__scan_all__now')).toEqual({ server: 'sonarqube', tool: 'scan_all__now' })
  expect(ownTool('edit_file')).toEqual({ server: null, tool: 'edit_file' })
})

test('the CLI’s own sub-agent is its Agent tool, unless it was refused', () => {
  expect(isOwnSubAgent(own('1', 'claude__Agent', { status: 'running' }))).toBe(true)
  expect(isOwnSubAgent(own('1', 'claude__Agent', { status: 'denied' }))).toBe(false)
  expect(isOwnSubAgent(own('1', 'claude__Read'))).toBe(false)
  // a tool of KOLONİ's that happened to have the name is not one
  expect(isOwnSubAgent(toolCall('1', 'r', 'claude__Agent', 'running'))).toBe(false)
})

test('its task is the description, or the first line of the prompt', () => {
  const task = (args: string) => ownSubAgentTask(own('1', 'claude__Agent', { arguments: args }))
  expect(task('{"description":"Look around","prompt":"Read hello.py\\nand report"}')).toBe('Look around')
  expect(task('{"prompt":"\\nRead hello.py\\nand report"}')).toBe('Read hello.py')
  expect(task('not json')).toBe('')
})

test('what was done inside a sub-agent is found by the call it hangs off, in order', () => {
  const state = convState({
    toolCalls: [
      own('1', 'claude__Agent'),
      own('3', 'claude__Grep', { parent_call_id: '1' }),
      own('2', 'claude__Read', { parent_call_id: '1' }),
      own('4', 'claude__Read'),
      // an old record, or one whose sub-agent is not on record
      own('5', 'claude__Read', { parent_call_id: 'gone' }),
    ],
  })
  expect(innerCalls(state, '1').map(c => c.id)).toEqual(['2', '3'])
  expect([...subAgentIds(state.toolCalls)]).toEqual(['1'])
})

test('what is shown of a sub-agent’s ending claims no more than the record knows', async () => {
  const { ownSubAgentEnding } = await import('./ownWork')
  expect(ownSubAgentEnding({ status: 'running', result: null })).toBeNull()
  expect(ownSubAgentEnding({ status: 'succeeded', result: 'It prints hi.' })).toEqual({ label: 'Its report', text: 'It prints hi.' })
  expect(ownSubAgentEnding({ status: 'failed', result: 'It broke.' })).toEqual({ label: 'How it ended', text: 'It broke.' })
  expect(ownSubAgentEnding({ status: 'interrupted', result: '' })).toBeNull()
  // a record from before its work was followed: launched is all that is known
  const old = ownSubAgentEnding({ status: 'succeeded', result: 'Async agent launched.' })
  expect(old?.label).toBe('How it ended')
  expect(old?.text).toMatch(/not on record/)
})

test('agy’s own tools are recorded under its name, like the other CLIs’', () => {
  expect(ownTool('agy__view_file')).toEqual({ server: null, tool: 'view_file' })
})
