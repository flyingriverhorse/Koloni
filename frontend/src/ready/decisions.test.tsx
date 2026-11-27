import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { afterEach, expect, test, vi } from 'vitest'
import type { Decision, DecisionLog } from '../api/types'
import { Decisions } from './Decisions'
import { heardOf, markdown, markdownRow, weekStart } from './decisionLog'
import { useApp } from '../state/store'
import { conversation, convState, question } from '../test-fixtures'
import { since } from '../usage/period'

type Log = Omit<DecisionLog, 'more'> & { more?: boolean }

/** Ready for you's Decided for you (karar defteri): the period's chips, its rows and what can still be done about
 * them, Show all, Copy as Markdown and the empty state. */

afterEach(() => vi.unstubAllGlobals())

const NOW = new Date(2026, 10, 25, 12, 0)
const at = (hour: number, minute: number) => new Date(2026, 10, 25, hour, minute).toISOString()

const answer: Decision = {
  id: 'answer:q1',
  at: at(4, 40),
  kind: 'answer',
  who: 'orchestrator',
  what: 'Answered a question for you',
  quote: 'Which database for the tests?',
  answer: 'SQLite',
  options: ['Postgres'],
  why: 'they make one in a temp folder',
  conversation_id: 'c1',
  chat: 'Fix login',
  link: { kind: 'question', id: 'q1' },
  undo: 'change',
  undo_reason: null,
  seen: false,
}
const ran: Decision = {
  id: 'command:k1',
  at: at(3, 55),
  kind: 'command',
  who: 'your_words',
  what: "Ran a command without asking, on a line of this project's rules",
  quote: 'rm -rf build',
  answer: null,
  why: 'You may delete ./build.',
  conversation_id: 'c1',
  chat: 'Fix login',
  link: { kind: 'command', id: 'k1' },
  undo: 'none',
  undo_reason: 'it ran',
  seen: false,
}
const task: Decision = {
  ...ran,
  id: 'task:t1',
  at: at(2, 10),
  kind: 'task',
  who: 'orchestrator',
  what: 'Decided on a task the Scout proposed',
  quote: 'Fix the login timeout',
  answer: 'Add',
  why: 'it blocks the release',
  chat: null,
  link: { kind: 'task', id: 't1' },
  undo: 'change',
  undo_reason: null,
}
const many = (n: number): Decision[] =>
  Array.from({ length: n }, (_, i) => ({
    ...answer,
    id: `answer:q${i}`,
    quote: `Question ${i}?`,
    seen: i < 3 ? false : true,
  }))

function view(log: Log, leftAt: string | null = null, onOpenChat = vi.fn()) {
  const onLoad = vi.fn().mockResolvedValue({ more: false, ...log })
  render(<Decisions onLoad={onLoad} leftAt={leftAt} onOpenChat={onOpenChat} />)
  return { onLoad, onOpenChat }
}

test('its count and how many you have not seen; since you left first, where you left; the period by its chips', async () => {
  const left = at(1, 0)
  const { onLoad } = view({ rows: many(7), judge_fine: 0 }, left)
  const box = await screen.findByRole('region', { name: 'Decided for you 7, 3 not seen' })
  expect(onLoad).toHaveBeenLastCalledWith(left)
  const chips = within(box).getByRole('group', { name: 'Decisions since' })
  expect(within(chips).getByRole('button', { name: 'Since I left' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(within(chips).getByRole('button', { name: 'Week' }))
  expect(onLoad).toHaveBeenLastCalledWith(weekStart())
  await userEvent.click(within(chips).getByRole('button', { name: 'Today' }))
  expect(onLoad).toHaveBeenLastCalledWith(since('today'))
})

test('how many were decided since you left is told the page, read with Since I left - not where more were', async () => {
  const onLeft = vi.fn()
  const onLoad = vi.fn().mockResolvedValue({ rows: many(4), judge_fine: 0, more: false })
  render(<Decisions onLoad={onLoad} leftAt={at(1, 0)} onLeft={onLeft} />)
  await vi.waitFor(() => expect(onLeft).toHaveBeenCalledWith(4))
  onLoad.mockResolvedValue({ rows: many(2), judge_fine: 0, more: false })
  await userEvent.click(screen.getByRole('button', { name: 'Today' }))
  expect(onLeft).toHaveBeenCalledTimes(1)
})

test('"Since I left" is not offered where the project was never left', async () => {
  view({ rows: [answer], judge_fine: 0 })
  const chips = await screen.findByRole('group', { name: 'Decisions since' })
  expect(
    within(chips)
      .getAllByRole('button')
      .map(chip => chip.textContent),
  ).toEqual(['Today', 'Week', 'Not seen'])
})

test('five rows, then Show all; each says when, who, where, what, the words it is of and why, and opens where it is', async () => {
  const { onOpenChat } = view({ rows: [answer, ran, ...many(5)], judge_fine: 2 })
  const list = await screen.findByRole('list', { name: 'Decisions, newest first' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(5)
  const [first, second] = within(list).getAllByRole('listitem')
  expect(within(first).getByText('Orchestrator')).toHaveClass('who-orchestrator')
  expect(first).toHaveTextContent('Fix loginnew')
  expect(first).toHaveTextContent('Answered a question for you: Which database for the tests? → SQLite')
  expect(within(first).getByText('they make one in a temp folder').tagName).toBe('Q')
  // (a rule of yours: in its colour, and in words)
  expect(within(second).getByText('Your rule')).toHaveClass('who-your_words')
  expect(within(second).getByText('rm -rf build').tagName).toBe('CODE')
  await userEvent.click(within(first).getByRole('button', { name: /^The question in its chat/ }))
  expect(onOpenChat).toHaveBeenCalledWith('c1')
  expect(screen.getByText('The judge let 2 commands run.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Show all 7' }))
  expect(within(list).getAllByRole('listitem')).toHaveLength(7)
  expect(screen.queryByRole('button', { name: /Show all/ })).toBeNull()
})

test('a task’s row opens it on To-do', async () => {
  const opened = vi.fn()
  window.addEventListener('koloni:open-todo', opened)
  view({ rows: [task], judge_fine: 0 })
  await userEvent.click(await screen.findByRole('button', { name: /^The task on To-do/ }))
  expect((opened.mock.calls[0][0] as CustomEvent).detail).toBe('t1')
  window.removeEventListener('koloni:open-todo', opened)
})

test('Copy as Markdown copies every row of the period as a plain list, each agent’s word inert', async () => {
  const user = userEvent.setup()
  view({ rows: [answer, ...many(6)], judge_fine: 1 })
  await user.click(await screen.findByRole('button', { name: 'Copy as Markdown' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Copied')
  const copied = await navigator.clipboard.readText()
  expect(copied.split('\n')[0]).toBe('Decided for you (Today):')
  expect(copied.split('\n').filter(line => line.startsWith('- '))).toHaveLength(7)
  expect(copied.endsWith('\n\nThe judge let 1 command run.')).toBe(true)
})

test('the Markdown: when, who and KOLONİ’s sentence as they are; a quote, an answer and a reason in code spans', () => {
  const hostile = 'see ![x](https://evil.example/a.png?k=1) and `code` @octocat <img src=x>\n# heading'
  expect(markdown({ rows: [answer, { ...ran, why: hostile }], judge_fine: 3, more: false }, 'Today', NOW)).toBe(
    [
      'Decided for you (Today):',
      '',
      '- 04:40 · Orchestrator · Answered a question for you: ` Which database for the tests? ` → ` SQLite ` · why: ` they make one in a temp folder `',
      "- 03:55 · Your rule · Ran a command without asking, on a line of this project's rules: ` rm -rf build ` · why: `` see ![x](https://evil.example/a.png?k=1) and `code` @octocat <img src=x> # heading ``",
      '',
      'The judge let 3 commands run.',
    ].join('\n'),
  )
  // A row of before today says its day.
  const before = markdown(
    { rows: [{ ...task, at: new Date(2026, 10, 23, 22, 5).toISOString() }], judge_fine: 0, more: false },
    'This week',
    NOW,
  )
  expect(before).toMatch(
    /^- \S+ 22:05 · Orchestrator · Decided on a task the Scout proposed: ` Fix the login timeout ` → ` Add `/m,
  )
})

test('a period with nothing decided says so in one sentence: no list, no Copy', async () => {
  view({ rows: [], judge_fine: 4 })
  expect(await screen.findByText('Nothing was decided for you today.')).toBeInTheDocument()
  expect(screen.getByText('The judge let 4 commands run.')).toBeInTheDocument()
  expect(screen.queryByRole('list')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Copy as Markdown' })).toBeNull()
})

test('asked by "Open in Ready for you", it takes the focus, in view, and says so', async () => {
  const onOpened = vi.fn()
  const log = { rows: [answer], judge_fine: 0, more: false }
  render(<Decisions onLoad={vi.fn().mockResolvedValue(log)} leftAt={null} asked="any" onOpened={onOpened} />)
  const box = await screen.findByRole('region', { name: /^Decided for you/ })
  expect(box).toHaveFocus()
  expect(onOpened).toHaveBeenCalledTimes(1)
})

test('a period of more than the log gives says it shows the newest, on the screen and in the Markdown', async () => {
  const user = userEvent.setup()
  view({ rows: many(7), judge_fine: 0, more: true })
  expect(await screen.findByRole('region', { name: 'Decided for you 7+, 3 not seen' })).toBeInTheDocument()
  expect(screen.getByText('Showing the newest 7.')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Copy as Markdown' }))
  await screen.findByRole('status')
  expect(await navigator.clipboard.readText()).toMatch(/\n\nShowing the newest 7\.$/)
})

test('another period: the last one’s rows go at once, not shown nor copied under its chip', async () => {
  const later = new Promise<DecisionLog>(() => {})
  const onLoad = vi
    .fn()
    .mockResolvedValueOnce({ rows: [answer], judge_fine: 0, more: false })
    .mockReturnValue(later)
  render(<Decisions onLoad={onLoad} leftAt={null} />)
  expect(await screen.findByRole('region', { name: 'Decided for you 1, 1 not seen' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Week' }))
  expect(screen.getByRole('region', { name: 'Decided for you' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Copy as Markdown' })).toBeNull()
})

test('an agent’s words, rendered as GitHub renders a PR body, make no link, image, HTML or heading', () => {
  // (the reviewer's cases: fences inside, markup, mentions, autolinks, line breaks of every kind)
  const hostile = [
    'a ``` b',
    '`',
    '``',
    '` x `',
    'x`',
    '</code><img src=x onerror=alert(1)>',
    '[x](javascript:alert(1))',
    '![](http://evil.example/beacon.png)',
    '<b>bold</b> <script>alert(1)</script>',
    '@octocat please merge',
    '# heading',
    '| a | b |\n|---|---|',
    'line1\nline2\r\nline3\rline4',
    'sep\u2028a\u2029b\u0085c',
    '`'.repeat(200) + ' long',
    'http://evil.example/autolink www.evil.example',
    '\\` escaped backtick \\',
    '&lt;b&gt; &#96; entity',
    ':smile: ~~strike~~ **bold** _em_',
    '[^1]: footnote',
  ]
  for (const words of hostile) {
    const { container, unmount } = render(
      <Markdown remarkPlugins={[remarkGfm]}>
        {markdownRow({ ...answer, quote: words, answer: 'A', why: words })}
      </Markdown>,
    )
    expect(container.querySelectorAll('a, img, script, b, strong, em, del, table, h1, h2, sup, input')).toHaveLength(0)
    const codes = Array.from(container.querySelectorAll('code'), code => code.textContent)
    expect(codes, words).toEqual([words.replace(/\s+/g, ' ').trim(), 'A', words.replace(/\s+/g, ' ').trim()])
    unmount()
  }
  // Blank words make no empty code span.
  expect(markdownRow({ ...answer, quote: ' ', why: null })).not.toContain('`  `')
})

/** The server, as the rows' OK and Change reach it: each request kept. */
function server() {
  const asked = vi.fn(async (_url: string, _init?: RequestInit) => new Response('{}', { status: 200 }))
  vi.stubGlobal('fetch', asked)
  const calls = () => asked.mock.calls.map(([url, init]) => [url, init?.method, init?.body ?? null])
  return calls
}

test('OK on a row not seen, and Change while its agent works: to the server, then the log is read again', async () => {
  const calls = server()
  const unseenCommand = { ...ran, id: 'command:k2', link: { kind: 'command' as const, id: 'k2' } }
  const { onLoad } = view({ rows: [answer, unseenCommand], judge_fine: 0 })
  const list = await screen.findByRole('list', { name: 'Decisions, newest first' })
  const [card, command] = within(list).getAllByRole('listitem')
  await userEvent.click(within(card).getByRole('button', { name: 'OK' }))
  await vi.waitFor(() => expect(onLoad).toHaveBeenCalledTimes(2))
  await userEvent.click(within(card).getByRole('button', { name: 'Change → Postgres' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Sent to the agent that asked, while it works')
  await userEvent.click(within(command).getByRole('button', { name: 'OK' }))
  // (each OK reads the project's board again too: the pill's and the chat's line's count, K1)
  await vi.waitFor(() => expect(calls().filter(([url]) => url === '/api/board')).toHaveLength(2))
  expect(calls().filter(([, method]) => method !== 'GET')).toEqual([
    ['/api/questions/q1/ok', 'POST', '{}'],
    ['/api/questions/q1/change', 'POST', JSON.stringify({ answer: 'Postgres' })],
    ['/api/commands/k2/seen', 'POST', '{}'],
  ])
  // (it ran: no Change, and why)
  expect(command).toHaveTextContent("can't be undone: it ran")
  expect(within(command).queryByRole('button', { name: /Change/ })).toBeNull()
})

test('an answer whose agent finished: Change and redo, what it costs, to the project’s decision', async () => {
  const calls = server()
  useApp.setState({ projectId: 'p1' })
  const finished: Decision = { ...answer, undo: 'change_and_redo' }
  const gone: Decision = { ...answer, id: 'answer:q2', undo: 'none', undo_reason: 'its work was taken in' }
  const { onLoad } = view({ rows: [finished, gone], judge_fine: 0 })
  const [row, taken] = within(await screen.findByRole('list', { name: 'Decisions, newest first' })).getAllByRole(
    'listitem',
  )
  expect(within(row).queryByRole('button', { name: 'Change → Postgres' })).toBeNull()
  expect(row).toHaveTextContent('starts a new turn')
  expect(row).not.toHaveTextContent('$')
  await userEvent.click(within(row).getByRole('button', { name: 'Change and redo → Postgres' }))
  expect(await screen.findByRole('status')).toHaveTextContent('A new turn of its chat started')
  expect(calls()).toEqual([['/api/projects/p1/decisions/q1/redo', 'POST', JSON.stringify({ answer: 'Postgres' })]])
  await vi.waitFor(() => expect(onLoad).toHaveBeenCalledTimes(2))
  // (its work taken in: no button, and why)
  expect(within(taken).queryByRole('button', { name: /Change/ })).toBeNull()
  expect(taken).toHaveTextContent("can't be undone: its work was taken in")
})

test('Change and redo on a job whose branch you pushed says it adds to that branch', async () => {
  const pushed: Decision = {
    ...answer,
    undo: 'change_and_redo',
    undo_note: 'adds to the branch koloni/fix-login that you pushed',
  }
  view({ rows: [pushed], judge_fine: 0 })
  const button = await screen.findByRole('button', { name: 'Change and redo → Postgres' })
  expect(button).toHaveAttribute('title', 'starts a new turn; adds to the branch koloni/fix-login that you pushed')
  expect(button.closest('li')).toHaveTextContent(
    'starts a new turn; adds to the branch koloni/fix-login that you pushed',
  )
})

test('a row of the open chat tells its store at once, as the chat’s own box did', async () => {
  const ok = vi.spyOn(useApp.getState(), 'decidedOk').mockResolvedValue()
  const changed = vi.spyOn(useApp.getState(), 'decidedChange').mockResolvedValue()
  useApp.setState({ conv: convState({ conversation: { ...conversation, id: 'c1' } }) })
  view({ rows: [answer], judge_fine: 0 })
  const row = (await screen.findAllByRole('listitem'))[0]
  await userEvent.click(within(row).getByRole('button', { name: 'OK' }))
  await userEvent.click(within(row).getByRole('button', { name: 'Change → Postgres' }))
  expect(ok).toHaveBeenCalledWith('q1')
  expect(changed).toHaveBeenCalledWith('q1', 'Postgres')
  ok.mockRestore()
  changed.mockRestore()
  useApp.setState({ conv: null })
})

test('a To-do choice: OK decides nothing - its word seen -; Change sends the state its row showed; refused, it is read again', async () => {
  const seen = vi.spyOn(useApp.getState(), 'seenTask').mockResolvedValue()
  const decide = vi.spyOn(useApp.getState(), 'decideTask')
  vi.spyOn(useApp.getState(), 'loadBacklog').mockResolvedValue()
  vi.spyOn(useApp.getState(), 'loadBoard').mockResolvedValue()
  const asked = vi.fn(async (url: string, _init?: RequestInit) =>
    url.endsWith('/t1/decide')
      ? new Response(JSON.stringify({ detail: 'it changed since you looked: read the decisions again' }), {
          status: 409,
        })
      : new Response('{}', { status: 200 }),
  )
  vi.stubGlobal('fetch', asked)
  const { onLoad } = view({
    rows: [task, { ...task, id: 'task:t2', answer: 'Reject', link: { kind: 'task', id: 't2' } }],
    judge_fine: 0,
  })
  const [added, turned] = within(await screen.findByRole('list', { name: 'Decisions, newest first' })).getAllByRole(
    'listitem',
  )
  await userEvent.click(within(added).getByRole('button', { name: 'Change → Reject' }))
  expect(await within(added).findByRole('alert')).toHaveTextContent('it changed since you looked')
  await vi.waitFor(() => expect(onLoad).toHaveBeenCalledTimes(2))
  await userEvent.click(within(added).getByRole('button', { name: 'OK' }))
  await userEvent.click(within(turned).getByRole('button', { name: 'OK' }))
  await userEvent.click(within(turned).getByRole('button', { name: 'Change → Add' }))
  expect(seen.mock.calls).toEqual([['t1'], ['t2']])
  expect(decide).not.toHaveBeenCalled()
  expect(asked.mock.calls.map(([url, init]) => [url, init?.body])).toEqual([
    ['/api/backlog/t1/decide', JSON.stringify({ decision: 'reject', expect: 'added' })],
    ['/api/backlog/t2/decide', JSON.stringify({ decision: 'approve', expect: 'proposed' })],
  ])
  vi.restoreAllMocks()
})

test('Not seen: what waits for your OK, of any age - and opened at it when asked so', async () => {
  const onLoad = vi.fn().mockResolvedValue({ rows: [answer], judge_fine: 0, more: false })
  const onOpened = vi.fn()
  render(<Decisions onLoad={onLoad} leftAt={at(1, 0)} asked="unseen" onOpened={onOpened} />)
  const chips = await screen.findByRole('group', { name: 'Decisions since' })
  await vi.waitFor(() =>
    expect(within(chips).getByRole('button', { name: 'Not seen' })).toHaveAttribute('aria-pressed', 'true'),
  )
  expect(onLoad).toHaveBeenLastCalledWith(null, true)
  expect(onOpened).toHaveBeenCalledTimes(1)
})

test('it is read again on what the store hears change it, and when the window comes back', async () => {
  const { onLoad } = view({ rows: [answer], judge_fine: 0 })
  await screen.findByRole('list', { name: 'Decisions, newest first' })
  expect(onLoad).toHaveBeenCalledTimes(1)
  act(() => useApp.setState({ backlog: [{ id: 't9', status: 'todo', po: { lead: 'add' } } as never] }))
  await vi.waitFor(() => expect(onLoad).toHaveBeenCalledTimes(2))
  act(() => void window.dispatchEvent(new Event('focus')))
  await vi.waitFor(() => expect(onLoad).toHaveBeenCalledTimes(3))
})

test('another project’s reader: the last project’s rows go at once', async () => {
  const first = vi.fn().mockResolvedValue({ rows: [answer], judge_fine: 0, more: false })
  const { rerender } = render(<Decisions onLoad={first} leftAt={null} />)
  await screen.findByRole('list', { name: 'Decisions, newest first' })
  const other = vi.fn().mockReturnValue(new Promise<DecisionLog>(() => {}))
  rerender(<Decisions onLoad={other} leftAt={null} />)
  expect(screen.queryByRole('list', { name: 'Decisions, newest first' })).toBeNull()
})

test('a line of your own message is "Your words"; another rule of yours "Your rule"', async () => {
  view({
    rows: [
      { ...ran, source: 'message' },
      { ...ran, id: 'command:k3', source: 'rules' },
    ],
    judge_fine: 0,
  })
  const [words, rule] = within(await screen.findByRole('list', { name: 'Decisions, newest first' })).getAllByRole(
    'listitem',
  )
  expect(within(words).getByText('Your words')).toHaveClass('who-your_words')
  expect(within(rule).getByText('Your rule')).toBeInTheDocument()
  expect(markdownRow({ ...ran, source: 'message' })).toContain(' · Your words · ')
})

test('what the store hears is made again only where an array it reads is another - a token streamed is none', () => {
  const questions = [question('q1', 'r1')]
  const filter = vi.spyOn(questions, 'filter')
  const conv = convState({ questions })
  const first = heardOf(null, conv)
  // (a token streamed: another state, the same arrays)
  expect(heardOf(null, { ...conv, messages: [] })).toBe(first)
  expect(filter).toHaveBeenCalledTimes(1)
  const decided = question('q2', 'r1', { status: 'answered', answer: 'Yes', lead_why: 'it is safe' })
  expect(heardOf(null, { ...conv, questions: [...questions, decided] })).toBe('q2')
})
