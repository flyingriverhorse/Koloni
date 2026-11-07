import { expect, test } from 'vitest'
import { agent, convState, run, toolCall } from '../test-fixtures'
import { refusedIn } from './refused'

/** The words the server refuses with in a turn nobody is watching (app/agent.py, NOBODY). */
const nobody = (what: string) =>
  `not done: nobody is here to ask. This turn was started by the trigger "Nightly", which does not allow it to ${what}. ` +
  "That is the user's standing decision, not a tool error: do not try it another way. Go on with what you may do, and say in your report what you would have asked for."

const turn = (calls: Parameters<typeof convState>[0]['toolCalls']) =>
  convState({ runs: [run('n', 'completed', { unattended: true, trigger_id: 't1', trigger_name: 'Nightly' })], agents: [agent('n')], toolCalls: calls })

test('what a turn was refused because nobody was there to ask is listed: a file, a command, a sub-agent', () => {
  const state = turn([
    toolCall('1', 'n', 'read_file', 'succeeded', '{"path":"hello.py"}', { result: "print('hi')" }),
    toolCall('2', 'n', 'write_file', 'denied', '{"path":"made.txt","content":"x"}', { result: nobody('change files') }),
    toolCall('3', 'n', 'run_command', 'denied', '{"command":"python check.py"}', { result: nobody('run "python check.py"') }),
    toolCall('4', 'n', 'spawn_agent', 'denied', '{"role":"Coder","task":"Fix it"}', { result: nobody('open a Coder sub-agent') }),
  ])
  expect(refusedIn(state, 'n')).toEqual([
    { id: '2', what: 'write made.txt', allow: { write: true } },
    { id: '3', what: 'run `python check.py`', allow: { command: 'python check.py' } },
    { id: '4', what: 'open a Coder sub-agent', allow: { agents: 1 } },
  ])
})

test('the command is the line the server refused, read out of its words - quotes and all - not the one the agent typed', () => {
  const line = 'python -c "print(\\"a b\\")"'
  const state = turn([toolCall('3', 'n', 'run_command', 'denied', '{"command":"  python -c  x "}', { result: nobody(`run ${JSON.stringify(line)}`) })])
  expect(refusedIn(state, 'n')).toEqual([{ id: '3', what: `run \`${line}\``, allow: { command: line } }])
})

test('what no trigger can allow is listed without a way to allow it', () => {
  const state = turn([
    // in another folder: a trigger's commands run in the project folder only
    toolCall('1', 'n', 'run_command', 'denied', '{"command":"make test","cwd":"sub"}', { result: nobody('run "make test" in sub') }),
    toolCall('2', 'n', 'ask_user', 'denied', '{"question":"Which?"}', { result: nobody('ask the user anything') }),
    toolCall('3', 'n', 'create_role', 'denied', '{"name":"Documenter"}', { result: nobody('create the role Documenter') }),
    toolCall('4', 'n', 'spawn_agent', 'denied', '{"role":"Reviewer","provider":"Strong"}', {
      result: nobody('give a sub-agent another model (Strong); leave provider and model out'),
    }),
    toolCall('5', 'n', 'remember', 'failed', '{"text":"x","propose":true}', {
      result: 'error: nothing is put forward for the core in a turn nobody is watching: nobody is here to ask. Leave propose out to keep it as a note.',
    }),
    toolCall('6', 'n', 'claude__WebFetch', 'denied', '{"url":"https://example.com"}', { result: nobody('use WebFetch') }),
    // a file that gives later turns leave, where the trigger does let its turns change files: not "change files" again
    toolCall('7', 'n', 'write_file', 'denied', '{"path":".claude/settings.json","content":"{}"}', {
      result: nobody('change ".claude/settings.json": such a file tells later turns what they may do, or runs by itself, which no trigger allows'),
    }),
  ])
  expect(refusedIn(state, 'n').map(r => [r.what, r.allow])).toEqual([
    ['run `make test` in sub', null],
    ['ask the user anything', null],
    ['create the role Documenter', null],
    ['give a sub-agent another model (Strong); leave provider and model out', null],
    ['put a note forward for the core', null],
    ['use WebFetch', null],
    ['change ".claude/settings.json": such a file tells later turns what they may do, or runs by itself, which no trigger allows', null],
  ])
})

test('an agent that was not opened because its provider works with its own tools is listed as that', () => {
  const state = turn([
    toolCall('1', 'n', 'spawn_agent', 'denied', '{"role":"Coder","task":"x"}', {
      result:
        'Codex cannot work in a turn nobody is watching: it works with its own tools - KOLONİ sees of them only what the CLI asks about - so it cannot be held to what the trigger allows, and nobody is here to ask. Choose another provider for this conversation or role, or set this one to a way of working that uses KOLONİ\'s tools (a session, or one step at a time).',
    }),
  ])
  expect(refusedIn(state, 'n').map(r => [r.what, r.allow])).toEqual([['open an agent on Codex, which works with its own tools', null]])
})

test('a CLI’s own write, and a sub-agent opened for a discussion, can be allowed like KOLONİ’s own', () => {
  const state = turn([
    toolCall('1', 'n', 'edit_file', 'denied', '{"path":"src/a.py"}', { origin: 'cli', result: nobody('change files') }),
    toolCall('2', 'n', 'discuss', 'denied', '{"topic":"x","with":["Reviewer"]}', { result: nobody('open a Reviewer for a discussion') }),
  ])
  expect(refusedIn(state, 'n')).toEqual([
    { id: '1', what: 'write src/a.py', allow: { write: true } },
    { id: '2', what: 'open a Reviewer for a discussion', allow: { agents: 1 } },
  ])
})

test('only refusals for want of somebody to ask are listed, each once, and only this turn’s', () => {
  const state = convState({
    runs: [run('n', 'completed', { unattended: true, trigger_id: 't1', trigger_name: 'Nightly' }), run('r', 'completed')],
    agents: [agent('n'), agent('n', 'completed', { id: 'kid', parent_agent_id: 'n', depth: 1 })],
    toolCalls: [
      toolCall('1', 'n', 'run_command', 'failed', '{"command":"nope"}', { result: 'error: exit code 1' }),
      toolCall('2', 'n', 'write_file', 'denied', '{"path":"x.txt"}', { result: 'the Reviewer role may not write files' }),
      toolCall('3', 'n', 'write_file', 'denied', '{"path":"made.txt"}', { result: nobody('change files') }),
      // tried again, and by a sub-agent of the turn: the same request is one line
      toolCall('4', 'n', 'write_file', 'denied', '{"path":"made.txt"}', { result: nobody('change files'), agent_id: 'kid' }),
      toolCall('5', 'r', 'write_file', 'denied', '{"path":"other.txt"}', { result: nobody('change files') }),
      // a call that went through says nothing of the kind, whatever its result quotes
      toolCall('6', 'n', 'read_file', 'succeeded', '{"path":"notes.md"}', { result: 'nobody is here to ask' }),
    ],
  })
  expect(refusedIn(state, 'n').map(r => r.what)).toEqual(['write made.txt'])
  expect(refusedIn(state, 'r').map(r => r.what)).toEqual(['write other.txt'])
  expect(refusedIn(state, 'none')).toEqual([])
})
