import { expect, test } from 'vitest'
import type { FileChange, Merge, Message } from '../api/types'
import { agent, fileChange } from '../test-fixtures'
import { GROUPS, PLACE, changeRows, changeTree, changesCount, changesSaid, heading, standsOn } from './changeGroups'

const merge = (agentId: string, status: Merge['status'], over: Partial<Merge> = {}): Merge => ({
  id: `g-${agentId}`,
  run_id: 'r',
  agent_id: agentId,
  status,
  files: [],
  kept_in: null,
  created_at: '2026-11-07T10:00:00Z',
  decided_at: null,
  ...over,
})
const names: Record<string, string> = { r: 'Lead', c: 'Coder', t: 'Tester', d: 'Docs' }
const rows = (over: Partial<Parameters<typeof changeRows>[0]>) => changeRows({ changes: [], git: null, agents: [], merges: [], messages: [], name: id => names[id] ?? 'an agent', ...over })

test('the groups go by what you have to do, top to bottom', () => {
  expect(GROUPS).toEqual(['Waits for you', 'At work', 'Kept', 'In the project', 'Not by an agent', 'Needs a look', 'Closed'])
})

test('each state of a change lands in the group of what you have to do about it, said in words - no letters', () => {
  const statuses = Object.keys(PLACE) as FileChange['status'][]
  const got = rows({ changes: statuses.map((status, n) => fileChange(`f${n}`, 'r', { path: `${status}.txt`, status, diff: '+b' })) })
  expect(got.map(r => [r.path, r.group, r.words])).toEqual([
    ['proposed.txt', 'Waits for you', 'changed'],
    ['approved.txt', 'In the project', 'changed, yes given, not made yet'],
    ['applied.txt', 'In the project', 'changed'],
    ['merged.txt', 'In the project', 'changed, put together with yours'],
    ['conflict.txt', 'Needs a look', 'changed, changed on disk since'],
    ['failed.txt', 'Needs a look', 'changed, not written: the disk refused'],
    ['rejected.txt', 'Closed', 'changed, you said no'],
    ['reverted.txt', 'Closed', 'changed, reverted'],
    ['discarded.txt', 'Closed', 'changed, never made'],
  ])
  expect(rows({ changes: [fileChange('n', 'r', { path: 'n.txt', kind: 'create', status: 'proposed' }), fileChange('d', 'r', { path: 'd.txt', kind: 'delete', status: 'proposed' })] }).map(r => r.words)).toEqual(['new', 'deleted'])
})

test('a copy is one row, by how it stands; git’s files no agent made, the gone, the outside and the scratch each go where they belong', () => {
  const got = rows({
    agents: [
      agent('r', 'running', { id: 'r' }),
      agent('r', 'running', { id: 'c', copy: { state: 'own' } }),
      agent('r', 'completed', { id: 't', copy: { state: 'own' } }),
      agent('r', 'failed', { id: 'd', copy: { state: 'own' } }),
    ],
    merges: [merge('t', 'pending'), merge('d', 'kept', { kept_in: 'C:/kept' })],
    changes: [
      // (one in a copy is its copy's row; a newer one does not hide the project's own record of the file)
      fileChange('b1', 'r', { agent_id: 'c', path: 'b.py', status: 'applied', created_at: '2026-11-07T10:00:00Z' }),
      fileChange('b2', 'r', { agent_id: 'c', path: 'b.py', status: 'in_copy', created_at: '2026-11-07T11:00:00Z' }),
      fileChange('x', 'r', { path: '.koloni/tmp/x.txt', status: 'proposed' }),
      fileChange('g', 'r', { path: 'g.py', status: 'applied', gone: true }),
      fileChange('p', 'r', { path: 'C:/notes/plan.md', status: 'applied' }),
      // (said no to, then changed again by someone else: git sees it)
      fileChange('o', 'r', { path: 'old.txt', status: 'rejected' }),
    ],
    git: [
      { path: 'old.txt', status: 'M' },
      { path: 'user.txt', status: '?' },
      { path: 'b.py', status: 'M' },
    ],
  })
  expect(got.map(r => [r.key, r.group, r.words, r.who === null])).toEqual([
    ['copy:t', 'Waits for you', 'its working copy', true],
    ['copy:c', 'At work', 'its working copy', true],
    ['copy:d', 'Kept', 'its working copy', true],
    ['b.py', 'In the project', 'changed', false],
    ['C:/notes/plan.md', 'In the project', 'changed, outside the project', false],
    ['old.txt', 'Not by an agent', 'changed', true],
    ['user.txt', 'Not by an agent', 'new, not in git', true],
    ['g.py', 'Needs a look', 'changed, not on disk now', false],
  ])
  expect(got.find(r => r.key === 'copy:t')?.path).toBe("Tester's copy")
})

test('on a branch looked at, what git says is what that branch changed', () => {
  expect(rows({ git: [{ path: 'pay.py', status: 'A' }], branch: 'refs/heads/feature/pay' }).map(r => [r.group, r.words])).toEqual([['Changed on feature/pay', 'new']])
})

test('a change is listed under its agent and your message, the time first', () => {
  const asked = { id: 'm', run_id: 'r', role: 'user', content: 'The login   fails after a reset/sign-in and much more than forty letters', created_at: '2026-11-07T10:42:00Z' } as Message
  // (the time as this browser writes it: "10:42", or "10:42 AM")
  expect(heading(fileChange('f', 'r'), 'Coder', [asked])).toMatch(/^[^·]*\d\d:42[^·]* · Coder · “The login fails after a reset\/sign-in an…”$/)
  expect(heading(fileChange('f', 'r2'), 'Coder', [asked])).toMatch(/^[^·]+ · Coder$/)
})

test('the tree: each group a folder with its count, its lines in it, the files by name with their folder after - or in their folders', () => {
  const got = rows({ changes: [fileChange('a', 'r', { path: 'src/a.py', status: 'proposed' })], git: [{ path: 'docs/x/y.md', status: 'M' }], branch: null })
  const flat = changeTree(got, false)
  expect(flat.map(f => [f.path, f.folder ?? false, f.meta, f.where])).toEqual([
    ['Waits for you', true, '1', undefined],
    ['Not by an agent', true, '1', undefined],
    [expect.stringMatching(/^Waits for you\/[^/]+ · Lead$/), true, '', undefined],
    [expect.stringMatching(/^Waits for you\/[^/]+ · Lead\/a\.py$/), false, 'changed', 'src'],
    ['Not by an agent/y.md', false, 'changed', 'docs/x'],
  ])
  expect(changeTree(got, true).map(f => f.path).at(-1)).toBe('Not by an agent/docs/x/y.md')
  // (a '/' in a group's name does not split it into folders)
  expect(changeTree(rows({ git: [{ path: 'a.py', status: 'M' }], branch: 'feature/pay' }), false).map(f => f.path)).toEqual(['Changed on feature∕pay', 'Changed on feature∕pay/a.py'])
})

test('the top line says what the list is, in plain words - not what the tool is doing', () => {
  expect(changesSaid(undefined, 0, 'shop', null)).toBe('Looking for changes…')
  expect(changesSaid({ list: [] }, 0, 'shop', null)).toBe('Nothing changed.')
  expect(changesSaid({ list: [] }, 2, 'shop', null)).toBe("This chat's work, and what git sees changed in shop since the last commit.")
  expect(changesSaid({ list: null }, 2, 'shop', null)).toBe("No git here, or it did not answer in time: this is what this chat's agents changed.")
  expect(changesSaid({ list: null, failed: true }, 2, 'shop', null)).toBe("The changes could not be read: this is what this chat's agents changed.")
  // (a read that failed is said so, not "Nothing changed")
  expect(changesSaid({ list: null, failed: true }, 0, 'shop', null)).toBe('The changes could not be read.')
  expect(changesSaid({ list: [] }, 2, 'shop', 'refs/heads/x')).toBe('')
})

test('a file stands on its latest live change, in Files and in Changes alike: one closed after it with nothing in it (B-342), or said no to, does not hide it', () => {
  const applied = fileChange('a', 'r', { path: 'x.py', status: 'applied', diff: '@@ -1 +1 @@\n-a\n+b\n', created_at: '2026-11-07T10:00:00Z' })
  const empty = fileChange('b', 'r', { path: 'x.py', status: 'discarded', diff: '', additions: 0, deletions: 0, created_at: '2026-11-07T11:00:00Z' })
  const refused = fileChange('c', 'r', { path: 'x.py', status: 'rejected', diff: '@@ -1 +1 @@\n-b\n+c\n', created_at: '2026-11-07T12:00:00Z' })
  for (const changes of [[applied, empty], [applied, refused]]) {
    expect(standsOn(changes).get('x.py')?.id).toBe('a')
    expect(standsOn(changes, true).get('x.py')?.id).toBe('a')
    // (git still sees the agent's own change: it is in the project, not "Not by an agent")
    expect(rows({ changes, git: [{ path: 'x.py', status: 'M' }] }).map(r => [r.key, r.group])).toEqual([['x.py', 'In the project']])
  }
  // (a copy's change: the Files tree marks it, Changes leaves it to the copy's row)
  const inCopy = fileChange('d', 'r', { path: 'x.py', status: 'in_copy', diff: '+', created_at: '2026-11-07T13:00:00Z' })
  expect(standsOn([applied, inCopy], true).get('x.py')?.id).toBe('d')
  expect(standsOn([applied, inCopy]).get('x.py')?.id).toBe('a')
  // Only a file no change of this chat stands on is "Not by an agent".
  expect(rows({ changes: [refused], git: [{ path: 'x.py', status: 'M' }] }).map(r => [r.key, r.group])).toEqual([['x.py', 'Not by an agent']])
})

test('"Changes · N": with git, what git lists - as the top bar counts; without, what is not closed', () => {
  const got = rows({ changes: [fileChange('p', 'r', { path: 'p.py', status: 'proposed' }), fileChange('o', 'r', { path: 'o.py', status: 'rejected', diff: '+' })] })
  expect(changesCount(got, null)).toBe(1)
  expect(changesCount(got, [{ path: 'a', status: 'M' }, { path: 'b', status: '?' }, { path: 'c', status: 'D' }])).toBe(3)
})
