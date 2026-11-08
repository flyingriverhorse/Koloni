import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import { memoryRecord, projectMemory } from '../test-fixtures'
import { MemoryPage } from './MemoryPage'
import { byTopic, meter, sourceOf, whereOf } from './memoryText'

const handlers = () => ({
  onApprove: vi.fn().mockResolvedValue(undefined),
  onReject: vi.fn().mockResolvedValue(undefined),
  onRestore: vi.fn().mockResolvedValue(undefined),
  onConfirm: vi.fn().mockResolvedValue(undefined),
  onCorrect: vi.fn().mockResolvedValue(undefined),
  onWrite: vi.fn().mockResolvedValue(undefined),
  onSaveRules: vi.fn().mockResolvedValue(undefined),
  onSavePreferences: vi.fn().mockResolvedValue(undefined),
  onAddPreference: vi.fn().mockResolvedValue(undefined),
  onReload: vi.fn().mockResolvedValue(undefined),
})

const section = (name: string | RegExp) => screen.getByRole('region', { name })
const panel = (name: string) => screen.getByRole('tabpanel', { name: new RegExp(`^${name}`) })
/** Opens a tab and gives back what it shows. */
async function tab(name: string) {
  await userEvent.click(screen.getByRole('tab', { name: new RegExp(`^${name}`) }))
  return panel(name)
}
/** The ⋯ of a row, then one of its items. */
async function menu(row: HTMLElement, item: string) {
  await userEvent.click(within(row).getByRole('button', { name: /^More for/ }))
  await userEvent.click(screen.getByRole('menuitem', { name: item }))
}
/** The line of what waits for your word, unfolded. */
async function waits() {
  await userEvent.click(screen.getByRole('button', { name: /wait.? for your word/ }))
  return section('Waits for you')
}

const fact = memoryRecord('f1', {
  tier: 'fact',
  text: 'The greeting is spelled merhaba.',
  about: 'greeting',
  agent_id: 'a1',
  agent_name: 'Reviewer',
  source: { path: 'notes.md', start: 3, end: 4 },
  source_state: 'unchanged',
  checked_how: 'read by the agent in the turn it was noted',
})
const stale = memoryRecord('f2', {
  tier: 'fact',
  text: 'The port is 8790.',
  about: 'port',
  agent_name: 'Lead',
  source: { path: 'config.ini', start: 2, end: 2 },
  source_state: 'changed',
})
const own = memoryRecord('f3', { tier: 'fact', origin: 'user', text: 'Commits are signed off.', about: null })

test('the words for a source say what is known and no more', () => {
  expect(whereOf(fact)).toBe('notes.md:3-4')
  expect(sourceOf(fact)).toBe('source unchanged since noted')
  expect(sourceOf(stale)).toBe('source changed since noted: check again')
  expect(sourceOf({ source_state: 'moved' })).toBe('source moved since noted: check again')
  expect(whereOf(own)).toBeNull()
  expect(sourceOf(own)).toBe('no source')
  expect(meter(1240, 4000)).toBe('1 240 / 4 000 characters')
  expect(meter(0, 4000)).toBe('0 / 4 000 characters')
})

test('four tabs by how a record reaches an agent, Facts first; arrows move between them; each says in one line what it holds, the rest behind its "?"', async () => {
  render(<MemoryPage memory={projectMemory({ core: [fact], preferences: 'Answer in Turkish.\n\nKeep it short.', rules: 'Sign off.' })} {...handlers()} />)
  const tabs = within(screen.getByRole('tablist', { name: 'Memory' })).getAllByRole('tab')
  expect(tabs.map(t => t.textContent)).toEqual(['Told 3', 'Facts 1', 'Notes 0', 'History 0'])
  expect(tabs[1]).toHaveAttribute('aria-selected', 'true')
  expect(panel('Facts')).toHaveTextContent('Given to an agent when its work names the subject.')
  // the old "how it works" is the Facts tab's "?", all of it there
  expect(panel('Facts')).toHaveTextContent('“Source unchanged since noted” only means the file lines a record rests on read as they did when it was written. It does not mean the record is right.')
  expect(within(panel('Facts')).getByRole('button', { name: 'About this' })).toBeInTheDocument()
  // its count of characters stays in sight: a full core refuses more
  expect(panel('Facts')).toHaveTextContent('32 / 4 000 characters')
  tabs[1].focus()
  await userEvent.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: /^Notes/ })).toHaveFocus()
  expect(panel('Notes')).toHaveTextContent('Found only when an agent looks.')
  await userEvent.keyboard('{ArrowRight}')
  expect(panel('History')).toHaveTextContent('Decisions and what was removed. Nothing is deleted.')
  await userEvent.keyboard('{ArrowRight}')
  expect(screen.getByRole('tab', { name: /^Told/ })).toHaveFocus()
  expect(panel('Told')).toHaveTextContent('Said to every agent, always.')
  // only the tab chosen is shown; no counters, no "how this works", no fold by topic
  expect(screen.getAllByRole('tabpanel')).toHaveLength(1)
  expect(document.querySelector('.memory-stats')).toBeNull()
  expect(screen.queryByText('How this works')).toBeNull()
  expect(screen.queryByRole('region', { name: 'By topic' })).toBeNull()
})

test('a fact is one row: its words and subject, then where it rests, how that stands, who and when', () => {
  render(<MemoryPage memory={projectMemory({ core: [fact, stale, own], core_chars: 1240 })} {...handlers()} />)
  const [first, second, third] = within(panel('Facts')).getAllByRole('article')
  expect(first).toHaveTextContent('The greeting is spelled merhaba.')
  expect(first).toHaveTextContent('greeting')
  expect(first).toHaveTextContent('noted by Reviewer')
  expect(first).toHaveTextContent('notes.md:3-4')
  expect(first).toHaveTextContent('source unchanged since noted')
  expect(second).toHaveTextContent('config.ini:2-2')
  expect(second).toHaveTextContent('source changed since noted: check again')
  expect(third).toHaveTextContent('written by you')
  expect(third).toHaveTextContent('no source')
  // a source unchanged has nothing to look again at
  expect(within(first).queryByRole('button', { name: 'Look again' })).toBeNull()
  expect(within(second).getByRole('button', { name: 'Look again' })).toHaveAttribute('aria-expanded', 'false')
  // nothing is called more certain than the records say
  expect(document.body.textContent).not.toMatch(/\b(fresh|verified|true|valid|up to date)\b/i)
})

test('a fact put forward from a working state says it rests on no file, never how "the file" was looked at', () => {
  const fromState = memoryRecord('f4', {
    tier: 'fact',
    text: 'The build runs on port 8080.',
    checked_how: "no file - put forward from the agent's working state when its earlier work was summarised",
  })
  render(<MemoryPage memory={projectMemory({ core: [fact, fromState] })} {...handlers()} />)
  const [first, second] = within(panel('Facts')).getAllByRole('article')
  expect(first).toHaveTextContent('how the file was looked at: read by the agent in the turn it was noted')
  expect(second).toHaveTextContent("no file - put forward from the agent's working state")
  expect(second).not.toHaveTextContent('how the file was looked at')
})

test('a fact no work can name says it is only found by looking it up', () => {
  render(<MemoryPage memory={projectMemory({ core: [fact, own] })} {...handlers()} />)
  expect(panel('Facts')).toHaveTextContent('A fact is given to an agent whose work names its subject; any agent can look the rest up.')
  expect(document.body.textContent).not.toMatch(/every agent of this project is given/i)
  const [withSubject, without] = within(panel('Facts')).getAllByRole('article')
  expect(without).toHaveTextContent('no subject: only found by looking it up')
  expect(withSubject).not.toHaveTextContent('no subject')
  expect(withSubject).not.toHaveTextContent('too general')
  // a subject no work can name (the backend says which: only file endings, stop words, one letter)
  const general = memoryRecord('f4', { tier: 'fact', origin: 'user', text: 'Docs are markdown.', about: 'md', given_unasked: false })
  render(<MemoryPage memory={projectMemory({ core: [general] })} {...handlers()} />)
  const shown = within(screen.getAllByRole('tabpanel', { name: /^Facts/ })[1]).getByRole('article')
  expect(shown).toHaveTextContent('this subject is too general to be matched: only found by looking it up')
  expect(shown).not.toHaveTextContent('no subject')
})

test('a fact is corrected in place or removed from its ⋯, by keyboard too; a refusal shows next to it and changes nothing', async () => {
  const h = handlers()
  render(<MemoryPage memory={projectMemory({ core: [fact, stale] })} {...h} />)
  const [first, second] = within(panel('Facts')).getAllByRole('article')
  await menu(first, 'Correct')
  const words = within(first).getByLabelText('Fact')
  expect(words).toHaveValue('The greeting is spelled merhaba.')
  await userEvent.clear(words)
  await userEvent.type(words, 'The greeting is merhaba.')
  await userEvent.clear(within(first).getByLabelText('Subject'))
  await userEvent.click(within(first).getByRole('button', { name: 'Save correction' }))
  expect(h.onCorrect).toHaveBeenCalledWith('f1', { text: 'The greeting is merhaba.', about: null })

  h.onCorrect.mockRejectedValue(new ApiError(409, 'source changed since it was noted: check again'))
  await menu(second, 'Correct')
  await userEvent.type(within(second).getByLabelText('Fact'), ' Really.')
  await userEvent.click(within(second).getByRole('button', { name: 'Save correction' }))
  expect(await within(second).findByRole('alert')).toHaveTextContent('source changed since it was noted: check again')
  expect(within(second).getByLabelText('Fact')).toHaveValue('The port is 8790. Really.') // still there to look at

  // the ⋯ by keyboard: it opens with the focus in it, arrows go down its items, Esc closes it back on its button
  const more = within(first).getByRole('button', { name: /^More for/ })
  more.focus()
  await userEvent.keyboard('{Enter}')
  expect(screen.getByRole('menu')).toHaveFocus()
  expect(more).toHaveAttribute('aria-expanded', 'true')
  await userEvent.keyboard('{ArrowDown}')
  expect(screen.getByRole('menuitem', { name: 'Correct' })).toHaveFocus()
  await userEvent.keyboard('{ArrowDown}')
  expect(screen.getByRole('menuitem', { name: 'Remove' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('menu')).toBeNull()
  expect(more).toHaveFocus()
  await userEvent.keyboard('{Enter}')
  await userEvent.keyboard('{ArrowUp}')
  await userEvent.keyboard('{Enter}')
  expect(h.onReject).toHaveBeenCalledWith('f1')
})

test('Look again: a changed source unfolds its lines as they read now with Correct and Remove, and no confirm', async () => {
  const h = handlers()
  const gone = { ...stale, excerpt: null }
  const read = { ...stale, id: 'f6', excerpt: 'port = 9000', modified_in_turn: true, source_modified: '2026-10-05T09:30:00Z' }
  render(<MemoryPage memory={projectMemory({ core: [gone, read] })} {...h} />)
  const [first, second] = within(panel('Facts')).getAllByRole('article')
  // folded, no lines in sight
  expect(within(first).queryByRole('group', { name: /as it reads now/ })).toBeNull()
  await userEvent.click(within(first).getByRole('button', { name: 'Look again' }))
  expect(within(first).getByRole('button', { name: 'Look again' })).toHaveAttribute('aria-expanded', 'true')
  // nothing can be read there: it says so, and shows no lines
  expect(first).toHaveTextContent('config.ini:2-2 cannot be read now')
  await userEvent.click(within(second).getByRole('button', { name: 'Look again' }))
  const looked = within(second).getByRole('group', { name: 'Its lines now' })
  expect(within(looked).getByRole('group', { name: 'config.ini:2-2 as it reads now' })).toHaveTextContent('port = 9000')
  expect(looked).toHaveTextContent(/this file was last changed while agents were at work \(.*2026.*\)/)
  // the server would refuse a confirm of changed lines: it is not offered
  expect(within(looked).queryByRole('button', { name: 'These are the same lines' })).toBeNull()
  await userEvent.click(within(looked).getByRole('button', { name: 'Remove' }))
  expect(h.onReject).toHaveBeenCalledWith('f6')
  await userEvent.click(within(looked).getByRole('button', { name: 'Correct' }))
  expect(within(second).getByLabelText('Fact')).toHaveValue('The port is 8790.')
  expect(h.onConfirm).not.toHaveBeenCalled()
})

test('Look again: a moved source shows both places, and you say these are the same lines', async () => {
  const h = handlers()
  const moved = {
    ...fact,
    source_state: 'moved' as const,
    excerpt: '\nThe greeting is spelled selam.',
    found_at: { start: 10, end: 11, excerpt: 'The greeting is spelled merhaba.\nIt is printed by hello.py at start.' },
  }
  render(<MemoryPage memory={projectMemory({ core: [moved] })} {...h} />)
  const card = within(panel('Facts')).getByRole('article')
  expect(card).toHaveTextContent('source moved since noted: check again')
  await userEvent.click(within(card).getByRole('button', { name: 'Look again' }))
  expect(within(card).getByRole('group', { name: 'notes.md:3-4 as it reads now' })).toHaveTextContent('selam')
  const found = within(card).getByRole('group', { name: 'the lines as they were noted, found at notes.md:10-11' })
  expect(found).toHaveTextContent('The greeting is spelled merhaba.')
  expect(card).toHaveTextContent('Given to no agent until you have looked')
  h.onConfirm.mockRejectedValueOnce(new ApiError(409, 'source changed since it was noted: check again'))
  await userEvent.click(within(card).getByRole('button', { name: 'These are the same lines' }))
  expect(h.onConfirm).toHaveBeenCalledWith('f1')
  expect(await within(card).findByRole('alert')).toHaveTextContent('source changed since it was noted')
})

test('what waits for your word is one line that unfolds its notes in place: approved as it is, with your edits, or rejected', async () => {
  const h = handlers()
  const proposal = memoryRecord('n1', {
    text: 'Tests run with pytest -q.',
    about: 'tests',
    agent_name: 'Tester',
    wants_core: true,
    source: { path: 'README.md', start: 10, end: 12 },
    source_state: 'unchanged',
    checked_how: 'not seen by KOLONİ',
    last_change: { agent_id: 'a2', agent_name: 'Coder', at: '2026-10-05T09:00:00Z' },
  })
  render(<MemoryPage memory={projectMemory({ proposals: [proposal], journal: [proposal] })} {...h} />)
  const line = screen.getByRole('button', { name: '● 1 fact waits for your word' })
  expect(line).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByRole('region', { name: 'Waits for you' })).toBeNull()
  const card = within(await waits()).getByRole('article')
  expect(line).toHaveAttribute('aria-expanded', 'true')
  expect(card).toHaveTextContent('README.md:10-12')
  expect(card).toHaveTextContent('source unchanged since noted')
  expect(card).toHaveTextContent('not seen by KOLONİ')
  expect(card).toHaveTextContent(/last recorded change to README\.md by an agent: Coder/)
  expect(within(card).queryByText('Would replace')).not.toBeInTheDocument()

  await userEvent.click(within(card).getByRole('button', { name: 'Approve' }))
  expect(h.onApprove).toHaveBeenCalledWith('n1', undefined)

  await userEvent.click(within(card).getByRole('button', { name: 'Edit and approve' }))
  const words = within(card).getByLabelText('Fact')
  await userEvent.clear(words)
  await userEvent.type(words, 'The tests run with pytest -q.')
  await userEvent.click(within(card).getByRole('button', { name: 'Approve as edited' }))
  expect(h.onApprove).toHaveBeenLastCalledWith('n1', 'The tests run with pytest -q.')

  await userEvent.click(within(card).getByRole('button', { name: 'Reject' }))
  expect(h.onReject).toHaveBeenCalledWith('n1')
})

test('what waits comes with the lines it rests on, and says so when the file changed while agents were at work; the journal shows none', async () => {
  const LINES = 'The greeting is spelled merhaba.\nIt is printed by hello.py at start.'
  const proposal = memoryRecord('n1', {
    wants_core: true,
    source: { path: 'notes.md', start: 3, end: 4 },
    excerpt: LINES,
    source_modified: '2026-10-05T09:30:00Z',
    modified_in_turn: true,
  })
  render(<MemoryPage memory={projectMemory({ proposals: [proposal], core: [{ ...fact, excerpt: LINES }], journal: [proposal] })} {...handlers()} />)
  const card = within(await waits()).getByRole('article')
  const lines = within(card).getByRole('group', { name: 'notes.md:3-4 as it reads now' })
  expect(lines.querySelector('pre')?.textContent).toBe(LINES) // as they are, line by line
  expect(card).toHaveTextContent(/this file was last changed while agents were at work \(.*2026.*\)/)
  // a fact whose source is unchanged is a row: no lines
  expect(within(panel('Facts')).queryByRole('group', { name: /as it reads now/ })).toBeNull()
  expect(within(await tab('Notes')).queryByRole('group', { name: /as it reads now/ })).toBeNull()
})

test('a note that waits and whose source moved can be confirmed before it is approved', async () => {
  const h = handlers()
  const waiting = memoryRecord('n1', { wants_core: true, source: { path: 'b.md', start: 1, end: 2 }, source_state: 'moved', found_at: { start: 2, end: 3, excerpt: 'same\nlines' } })
  render(<MemoryPage memory={projectMemory({ proposals: [waiting] })} {...h} />)
  await userEvent.click(within(await waits()).getByRole('button', { name: 'These are the same lines' }))
  expect(h.onConfirm).toHaveBeenLastCalledWith('n1')
})

test('a note that would replace a fact shows that fact beside it', async () => {
  const instead = memoryRecord('n2', {
    text: 'The port is 9000.',
    about: 'Port',
    status: 'proposed',
    supersedes_id: 'f2',
    source: { path: 'config.ini', start: 2, end: 2 },
    source_state: 'unchanged',
  })
  // put forward on its own, having taken the place of an older note: nothing in the core goes
  const fresh = memoryRecord('n3', { text: 'Docs are in docs/.', about: 'docs', wants_core: true, supersedes_id: 'n0' })
  render(<MemoryPage memory={projectMemory({ core: [stale], proposals: [instead, fresh] })} {...handlers()} />)
  expect(screen.getByRole('button', { name: '● 2 facts wait for your word' })).toBeInTheDocument()
  const [first, second] = within(await waits()).getAllByRole('article')
  const replaced = within(first).getByRole('group', { name: 'Would replace' })
  expect(replaced).toHaveTextContent('The port is 8790.')
  expect(replaced).toHaveTextContent('source changed since noted: check again')
  expect(within(first).getByRole('group', { name: 'Put forward' })).toHaveTextContent('The port is 9000.')
  expect(within(second).queryByRole('group', { name: 'Would replace' })).not.toBeInTheDocument()
})

test('a refused approval says why next to the record: the source changed, or the core is full', async () => {
  const h = handlers()
  const one = memoryRecord('n1', { text: 'One.', wants_core: true, source: { path: 'a.md', start: 1, end: 1 }, source_state: 'changed' })
  const two = memoryRecord('n2', { text: 'Two.', wants_core: true, source: { path: 'b.md', start: 1, end: 1 }, source_state: 'unchanged' })
  render(<MemoryPage memory={projectMemory({ proposals: [one, two] })} {...h} />)
  const [first, second] = within(await waits()).getAllByRole('article')
  h.onApprove.mockRejectedValueOnce(new ApiError(409, 'source changed since it was noted: check again'))
  await userEvent.click(within(first).getByRole('button', { name: 'Approve' }))
  expect(await within(first).findByRole('alert')).toHaveTextContent('source changed since it was noted: check again')
  expect(within(second).queryByRole('alert')).not.toBeInTheDocument()
  h.onApprove.mockRejectedValueOnce(new ApiError(422, 'the core holds at most 4000 characters and has 3990'))
  await userEvent.click(within(second).getByRole('button', { name: 'Approve' }))
  expect(await within(second).findByRole('alert')).toHaveTextContent('the core holds at most 4000 characters')
  // both are still waiting
  expect(within(section('Waits for you')).getAllByRole('article')).toHaveLength(2)
})

test('the last note that waited, decided, leaves its line saying nothing waits, with the focus on it; a page with nothing waiting has no line', async () => {
  const h = handlers()
  const waiting = memoryRecord('n1', { text: 'Waits.', wants_core: true })
  const { rerender } = render(<MemoryPage memory={projectMemory({ proposals: [waiting] })} {...h} />)
  await userEvent.click(within(await waits()).getByRole('button', { name: 'Approve' }))
  // the memory is read again after the decision: nothing waits now
  rerender(<MemoryPage memory={projectMemory({ core: [{ ...waiting, tier: 'fact' }] })} {...h} />)
  expect(within(section('Waits for you')).getByText('Nothing waits for you.')).toHaveFocus()
  expect(screen.getByRole('button', { name: 'Nothing waits for your word' })).toBeInTheDocument()
  rerender(<MemoryPage key="other" memory={projectMemory()} {...h} />)
  expect(screen.queryByRole('button', { name: /for your word/ })).toBeNull()
})

test('notes are rows with who wrote them, filtered by topic and by writer', async () => {
  const withFile = memoryRecord('n1', {
    text: 'The greeting is printed by hello.py.',
    about: 'greeting',
    agent_name: 'Reviewer',
    source: { path: 'hello.py', start: 1, end: 1 },
    source_state: 'unchanged',
    checked_how: 'not seen by KOLONİ',
  })
  const bare = memoryRecord('n2', { text: 'The team prefers small commits.', about: null, agent_name: 'Lead' })
  const auto = memoryRecord('n3', { text: 'Paginate the list.', about: 'greeting', origin: 'auto', agent_id: null, agent_name: null, noted_by: { provider_name: 'Fast', model_id: 'q' } })
  render(<MemoryPage memory={projectMemory({ journal: [withFile, bare, auto] })} {...handlers()} />)
  const notes = await tab('Notes')
  const [first, second] = within(notes).getAllByRole('article')
  expect(first).toHaveTextContent('hello.py:1-1')
  expect(first).toHaveTextContent('not seen by KOLONİ')
  expect(second).toHaveTextContent('no source')
  // the journal is never handed out anyway: no word of subjects matched
  expect(second).not.toHaveTextContent('no subject')
  // no search box of its own: the one on top searches it
  expect(screen.queryByLabelText('Search the journal')).toBeNull()
  const writers = within(notes).getByLabelText('Written by')
  expect(within(writers).getAllByRole('option').map(o => o.textContent)).toEqual(['Anyone', 'Reviewer', 'Lead', 'fast model'])
  await userEvent.selectOptions(writers, 'fast model')
  expect(within(notes).getByRole('article')).toHaveTextContent('Paginate the list.')
  await userEvent.selectOptions(writers, '')
  const topic = within(notes).getByLabelText('Topic')
  await userEvent.selectOptions(topic, '=greeting')
  expect(within(notes).getAllByRole('article')).toHaveLength(2)
  await userEvent.selectOptions(writers, 'Lead')
  expect(within(notes).queryByRole('article')).toBeNull()
  expect(within(notes).getByText('No note matches.')).toBeInTheDocument()
})

test('Make it a fact: Add a fact opens in Facts with the note’s words and subject, never its file; saved, it is your fact and the note stays', async () => {
  const h = handlers()
  const note = memoryRecord('n1', { text: 'Tests run with pytest.', about: 'tests', source: { path: 'README.md', start: 1, end: 2 } })
  render(<MemoryPage memory={projectMemory({ journal: [note] })} {...h} />)
  await tab('Notes')
  await menu(within(panel('Notes')).getByRole('article'), 'Make it a fact')
  expect(screen.getByRole('tab', { name: /^Facts/ })).toHaveAttribute('aria-selected', 'true')
  const box = section('Add a fact')
  expect(within(box).getByLabelText('Fact')).toHaveValue('Tests run with pytest.')
  expect(within(box).getByLabelText('Fact')).toHaveFocus()
  expect(within(box).getByLabelText('Subject')).toHaveValue('tests')
  expect(within(box).getByLabelText('Subject').closest('details')).toHaveAttribute('open') // the subject filled in is in sight
  expect(within(box).getByLabelText('File')).toHaveValue('')
  await userEvent.click(within(box).getByRole('button', { name: 'Add to the core' }))
  expect(h.onWrite).toHaveBeenCalledWith({ text: 'Tests run with pytest.', about: 'tests', file: null, start_line: null, end_line: null })
  expect(h.onReject).not.toHaveBeenCalled()
  // closed and opened again, the box starts empty: the note is not offered a second time
  const open = within(panel('Facts')).getByRole('button', { name: '＋ Add a fact' })
  await userEvent.click(open)
  await userEvent.click(open)
  expect(within(section('Add a fact')).getByLabelText('Fact')).toHaveValue('')
})

test('Make it a fact over a fact half typed asks before replacing it; an empty box is filled at once', async () => {
  const one = memoryRecord('n1', { text: 'Tests run with pytest.', about: 'tests' })
  const two = memoryRecord('n2', { text: 'Docs are in docs/.', about: 'docs' })
  render(<MemoryPage memory={projectMemory({ journal: [one, two] })} {...handlers()} />)
  await userEvent.click(within(panel('Facts')).getByRole('button', { name: '＋ Add a fact' }))
  const words = within(section('Add a fact')).getByLabelText('Fact')
  await userEvent.type(words, 'My own words')
  await tab('Notes')
  await menu(within(panel('Notes')).getAllByRole('article')[0], 'Make it a fact')
  const asked = screen.getByRole('alertdialog')
  expect(asked).toHaveTextContent('Replace what you typed with the note’s words?')
  expect(within(asked).getByRole('button', { name: 'Replace' })).toHaveFocus()
  await userEvent.click(within(asked).getByRole('button', { name: 'Keep editing' }))
  expect(words).toHaveValue('My own words')
  await tab('Notes')
  await menu(within(panel('Notes')).getAllByRole('article')[1], 'Make it a fact')
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Replace' }))
  expect(words).toHaveValue('Docs are in docs/.')
  expect(within(section('Add a fact')).getByLabelText('Subject')).toHaveValue('docs')
  // emptied, the next one fills it without a question
  await userEvent.clear(words)
  await tab('Notes')
  await menu(within(panel('Notes')).getAllByRole('article')[0], 'Make it a fact')
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(words).toHaveValue('Tests run with pytest.')
})

test('what waits for your word is searched too: a hit opens the waiting line at that note', async () => {
  const waiting = memoryRecord('n1', { text: 'Tests run with pytest -q.', about: 'tests', wants_core: true })
  render(<MemoryPage memory={projectMemory({ proposals: [waiting], journal: [waiting] })} {...handlers()} />)
  expect(screen.queryByRole('region', { name: 'Waits for you' })).toBeNull()
  await userEvent.type(screen.getByLabelText('Search everything this project remembers'), 'pytest')
  const found = screen.getByRole('region', { name: 'Search' })
  expect(within(found).getAllByRole('group').map(g => g.getAttribute('aria-label'))).toEqual(['Waiting for your word', 'In Notes'])
  await userEvent.click(within(within(found).getByRole('group', { name: 'Waiting for your word' })).getByRole('button'))
  expect(screen.getByRole('button', { name: '● 1 fact waits for your word' })).toHaveAttribute('aria-expanded', 'true')
  expect(within(section('Waits for you')).getByRole('article')).toHaveFocus()
})

test('facts are filtered by topic, in place of the fold by topic', async () => {
  const at = (day: number) => `2026-10-${String(day).padStart(2, '0')}T10:00:00Z`
  const records = [
    memoryRecord('t1', { tier: 'fact', about: 'Greeting', observed_at: at(1) }),
    memoryRecord('t2', { tier: 'fact', about: 'greeting ', text: 'a note on it', observed_at: at(9) }),
    memoryRecord('t3', { tier: 'fact', about: null, text: 'no subject here', observed_at: at(20) }),
    memoryRecord('t4', { tier: 'fact', about: 'port', observed_at: at(5) }),
  ]
  const topics = byTopic(records)
  expect(topics.map(t => [t.about, t.records.length])).toEqual([['Greeting', 2], ['port', 1], [null, 1]])
  const { rerender } = render(<MemoryPage memory={projectMemory({ core: records })} {...handlers()} />)
  const filter = within(panel('Facts')).getByLabelText('Topic')
  expect(within(filter).getAllByRole('option').map(o => o.textContent)).toEqual(['All topics', 'Greeting', 'port', 'no subject'])
  await userEvent.selectOptions(filter, '=greeting')
  expect(within(panel('Facts')).getAllByRole('article')).toHaveLength(2)
  await userEvent.selectOptions(filter, '=port')
  expect(within(panel('Facts')).getByRole('article')).toHaveTextContent('The greeting is spelled merhaba.')
  // its one fact removed, the topic is gone: all are shown again, not an empty list
  rerender(<MemoryPage memory={projectMemory({ core: records.slice(0, 3) })} {...handlers()} />)
  expect(within(panel('Facts')).getByLabelText('Topic')).toHaveValue('')
  expect(within(panel('Facts')).getAllByRole('article')).toHaveLength(3)
  await userEvent.selectOptions(within(panel('Facts')).getByLabelText('Topic'), '=')
  expect(within(panel('Facts')).getByRole('article')).toHaveTextContent('no subject here')
})

test('what was removed or replaced is under History and can be taken back', async () => {
  const h = handlers()
  const removed = memoryRecord('f9', { tier: 'fact', text: 'The port is 8000.', status: 'rejected', decided_by: 'user', decided_at: '2026-10-05T11:00:00Z' })
  const replaced = memoryRecord('n9', { text: 'An older note.', status: 'superseded', decided_by: 'agent', decided_at: '2026-10-05T11:00:00Z' })
  render(<MemoryPage memory={projectMemory({ past: [removed, replaced] })} {...h} />)
  await tab('History')
  const [first, second] = within(section('Removed / replaced')).getAllByRole('article')
  expect(first).toHaveTextContent('removed by you')
  expect(second).toHaveTextContent('replaced by an agent’s newer note')
  h.onRestore.mockRejectedValueOnce(new ApiError(409, 'the core has another fact on this subject: remove that one first'))
  await userEvent.click(within(first).getByRole('button', { name: 'Take back' }))
  expect(h.onRestore).toHaveBeenCalledWith('f9')
  expect(await within(first).findByRole('alert')).toHaveTextContent('remove that one first')
})

test('this project’s rules are one text with a counter, saved as written; what they are is behind the Told tab’s "?"', async () => {
  const h = handlers()
  render(<MemoryPage memory={projectMemory({ rules: 'Sign off commits.' })} {...h} />)
  const told = await tab('Told')
  const about = within(told).getByText(/This project’s rules are like an AGENTS\.md or CLAUDE\.md file: every agent working in this project is given them each turn\. Only you write either\.$/)
  expect(about).not.toBeVisible()
  await userEvent.click(within(told).getByRole('button', { name: 'About this' }))
  expect(about).toBeVisible()
  const rules = section('This project’s rules')
  const text = within(rules).getByLabelText('Rules')
  expect(text).toHaveValue('Sign off commits.')
  expect(text).toHaveAttribute('maxlength', '1500')
  expect(within(rules).getByText('17 / 1 500')).toBeInTheDocument()
  expect(within(rules).getByRole('button', { name: 'Save rules' })).toBeDisabled() // nothing changed
  await userEvent.type(text, ' No force-push.')
  // a draft is kept while another tab is open
  await tab('Facts')
  await tab('Told')
  await userEvent.click(within(rules).getByRole('button', { name: 'Save rules' }))
  expect(h.onSaveRules).toHaveBeenCalledWith('Sign off commits. No force-push.')
})

test('the first save that puts the rules into the folder’s .koloni/ says so, once', async () => {
  const h = handlers()
  const { rerender } = render(<MemoryPage memory={projectMemory()} {...h} />)
  h.onSaveRules.mockImplementation(async (rules: string) => rerender(<MemoryPage memory={projectMemory({ rules, rules_kept: true })} {...h} />))
  await tab('Told')
  await userEvent.type(within(section('This project’s rules')).getByLabelText('Rules'), 'Sign off commits.')
  await userEvent.click(within(section('This project’s rules')).getByRole('button', { name: 'Save rules' }))
  expect(within(section('This project’s rules')).getByRole('status')).toHaveTextContent(/^Saved in \.koloni\/ in this folder \(kept in git\)$/)
  await userEvent.type(within(section('This project’s rules')).getByLabelText('Rules'), ' No force-push.')
  await userEvent.click(within(section('This project’s rules')).getByRole('button', { name: 'Save rules' }))
  expect(within(section('This project’s rules')).queryByText(/Saved in \.koloni/)).not.toBeInTheDocument()
})

test('a folder’s rules.md that is not read is said beside the rules, which still save here', async () => {
  const why = '.koloni/rules.md: the rules have at most 1500 characters: the rules saved in KOLONİ are used, and a save here does not change the file'
  render(<MemoryPage memory={projectMemory({ rules: 'Sign off commits.', rules_not_read: why })} {...handlers()} />)
  await tab('Told')
  expect(within(section('This project’s rules')).getByText(why)).toBeInTheDocument()
})

test('you write a fact yourself from ＋ Add a fact, with or without the file lines it rests on', async () => {
  const h = handlers()
  render(<MemoryPage memory={projectMemory()} {...h} />)
  expect(panel('Facts')).toHaveTextContent('Nothing is in the core yet. Agents are given only what you approve or write here.')
  const open = within(panel('Facts')).getByRole('button', { name: '＋ Add a fact' })
  expect(open).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(open)
  const box = section('Add a fact')
  // what it does is in sight: it replaces the fact on the same subject
  expect(box).toHaveTextContent('It goes into the core at once, replacing the fact on the same subject.')
  const add = within(box).getByRole('button', { name: 'Add to the core' })
  expect(add).toBeDisabled()
  expect(within(box).getByLabelText('Fact')).toHaveAttribute('maxlength', '500')
  expect(within(box).getByLabelText('Subject').closest('details')).not.toHaveAttribute('open')
  await userEvent.type(within(box).getByLabelText('Fact'), 'The port is 8790.')
  await userEvent.click(add)
  expect(h.onWrite).toHaveBeenLastCalledWith({ text: 'The port is 8790.', about: null, file: null, start_line: null, end_line: null })
  expect(within(box).getByLabelText('Fact')).toHaveValue('') // written: the box is empty again

  await userEvent.type(within(box).getByLabelText('Fact'), 'The host is example.')
  await userEvent.click(within(box).getByText('Subject, file and lines'))
  await userEvent.type(within(box).getByLabelText('Subject'), 'host')
  await userEvent.type(within(box).getByLabelText('File'), 'config.ini')
  await userEvent.type(within(box).getByLabelText('First line'), '3')
  h.onWrite.mockRejectedValueOnce(new ApiError(422, 'config.ini has 2 lines: there are no lines 3-3'))
  await userEvent.click(add)
  expect(h.onWrite).toHaveBeenLastCalledWith({ text: 'The host is example.', about: 'host', file: 'config.ini', start_line: 3, end_line: null })
  expect(await within(box).findByRole('alert')).toHaveTextContent('there are no lines 3-3')
  expect(within(box).getByLabelText('Fact')).toHaveValue('The host is example.') // refused: kept to fix
})

test('an empty memory says so in plain words, and one not read yet says that instead', async () => {
  const { rerender } = render(<MemoryPage memory={projectMemory()} {...handlers()} />)
  expect(within(panel('Facts')).getByText(/Nothing is in the core yet/)).toBeInTheDocument()
  // nothing waits: no line for it
  expect(screen.queryByRole('button', { name: /for your word/ })).not.toBeInTheDocument()
  expect(within(await tab('Notes')).getByText('Agents have noted nothing yet.')).toBeInTheDocument()
  expect(within(await tab('History')).getByText('Nothing has been removed or replaced.')).toBeInTheDocument()
  expect(within(section('Recent decisions')).getByText('Nothing has been decided yet.')).toBeInTheDocument()
  rerender(<MemoryPage memory={null} {...handlers()} />)
  expect(screen.getByText('Reading the project’s memory…')).toBeInTheDocument()
  expect(screen.queryByText(/Nothing is in the core yet/)).not.toBeInTheDocument()
  rerender(<MemoryPage memory={null} error="Failed to fetch" {...handlers()} />)
  expect(screen.getByRole('alert')).toHaveTextContent('Failed to fetch')
})

test('the last decisions are listed, what and when, so that one you did not make can be noticed', async () => {
  const at = '2026-10-07T09:30:00Z'
  const decisions = [
    { kind: 'rules' as const, at, memory_id: null, text: null, about: null },
    { kind: 'approved' as const, at, memory_id: 'f1', text: 'The greeting is spelled merhaba.', about: 'greeting' },
    { kind: 'rejected' as const, at, memory_id: 'n1', text: 'The port is 9000.', about: 'port' },
    { kind: 'removed' as const, at, memory_id: 'f2', text: 'The port is 8790.', about: 'port' },
    { kind: 'restored' as const, at, memory_id: 'f3', text: 'Commits are signed off.', about: null },
    { kind: 'corrected' as const, at, memory_id: 'f4', text: 'The host is example.', about: null },
    { kind: 'confirmed' as const, at, memory_id: 'f5', text: 'Docs are in docs/.', about: null },
    { kind: 'written' as const, at, memory_id: 'f6', text: 'CI uses Python 3.12.', about: null },
  ]
  render(<MemoryPage memory={projectMemory({ decisions })} {...handlers()} />)
  const history = await tab('History')
  const items = within(section('Recent decisions')).getAllByRole('listitem')
  expect(items.map(item => item.textContent?.replace(/ · [^·]*2026.*$/, ''))).toEqual([
    'Standing rules changed',
    'Approved into the core · The greeting is spelled merhaba.',
    'Rejected · The port is 9000.',
    'Removed · The port is 8790.',
    'Restored · Commits are signed off.',
    'Corrected · The host is example.',
    'Lines confirmed as the same · Docs are in docs/.',
    'Written into the core · CI uses Python 3.12.',
  ])
  for (const item of items) expect(item).toHaveTextContent(/2026/) // when
  // what the list is, and who is not claimed to have made them: behind History's "?"
  expect(history).toHaveTextContent('If one of them was not yours')
  expect(history).not.toHaveTextContent(/\byou (approved|rejected|removed|restored|corrected|wrote)\b/i)
})

test('the core can be taken as a Markdown file: a download, which changes nothing, and a refusal said beside it', async () => {
  const onExport = vi.fn().mockRejectedValueOnce(new Error('project not found')).mockResolvedValue(undefined)
  const { rerender } = render(<MemoryPage memory={projectMemory({ core: [fact] })} onExport={onExport} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: 'Export' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('project not found')
  await userEvent.click(screen.getByRole('button', { name: 'Export' }))
  expect(onExport).toHaveBeenCalledTimes(2)
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  // no project, nothing to take
  rerender(<MemoryPage memory={projectMemory({ core: [fact] })} {...handlers()} />)
  expect(screen.queryByRole('button', { name: 'Export' })).not.toBeInTheDocument()
})

test('the sources are looked at again when you ask', async () => {
  const h = handlers()
  render(<MemoryPage memory={projectMemory({ core: [fact] })} {...h} />)
  await userEvent.click(screen.getByRole('button', { name: 'Look at the sources again' }))
  expect(h.onReload).toHaveBeenCalled()
})

test('a note written in a turn nobody was watching says so; any other note does not', async () => {
  const watched = memoryRecord('n1', { text: 'The tests pass.', agent_name: 'Lead' })
  const alone = memoryRecord('n2', { text: 'The build was red at night.', agent_name: 'Lead', unattended: true })
  render(<MemoryPage memory={projectMemory({ journal: [watched, alone], proposals: [{ ...alone, id: 'n3', wants_core: true }] })} {...handlers()} />)
  // wherever the record is shown
  expect(within(await waits()).getByText('written with nobody watching')).toBeInTheDocument()
  const notes = within(await tab('Notes')).getAllByRole('article')
  expect(within(notes[0]).queryByText('written with nobody watching')).not.toBeInTheDocument()
  expect(within(notes[1]).getByText('written with nobody watching')).toBeInTheDocument()
})

test('a fact made of your words at a card says so, not that you wrote it on this page', () => {
  const said = memoryRecord('f5', { tier: 'fact', origin: 'user', text: 'say Hello', about: 'feedback: greet.py', decided_how: 'feedback' })
  render(<MemoryPage memory={projectMemory({ core: [own, said] })} {...handlers()} />)
  const [first, second] = within(panel('Facts')).getAllByRole('article')
  expect(first).toHaveTextContent('written by you')
  expect(second).toHaveTextContent('said by you at a card, asking for changes')
  expect(second).not.toHaveTextContent('written by you')
})

test('your preferences are one text in Told, saved as written (22b)', async () => {
  const h = handlers()
  render(<MemoryPage memory={projectMemory({ preferences: 'Answer in Turkish.' })} {...h} />)
  await tab('Told')
  const box = section('Your preferences')
  const text = within(box).getByLabelText('Preferences')
  expect(text).toHaveValue('Answer in Turkish.')
  expect(text).toHaveAttribute('maxlength', '1500')
  expect(within(box).getByRole('button', { name: 'Save preferences' })).toBeDisabled()
  await userEvent.type(text, ' Keep answers short.')
  await userEvent.click(within(box).getByRole('button', { name: 'Save preferences' }))
  expect(h.onSavePreferences).toHaveBeenCalledWith('Answer in Turkish. Keep answers short.')
  expect(h.onSaveRules).not.toHaveBeenCalled()
  expect(screen.queryByRole('group', { name: 'Suggested for your preferences' })).not.toBeInTheDocument()
})

test('a suggested preference, under your preferences, is added by you or turned down, never by itself', async () => {
  const h = handlers()
  const suggested = memoryRecord('s1', { tier: 'preference', status: 'proposed', origin: 'auto', text: 'the user wants short answers', about: null, noted_by: { provider_name: 'Fast', model_id: 'quick' } })
  render(<MemoryPage memory={projectMemory({ suggestions: [suggested] })} {...h} />)
  await tab('Told')
  const box = within(section('Your preferences')).getByRole('group', { name: 'Suggested for your preferences' })
  expect(box).toHaveTextContent('Nothing enters your preferences unless you add it.')
  expect(within(box).getByRole('article')).toHaveTextContent('the user wants short answers')
  expect(within(box).getByRole('article')).toHaveTextContent('noted by KOLONİ’s summariser (Fast · quick)')
  await userEvent.click(within(box).getByRole('button', { name: 'Add' }))
  expect(h.onAddPreference).toHaveBeenCalledWith('s1')
  await userEvent.click(within(box).getByRole('button', { name: 'Reject' }))
  expect(h.onReject).toHaveBeenCalledWith('s1')
  expect(h.onApprove).not.toHaveBeenCalled()
})

test('as you type, all that is on the page is sifted, grouped by tab, and said; a hit opens its tab at its row, whatever the filters', async () => {
  const note = memoryRecord('n1', { text: 'The port moved to 9000 in staging.', about: 'deploy', agent_name: 'Coder' })
  const other = memoryRecord('n2', { text: 'Docs are in docs/.', about: 'docs', agent_name: 'Lead' })
  const gone = memoryRecord('f9', { tier: 'fact', text: 'The port is 8000.', status: 'rejected', decided_by: 'user', decided_at: '2026-10-05T11:00:00Z' })
  const decisions = [{ kind: 'removed' as const, at: '2026-10-07T09:30:00Z', memory_id: 'f9', text: 'The port is 8000.', about: 'port' }]
  render(
    <MemoryPage
      memory={projectMemory({ core: [fact, stale], journal: [note, other], past: [gone], decisions, rules: 'Never change the port.\nSign off.', preferences: 'Short answers.' })}
      {...handlers()}
    />,
  )
  // filters that would hide the hits
  await tab('Notes')
  await userEvent.selectOptions(within(panel('Notes')).getByLabelText('Written by'), 'Lead')
  await tab('Facts')
  await userEvent.selectOptions(within(panel('Facts')).getByLabelText('Topic'), '=greeting')
  const box = screen.getByLabelText('Search everything this project remembers')
  await userEvent.type(box, 'PORT')
  const found = screen.getByRole('region', { name: 'Search' })
  expect(within(found).getByRole('status')).toHaveTextContent('5 on this page have “PORT”.')
  expect(within(found).getAllByRole('group').map(g => g.getAttribute('aria-label'))).toEqual(['In Told', 'In Facts', 'In Notes', 'In History'])
  expect(within(within(found).getByRole('group', { name: 'In Told' })).getByRole('button')).toHaveTextContent('Never change the port.')
  expect(within(within(found).getByRole('group', { name: 'In History' })).getAllByRole('button').map(b => b.textContent)).toEqual([
    'Removed · The port is 8000.',
    'The port is 8000.',
  ])
  // a fact the topic filter hid: shown, with the focus on its row
  await userEvent.click(within(within(found).getByRole('group', { name: 'In Facts' })).getByRole('button', { name: 'The port is 8790.' }))
  expect(within(panel('Facts')).getByLabelText('Topic')).toHaveValue('')
  expect(within(panel('Facts')).getByText('The port is 8790.').closest('article')).toHaveFocus()
  await userEvent.click(within(within(found).getByRole('group', { name: 'In Notes' })).getByRole('button'))
  expect(screen.getByRole('tab', { name: /^Notes/ })).toHaveAttribute('aria-selected', 'true')
  expect(within(panel('Notes')).getByText('The port moved to 9000 in staging.').closest('article')).toHaveFocus()
  await userEvent.click(within(within(found).getByRole('group', { name: 'In Told' })).getByRole('button'))
  expect(within(panel('Told')).getByLabelText('Rules')).toHaveFocus()
  await userEvent.click(within(within(found).getByRole('group', { name: 'In History' })).getAllByRole('button')[0])
  expect(within(panel('History')).getAllByRole('listitem')[0]).toHaveFocus()
  // nothing there
  await userEvent.clear(box)
  await userEvent.type(box, 'zebra')
  expect(within(found).getByRole('status')).toHaveTextContent('Nothing on this page has “zebra”.')
  expect(within(found).queryAllByRole('group')).toHaveLength(0)
})
