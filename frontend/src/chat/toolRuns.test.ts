import { expect, test } from 'vitest'
import type { ToolCall } from '../api/types'
import { assistantMessage, command, fileChange, toolCall, userMessage } from '../test-fixtures'
import { callsByMessage, runHead, toolRuns } from './toolRuns'

const ids = (runs: ToolCall[][]) => runs.map(run => run.map(call => call.id))
const never = () => false

test('calls of one agent in a row are one run, across its steps, and only until it writes', () => {
  // One call a step: each step is a message of its own, empty until the model writes.
  const messages = [
    userMessage('r', 'look around'),
    assistantMessage('m1', 'r', ''),
    assistantMessage('m2', 'r', ''),
    assistantMessage('m3', 'r', 'Two files read. Now the folder.'),
    assistantMessage('m4', 'r', ''),
    assistantMessage('m5', 'r', 'Done.'),
  ]
  const calls = [
    toolCall('1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}', { message_id: 'm1' }),
    toolCall('2', 'r', 'read_file', 'succeeded', '{"path":"b.py"}', { message_id: 'm2' }),
    toolCall('3', 'r', 'list_dir', 'succeeded', '{}', { message_id: 'm3' }),
    toolCall('4', 'r', 'list_dir', 'succeeded', '{"path":"docs"}', { message_id: 'm4' }),
  ]
  // (m3's words come before its call: they end the first run, and its call begins the next.)
  expect(ids(toolRuns(messages, callsByMessage(calls), never))).toEqual([['1', '2'], ['3', '4']])
})

test('a single call is not a run, nor are calls of another turn or another agent run on together', () => {
  const messages = [
    assistantMessage('m1', 'r', ''),
    { ...assistantMessage('m2', 'r', ''), agent_id: 'other' },
    assistantMessage('m3', 's', ''),
  ]
  const calls = [
    toolCall('1', 'r', 'read_file', 'succeeded', '{}', { message_id: 'm1' }),
    toolCall('2', 'r', 'read_file', 'succeeded', '{}', { message_id: 'm2' }),
    toolCall('3', 's', 'read_file', 'succeeded', '{}', { message_id: 'm3' }),
  ]
  expect(toolRuns(messages, callsByMessage(calls), never)).toEqual([])
})

test('a call that stands alone - a card, a row that waits - splits a run, so it is never inside one', () => {
  const messages = [assistantMessage('m', 'r', '')]
  const calls = ['1', '2', '3', '4', '5'].map(id => toolCall(id, 'r', 'read_file', 'succeeded', '{}', { message_id: 'm' }))
  expect(ids(toolRuns(messages, callsByMessage(calls), call => call.id === '3'))).toEqual([['1', '2'], ['4', '5']])
})

test('the head counts what was done by kind, a run of a kind together, whatever came first', () => {
  const calls = [
    toolCall('1', 'r', 'list_dir', 'succeeded'),
    toolCall('2', 'r', 'recall', 'succeeded', '{"query":"bug"}'),
    toolCall('3', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'),
    toolCall('4', 'r', 'read_file', 'succeeded', '{"path":"b.py"}'),
    toolCall('5', 'r', 'list_dir', 'succeeded', '{"path":"docs"}'),
    toolCall('6', 'r', 'run_command', 'succeeded', '{"command":"pytest"}'),
    toolCall('7', 'r', 'edit_file', 'succeeded', '{"path":"a.py"}'),
    toolCall('8', 'r', 'write_file', 'succeeded', '{"path":"b.py"}'),
    toolCall('9', 'r', 'notify', 'succeeded'),
    toolCall('10', 'r', 'search', 'succeeded', '{"pattern":"x"}'),
    toolCall('11', 'r', 'search', 'succeeded', '{"pattern":"y"}'),
  ]
  const head = runHead(calls, {
    commands: [command('c', 'r', { tool_call_id: '6' })],
    fileChanges: [
      fileChange('f1', 'r', { tool_call_id: '7', additions: 10, deletions: 3 }),
      fileChange('f2', 'r', { tool_call_id: '8', additions: 2, deletions: 0, status: 'merged' }),
      // (turned down: none of its lines were made)
      fileChange('f3', 'r', { tool_call_id: '8', additions: 50, deletions: 50, status: 'rejected' }),
    ],
  })
  expect(head).toEqual({
    what: 'Read 2 files, listed 2 folders, searched 2 times, recalled 1 memory, ran 1 command, edited 2 files (+12 −3), notify ×1',
    marks: [],
    status: 'succeeded',
  })
})

test('a call that failed, was refused or was cut off is not counted as done but marked by its own number; none done, the run reads as the worst', () => {
  const ok = toolCall('1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}')
  const bad = toolCall('2', 'r', 'read_file', 'failed', '{"path":"gone.py"}')
  const none = { commands: [], fileChanges: [] }
  expect(runHead([ok, bad], none)).toEqual({ what: 'Read 1 file', marks: [['failed', 1]], status: 'succeeded' })
  // Slice 51: the browser's calls are one kind, however many tools they span.
  const browsed = ['browser_open', 'browser_screenshot', 'browser_read'].map((name, at) => toolCall(`b${at}`, 'r', name, 'succeeded'))
  expect(runHead([ok, ...browsed], none).what).toBe('Read 1 file, tried the page in 3 steps')
  expect(runHead([ok, { ...bad, status: 'denied' }], none)).toMatchObject({ marks: [['denied', 1]], status: 'succeeded' })
  expect(runHead([ok, { ...bad, status: 'interrupted' }], none)).toMatchObject({ marks: [['interrupted', 1]], status: 'succeeded' })
  expect(runHead([bad, { ...bad, id: '3', status: 'denied' }], none)).toEqual({ what: '', marks: [['failed', 1], ['denied', 1]], status: 'failed' })
})

test('while it runs, the head says what runs now, and counts only what has ended', () => {
  const head = runHead(
    [
      toolCall('1', 'r', 'read_file', 'succeeded', '{"path":"a.py"}'),
      toolCall('2', 'r', 'read_file', 'succeeded', '{"path":"b.py"}'),
      toolCall('3', 'r', 'read_file', 'running', '{"path":"cart.py"}'),
      toolCall('4', 'r', 'list_dir', 'pending'),
    ],
    { commands: [], fileChanges: [] },
  )
  expect(head).toEqual({ what: 'Read 2 files · now: read_file cart.py', marks: [], status: 'running' })
})
