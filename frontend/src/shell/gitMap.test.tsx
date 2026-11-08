import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError, api } from '../api/client'
import type { GitStatus as Git, Merge } from '../api/types'
import { MessageList } from '../chat/MessageList'
import { useApp } from '../state/store'
import { agent, conversation, convState, fileChange, run } from '../test-fixtures'
import { MergeCard } from '../changes/MergeCard'
import { GitStatus } from './GitStatus'
import { gitLabel, gitRows } from './gitMap'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

const git = (over: Partial<Git> = {}): Git => ({
  branch: 'main',
  changed: 4,
  worktrees: [{ path: 'C:/p', branch: 'main', here: true }],
  branches: [],
  current: null,
  switch_blocked: null,
  reports: [],
  commit: false,
  ...over,
})

const merge = (status: Merge['status'], over: Partial<Merge> = {}): Merge => ({
  id: `g-${status}`,
  run_id: 'r',
  agent_id: 'docs',
  status,
  files: [],
  kept_in: null,
  created_at: '2026-10-21T21:00:00Z',
  decided_at: null,
  ...over,
})

test('the top bar says the branch, what is not committed, and the other worktrees', () => {
  expect(gitLabel(git())).toBe('⑂ main · 4 changed')
  expect(gitLabel(git({ changed: 0 }))).toBe('⑂ main')
  expect(gitLabel(git({ branch: '', changed: 1, worktrees: [...git().worktrees, { path: 'C:/w', branch: 'fix', here: false }] }))).toBe('⑂ no branch · 1 changed · 1 worktree')
})

test('each copy says how it stands in words, and how it gets back to the project’s branch', () => {
  const state = convState({
    runs: [run('r')],
    agents: [
      agent('r', 'running', { id: 'lead' }),
      agent('r', 'running', { id: 'coder', parent_agent_id: 'lead', name: 'Coder', role_name: 'Coder', depth: 1, provider_name: 'Codex', copy: { state: 'own' } }),
      agent('r', 'completed', { id: 'docs', parent_agent_id: 'lead', name: 'Docs writer', role_name: 'Writer', depth: 1, copy: { state: 'own' } }),
      agent('r', 'failed', { id: 'tester', parent_agent_id: 'lead', name: 'Tester', role_name: 'Tester', depth: 1, copy: { state: 'own' } }),
    ],
    fileChanges: [
      fileChange('c1', 'r', { agent_id: 'coder', path: 'a.ts', status: 'in_copy' }),
      fileChange('c2', 'r', { agent_id: 'coder', path: 'a.ts', status: 'in_copy' }),
      fileChange('c3', 'r', { agent_id: 'coder', path: 'b.ts', status: 'in_copy' }),
    ],
    merges: [merge('pending'), merge('interrupted', { id: 'k', agent_id: 'tester', kept_in: 'C:/kept' })],
  })
  const rows = gitRows(git({ commit: true }), state)
  expect(rows.map(r => [r.section, r.what, r.state, r.small, r.act?.label])).toEqual([
    ['copies', 'Coder', 'working', '2 files so far · works in its own copy (Codex) · goes into main when you take it in · then offered for a commit on main', 'See changes'],
    ['copies', 'Docs writer', 'finished, waits for you', 'works in its own copy · goes into main when you take it in · then offered for a commit on main', 'Take in…'],
    ['copies', 'Tester', 'kept', 'in its copy · nothing was taken · goes in only if you take it in', 'Look'],
  ])
  // A chat that does not ask: in by itself when it finishes.
  const unasked = { ...state, conversation: { ...conversation, permission_mode: 'full_auto' as const } }
  expect(gitRows(git(), unasked)[0].small).toBe('2 files so far · works in its own copy (Codex) · goes into main when it finishes')
})

test('other branches are compared with the project’s, and what an agent said is held against git', () => {
  const rows = gitRows(
    git({
      branches: [
        { name: 'fix-login', ref: 'refs/heads/fix-login', remote: false, ahead: 3, behind: 0, joined: false, worktree: 'C:\\w\\fix', sha: null, subject: null, last_at: null },
        { name: 'docs', ref: 'refs/heads/docs', remote: false, ahead: 0, behind: 2, joined: true, worktree: null, sha: 'd0c5', subject: 'docs', last_at: null },
        { name: 'spike', ref: 'refs/remotes/origin/spike', remote: true, ahead: 1, behind: 1, joined: false, worktree: null, sha: null, subject: null, last_at: null },
      ],
      reports: [
        { agent: 'Codex', branch: 'fix-login', worktree: null, commits: 3, merge_into: 'main', why: 'a fix', at: null, seen: true },
        { agent: 'Coder', branch: 'gone', worktree: null, commits: null, merge_into: null, why: 'tried', at: null, seen: false },
      ],
    }),
    null,
  )
  expect(rows.map(r => [r.section, r.what, r.state, r.small])).toEqual([
    ['branches', 'Codex said it made the branch fix-login', 'not joined', 'in its own folder C:\\w\\fix · 3 commits ahead of main · said by Codex: goes into main'],
    ['branches', 'Branch docs', 'joined ✓', 'already in main · d0c5 docs'],
    ['branches', 'Remote branch spike', 'not joined', '1 commit ahead of main · 1 behind · nobody said where it goes'],
    ['said', 'Coder said it made the branch gone', 'not seen in git', 'tried'],
  ])
})

test('KOLONİ’s line on a turn’s git is said in the chat, with Show git', async () => {
  const onShowGit = vi.fn()
  const state = convState({
    runs: [run('r', 'completed')],
    messages: [{ id: 'g', conversation_id: 'c', run_id: 'r', agent_id: null, role: 'git', content: 'Codex switched the project to branch fix-login during this turn (it was on main). Not reported.', from_agent_id: null, delivered_at: null, discussion_id: null, created_at: '2026-10-21T21:52:00Z', status: 'complete' } as never],
  })
  render(<MessageList state={state} onRemoveQueued={() => {}} onOpenChange={() => {}} onDecide={async () => {}} onDecideCommand={async () => {}} onShowGit={onShowGit} />)
  expect(screen.getByRole('note')).toHaveTextContent('Codex switched the project to branch fix-login during this turn (it was on main). Not reported.Show git')
  await userEvent.click(screen.getByRole('button', { name: 'Show git' }))
  expect(onShowGit).toHaveBeenCalled()
})

test('B-186: the top bar reads git again as a change reaches the project after its turn - a take in, an Undo', async () => {
  const read = vi.spyOn(api, 'get').mockResolvedValue(git())
  const state = convState({ runs: [run('r', 'completed')], fileChanges: [fileChange('f1', 'r', { status: 'proposed' })], merges: [merge('pending')] })
  useApp.setState({ conv: state })
  render(<GitStatus projectId="p" />)
  await screen.findByRole('button', { name: /main · 4 changed/ })
  const before = read.mock.calls.length
  // (a change written in a copy has not reached the project: nothing is read for it)
  act(() => useApp.setState({ conv: { ...state, fileChanges: [fileChange('f1', 'r', { status: 'in_copy' }), fileChange('f2', 'r', { status: 'proposed' })] } }))
  await new Promise(resolve => setTimeout(resolve, 50))
  expect(read.mock.calls.length).toBe(before)
  act(() => useApp.setState({ conv: { ...state, merges: [merge('applied')] } }))
  await waitFor(() => expect(read.mock.calls.length).toBe(before + 1))
  act(() => useApp.setState({ conv: { ...state, merges: [merge('applied')], fileChanges: [fileChange('f1', 'r', { status: 'reverted' })] } }))
  await waitFor(() => expect(read.mock.calls.length).toBe(before + 2))
  read.mockRestore()
})

test('the open map reads git again a few seconds after each answer; a closed one does not', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const read = vi.spyOn(api, 'get').mockResolvedValue(git())
  useApp.setState({ conv: null })
  render(<GitStatus projectId="p" />)
  const button = await screen.findByRole('button', { name: /main · 4 changed/ })
  await act(() => vi.advanceTimersByTimeAsync(9000))
  expect(read).toHaveBeenCalledTimes(1)
  act(() => button.click())
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2))
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(read).toHaveBeenCalledTimes(3)
  act(() => button.click())
  // (the one already asked for is the last)
  await act(() => vi.advanceTimersByTimeAsync(9000))
  expect(read).toHaveBeenCalledTimes(4)
  read.mockRestore()
})

test('an open map keeps what it shows through a read with no answer; with nothing read yet there is no git', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const read = vi.spyOn(api, 'get').mockResolvedValueOnce(null).mockResolvedValue(git())
  useApp.setState({ conv: null })
  render(<GitStatus projectId="p" />)
  await waitFor(() => expect(read).toHaveBeenCalledTimes(1))
  expect(screen.queryByRole('button', { name: /main/ })).toBeNull()
  useApp.setState({ gitAsked: useApp.getState().gitAsked + 1 }) // (Show git: opened)
  const map = await screen.findByRole('region', { name: 'Where the work is' })
  // (git slower than its 5 s, then the server not reached)
  read.mockResolvedValueOnce(null).mockRejectedValueOnce(new Error('offline'))
  for (const _ of [1, 2]) await act(() => vi.advanceTimersByTimeAsync(3500))
  expect(read).toHaveBeenCalledTimes(4)
  expect(map).toBeInTheDocument()
  expect(useApp.getState().gitBranch).toBe('main')
  read.mockRestore()
})

test('a read on its way as the branch is switched does not put the old branch back', async () => {
  let answer: (seen: Git) => void = () => {}
  const read = vi.spyOn(api, 'get').mockResolvedValueOnce(git({ branches: [branch('feature')] }))
  const post = vi.spyOn(api, 'post').mockResolvedValue(git({ branch: 'feature', changed: 0 }))
  useApp.setState({ conv: null })
  render(<GitStatus projectId="p" />)
  const button = await screen.findByRole('button', { name: /main · 4 changed/ })
  // (the read as it opens is still on its way as the switch is answered: main, from before it)
  read.mockImplementationOnce(() => new Promise(resolve => (answer = resolve as (seen: Git) => void)))
  read.mockResolvedValue(git({ branch: 'feature', changed: 0 }))
  await userEvent.click(button)
  await userEvent.click(screen.getAllByRole('button', { name: 'Switch to' })[0])
  expect(await screen.findByRole('button', { name: '⑂ feature' })).toBeInTheDocument()
  act(() => answer(git({ branches: [branch('feature')] })))
  await waitFor(() => expect(read.mock.calls.length).toBeGreaterThanOrEqual(3))
  expect(screen.getByRole('button', { name: '⑂ feature' })).toBeInTheDocument()
  expect(useApp.getState().gitBranch).toBe('feature')
  read.mockRestore()
  post.mockRestore()
})

const branch = (name: string, over: Partial<Git['branches'][number]> = {}): Git['branches'][number] => ({
  name,
  ref: `refs/heads/${name}`,
  remote: false,
  ahead: 1,
  behind: 0,
  joined: false,
  worktree: null,
  sha: 'a1b2c3d',
  subject: 'fix the login',
  last_at: null,
  ...over,
})

test('K-dallar: a branch is looked at read only, a local one switched to - and not while something holds the project', async () => {
  const branches = [branch('feature'), branch('origin/feature', { ref: 'refs/remotes/origin/feature', remote: true }), branch('side', { worktree: 'C:\w\side' })]
  const read = vi.spyOn(api, 'get').mockResolvedValue(git({ branches, current: branch('main', { ahead: 0, subject: 'as it was' }) }))
  // (switched, the project is on feature: what git is read as after it, too)
  const post = vi.spyOn(api, 'post').mockImplementation(async () => {
    read.mockResolvedValue(git({ branch: 'feature', changed: 0 }))
    return git({ branch: 'feature', changed: 0 })
  })
  useApp.setState({ conv: null })
  render(<GitStatus projectId="p" />)
  await userEvent.click(await screen.findByRole('button', { name: /main · 4 changed/ }))
  const map = screen.getByRole('region', { name: 'Where the work is' })
  expect(map).toHaveTextContent('a1b2c3d as it was')
  expect(within(map).getAllByRole('button', { name: 'Look' })).toHaveLength(3)
  // (a remote's branch: Look only; one open in another worktree: git switches to it only there)
  const switches = within(map).getAllByRole('button', { name: 'Switch to' })
  expect(switches).toHaveLength(2)
  expect(switches[1]).toBeDisabled()
  await userEvent.click(within(map).getAllByRole('button', { name: 'Look' })[0])
  expect(useApp.getState().filesRef).toBe('refs/heads/feature')
  await userEvent.click(screen.getByRole('button', { name: /main · 4 changed/ }))
  await userEvent.click(screen.getAllByRole('button', { name: 'Switch to' })[0])
  expect(post).toHaveBeenCalledWith('/projects/p/git/switch', { name: 'feature', new: false })
  expect(await screen.findByRole('button', { name: '⑂ feature' })).toBeInTheDocument()
  expect(useApp.getState().gitBranch).toBe('feature')
  const why = 'Coder is at work — wait for the turn to end'
  read.mockResolvedValue(git({ branches, switch_blocked: why }))
  // (closed and opened again: read again as it opens)
  await userEvent.click(screen.getByRole('button', { name: '⑂ feature' }))
  await userEvent.click(screen.getByRole('button', { name: '⑂ feature' }))
  expect(await screen.findByText(`Can't switch branches now: ${why}.`)).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Switch to' }).every(one => (one as HTMLButtonElement).disabled)).toBe(true)
  expect(screen.getByRole('button', { name: '+ New branch' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '+ New branch' })).toHaveAttribute('title', why)
  read.mockRestore()
  post.mockRestore()
})

test('K-dallar: a Take in card says its copy was made on another branch than the project is on now', () => {
  const card = () => render(<MergeCard merge={merge('pending', { agent_id: 'coder', files: [] })} name="Coder" onDecide={async () => {}} />)
  useApp.setState({ conv: convState({ agents: [agent('r', 'completed', { id: 'coder', copy: { state: 'own', branch: 'main' } })] }), gitBranch: 'main' })
  card()
  expect(screen.queryByText(/made on/)).toBeNull()
  cleanup()
  useApp.setState({ gitBranch: 'feature-x' })
  card()
  expect(screen.getByRole('note')).toHaveTextContent('made on main, the project is now on feature-x')
})

test('K-dallar: New branch from here - a name, then the server makes it where the project stands; not while something holds the project', async () => {
  const read = vi.spyOn(api, 'get').mockResolvedValue(git())
  const post = vi.spyOn(api, 'post').mockRejectedValueOnce(new ApiError(422, "'a..b' is not a name git takes for a branch", "'a..b' is not a name git takes for a branch")).mockImplementation(async () => {
    read.mockResolvedValue(git({ branch: 'fix/login' }))
    return git({ branch: 'fix/login' })
  })
  useApp.setState({ conv: null })
  render(<GitStatus projectId="p" />)
  await userEvent.click(await screen.findByRole('button', { name: /main · 4 changed/ }))
  // K-git-not: folded behind its button; it opens with the focus in the name, and Esc or an empty blur folds it - not the map.
  const map = screen.getByRole('region', { name: 'Where the work is' })
  const toggle = screen.getByRole('button', { name: '+ New branch' })
  expect(screen.queryByRole('textbox', { name: 'New branch name' })).toBeNull()
  await userEvent.click(toggle)
  expect(screen.getByRole('textbox', { name: 'New branch name' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('textbox', { name: 'New branch name' })).toBeNull()
  expect(map).toBeInTheDocument()
  expect(toggle).toHaveFocus()
  await userEvent.click(toggle)
  await userEvent.click(map)
  expect(screen.queryByRole('textbox', { name: 'New branch name' })).toBeNull()
  await userEvent.click(toggle)
  const made = screen.getByRole('button', { name: 'Create' })
  expect(made).toBeDisabled()
  await userEvent.type(screen.getByRole('textbox', { name: 'New branch name' }), 'a..b')
  await userEvent.click(made)
  expect(await screen.findByRole('alert')).toHaveTextContent('not a name git takes for a branch')
  await userEvent.clear(screen.getByRole('textbox', { name: 'New branch name' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'New branch name' }), ' fix/login {Enter}')
  expect(post).toHaveBeenLastCalledWith('/projects/p/git/switch', { name: 'fix/login', new: true })
  expect(await screen.findByRole('button', { name: /⑂ fix\/login/ })).toBeInTheDocument()
  expect(screen.queryByRole('textbox', { name: 'New branch name' })).toBeNull()
  read.mockRestore()
  post.mockRestore()
})


test('K-dal-takim D2: a koloni/ branch says the team working on it', () => {
  const state = convState({
    agents: [
      agent('r', 'completed', { id: 'lead', name: 'Lead', depth: 0 }),
      agent('r', 'running', { id: 'tl', name: 'Team lead', parent_agent_id: 'lead', copy: { state: 'own', branch: 'main', on_branch: 'koloni/login' } }),
      agent('r', 'running', { id: 'c1', name: 'Coder 1', parent_agent_id: 'tl', copy: { state: 'parent' } }),
      agent('r', 'running', { id: 'c2', name: 'Coder 2', parent_agent_id: 'lead', copy: { state: 'own' } }),
    ],
  })
  const rows = gitRows(git({ branches: [branch('koloni/login'), branch('fix-login')] }), state)
  expect(rows.find(r => r.key === 'b:refs/heads/koloni/login')?.what).toBe('Branch koloni/login · team Team lead, Coder 1')
  expect(rows.find(r => r.key === 'b:refs/heads/fix-login')?.what).toBe('Branch fix-login')
})

test('Where the work is: your branch, the agents’ copies of this chat, the other branches and what was said - each in words, no colour legend', async () => {
  const said = { agent: 'Coder', branch: 'gone', worktree: null, commits: null, merge_into: null, why: 'tried', at: null, seen: false }
  const read = vi.spyOn(api, 'get').mockResolvedValue(git({ branches: [branch('feature')], reports: [said] }))
  useApp.setState({ conv: convState({ agents: [agent('r', 'completed', { id: 'docs', name: 'Docs writer', copy: { state: 'own' } })], merges: [merge('pending')] }) })
  render(<GitStatus projectId="p" />)
  await userEvent.click(await screen.findByRole('button', { name: /main · 4 changed/ }))
  const map = screen.getByRole('region', { name: 'Where the work is' })
  expect(within(map).getAllByRole('heading', { level: 4 }).map(h => h.textContent)).toEqual(['Your branch', 'Agents’ copies · this chat', 'Other branches', 'Said, not seen in git'])
  expect(map).toHaveTextContent('From git, read only. KOLONİ changes nothing here but the branch you switch to.')
  expect(map).toHaveTextContent('main · now4 files not saved in git yet')
  expect(within(map).getByRole('group', { name: 'Agents’ copies · this chat' })).toHaveTextContent('Docs writer · finished, waits for you')
  expect(within(map).getByRole('group', { name: 'Other branches' })).toHaveTextContent('Branch feature · not joined1 commit ahead of main')
  expect(map.querySelector('.git-dot, .git-legend')).toBeNull()
  // (Take in… is on the copy's card, in the agent's window)
  await userEvent.click(within(map).getByRole('button', { name: 'Take in…' }))
  expect(useApp.getState().selectedNodeId).toBe('agent:docs')
  read.mockRestore()
})
