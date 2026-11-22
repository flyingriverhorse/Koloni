import { expect, test } from 'vitest'
import { assistantMessage, toolCall } from '../test-fixtures'
import { type Group, splitTurn } from './splitTurn'

const group = (id: string, ...pieces: [string, boolean][]): Group => ({
  message: assistantMessage(id, 'r', id),
  pieces: pieces.map(([key, folds]) => ({ key, node: key, folds, calls: [toolCall(key, 'r', 'read_file', key === 'x' ? 'failed' : 'succeeded')] })),
})

test('splitTurn: what folds, what stays out in its order, the answer and after', () => {
  const groups = [group('m1', ['w1', true], ['x', true]), group('m2', ['spawn', false], ['w2', true]), group('a', ['answer', true]), group('k', ['line', true])]
  const split = splitTurn(groups, 'a')
  expect(split).toMatchObject({ count: 3, kept: [{ message: { id: 'm2' }, pieces: [{ key: 'spawn' }] }], rest: [{ message: { id: 'a' } }, { message: { id: 'k' } }] })
  // (A group split in two keeps its message on both sides.)
  expect(split.fold?.map(one => [one.message.id, one.pieces.map(piece => piece.key)])).toEqual([
    ['m1', ['w1', 'x']],
    ['m2', ['w2']],
  ])
  expect(split.calls.map(call => call.id)).toEqual(['w1', 'x', 'w2'])
})

test('splitTurn: under two steps, or with no answer among the groups, nothing folds', () => {
  const groups = [group('m1', ['w1', true], ['spawn', false]), group('a', ['answer', true])]
  expect(splitTurn(groups, 'a')).toMatchObject({ fold: null, kept: [], rest: groups, count: 1 })
  expect(splitTurn(groups, 'gone')).toMatchObject({ fold: null, rest: groups })
})
