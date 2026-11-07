import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { Merge, MergeFile } from '../api/types'
import { MessageList } from '../chat/MessageList'
import { keptNote } from '../agents/teamRun'
import { agent, assistantMessage, convState, fileChange, run, toolCall, userMessage } from '../test-fixtures'
import { canContinue, cardMerges, hasCard } from './copies'
import { MergeCard } from './MergeCard'
import { useApp } from '../state/store'

/** Slice 30: a file both sides changed is merged line by line; what clashes is asked about; a check; a commit. */

const DIFF = '--- a/lines.txt\n+++ b/lines.txt\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO-agent\n three'
const CLASH = '--- a/lines.txt\n+++ b/lines.txt\n@@ -1,3 +1,3 @@\n one\n-TWO-user\n+TWO-agent\n three'
/** What goes in whichever side is taken of the lines that clash. */
const REST = '--- a/lines.txt\n+++ b/lines.txt\n@@ -5,3 +5,3 @@\n five\n-six\n+SIX-agent\n seven'

const file = (path: string, over: Partial<MergeFile> = {}): MergeFile => ({
  path,
  kind: 'changed',
  state: 'ready',
  diff: DIFF,
  additions: 1,
  deletions: 1,
  note: null,
  ...over,
})

const merge = (over: Partial<Merge> = {}): Merge => ({
  id: 'g1',
  run_id: 'r',
  agent_id: 'coder',
  status: 'pending',
  files: [file('a.txt', { kind: 'new' })],
  kept_in: null,
  check: null,
  commit: null,
  created_at: '2026-10-13T10:00:00Z',
  decided_at: null,
  ...over,
})

/** The same lines changed on both sides; the user's change came last. */
const lines = file('lines.txt', {
  state: 'conflict',
  whole: false,
  diff: REST,
  clash: CLASH,
  sides: { project: { changed_at: '2026-10-13T10:05:00Z' }, agent: { changed_at: '2026-10-13T10:01:00Z' }, newer: 'project' },
})
/** Not text: the two files stand against each other as wholes. */
const blob = file('blob.bin', {
  state: 'conflict',
  whole: true,
  diff: null,
  additions: null,
  deletions: null,
  note: 'changed in the project meanwhile, and not merged line by line: it is not text, or is larger than 1 MiB',
  sides: { project: { changed_at: '2026-10-13T10:00:30Z' }, agent: { changed_at: '2026-10-13T10:02:00Z' }, newer: 'agent' },
})

// --- the files -------------------------------------------------------------------------------

test('a file that went together with the project’s changes stands apart, says so, and is taken with Apply like any other', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<MergeCard merge={merge({ files: [file('a.txt', { kind: 'new' }), file('lines.txt', { state: 'merged' })] })} name="Coder" onDecide={onDecide} />)
  expect(screen.getByText("Take in Coder's work? · 2 files")).toBeInTheDocument()
  const group = screen.getByRole('group', { name: "Merged with the project's changes" })
  expect(within(group).getByText('lines.txt')).toBeInTheDocument()
  expect(group).toHaveTextContent("The project changed these too. Coder's changes and the project's are put together line by line: each diff shows what that does to the project's file as it is now.")
  expect(within(screen.getByRole('group', { name: 'Files to take in' })).queryByText('lines.txt')).not.toBeInTheDocument()
  // nothing clashes: nothing is asked file by file
  expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenCalledWith('approve', {}, {})
})

test('the same lines: what clashes, when each side changed it and which is newer - and nothing is applied before you say whose are taken', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  render(<MergeCard merge={merge({ files: [file('a.txt', { kind: 'new' }), lines] })} name="Coder" onDecide={onDecide} />)
  const group = screen.getByRole('group', { name: 'Changed on both sides' })
  const one = within(group).getByRole('group', { name: 'lines.txt' })
  // both sides of what clashes
  expect(one).toHaveTextContent("The same lines changed on both sides: − the project's lines, + Coder's.")
  expect(within(one).getByText('TWO-user')).toBeInTheDocument()
  expect(within(one).getByText('TWO-agent')).toBeInTheDocument()
  // both times, and the mark on the later one - it is only said
  const [projects, agents] = within(one).getAllByText((_text, element) => element?.tagName === 'TIME')
  expect(projects).toHaveAttribute('datetime', '2026-10-13T10:05:00Z')
  expect(agents).toHaveAttribute('datetime', '2026-10-13T10:01:00Z')
  // (a word of its own: read out as one, not run into the time)
  expect(projects.parentElement?.textContent).toMatch(/^The project's file: .*\S newer$/)
  expect(agents.parentElement).toHaveTextContent(/^Coder's change: /)
  expect(agents.parentElement).not.toHaveTextContent('newer')
  const choice = within(one).getByRole('radiogroup', { name: 'Whose lines of lines.txt' })
  expect(within(choice).getByRole('radio', { name: "Take Coder's lines" })).not.toBeChecked()
  expect(within(choice).getByRole('radio', { name: "Keep the project's lines" })).not.toBeChecked()
  // what does not clash is not part of the choice
  expect(one).toHaveTextContent("The rest of Coder's changes to it is taken either way, and what else the project changed in it stays")
  expect(within(one).getByText('SIX-agent')).toBeInTheDocument()
  // nothing is chosen for you
  expect(screen.getByRole('button', { name: 'Take in' })).toBeDisabled()
  expect(group).toHaveTextContent('Say whose side is taken of this file: until then nothing is taken in. Nothing is chosen for you; which side is newer is only said.')
  await userEvent.click(within(choice).getByRole('radio', { name: "Keep the project's lines" }))
  expect(group).toHaveTextContent('Take in takes what you chose.')
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenCalledWith('approve', { 'lines.txt': 'project' }, {})
  // Discard needs no choice, and carries none
  await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
  expect(onDecide).toHaveBeenLastCalledWith('reject')
})

test('a file that could not be merged line by line is asked about whole, and says why; a side whose time is not known says that', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const gone = file('gone.txt', {
    kind: 'deleted',
    state: 'conflict',
    whole: true,
    note: 'changed in the project meanwhile, and not merged line by line: one side deleted it and the other changed it',
    sides: { project: { changed_at: '2026-10-13T10:05:00Z' }, agent: { changed_at: null }, newer: null },
  })
  render(<MergeCard merge={merge({ files: [blob, gone, lines] })} name="Coder" onDecide={onDecide} />)
  const one = screen.getByRole('group', { name: 'blob.bin' })
  expect(one).toHaveTextContent('blob.bin — changed in the project meanwhile, and not merged line by line: it is not text, or is larger than 1 MiB')
  expect(within(one).getByRole('radio', { name: "Take Coder's file" })).toBeInTheDocument()
  expect(within(one).getByRole('radio', { name: "Keep the project's file" })).toBeInTheDocument()
  expect(within(one).getByText('newer').parentElement).toHaveTextContent(/^Coder's change: /)
  const other = screen.getByRole('group', { name: 'gone.txt' })
  expect(other).toHaveTextContent("Coder's change: not known")
  expect(within(other).queryByText('newer')).not.toBeInTheDocument()
  // each file is asked about; what is said of two is not yet all three
  expect(screen.getByRole('group', { name: 'Changed on both sides' })).toHaveTextContent('Say whose side is taken of each of these, 3 still')
  await userEvent.click(within(one).getByRole('radio', { name: "Take Coder's file" }))
  await userEvent.click(within(other).getByRole('radio', { name: "Keep the project's file" }))
  expect(screen.getByRole('button', { name: 'Take in' })).toBeDisabled()
  await userEvent.click(screen.getByRole('radio', { name: "Take Coder's lines" }))
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenCalledWith('approve', { 'blob.bin': 'agent', 'gone.txt': 'project', 'lines.txt': 'agent' }, {})
})

test('B-56: Apply sends what the card shows; a file that moved since is shown again, the refusal says why, and the choice made on the old one is gone', async () => {
  const fresh = file('a.txt', { kind: 'new', shown: [null, 'n1'] })
  const before = { ...lines, shown: ['p1', 'a1'] }
  const onDecide = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(409, 'lines.txt changed since you looked: nothing was taken in. Check the card again'))
    .mockResolvedValue(undefined)
  const { rerender } = render(<MergeCard merge={merge({ files: [fresh, before] })} name="Coder" onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('radio', { name: "Take Coder's lines" }))
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenLastCalledWith('approve', { 'lines.txt': 'agent' }, { 'a.txt': [null, 'n1'], 'lines.txt': ['p1', 'a1'] })
  expect(await screen.findByRole('alert')).toHaveTextContent('lines.txt changed since you looked: nothing was taken in. Check the card again')
  // The card as it is now comes as its record: the user's later lines, and no choice of the old ones.
  const after = { ...lines, clash: CLASH.replace('TWO-user', 'TWO-user-later'), shown: ['p2', 'a1'] }
  rerender(<MergeCard merge={merge({ files: [fresh, after] })} name="Coder" onDecide={onDecide} />)
  expect(screen.getByText('TWO-user-later')).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: "Take Coder's lines" })).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Take in' })).toBeDisabled()
  await userEvent.click(screen.getByRole('radio', { name: "Keep the project's lines" }))
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenLastCalledWith('approve', { 'lines.txt': 'project' }, { 'a.txt': [null, 'n1'], 'lines.txt': ['p2', 'a1'] })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('keeping the project’s whole file holds when the project rewrites it (it writes nothing); taking Coder’s does not', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const card = (shown: string) => merge({ files: [{ ...blob, shown: ['p' + shown, 'a1'] }, { ...blob, path: 'other.bin', shown: ['q' + shown, 'b1'] }] })
  const { rerender } = render(<MergeCard merge={card('1')} name="Coder" onDecide={onDecide} />)
  const whose = (path: string) => screen.getByRole('radiogroup', { name: `Whose file of ${path}` })
  await userEvent.click(within(whose('blob.bin')).getByRole('radio', { name: "Keep the project's file" }))
  await userEvent.click(within(whose('other.bin')).getByRole('radio', { name: "Take Coder's file" }))
  rerender(<MergeCard merge={card('2')} name="Coder" onDecide={onDecide} />)
  expect(within(whose('blob.bin')).getByRole('radio', { name: "Keep the project's file" })).toBeChecked()
  expect(within(whose('other.bin')).getByRole('radio', { name: "Take Coder's file" })).not.toBeChecked()
  await userEvent.click(within(whose('other.bin')).getByRole('radio', { name: "Keep the project's file" }))
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenLastCalledWith('approve', { 'blob.bin': 'project', 'other.bin': 'project' }, { 'blob.bin': ['p2', 'a1'], 'other.bin': ['q2', 'b1'] })
})

test('once your choice is written into the copy the file is one that went together, and the card says whose lines it has', () => {
  render(<MergeCard merge={merge({ files: [file('lines.txt', { state: 'merged', chose: 'project' })] })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByRole('group', { name: "Merged with the project's changes" })).toHaveTextContent(
    "Where the same lines had changed on both sides, they are as you chose: lines.txt — the project's.",
  )
  expect(screen.queryByRole('group', { name: 'Changed on both sides' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Take in' })).toBeEnabled()
})

// --- the check -------------------------------------------------------------------------------

const check = (over: Partial<NonNullable<Merge['check']>> = {}): NonNullable<Merge['check']> => ({
  command: 'python -m pytest -q',
  state: 'not_run',
  exit_code: null,
  output: null,
  note: null,
  stale: false,
  ...over,
})

test('with no check command the card says that nothing was checked', () => {
  render(<MergeCard merge={merge()} name="Coder" onDecide={vi.fn()} onCheck={vi.fn()} />)
  expect(screen.getByText('No test command is set: not tested.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Run the test/ })).not.toBeInTheDocument()
  expect(screen.queryByText(/passed/)).not.toBeInTheDocument()
})

test('a check that has not run says so, and you start it from the card - with what you chose, and not before', async () => {
  const onCheck = vi.fn().mockResolvedValue(undefined)
  render(<MergeCard merge={merge({ files: [lines], check: check() })} name="Coder" onDecide={vi.fn()} onCheck={onCheck} />)
  const block = screen.getByRole('group', { name: 'Test' })
  expect(within(block).getByText('python -m pytest -q')).toBeInTheDocument()
  expect(within(block).getByText('not run')).toBeInTheDocument()
  // what of it is undone afterwards, and what is not: the linked folders are the project's own
  expect(block).toHaveTextContent(
    "It runs in the copy, on what Take in would take. What it writes to the copy's own files is put back afterwards; the dependency folders linked into the copy (node_modules, .venv, venv) are the project's own, and what it writes there stays.",
  )
  expect(block).not.toHaveTextContent('not touched')
  const start = within(block).getByRole('button', { name: 'Run the test' })
  expect(start).toBeDisabled()
  expect(screen.getByRole('group', { name: 'Changed on both sides' })).toHaveTextContent('until then nothing is taken in, and the test does not run.')
  await userEvent.click(screen.getByRole('radio', { name: "Take Coder's lines" }))
  await userEvent.click(start)
  expect(onCheck).toHaveBeenCalledWith({ 'lines.txt': 'agent' })
})

test('a check not run says why as a warning, and Apply is not held back (B-355)', () => {
  const note = 'below Full auto it runs only when you say: press Run the test before you Take in'
  const { rerender } = render(<MergeCard merge={merge({ check: check({ note }) })} name="Coder" onDecide={vi.fn()} onCheck={vi.fn()} />)
  const block = within(screen.getByRole('group', { name: 'Test' }))
  expect(block.getByText('not run')).toHaveClass('tag-warn')
  expect(block.getByText(note)).not.toHaveClass('muted')
  expect(screen.getByRole('button', { name: 'Take in' })).toBeEnabled()
  // (with no reason given it is the plain tag, as before)
  rerender(<MergeCard merge={merge({ check: check() })} name="Coder" onDecide={vi.fn()} onCheck={vi.fn()} />)
  expect(within(screen.getByRole('group', { name: 'Test' })).getByText('not run')).not.toHaveClass('tag-warn')
})

test('while it runs nothing is applied or discarded; "passed" is said only of exit code 0, and a failed one shows its code and the end of what it wrote', async () => {
  const { rerender } = render(<MergeCard merge={merge({ check: check({ state: 'running' }) })} name="Coder" onDecide={vi.fn()} onCheck={vi.fn()} />)
  expect(within(screen.getByRole('group', { name: 'Test' })).getByText('running…')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Run the test' })).toBeDisabled()
  // neither answer is taken meanwhile, and the card says what they wait for
  expect(screen.getByRole('button', { name: 'Take in' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Discard' })).toBeDisabled()
  expect(screen.getByRole('group', { name: 'Test' })).toHaveTextContent('Take in and Discard wait until the test is over.')
  rerender(<MergeCard merge={merge({ check: check({ state: 'passed', exit_code: 0, output: '2 passed' }) })} name="Coder" onDecide={vi.fn()} onCheck={vi.fn()} />)
  const block = screen.getByRole('group', { name: 'Test' })
  expect(within(block).getByText('passed')).toBeInTheDocument()
  expect(within(block).getByText('exit code 0')).toBeInTheDocument()
  expect(within(block).getByText('2 passed')).toBeInTheDocument()
  expect(block).not.toHaveTextContent('earlier state')
  expect(block).not.toHaveTextContent('wait until the test is over')
  expect(screen.getByRole('button', { name: 'Run the test again' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Take in' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Discard' })).toBeEnabled()
  // failed: the decision is still yours
  rerender(<MergeCard merge={merge({ check: check({ state: 'failed', exit_code: 1, output: 'AssertionError' }) })} name="Coder" onDecide={vi.fn()} onCheck={vi.fn()} />)
  expect(within(screen.getByRole('group', { name: 'Test' })).getByText('failed')).toBeInTheDocument()
  expect(screen.getByText('exit code 1')).toBeInTheDocument()
  expect(screen.getByText('AssertionError')).toBeInTheDocument()
  expect(screen.queryByText('passed')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Take in' })).toBeEnabled()
  // one that never came to an end has no exit code, and says why instead
  rerender(<MergeCard merge={merge({ check: check({ state: 'failed', note: 'timed out after 600 seconds and was stopped' }) })} name="Coder" onDecide={vi.fn()} onCheck={vi.fn()} />)
  expect(screen.getByRole('group', { name: 'Test' })).toHaveTextContent('failed')
  expect(screen.getByText('timed out after 600 seconds and was stopped')).toBeInTheDocument()
  expect(screen.queryByText(/exit code/)).not.toBeInTheDocument()
})

test('a result of an earlier state is said to be that, and one that did not run says why', () => {
  const { rerender } = render(<MergeCard merge={merge({ check: check({ state: 'passed', exit_code: 0, stale: true }) })} name="Coder" onDecide={vi.fn()} onCheck={vi.fn()} />)
  expect(screen.getByText('This result is of an earlier state: the files have changed since the test ran.')).toBeInTheDocument()
  rerender(<MergeCard merge={merge({ check: check({ note: 'the trigger of this turn does not let this command run: not checked' }) })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByRole('group', { name: 'Test' })).toHaveTextContent('not run')
  expect(screen.getByText('the trigger of this turn does not let this command run: not checked')).toBeInTheDocument()
})

test('a kept copy’s card shows how its check went and asks for the same choices, but the check is not run again there', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const kept = merge({ status: 'interrupted', kept_in: 'C:\\runtime\\copies\\coder\\tree', files: [lines], check: check({ state: 'failed', exit_code: 1 }) })
  render(<MergeCard merge={kept} name="Coder" onDecide={onDecide} onCheck={vi.fn()} />)
  const block = screen.getByRole('group', { name: 'Test' })
  expect(within(block).getByText('failed')).toBeInTheDocument()
  expect(block).toHaveTextContent('The test is not run on a kept copy: its dependency folders are no longer linked.')
  expect(screen.queryByRole('button', { name: /Run the test/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Take in' })).toBeDisabled()
  await userEvent.click(screen.getByRole('radio', { name: "Take Coder's lines" }))
  await userEvent.click(screen.getByRole('button', { name: 'Take in' }))
  expect(onDecide).toHaveBeenCalledWith('approve', { 'lines.txt': 'agent' }, {})
})

// --- the commit ------------------------------------------------------------------------------

const taken = merge({
  status: 'applied',
  decided_at: '2026-10-13T10:10:00Z',
  files: [file('a.txt', { kind: 'new', state: 'applied' }), file('lines.txt', { state: 'applied' }), file('blob.bin', { state: 'refused', note: "the project's own file was kept: the user chose it" })],
  commit: { state: 'offered', message: 'Coder: do it', sha: null },
})

test('once it is in the project the card goes on with the commit: the files taken, what it holds, a message to edit - and your click', async () => {
  const onCommit = vi.fn().mockResolvedValue(undefined)
  render(<MergeCard merge={taken} name="Coder" onDecide={vi.fn()} onCommit={onCommit} />)
  const step = screen.getByRole('group', { name: "Commit of Coder's changes" })
  expect(within(step).getByText("Commit these 2 files of Coder's?")).toBeInTheDocument()
  // the files that were taken - not the one that was not
  expect(within(step).getByText('a.txt, lines.txt')).toBeInTheDocument()
  expect(step).not.toHaveTextContent('blob.bin')
  expect(step).toHaveTextContent("The commit holds Coder's changes to these files and nothing else: edits of your own in them stay uncommitted, and what you have staged of other files stays staged (in these files it is unstaged, still in the file). A file where yours and Coder's touch the same lines goes in whole; one git ignores, or one you staged something in that the file does not hold, is left out - each is said. It is your commit: the repository's own name and its own hooks - a hook may change what goes in, and touch your files itself.")
  expect(step).not.toHaveTextContent('this changes a hook')
  // no Apply, no Discard: that is decided
  expect(screen.queryByRole('button', { name: 'Take in' })).not.toBeInTheDocument()
  const message = within(step).getByLabelText('Message')
  expect(message).toHaveValue('Coder: do it')
  await userEvent.clear(message)
  expect(within(step).getByRole('button', { name: 'Commit' })).toBeDisabled()
  await userEvent.type(message, "Take the Coder's work")
  await userEvent.click(within(step).getByRole('button', { name: 'Commit' }))
  expect(onCommit).toHaveBeenCalledWith("Take the Coder's work", undefined)
})

test('a commit that is refused says why and stays offered; "Not now" puts it aside without taking the offer away', async () => {
  const onCommit = vi.fn().mockRejectedValue({ detail: 'not committed: HEAD is not on a branch' })
  render(<MergeCard merge={taken} name="Coder" onDecide={vi.fn()} onCommit={onCommit} />)
  await userEvent.click(screen.getByRole('button', { name: 'Commit' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('not committed: HEAD is not on a branch')
  expect(screen.getByRole('button', { name: 'Commit' })).toBeEnabled()
  await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
  const aside = screen.getByRole('group', { name: "Commit of Coder's changes" })
  expect(aside).toHaveTextContent("Coder's 2 files are in the project, not committed.")
  expect(screen.queryByLabelText('Message')).not.toBeInTheDocument()
  await userEvent.click(within(aside).getByRole('button', { name: 'Commit…' }))
  expect(screen.getByLabelText('Message')).toHaveValue('Coder: do it')
})

test("where an agent changed git's hooks in the turn the commit asks: with them, or without", async () => {
  const onCommit = vi.fn().mockResolvedValue(undefined)
  const asks = merge({ ...taken, commit: { ...taken.commit!, asks: ['hooks'] } })
  render(<MergeCard merge={asks} name="Coder" onDecide={vi.fn()} onCommit={onCommit} />)
  const step = screen.getByRole('group', { name: "Commit of Coder's changes" })
  expect(step).toHaveTextContent("An agent changed this repository's commit hooks or git settings in this turn: commit with them, or without them?")
  expect(step).not.toHaveTextContent('.git/config was changed')
  expect(within(step).queryByRole('button', { name: 'Commit' })).not.toBeInTheDocument()
  await userEvent.click(within(step).getByRole('button', { name: 'Commit without them' }))
  expect(onCommit).toHaveBeenCalledWith('Coder: do it', 'without')
})

test('a taken file in a hook folder is warned about: it runs when you commit', () => {
  const hooks = merge({ ...taken, files: [file('.husky/pre-commit', { state: 'applied' }), file('tools/.githooks/pre-push', { state: 'applied' }), file('src/husky.ts', { state: 'applied' }), file('.pre-commit-config.yaml', { state: 'applied' }), file('docs/lefthook.yml.md', { state: 'applied' })] })
  render(<MergeCard merge={hooks} name="Coder" onDecide={vi.fn()} onCommit={vi.fn()} />)
  expect(screen.getByText('.husky/pre-commit').parentElement).toHaveTextContent('.husky/pre-commit — this changes a hook: it runs when you commit.')
  expect(screen.getByText('tools/.githooks/pre-push').parentElement).toHaveTextContent('this changes a hook')
  expect(screen.getByText('.pre-commit-config.yaml').parentElement).toHaveTextContent('this changes a hook')
  expect(screen.getAllByText(/this changes a hook/)).toHaveLength(3)
})

test('a commit that was made says which one it is; a merge with neither a decision to make nor a commit has no card', () => {
  const made = merge({ ...taken, commit: { state: 'committed', message: "Take the Coder's work", sha: '0123456789abcdef0123456789abcdef01234567', holds: 'a.txt | 1 +\n 1 file changed, 1 insertion(+)' } })
  const { container, rerender } = render(<MergeCard merge={made} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByRole('group', { name: "Commit of Coder's changes" })).toHaveTextContent("Committed 2 files of Coder's as 0123456789: Take the Coder's work")
  // what the commit holds, as git says of it
  expect(screen.getByText(/1 file changed, 1 insertion/)).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(screen.getByRole('group', { name: "Commit of Coder's changes" })).not.toHaveTextContent('went in whole')
  // what did not go in as the agent's change alone: each said, a sentence of its own
  const notes = ['lines.txt went in whole, as the project has it: any edits of your own there went into this commit too', '.env was left out of the commit: git ignores it']
  rerender(<MergeCard merge={merge({ ...taken, commit: { ...made.commit!, notes } })} name="Coder" onDecide={vi.fn()} />)
  const said = screen.getByRole('group', { name: "Commit of Coder's changes" })
  expect(within(said).getByText(`${notes[0]}.`)).toBeInTheDocument()
  expect(within(said).getByText('.env was left out of the commit: git ignores it.')).toBeInTheDocument()
  rerender(<MergeCard merge={merge({ ...taken, commit: null })} name="Coder" onDecide={vi.fn()} />)
  expect(container).toBeEmptyDOMElement()
})

test('a commit that is not offered says why, in one line where it would be', () => {
  const why = 'the project folder is a subfolder of a git repository'
  render(<MergeCard merge={merge({ ...taken, commit: { state: 'not_offered', message: why, sha: null } })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.getByRole('group', { name: "Commit of Coder's changes" })).toHaveTextContent(`Not offered as a commit: ${why}.`)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test('the chat shows the commit step under the agent after its changes are in, and its button carries the message', async () => {
  const state = convState({
    runs: [run('r', 'completed')],
    agents: [agent('r', 'completed', { id: 'lead' }), agent('r', 'completed', { id: 'coder', parent_agent_id: 'lead', role_name: 'Coder', depth: 1, task: 'do it', tool_call_id: 's1', copy: { state: 'own' } })],
    messages: [userMessage('r', 'go'), { ...assistantMessage('m0', 'r', ''), agent_id: 'lead' }],
    toolCalls: [toolCall('s1', 'r', 'spawn_agent', 'succeeded', '{"role":"Coder","task":"do it"}', { agent_id: 'lead', message_id: 'm0' })],
    merges: [taken],
  })
  expect(hasCard(taken)).toBe(true)
  expect(cardMerges(state, 'coder')).toEqual([taken])
  expect(hasCard(merge({ ...taken, commit: null }))).toBe(false)
  const onCommitMerge = vi.fn().mockResolvedValue(undefined)
  const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn() }
  render(<MessageList {...handlers} state={state} onCommitMerge={onCommitMerge} />)
  await userEvent.click(within(screen.getByRole('group', { name: "Commit of Coder's changes" })).getByRole('button', { name: 'Commit' }))
  expect(onCommitMerge).toHaveBeenCalledWith('g1', 'Coder: do it', undefined)
  // what was not taken of it is still said, beside the offer
  expect(screen.getByRole('group', { name: "Not all of Coder's work reached the project" })).toHaveTextContent("blob.bin — the project's own file was kept: the user chose it")
  cleanup()
})

test('G1.3, B-84: the kept copy of a recipe turn says how its teams that ended early ended, and what Take in takes in too', () => {
  const kept = merge({ agent_id: 'lead', status: 'interrupted', kept_in: 'C:/copies/lead' })
  const stopped = (team: string, agents: string[], more = {}) => ({
    team_id: team,
    recipe_id: null,
    no_recipe: false,
    picked_by: 'user' as const,
    why: null,
    state: { run_id: 'r', team, recipe: 'Build then test', status: 'stopped' as const, why: 'rule broken: Test it was not done', steps: [], agents, ended_ready: false, passes: [], ...more },
  })
  // (Docs was at Ready for you as the turn ended: it did not end early.)
  const teams = [stopped('Web app', ['coder']), stopped('Docs', ['writer'], { why: 'the turn ended before Take in', ended_ready: true })]
  const also = keptNote(teams, [fileChange('f1', 'r', { agent_id: 'coder', status: 'in_copy' }), fileChange('f2', 'r', { agent_id: 'writer', status: 'in_copy' })], 'r')
  render(<MergeCard merge={kept} name="Lead" also={also} onDecide={vi.fn()} />)
  expect(screen.getByText('Web app: rule broken: Test it was not done. Take in also takes in what Web app left before it stopped.')).toBeInTheDocument()
})

test('K-dikkat-satiri: one "Worth a look" line names each reason with a few of its files; none on a clean card', () => {
  const env = ['.env', 'a/.env', 'b/.env', 'c/.env'].map(path => file(path))
  const { container, rerender } = render(
    <MergeCard merge={merge({ files: [file('a.txt'), ...env, file('old.py', { kind: 'deleted' }), file('done.sql', { state: 'applied' })] })} name="Coder" onDecide={vi.fn()} />,
  )
  expect(screen.getByRole('note', { name: 'Worth a look' })).toHaveTextContent(
    'Worth a look config or env: .env, a/.env, b/.env +1 more · deleted: old.py',
  )
  expect(container.textContent).not.toMatch(/score|risk/i)
  rerender(<MergeCard merge={merge({ files: [file('a.txt'), file('done.sql', { state: 'applied' })] })} name="Coder" onDecide={vi.fn()} />)
  expect(screen.queryByRole('note', { name: 'Worth a look' })).toBeNull()
})

test('K-devam-butce: a kept card of an agent stopped at a step limit offers Continue (+N steps) beside Apply and Discard', async () => {
  const go = vi.fn().mockResolvedValue(undefined)
  const kept = merge({ status: 'interrupted', kept_in: 'C:\\runtime\\copies\\coder' })
  const { rerender } = render(<MergeCard merge={kept} name="Coder" unfinished onDecide={vi.fn()} onContinue={{ steps: 25, run: go }} />)
  expect(screen.getAllByRole('button').map(b => b.textContent)).toEqual(['Take in', 'Continue (+25 steps)', 'Discard'])
  await userEvent.click(screen.getByRole('button', { name: 'Continue (+25 steps)' }))
  expect(go).toHaveBeenCalledTimes(1)
  // Its turn over, or the agent stopped for another reason: no such button.
  rerender(<MergeCard merge={kept} name="Coder" unfinished onDecide={vi.fn()} />)
  expect(screen.queryByRole('button', { name: /Continue/ })).toBeNull()
  // The offer is the card's judgement of the agent and its turn: a step limit, in a turn that still runs.
  const state = convState({ merges: [kept], runs: [run('r')], agents: [agent('r', 'failed', { id: 'coder', error: 'step_limit' })] })
  expect(canContinue(state, kept)).toBe(true)
  expect(canContinue({ ...state, agents: [agent('r', 'failed', { id: 'coder', error: "stopped at its role's limit of 3 steps" })] }, kept)).toBe(true)
  expect(canContinue({ ...state, agents: [agent('r', 'failed', { id: 'coder', error: "stopped at its role's limit of 10 tokens: it used 55" })] }, kept)).toBe(false)
  expect(canContinue({ ...state, runs: [run('r', 'completed')] }, kept)).toBe(false)
})

test('K-dal-takim: a branch is merged whole - what is in the way is said, and Merge looks again', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const branch = { name: 'koloni/fix', into: 'main', conflicts: ['lines.txt'], dirty: ['notes.txt'], note: null }
  render(<MergeCard merge={merge({ files: [file('lines.txt')], branch })} name="Coder" onDecide={onDecide} />)
  expect(screen.getByText('Merge koloni/fix into main? · 1 file')).toBeInTheDocument()
  const note = screen.getByRole('note', { name: 'Not merged yet' })
  expect(note).toHaveTextContent('Changed on both sides, and git does not put them together: lines.txt')
  expect(note).toHaveTextContent('Your uncommitted changes are in the way (commit, stash or unstage them first): notes.txt')
  expect(screen.getByText(/where KOLONİ committed them/)).toHaveTextContent("as one commit by KOLONİ - not the agents' own steps")
  await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
  expect(onDecide).toHaveBeenCalledWith('approve', {}, {})
  cleanup()
  render(<MergeCard merge={merge({ files: [file('lines.txt')], branch: { ...branch, conflicts: [], dirty: [] } })} name="Coder" onDecide={onDecide} />)
  expect(screen.queryByRole('note', { name: 'Not merged yet' })).not.toBeInTheDocument()
})

test("K-dal-takim: a backlog task's whole turn on a branch - the Orchestrator's own card waits for you", async () => {
  const { WaitingList } = await import('../chat/MessageList')
  const { waitingSummary, waitingOf } = await import('../chat/waiting')
  const branch = { name: 'koloni/second-task', into: 'main', conflicts: [], dirty: [], note: null }
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'completed', { id: 'lead' })],
    messages: [userMessage('r', 'Second task'), { ...assistantMessage('m0', 'r', 'done'), agent_id: 'lead' }],
    merges: [merge({ agent_id: 'lead', run_id: 'r', files: [file('b.txt', { kind: 'new' })], branch })],
  })
  expect(waitingSummary(waitingOf(state))).toMatch(/1 /)
  const onDecideMerge = vi.fn().mockResolvedValue(undefined)
  const on = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn(), onDecideMerge }
  render(<WaitingList state={state} on={on as never} onDecidePlan={vi.fn()} known={{ roles: [], providers: [] }} />)
  expect(screen.getByText('Merge koloni/second-task into main? · 1 file')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
  expect(onDecideMerge).toHaveBeenCalledWith('g1', 'approve', {}, {})
  cleanup()
})


test('K-dal-takim D2: an agent may resolve the conflicts, the branch may be kept, and the way is asked once', async () => {
  const onDecide = vi.fn().mockResolvedValue(undefined)
  const resolveMerge = vi.fn().mockResolvedValue(undefined)
  useApp.setState({ resolveMerge })
  const branch = { name: 'koloni/fix', into: 'main', conflicts: ['lines.txt'], dirty: [], note: null, resolve: true }
  render(<MergeCard merge={merge({ files: [file('lines.txt')], branch })} name="Coder" onDecide={onDecide} />)
  expect(screen.getByText(/your branch is not touched/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Let an agent resolve the conflicts' }))
  expect(resolveMerge).toHaveBeenCalledWith('g1')
  await userEvent.click(screen.getByRole('checkbox', { name: /Keep this branch after merging/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
  expect(onDecide).toHaveBeenCalledWith('approve', {}, {}, { keep_branch: true })
  cleanup()
  // The project's first finished branch with a GitHub remote: which way - a pull request greyed out, with why.
  const asks = { ...branch, conflicts: [], resolve: null, ask_way: true }
  render(<MergeCard merge={merge({ files: [file('lines.txt')], branch: { ...asks, pr_off: 'gh is not logged in: run gh auth login' } })} name="Coder" onDecide={onDecide} />)
  expect(screen.queryByRole('button', { name: 'Let an agent resolve the conflicts' })).toBeNull()
  expect(screen.getByRole('radio', { name: /Open a pull request/ })).toBeDisabled()
  expect(screen.getByText(/not now: gh is not logged in/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Merge' }))
  expect(onDecide).toHaveBeenLastCalledWith('approve', {}, {}, { keep_branch: false, way: 'merge' })
  cleanup()
  render(<MergeCard merge={merge({ files: [file('lines.txt')], branch: asks })} name="Coder" onDecide={onDecide} />)
  await userEvent.click(screen.getByRole('radio', { name: /Open a pull request/ }))
  expect(screen.getByText('Open a pull request for koloni/fix into main? · 1 file')).toBeInTheDocument()
  expect(screen.getByText(/KOLONİ never merges it/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open pull request' }))
  expect(onDecide).toHaveBeenLastCalledWith('approve', {}, {}, { keep_branch: false, way: 'pull_request' })
  cleanup()
})

test('K-dal-takim D2: a pull request opened says what was pushed and where it is', () => {
  const commit = { state: 'pull_request' as const, message: 'fix two', sha: 'abcdef1234567', url: 'https://github.com/owner/repo/pull/7', pushed: 'origin/koloni/fix' }
  render(<MergeCard merge={merge({ status: 'applied', files: [file('lines.txt')], commit })} name="Coder" onDecide={vi.fn()} />)
  const step = screen.getByRole('group', { name: "Pull request of Coder's changes" })
  expect(step).toHaveTextContent('Pushed to origin/koloni/fix as one commit (abcdef1234)')
  expect(within(step).getByRole('link', { name: 'https://github.com/owner/repo/pull/7' })).toHaveAttribute('href', 'https://github.com/owner/repo/pull/7')
})
