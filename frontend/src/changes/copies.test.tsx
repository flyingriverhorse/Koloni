import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Agent, Merge, Snapshot } from '../api/types'
import { type AgentData, deriveGraph } from '../canvas/deriveGraph'
import { MessageList } from '../chat/MessageList'
import { Inspector } from '../inspector/Inspector'
import { RunStatus } from '../shell/RunStatus'
import { applyEvent, fromSnapshot } from '../state/applyEvent'
import { agent, assistantMessage, convState, fileChange, run, toolCall, userMessage } from '../test-fixtures'
import { AgentWindow } from '../agents/AgentWindow'
import { CHANGE_LABEL } from './changeLabel'
import { copyLine, copyOwner, inCopyOf, inProject, pendingMerge } from './copies'
import { MergeCard } from './MergeCard'
import { NotApplied } from './NotApplied'

const DIFF = '--- a/a.txt\n+++ b/a.txt\n@@ -0,0 +1 @@\n+A'

const merge = (over: Partial<Merge> = {}): Merge => ({
  id: 'g1',
  run_id: 'r',
  agent_id: 'coder',
  status: 'pending',
  files: [
    { path: 'a.txt', kind: 'new', state: 'ready', diff: DIFF, additions: 1, deletions: 0, note: null },
    { path: 'b.txt', kind: 'changed', state: 'ready', diff: DIFF, additions: 2, deletions: 1, note: null },
  ],
  kept_in: null,
  created_at: '2026-10-09T10:00:00Z',
  decided_at: null,
  ...over,
})

/**
 * A lead that opened a Coder. The Coder changed two files in its working copy and is done;
 * the turn waits for the user's word on taking them into the project. A Helper it opened
 * worked in the Coder's copy.
 */
const state = convState({
  runs: [run('r', 'waiting_approval')],
  agents: [
    agent('r', 'waiting', { id: 'lead' }),
    agent('r', 'completed', { id: 'coder', parent_agent_id: 'lead', role_name: 'Coder', depth: 1, task: 'A', tool_call_id: 's1', copy: { state: 'own' } }),
    agent('r', 'completed', { id: 'helper', parent_agent_id: 'coder', role_name: 'Helper', depth: 2, task: 'B', copy: { state: 'parent' } }),
  ],
  messages: [userMessage('r', 'go'), { ...assistantMessage('m0', 'r', ''), agent_id: 'lead' }, { ...assistantMessage('m1', 'r', ''), agent_id: 'coder' }],
  toolCalls: [
    toolCall('s1', 'r', 'spawn_agent', 'running', '{"role":"Coder","task":"A"}', { agent_id: 'lead', message_id: 'm0' }),
    toolCall('1', 'r', 'write_file', 'succeeded', '{"path":"a.txt","content":"A"}', { agent_id: 'coder', message_id: 'm1' }),
  ],
  fileChanges: [
    fileChange('f1', 'r', { agent_id: 'coder', tool_call_id: '1', path: 'a.txt', status: 'in_copy' }),
    fileChange('f2', 'r', { agent_id: 'helper', tool_call_id: '1', path: 'b.txt', status: 'in_copy' }),
    fileChange('f3', 'r', { agent_id: 'lead', tool_call_id: '1', path: 'c.txt', status: 'applied' }),
  ],
  merges: [merge()],
})

const agentData = (g: ReturnType<typeof deriveGraph>, id: string) => g.nodes.find(n => n.id === id)!.data as AgentData
const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn() }

// --- what the records say ------------------------------------------------------------------

test('where an agent changes files: in its own copy, in the copy of the agent above it, or in the project', () => {
  const [lead, coder, helper] = state.agents
  expect(copyLine(state, lead)).toBeNull()
  expect(copyLine(state, coder)).toBe('works in its own copy')
  expect(copyLine(state, helper)).toBe("works in Coder's copy")
  // (K-dal-takim: one on a branch of its own says which; those below it are in its copy still)
  const onBranch = { ...state, agents: state.agents.map(a => (a.id === 'coder' ? { ...a, copy: { state: 'own' as const, on_branch: 'koloni/fix' } } : a)) }
  expect(copyLine(onBranch, onBranch.agents[1])).toBe('works on branch koloni/fix')
  expect(copyLine(onBranch, helper)).toBe("works in Coder's copy")
  expect(copyOwner(state, helper)?.id).toBe('coder')
  expect(copyLine(state, { ...coder, copy: { state: 'too_big' } })).toBe('too big to copy — works in the project')
  // an agent from before working copies says nothing
  expect(copyLine(state, { ...coder, copy: undefined } as never)).toBeNull()
})

test('a change that is still in a copy says whose; one in the project says nothing of a copy', () => {
  const [mine, helpers, leads] = state.fileChanges
  expect(inCopyOf(state, mine)).toBe("in Coder's copy")
  expect(inCopyOf(state, helpers)).toBe("in Coder's copy")
  expect(inCopyOf(state, leads)).toBeNull()
  // "Changes" counts what is in the project
  expect(inProject(state.fileChanges).map(c => c.id)).toEqual(['f3'])
})

test('an agent’s changes on their way into the project come with the snapshot and are kept up to date', () => {
  let s = fromSnapshot({ merges: [merge()], last_event_id: 4 } as Snapshot)
  expect(pendingMerge(s, 'coder')?.id).toBe('g1')
  expect(pendingMerge(s, 'lead')).toBeNull()
  s = applyEvent(s, 5, 'merge.updated', merge({ status: 'applied' }))
  expect(s.merges).toHaveLength(1)
  expect(pendingMerge(s, 'coder')).toBeNull()
  s = applyEvent(s, 6, 'merge.updated', merge({ id: 'g2', agent_id: 'lead' }))
  expect(s.merges.map(m => m.id)).toEqual(['g1', 'g2'])
  // a server from before working copies sends none, not nothing
  expect(fromSnapshot({ last_event_id: 0 } as Snapshot).merges).toEqual([])
})

// --- the card ------------------------------------------------------------------------------

test('one card for an agent: how many files, each with its diff to open, Apply and Discard', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<MergeCard merge={merge()} name="Coder" onDecide={onDecide} />)
  expect(screen.getByText("Take in Coder's work? · 2 files")).toBeInTheDocument()
  const list = screen.getByRole('group', { name: 'Files to take in' })
  expect(within(list).getByText('a.txt')).toBeInTheDocument()
  expect(within(list).getByText('b.txt')).toBeInTheDocument()
  expect(within(list).getByText('+2')).toBeInTheDocument()
  expect(screen.queryByText('Changed in the project meanwhile')).not.toBeInTheDocument()
  expect(screen.queryByText(/did not finish/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenCalledWith('approve', {}, {})
  await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
  expect(onDecide).toHaveBeenLastCalledWith('reject')
  expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
})

test('files that changed in the project meanwhile stand apart, and what is already in is not asked about', () => {
  const mixed = merge({
    files: [
      { path: 'a.txt', kind: 'new', state: 'applied', diff: DIFF, additions: 1, deletions: 0, note: null },
      { path: 'hello.py', kind: 'changed', state: 'conflict', whole: true, diff: DIFF, additions: 1, deletions: 1, note: 'changed in the project meanwhile, and not merged line by line: git was not found on this machine' },
      { path: 'blob.bin', kind: 'new', state: 'ready', diff: null, additions: null, deletions: null, note: null },
      { path: '.github/x.yml', kind: 'new', state: 'refused', diff: null, additions: null, deletions: null, note: 'no trigger allows it' },
    ],
  })
  render(<MergeCard merge={mixed} name="Coder" unfinished onDecide={vi.fn()} />)
  // the count is of what the decision is about
  expect(screen.getByText("Take in Coder's work? · 2 files")).toBeInTheDocument()
  // (what the card says of such a file, and the choice it asks for: MergeCard.test.tsx)
  const apart = screen.getByRole('group', { name: 'Changed on both sides' })
  expect(within(apart).getByText('hello.py', { selector: '.merge-file-path' })).toBeInTheDocument()
  expect(within(screen.getByRole('group', { name: 'Files to take in' })).getByText('blob.bin')).toBeInTheDocument()
  // a file that is not text has no diff, and no numbers are made up for it
  expect(screen.getByText(/Not text, or too large to show/)).toBeInTheDocument()
  expect(screen.getByText(/Already in the project/)).toHaveTextContent('a.txt')
  expect(screen.getByText(/Not taken/)).toHaveTextContent('.github/x.yml — no trigger allows it')
  expect(screen.getByText('Coder did not finish its work: this is what it had changed.')).toBeInTheDocument()
})

// --- after a restart: the copy that was kept ---------------------------------------------------

const KEPT = 'C:\\runtime\\copies\\coder\\tree'
const kept = (over: Partial<Merge> = {}) => merge({ status: 'kept', kept_in: KEPT, ...over })

test('a kept copy comes back as a card: what it had changed, where it is, Apply or Discard', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<MergeCard merge={kept()} name="Coder" onDecide={onDecide} />)
  expect(screen.getByText("Coder's changes did not reach the project — take in what it had changed? · 2 files")).toBeInTheDocument()
  expect(within(screen.getByRole('group', { name: 'Files to take in' })).getByText('a.txt')).toBeInTheDocument()
  expect(screen.getByText(/Its working copy is kept in/)).toHaveTextContent(`${KEPT}. Discard deletes that folder.`)
  // its turn is over: nothing is held, and the card does not say so
  expect(screen.queryByText(/Until you decide it holds these files/)).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenCalledWith('approve', {}, {})
  await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
  expect(onDecide).toHaveBeenLastCalledWith('reject')
})

test('a kept copy that cannot be compared is only to discard, and says where it is', () => {
  const why = `interrupted by a restart: its files are kept in ${KEPT}`
  const unread = kept({ files: [{ path: 'a.txt', kind: 'new', state: 'refused', diff: null, additions: null, deletions: null, note: why }] })
  render(<MergeCard merge={unread} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByText("Coder's changes did not reach the project — nothing of it can be taken in from here")).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Take in' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument()
  expect(screen.getByText(/Not taken/)).toHaveTextContent(`a.txt — ${why}`)
  expect(screen.getByText(/Its working copy is kept in/)).toHaveTextContent(KEPT)
})

test('a copy kept for files that were not taken says that some of it is in the project, not that it was interrupted', () => {
  const link = 'a link is in its path'
  const files: Merge['files'] = [
    { path: 'a.txt', kind: 'new', state: 'applied', diff: DIFF, additions: 1, deletions: 0, note: null },
    { path: 'out/b.txt', kind: 'new', state: 'refused', diff: null, additions: null, deletions: null, note: link },
  ]
  const { rerender } = render(<MergeCard merge={kept({ files })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByText("Some of Coder's changes are in the project, the rest is kept in its copy — nothing more of it can be taken in from here")).toBeInTheDocument()
  expect(screen.queryByText(/Interrupted/)).not.toBeInTheDocument()
  expect(screen.getByText(/Already in the project/)).toHaveTextContent('a.txt')
  expect(screen.getByText(/Not taken/)).toHaveTextContent(`out/b.txt — ${link}`)
  expect(screen.queryByRole('button', { name: 'Take in' })).not.toBeInTheDocument()
  // with a file still to take, that is what is asked
  rerender(<MergeCard merge={kept({ files: [...files, merge().files[1]] })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByText("Some of Coder's changes are in the project, the rest is kept in its copy — take in what it had changed? · 1 file")).toBeInTheDocument()
  // nothing of it in the project: whether its turn broke off is not on the card, and is not said
  rerender(<MergeCard merge={kept({ files: [files[1]] })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByText("Coder's changes did not reach the project — nothing of it can be taken in from here")).toBeInTheDocument()
})

test('a kept copy with nothing to say what it started from shows its files against the project as it is now, and says so', () => {
  const differs = { state: 'conflict' as const, diff: DIFF, additions: 1, deletions: 0, note: null, two_way: true }
  const unknown = kept({ files: [{ path: 'a.txt', kind: 'new', ...differs }, { path: 'b.txt', kind: 'changed', ...differs }] })
  render(<MergeCard merge={unknown} name="Coder" onDecide={vi.fn()} />)
  // not "what it had changed": which side changed a file is not known
  expect(screen.getByText("Coder's changes did not reach the project — take in what its copy holds? · 2 files")).toBeInTheDocument()
  const group = screen.getByRole('group', { name: 'Differs from the project' })
  expect(within(group).getByText('a.txt')).toBeInTheDocument()
  expect(within(group).getByText('b.txt')).toBeInTheDocument()
  expect(group).toHaveTextContent(
    "What Coder's copy started from is not known, so these are shown against the project as it is now: each differs, and whether the copy or the project changed it cannot be told.",
  )
  expect(group).toHaveTextContent("Take in puts the copy's file in the project, over the project's where it has one; it deletes nothing.")
  expect(screen.queryByText('Changed in the project meanwhile')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Take in' })).toBeInTheDocument()
})

test('such a card does not offer the files nothing says the agent changed, and says how many and why', () => {
  const differs = { state: 'conflict' as const, diff: DIFF, additions: 1, deletions: 0, note: null, two_way: true }
  const other = { kind: 'changed' as const, state: 'left_out' as const, diff: null, additions: null, deletions: null, note: 'not offered', two_way: true }
  const unknown = kept({ files: [{ path: 'a.txt', kind: 'new', ...differs }, { path: 'hello.py', ...other }, { path: 'src/app.py', ...other }] })
  const { rerender } = render(<MergeCard merge={unknown} name="Coder" onDecide={vi.fn()} />)
  // they are not among what Apply takes, and are not listed one by one
  expect(screen.getByText(/take in what its copy holds\? · 1 file$/)).toBeInTheDocument()
  expect(screen.getByText('2 other files differ from the project and are not offered: what this copy started from is not known.')).toBeInTheDocument()
  expect(screen.queryByText('hello.py')).not.toBeInTheDocument()
  expect(screen.queryByText(/Not taken/)).not.toBeInTheDocument()
  // nothing but such files: only to discard
  rerender(<MergeCard merge={kept({ files: [{ path: 'hello.py', ...other }] })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByText('1 other file differs from the project and is not offered: what this copy started from is not known.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Take in' })).not.toBeInTheDocument()
  // once it is decided they are not lines of what was not applied: nothing says they were the agent's
  cleanup()
  render(<NotApplied merge={merge({ status: 'applied', files: [{ path: 'a.txt', kind: 'new', ...differs, state: 'applied' }, { path: 'hello.py', ...other }] })} name="Coder" />)
  expect(screen.queryByRole('group')).not.toBeInTheDocument()
})

test('B-189: a new file git ignores is said by name as not offered and not kept, apart from the rest', () => {
  const ready = { state: 'ready' as const, diff: DIFF, additions: 1, deletions: 0, note: null }
  const ignored = { kind: 'new' as const, state: 'left_out' as const, diff: null, additions: null, deletions: null, note: 'not offered: ignored by git - it is not kept' }
  render(<MergeCard merge={merge({ files: [{ path: 'a.py', kind: 'new', ...ready }, { path: 'data/clean.csv', ...ignored }] })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByText(/Not offered, ignored by git \(not kept\):/)).toHaveTextContent('Not offered, ignored by git (not kept): data/clean.csv')
  expect(screen.queryByText(/other file differs from the project/)).not.toBeInTheDocument()
})

test('the chat and the inspector show the kept copy as its card, not as lines of what was not applied', () => {
  const after = { ...state, runs: [run('r', 'interrupted')], merges: [kept()] }
  render(<MessageList {...handlers} state={after} onDecideMerge={vi.fn()} />)
  expect(screen.getAllByText(/Coder's changes did not reach the project/)).toHaveLength(1)
  expect(screen.queryByRole('group', { name: "Not all of Coder's work reached the project" })).not.toBeInTheDocument()
  cleanup()
  const renderMerge = vi.fn((m: Merge, of: Agent) => <div>card {m.id} of {of.id}</div>)
  render(<Inspector state={after} selectedId="agent:coder" onClose={() => {}} renderMerge={renderMerge} />)
  expect(screen.getByText('card g1 of coder')).toBeInTheDocument()
  // it does not wait for you the way a turn that runs does: the box says nothing of approval
  expect(agentData(deriveGraph(after), 'agent:coder').activity).not.toMatch(/approval/i)
  // once its folder is gone there is no card, and the lines say why
  cleanup()
  const gone = merge({ status: 'discarded', files: [{ path: 'a.txt', kind: 'new', state: 'refused', diff: null, additions: null, deletions: null, note: 'the folder its files were kept in is gone' }] })
  render(<MessageList {...handlers} state={{ ...after, merges: [gone] }} onDecideMerge={vi.fn()} />)
  expect(screen.queryByText(/did not reach the project/)).not.toBeInTheDocument()
  expect(screen.getByText('a.txt').parentElement).toHaveTextContent('a.txt — the folder its files were kept in is gone')
})

test('the agent whose changes wait is the one that asks, not the lead', () => {
  const g = deriveGraph(state)
  expect(agentData(g, 'agent:coder')).toMatchObject({ status: 'waiting_approval', activity: 'Waits for your approval', attention: true })
  expect(agentData(g, 'agent:lead')).toMatchObject({ status: 'waiting', attention: false })
  // once they are in the project it is done like any other
  const after = deriveGraph({ ...state, merges: [merge({ status: 'applied' })] })
  expect(agentData(after, 'agent:coder')).toMatchObject({ status: 'completed', attention: false })
})

// --- the chat and the inspector --------------------------------------------------------------

test('the chat shows the one card under the agent, and its buttons carry the decision', async () => {
  const onDecideMerge = vi.fn().mockResolvedValue(undefined)
  const { rerender } = render(<MessageList {...handlers} state={state} onDecideMerge={onDecideMerge} />)
  expect(screen.getAllByText(/Take in Coder's work\?/)).toHaveLength(1)
  // nothing is asked change by change
  expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  // (no file of it clashes: no choices to carry)
  expect(onDecideMerge).toHaveBeenCalledWith('g1', 'approve', {}, {})
  // decided: the card is gone
  rerender(<MessageList {...handlers} state={{ ...state, merges: [merge({ status: 'rejected' })] }} onDecideMerge={onDecideMerge} />)
  expect(screen.queryByText(/Take in Coder's work/)).not.toBeInTheDocument()
})

test('the inspector shows the card with the agent it is of, and says where the agent works', () => {
  const renderMerge = vi.fn((m: Merge, of: Agent) => <div>card {m.id} of {of.id}</div>)
  const { rerender } = render(<Inspector state={state} selectedId="agent:coder" onClose={() => {}} renderMerge={renderMerge} />)
  expect(screen.getByText('card g1 of coder')).toBeInTheDocument()
  expect(screen.getByText(/It works in its own copy: the project gets its changes when its work is over\./)).toBeInTheDocument()
  rerender(<Inspector state={state} selectedId="agent:lead" onClose={() => {}} renderMerge={renderMerge} />)
  expect(screen.queryByText(/card g1/)).not.toBeInTheDocument()
  expect(screen.queryByText(/copy/)).not.toBeInTheDocument()
  rerender(<Inspector state={{ ...state, agents: state.agents.map(a => (a.id === 'coder' ? { ...a, copy: { state: 'too_big' as const } } : a)) }} selectedId="agent:coder" onClose={() => {}} renderMerge={renderMerge} />)
  expect(screen.getByText(/This project is too big to copy/)).toBeInTheDocument()
})

test('the top bar names the agent whose changes wait for you, not one that is still at work', () => {
  const busy = agent('r', 'running', { id: 'tester', parent_agent_id: 'lead', role_name: 'Tester', depth: 1, task: 'C' })
  const { container, rerender } = render(<RunStatus conv={{ ...state, agents: [...state.agents, busy] }} connection="open" />)
  // (Ready: the words "wait for you" are the top bar's pill; the run status names the agent only.)
  const waiting = container.querySelector('[data-run="waiting_approval"]')
  expect(waiting).toHaveTextContent('Coder')
  expect(waiting).not.toHaveTextContent('Tester')
  // decided: it is whoever is at work again
  rerender(<RunStatus conv={{ ...state, runs: [run('r', 'running')], merges: [], agents: [...state.agents, busy] }} connection="open" />)
  expect(screen.getByText(/WORKING/)).toHaveTextContent('WORKING · Tester')
})

// --- what did not reach the project, and why ---------------------------------------------------

const file = (path: string, over: Partial<Merge['files'][number]> = {}): Merge['files'][number] => ({
  path,
  kind: 'new',
  state: 'refused',
  diff: null,
  additions: null,
  deletions: null,
  note: null,
  ...over,
})
/** Settled, and not all of it is in the project. */
const settled = merge({
  status: 'applied',
  files: [
    file('a.txt', { state: 'applied' }),
    file('.github/x.yml', { note: 'no trigger allows it' }),
    file('hello.py', { kind: 'changed', state: 'conflict' }),
    file('ext/a.bin'),
  ],
})

test('an agent whose project could not be copied says so, and not that it is too big', () => {
  const failed = { ...state.agents[1], copy: { state: 'failed' as const } }
  expect(copyLine(state, failed)).toBe('could not be copied — works in the project')
  render(<Inspector state={{ ...state, agents: [state.agents[0], failed] }} selectedId="agent:coder" onClose={() => {}} />)
  expect(screen.getByText(/This project could not be copied: it works in the project itself/)).toBeInTheDocument()
  expect(screen.queryByText(/too big/)).not.toBeInTheDocument()
})

test('a change thrown away with its copy is discarded; rejected is what you said no to', () => {
  expect(CHANGE_LABEL.discarded[0]).toBe('Discarded')
  expect(CHANGE_LABEL.rejected[0]).toBe('Rejected')
})

test('once it is settled, each file that did not reach the project is a line that says why', () => {
  const { rerender } = render(<NotApplied merge={settled} name="Coder" />)
  const lines = screen.getByRole('group', { name: "Not all of Coder's work reached the project" })
  expect(within(lines).getByText('.github/x.yml').parentElement).toHaveTextContent('.github/x.yml — no trigger allows it')
  expect(within(lines).getByText('hello.py').parentElement).toHaveTextContent('hello.py — changed in the project meanwhile')
  expect(within(lines).getByText('ext/a.bin').parentElement).toHaveTextContent('ext/a.bin — not taken')
  expect(within(lines).queryByText('a.txt')).not.toBeInTheDocument()
  // what you turned down says so; after a restart it says where the files are
  rerender(<NotApplied merge={merge({ status: 'rejected' })} name="Coder" />)
  expect(screen.getByText('a.txt').parentElement).toHaveTextContent('a.txt — you discarded it')
  // also for a file that had changed in the project meanwhile: the reason it is not there is your no
  const turnedDown = merge({ status: 'rejected', files: [file('hello.py', { state: 'conflict' }), file('c.txt', { note: 'could not be written' })] })
  rerender(<NotApplied merge={turnedDown} name="Coder" />)
  expect(screen.getByText('hello.py').parentElement).toHaveTextContent('hello.py — you discarded it')
  expect(screen.getByText('c.txt').parentElement).toHaveTextContent('c.txt — you discarded it')
  const kept = 'interrupted by a restart: its files are kept in C:\\runtime\\copies\\coder'
  rerender(<NotApplied merge={merge({ status: 'interrupted', files: [file('a.txt', { note: kept })] })} name="Coder" />)
  expect(screen.getByText('a.txt').parentElement).toHaveTextContent(`a.txt — ${kept}`)
  // nothing while the card still asks, and nothing when all of it is in
  rerender(<NotApplied merge={merge()} name="Coder" />)
  expect(screen.queryByRole('group')).not.toBeInTheDocument()
  rerender(<NotApplied merge={merge({ status: 'applied', files: [file('a.txt', { state: 'applied' })] })} name="Coder" />)
  expect(screen.queryByRole('group')).not.toBeInTheDocument()
})

test('the lines are with the agent: in its Changes, in its window, and under it in a turn nobody watched', async () => {
  // not text and never a change record: there is nothing else to show it by
  const quiet = { ...state, runs: [run('r', 'completed', { unattended: true })], fileChanges: [], merges: [settled] }
  // (its Changes are open from the start)
  const { unmount } = render(<Inspector state={quiet} selectedId="agent:coder" onClose={() => {}} />)
  expect(screen.getByRole('group', { name: "Not all of Coder's work reached the project" })).toHaveTextContent('ext/a.bin — not taken')
  unmount()
  const window = render(<AgentWindow state={quiet} agentId="coder" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByRole('group', { name: "Not all of Coder's work reached the project" })).toBeInTheDocument()
  window.unmount()
  render(<MessageList {...handlers} state={quiet} />)
  expect(screen.getByRole('group', { name: "Not all of Coder's work reached the project" })).toHaveTextContent('.github/x.yml — no trigger allows it')
})

test('an agent whose card waits is not said to be done: its row says its changes wait for you', () => {
  const { rerender } = render(<MessageList {...handlers} state={state} />)
  const row = () => screen.getByRole('button', { name: /Coder/, description: 'Show this agent on the canvas' })
  expect(row()).toHaveTextContent('changes wait for your decision')
  expect(row()).not.toHaveTextContent('done')
  rerender(<MessageList {...handlers} state={{ ...state, merges: [merge({ status: 'applied' })] }} />)
  expect(row()).toHaveTextContent('done')
  // and so its own window
  rerender(<AgentWindow state={state} agentId="coder" onClose={() => {}} onOpenChange={() => {}} onSelectAgent={() => {}} />)
  expect(screen.getByLabelText('Agent window')).toHaveTextContent('changes wait for your decision')
})

test('a file that could not be written says why on the card that asks again', () => {
  const again = merge({ files: [file('b.txt', { state: 'ready', note: 'could not be taken: the disk is full' })] })
  render(<MergeCard merge={again} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByText(/could not be taken: the disk is full/)).toBeInTheDocument()
})

test('an agent that waits for a file whose holder waits for you says so', () => {
  const waiting = {
    ...state,
    agents: [...state.agents, agent('r', 'blocked', { id: 'coder2', parent_agent_id: 'lead', role_name: 'Coder', name: 'Coder 2', depth: 1, task: 'B', waiting_for: { agent_id: 'coder', agent_name: 'Coder', path: 'a.txt' } })],
    claims: [{ path: 'a.txt', agent_id: 'coder' }],
  }
  const { rerender } = render(<Inspector state={waiting} selectedId="agent:coder2" onClose={() => {}} />)
  expect(screen.getByRole('note')).toHaveTextContent("Coder's changes wait for you: it goes on when you have decided.")
  rerender(<Inspector state={{ ...waiting, merges: [] }} selectedId="agent:coder2" onClose={() => {}} />)
  expect(screen.getByRole('note')).toHaveTextContent('It goes on when Coder is done with the file.')
})
