import { beforeEach, expect, test, vi } from 'vitest'
import type { ConvState } from '../state/applyEvent'
import { agent, command, convState, fileChange, run, toolCall, userMessage } from '../test-fixtures'
import { deriveGraph, type GroupData } from './deriveGraph'
import { agentOf, foldAll, foldGraph, nodeOf, readFolds, turnOf, writeFolds } from './foldGraph'
import { oneTurn } from './turns'

const cli = { origin: 'cli' as const }
const ids = (g: ReturnType<typeof foldGraph>) => g.nodes.map(n => n.id)
const open = (g: ReturnType<typeof foldGraph>, id: string) => (g.nodes.find(n => n.id === id)!.data as GroupData).open

test('an agent is one node with nothing inside: nothing to close (the user’s, 5 Nov)', () => {
  const g = deriveGraph(
    convState({
      runs: [run('r')],
      agents: [agent('r')],
      messages: [userMessage('r', 'x')],
      toolCalls: [toolCall('1', 'r', 'read_file', 'succeeded'), toolCall('2', 'r', 'claude__Agent', 'succeeded', '{}', cli)],
      commands: [command('k1', 'r')],
      fileChanges: [fileChange('f1', 'r')],
    }),
  )
  expect(ids(foldGraph(g, { 'agent:r': false }))).toEqual(['request:r', 'agent:r'])
  expect(open(foldGraph(g, { 'agent:r': false }), 'agent:r')).toBe(true)
  expect(foldAll(g, false)).toEqual({})
})

/** Two turns that are over (the first with a Reviewer, a command and two changes) and a third at work. */
function turns(over: Partial<ConvState> = {}) {
  return deriveGraph(
    convState({
      runs: [run('a', 'completed'), run('b', 'failed'), run('c')],
      messages: [userMessage('a', '\nFix the greeting\nand then the tests'), userMessage('b', 'x'.repeat(200)), userMessage('c', 'go on')],
      agents: [
        agent('a', 'completed'),
        agent('a', 'completed', { id: 'kid', parent_agent_id: 'a', role_name: 'Reviewer', depth: 1 }),
        agent('b', 'failed'),
        agent('c'),
      ],
      toolCalls: [
        toolCall('1', 'a', 'read_file', 'succeeded'),
        toolCall('2', 'a', 'search', 'succeeded'),
        toolCall('3', 'a', 'claude__Read', 'succeeded', '{}', cli),
        toolCall('4', 'a', 'read_file', 'succeeded', '{}', { agent_id: 'kid' }),
      ],
      commands: [command('k1', 'a')],
      fileChanges: [fileChange('f1', 'a'), fileChange('f2', 'a', { agent_id: 'kid' })],
      ...over,
    }),
  )
}

test('folding hides nothing of a turn without frames: no node stands for a turn, no line joins two turns', () => {
  const whole = turns()
  const g = foldGraph(whole, {})
  expect(ids(g)).toEqual(['request:a', 'agent:a', 'agent:kid', 'request:b', 'agent:b', 'request:c', 'agent:c'])
  expect(g.edges.every(e => whole.nodes.find(n => n.id === e.source)!.runId === whole.nodes.find(n => n.id === e.target)!.runId)).toBe(true)
  expect(foldAll(oneTurn(whole, 'a'), false)).toEqual({})
})

test('a call, a command or a file selected elsewhere is drawn as its agent; any other selection as it is', () => {
  const whole = turns()
  const state = { toolCalls: [{ id: '4', agent_id: 'kid' }], commands: [{ id: 'k1', agent_id: 'a' }], fileChanges: [{ id: 'f2', agent_id: 'kid' }] }
  expect([agentOf(state, 'call:4'), agentOf(state, 'command:k1'), agentOf(state, 'file:f2')]).toEqual(['agent:kid', 'agent:a', 'agent:kid'])
  expect([agentOf(state, 'file:nope'), agentOf(state, 'agent:c')]).toEqual(['file:nope', 'agent:c'])
  expect(nodeOf(whole, agentOf(state, 'file:f2'))?.id).toBe('agent:kid')
  expect(turnOf(whole, 'agent:c')).toBe('c')
  expect(turnOf(whole, 'nothing:x')).toBeNull()
})

beforeEach(() => localStorage.clear())

test('choices are remembered per conversation, in this browser', () => {
  writeFolds('c1', { 'agent:lead': false })
  expect(readFolds('c1')).toEqual({ 'agent:lead': false })
  expect(readFolds('c2')).toEqual({})
})

test('storage that is broken or closed costs the memory, not the canvas', () => {
  localStorage.setItem('koloni-canvas-groups:c1', '{"agent:lead": "no", "agent:kid": true}')
  expect(readFolds('c1')).toEqual({ 'agent:kid': true })
  localStorage.setItem('koloni-canvas-groups:c1', 'not json')
  expect(readFolds('c1')).toEqual({})
  const closed = () => {
    throw new Error('storage is closed')
  }
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(closed)
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(closed)
  expect(readFolds('c1')).toEqual({})
  expect(() => writeFolds('c1', { 'agent:lead': true })).not.toThrow()
  get.mockRestore()
  set.mockRestore()
})
