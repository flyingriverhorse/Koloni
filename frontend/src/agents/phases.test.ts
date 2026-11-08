import { expect, test } from 'vitest'
import type { Message } from '../api/types'
import { agent, assistantMessage, command, convState, fileChange, run, toolCall } from '../test-fixtures'
import { firstSentence, isTest, phaseLine, phasesOf, phaseTone } from './phases'

const said = (id: string, content: string, at = '2026-10-05T10:00:01Z'): Message => ({ ...assistantMessage(id, 'r', content), agent_id: 'a', created_at: at })
const call = (id: string, name: string, args: string, message: string, over = {}) => toolCall(id, 'r', name, 'succeeded', args, { agent_id: 'a', message_id: message, ...over })

// Coder, as in the sample: six reads over two steps, an edit, the tests twice with a fix between, a command it asks for.
const coder = convState({
  runs: [run('r')],
  agents: [agent('r', 'running', { id: 'a', role_name: 'Coder' })],
  messages: [said('m1', 'First I will see how parse() is used. Then the tests.'), said('m2', ''), said('m3', 'Fixing parse.'), said('m4', '')],
  toolCalls: [
    call('1', 'search', '{"pattern":"parse("}', 'm1'),
    call('2', 'read_file', '{"path":"a.py"}', 'm1'),
    call('3', 'claude__Read', '{"file_path":"b.py"}', 'm2', { origin: 'cli' }),
    call('4', 'edit_file', '{"path":"a.py"}', 'm3'),
    call('5', 'run_command', '{}', 'm3'),
    call('6', 'edit_file', '{"path":"a.py"}', 'm4'),
    call('7', 'run_command', '{}', 'm4'),
    call('8', 'run_command', '{}', 'm4'),
  ],
  fileChanges: [
    fileChange('f1', 'r', { agent_id: 'a', tool_call_id: '4', path: 'a.py', additions: 17, deletions: 1 }),
    fileChange('f2', 'r', { agent_id: 'a', tool_call_id: '6', path: 'a.py', additions: 3, deletions: 1 }),
  ],
  commands: [
    command('k1', 'r', { agent_id: 'a', tool_call_id: '5', command: 'python -m pytest -q', exit_code: 1 }),
    command('k2', 'r', { agent_id: 'a', tool_call_id: '7', command: 'python -m pytest -q', exit_code: 0 }),
    command('k3', 'r', { agent_id: 'a', tool_call_id: '8', command: 'python measure.py', status: 'proposed', exit_code: null }),
  ],
})

test('calls of one kind in a row are one phase, words end one and are the next one’s quote, a command that waits is no phase', () => {
  const phases = phasesOf(coder, { id: 'a', report: null, ended_at: null })
  expect(phases.map(p => [p.kind, p.calls.map(c => c.id).join(','), p.said])).toEqual([
    ['read', '1,2,3', 'First I will see how parse() is used.'], // across two steps: no words between
    ['change', '4', 'Fixing parse.'],
    ['command', '5', null],
    ['change', '6', null],
    ['command', '7', null], // (8 waits for the user: the window's last step, with its card)
  ])
  expect(phases.map(p => phaseLine(coder, p))).toEqual([
    { title: 'Looked around', result: 'searched 1 time, read 2 files' },
    { title: 'Changed a.py', result: '+17 −1' },
    { title: 'Ran the tests', result: 'failed (exit 1)' },
    { title: 'Changed a.py', result: '+3 −1' },
    { title: 'Ran the tests', result: 'passed' },
  ])
})

test('several commands, files and tools in a row are counted; a rerun that failed and then passed says so', () => {
  const state = convState({
    ...coder,
    toolCalls: [call('1', 'run_command', '{}', 'm1'), call('2', 'run_command', '{}', 'm1'), call('3', 'edit_file', '{}', 'm2'), call('4', 'write_file', '{}', 'm2'), call('5', 'notify', '{}', 'm3'), call('6', 'notify', '{}', 'm3', { status: 'failed' })],
    commands: [command('k1', 'r', { agent_id: 'a', tool_call_id: '1', command: 'npm test', exit_code: 2 }), command('k2', 'r', { agent_id: 'a', tool_call_id: '2', command: 'npm test', exit_code: 0 })],
    fileChanges: [fileChange('f1', 'r', { agent_id: 'a', tool_call_id: '3', path: 'a.py' }), fileChange('f2', 'r', { agent_id: 'a', tool_call_id: '4', path: 'b.py' })],
  })
  const lines = phasesOf(state, { id: 'a', report: null, ended_at: null }).map(p => phaseLine(state, p))
  expect(lines.map(l => l.title)).toEqual(['Ran the tests', 'Changed 2 files', 'Used notify ×2'])
  expect(lines[0].result).toBe('failed once, then passed')
  expect(lines[2].result).toBe('1 failed')
  const other = convState({ ...state, commands: [command('k1', 'r', { agent_id: 'a', tool_call_id: '1', command: 'ls' }), command('k2', 'r', { agent_id: 'a', tool_call_id: '2', command: 'make', exit_code: 2 })] })
  expect(phaseLine(other, phasesOf(other, { id: 'a', report: null, ended_at: null })[0])).toEqual({ title: 'Ran 2 commands', result: '1 OK, 1 failed' })
})

test('what it was handed, a sub-agent it opened, a talk and its report are phases of their own, named in words', () => {
  const state = convState({
    runs: [run('r')],
    agents: [agent('r', 'completed', { id: 'a', role_name: 'Coder' }), agent('r', 'completed', { id: 'kid', parent_agent_id: 'a', tool_call_id: '2', name: 'Reviewer', depth: 1 })],
    messages: [
      { ...said('h', 'Please look at b.py too'), role: 'agent', from_agent_id: 'kid' },
      said('m1', ''),
      said('m2', 'All done.'),
    ],
    toolCalls: [call('1', 'message_agent', '{"to":"Lead"}', 'm1'), call('2', 'spawn_agent', '{"role":"Reviewer"}', 'm1')],
  })
  const phases = phasesOf(state, { id: 'a', report: 'All done.', ended_at: '2026-10-05T10:05:00Z' })
  expect(phases.map(p => phaseLine(state, p).title)).toEqual(['Got a message from Reviewer', 'Talked to Orchestrator', 'Opened Reviewer', 'Wrote its report'])
  expect(phases[3].at).toBe('2026-10-05T10:05:00Z')
})

test('a running command is "running…"; the tests are known by their runner; a quote is one sentence', () => {
  const state = convState({ ...coder, commands: [command('k1', 'r', { agent_id: 'a', tool_call_id: '5', command: 'go build', status: 'running', exit_code: null })] })
  const phase = phasesOf(state, { id: 'a', report: null, ended_at: null }).find(p => p.kind === 'command')!
  expect(phaseLine(state, phase)).toEqual({ title: 'Ran go build', result: 'running…' })
  expect(['pytest -q', 'npx vitest run', 'npm run test', 'cargo test'].every(isTest)).toBe(true)
  expect(isTest('python measure.py')).toBe(false)
  expect(firstSentence('I will look.\nThen fix it.')).toBe('I will look.')
  expect(firstSentence('x'.repeat(300))).toHaveLength(160)
})

// --- what a group of commands may never hide (review of k-panel-a) --------------------------------------------------

const ranAll = (commands: Parameters<typeof command>[2][], calls = commands.map((_, i) => call(String(i + 1), 'run_command', '{}', 'm1'))) => {
  const state = convState({
    runs: [run('r')],
    agents: [agent('r', 'running', { id: 'a' })],
    messages: [said('m1', '')],
    toolCalls: calls,
    commands: commands.map((over, i) => command(`k${i + 1}`, 'r', { agent_id: 'a', tool_call_id: String(i + 1), ...over })),
  })
  const phases = phasesOf(state, { id: 'a', report: null, ended_at: null })
  return { state, phases, lines: phases.map(p => phaseLine(state, p)), tones: phases.map(p => phaseTone(state, p)) }
}

test('a: a blocked run after a good one is not "then passed": a blocked command keeps its exit 0', () => {
  const { lines, tones } = ranAll([{ command: 'pytest', exit_code: 1 }, { command: 'pytest', status: 'blocked', exit_code: 0 }])
  expect(lines[0].result).toBe('1 failed, 1 blocked by its sandbox')
  expect(tones[0]).toBe('bad')
})

test('b: every command of a group is counted in words, none left out', () => {
  const { lines } = ranAll([
    { command: 'a', exit_code: 0 },
    { command: 'b', status: 'rejected', exit_code: null },
    { command: 'c', status: 'interrupted', exit_code: null, started_at: '2026-10-05T10:00:02Z' },
    { command: 'd', status: 'killed', exit_code: null },
    { command: 'e', exit_code: null },
    { command: 'f', status: 'approved', exit_code: null, started_at: null },
    { command: 'g', status: 'timed_out', exit_code: null },
  ])
  expect(lines[0]).toEqual({ title: 'Ran 7 commands', result: '1 OK, 1 rejected, 1 interrupted, 1 stopped, 1 exit not reported, 1 approved, not started, 1 timed out' })
})

test('c: a command that never ran is not "Ran": rejected, did not start, approved and not started', () => {
  expect(ranAll([{ command: 'rm -rf x', status: 'rejected', exit_code: null }]).lines[0]).toEqual({ title: 'Asked you to run rm -rf x', result: 'rejected' })
  expect(ranAll([{ command: 'nope', status: 'failed_to_start', exit_code: null }]).lines[0]).toEqual({ title: 'Tried to run nope', result: 'did not start' })
  expect(ranAll([{ command: 'pytest', status: 'approved', exit_code: null, started_at: null }]).lines[0]).toEqual({ title: 'About to run pytest', result: 'approved, not started' })
})

test('d: the mark is the whole group’s - a failure anywhere is "bad", a refusal or an interruption never "ok"', () => {
  expect(ranAll([{ command: 'pytest', exit_code: 1 }, { command: 'pytest', exit_code: 0 }]).tones[0]).toBe('bad') // (its line says "failed once, then passed")
  expect(ranAll([{ command: 'b', status: 'rejected', exit_code: null }]).tones[0]).toBe('warn')
  expect(ranAll([{ command: 'c', status: 'interrupted', exit_code: null, started_at: '2026-10-05T10:00:02Z' }]).tones[0]).toBe('warn')
  expect(ranAll([{ command: 'ls', exit_code: 0 }, { command: 'pwd', exit_code: 0 }]).tones[0]).toBe('ok')
  const reads = convState({ ...coder, toolCalls: [call('1', 'read_file', '{}', 'm1', { status: 'failed' }), call('2', 'read_file', '{}', 'm1')] })
  const look = phasesOf(reads, { id: 'a', report: null, ended_at: null })[0]
  expect([phaseTone(reads, look), phaseLine(reads, look).result]).toEqual(['bad', 'read 2 files · 1 failed'])
})

test('e: a run_command refused or failed with no command on record is marked beside the ones that ran', () => {
  const calls = [call('1', 'run_command', '{}', 'm1'), call('2', 'run_command', '{}', 'm1', { status: 'denied' }), call('3', 'run_command', '{}', 'm1', { status: 'failed' })]
  const { lines, tones } = ranAll([{ command: 'ls', exit_code: 0 }], calls)
  expect(lines[0]).toEqual({ title: 'Ran ls', result: 'OK; 1 more command refused, 1 more command failed' })
  expect(tones[0]).toBe('bad')
})

test('f: a command KOLONİ warned of is never folded into a group: a step of its own, with its result', () => {
  const { lines } = ranAll([{ command: 'ls', exit_code: 0 }, { command: 'git push --force', exit_code: 0, danger: 'Overwrites a git remote' }, { command: 'pwd', exit_code: 0 }])
  expect(lines).toEqual([
    { title: 'Ran ls', result: 'OK' },
    { title: 'Ran git push --force', result: 'OK' },
    { title: 'Ran pwd', result: 'OK' },
  ])
})

test('a CLI’s own command that failed - ended with no exit code, its call failed - reads as failed, and its row says so', () => {
  const cli = [call('1', 'run_command', '{}', 'm1', { status: 'failed', origin: 'cli' })]
  const { lines, tones } = ranAll([{ command: 'make', exit_code: null, origin: 'cli' }], cli)
  expect(lines[0]).toEqual({ title: 'Ran make', result: 'failed (its CLI said so)' })
  expect(tones[0]).toBe('bad')
  // one that went, with no exit code said: not known, and not a pass
  const quiet = ranAll([{ command: 'make', exit_code: null, origin: 'cli' }], [call('1', 'run_command', '{}', 'm1', { origin: 'cli' })])
  expect([quiet.lines[0].result, quiet.tones[0]]).toEqual(['exit not reported', 'warn'])
})

test('run_command calls with no command on record are told by what happened to them, never as one that ran', () => {
  const bare = (...statuses: ('denied' | 'failed' | 'pending' | 'interrupted')[]) =>
    ranAll([], statuses.map((status, i) => call(String(i + 1), 'run_command', '{}', 'm1', { status })))
  expect(bare('denied').lines[0]).toEqual({ title: 'Asked to run a command', result: 'refused' })
  expect(bare('failed').lines[0]).toEqual({ title: 'Tried to run a command', result: 'failed' })
  expect(bare('pending').lines[0]).toEqual({ title: 'Running a command', result: 'now…' })
  expect(bare('pending').tones[0]).toBe('now')
  expect(bare('denied', 'failed').lines[0]).toEqual({ title: 'Tried to run 2 commands', result: '1 refused, 1 failed' })
  // an interrupted call is interrupted, not failed - in any group
  expect([bare('interrupted').lines[0].result, bare('interrupted').tones[0]]).toEqual(['interrupted', 'warn'])
  const reads = convState({ ...coder, toolCalls: [call('1', 'read_file', '{}', 'm1', { status: 'interrupted' })] })
  expect(phaseLine(reads, phasesOf(reads, { id: 'a', report: null, ended_at: null })[0]).result).toBe('read 1 file · 1 interrupted')
})

test('"passed" only where every command is a test run; else "OK"', () => {
  expect(ranAll([{ command: 'pytest', exit_code: 0 }, { command: 'ls', exit_code: 0 }]).lines[0].result).toBe('2 OK')
  expect(ranAll([{ command: 'pytest', exit_code: 0 }, { command: 'npm test', exit_code: 0 }]).lines[0].result).toBe('2 passed')
})
