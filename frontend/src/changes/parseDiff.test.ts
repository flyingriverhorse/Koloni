import { expect, test } from 'vitest'
import { parseDiff } from './parseDiff'

const diff = [
  '--- a/hello.py',
  '+++ b/hello.py',
  '@@ -1,3 +1,3 @@',
  ' import os',
  "-print('hi')",
  "+print('hello')",
  ' # end',
].join('\n')

test('headers are dropped and line numbers follow the hunk', () => {
  expect(parseDiff(diff)).toEqual([
    { kind: 'hunk', oldNo: null, newNo: null, text: '@@ -1,3 +1,3 @@' },
    { kind: 'ctx', oldNo: 1, newNo: 1, text: 'import os' },
    { kind: 'del', oldNo: 2, newNo: null, text: "print('hi')" },
    { kind: 'add', oldNo: null, newNo: 2, text: "print('hello')" },
    { kind: 'ctx', oldNo: 3, newNo: 3, text: '# end' },
  ])
})

test('a new file starts numbering at 1 and an empty diff yields nothing', () => {
  const lines = parseDiff(['--- a/n.py', '+++ b/n.py', '@@ -0,0 +1 @@', '+x'].join('\n'))
  expect(lines[1]).toMatchObject({ kind: 'add', newNo: 1, text: 'x' })
  expect(parseDiff('')).toEqual([])
})

test('a line that begins with +++ inside a hunk is content, not a header', () => {
  const lines = parseDiff(['--- a/f', '+++ b/f', '@@ -1 +1 @@', '-a', '+++ not a header'].join('\n'))
  expect(lines[2]).toMatchObject({ kind: 'add', text: '++ not a header' })
})

test('a second hunk restarts the numbering from its header', () => {
  const lines = parseDiff(
    ['--- a/f', '+++ b/f', '@@ -1,2 +1,2 @@', ' a', '-b', '+B', '@@ -40,2 +40,3 @@', ' y', '+z'].join('\n'),
  )
  expect(lines[5]).toMatchObject({ kind: 'ctx', oldNo: 40, newNo: 40 })
  expect(lines[6]).toMatchObject({ kind: 'add', newNo: 41 })
})

test('empty context lines and the no-newline marker are handled', () => {
  const lines = parseDiff(['--- a/f', '+++ b/f', '@@ -1,2 +1,2 @@', '', '-a', '\\ No newline at end of file', '+b'].join('\n'))
  expect(lines.map(l => l.kind)).toEqual(['hunk', 'ctx', 'del', 'add'])
  expect(lines[1]).toMatchObject({ oldNo: 1, newNo: 1, text: '' })
})
