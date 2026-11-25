import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { expect, test, vi } from 'vitest'
import type { Decision, DecisionLog } from '../api/types'
import { Decisions } from './Decisions'
import { markdown, markdownRow, weekStart } from './decisionLog'
import { since } from './period'

type Log = Omit<DecisionLog, 'more'> & { more?: boolean }

/** Today's Decisions (karar defteri): the period's chips, Show all, Copy as Markdown and the empty state. */

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
  why: 'they make one in a temp folder',
  conversation_id: 'c1',
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
  link: { kind: 'command', id: 'k1' },
  undo: 'none',
  undo_reason: 'it ran',
  seen: null,
}
const task: Decision = {
  ...ran,
  id: 'task:t1',
  at: at(2, 10),
  kind: 'task',
  who: 'orchestrator',
  what: 'Added a task the Scout proposed to To-do',
  quote: 'Fix the login timeout',
  why: 'it blocks the release',
  link: { kind: 'task', id: 't1' },
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

test('folded under its count and how many of its answers you have not seen; the period is chosen by its chips', async () => {
  const left = at(1, 0)
  const { onLoad } = view({ rows: many(7), judge_fine: 0 }, left)
  const fold = (await screen.findByText('· 7 (3 not seen)')).closest('details')!
  expect(fold).not.toHaveAttribute('open')
  expect(fold.querySelector('summary')).toHaveTextContent('Decisions· 7 (3 not seen)')
  expect(onLoad).toHaveBeenLastCalledWith(since('today'))
  const chips = within(fold).getByRole('group', { name: 'Decisions since' })
  expect(within(chips).getByRole('button', { name: 'Today' })).toHaveAttribute('aria-pressed', 'true')
  await userEvent.click(within(chips).getByRole('button', { name: 'This week' }))
  expect(onLoad).toHaveBeenLastCalledWith(weekStart())
  await userEvent.click(within(chips).getByRole('button', { name: 'Since I left' }))
  expect(onLoad).toHaveBeenLastCalledWith(left)
})

test('"Since I left" is not offered where the project was never left', async () => {
  view({ rows: [answer], judge_fine: 0 })
  const chips = await screen.findByRole('group', { name: 'Decisions since' })
  expect(
    within(chips)
      .getAllByRole('button')
      .map(chip => chip.textContent),
  ).toEqual(['Today', 'This week'])
})

test('five rows, then Show all; each says when, who, what, the words it is of and why, and opens where it is', async () => {
  const { onOpenChat } = view({ rows: [answer, ran, ...many(5)], judge_fine: 2 })
  const list = await screen.findByRole('list', { name: 'Decisions, newest first' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(5)
  const first = within(list).getAllByRole('listitem')[0]
  expect(first).toHaveTextContent(
    'Orchestrator · Answered a question for you: Which database for the tests? → SQLite · “they make one in a temp folder”not seen',
  )
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
      "- 03:55 · Check what I said first · Ran a command without asking, on a line of this project's rules: ` rm -rf build ` · why: `` see ![x](https://evil.example/a.png?k=1) and `code` @octocat <img src=x> # heading ``",
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
  expect(before).toMatch(/^- \S+ 22:05 · Orchestrator · Added a task/m)
})

test('a period with nothing decided says so in one sentence: no list, no Copy', async () => {
  view({ rows: [], judge_fine: 4 })
  expect(await screen.findByText('Nothing was decided for you today.')).toBeInTheDocument()
  expect(screen.getByText('The judge let 4 commands run.')).toBeInTheDocument()
  expect(screen.queryByRole('list')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Copy as Markdown' })).toBeNull()
})

test('asked from the chat’s "All decisions on Today", it opens itself and says so', async () => {
  const onOpened = vi.fn()
  const log = { rows: [answer], judge_fine: 0, more: false }
  render(<Decisions onLoad={vi.fn().mockResolvedValue(log)} leftAt={null} asked onOpened={onOpened} />)
  expect((await screen.findByText('· 1 (1 not seen)')).closest('details')).toHaveAttribute('open')
  expect(onOpened).toHaveBeenCalledTimes(1)
})

test('not asked, it is folded', async () => {
  view({ rows: [answer], judge_fine: 0 })
  expect((await screen.findByText('· 1 (1 not seen)')).closest('details')).not.toHaveAttribute('open')
})

test('a period of more than the log gives says it shows the newest, on the screen and in the Markdown', async () => {
  const user = userEvent.setup()
  view({ rows: many(7), judge_fine: 0, more: true })
  expect(await screen.findByText('· 7+ (3 not seen)')).toBeInTheDocument()
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
  expect(await screen.findByText('· 1 (1 not seen)')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'This week' }))
  expect(screen.queryByText('· 1 (1 not seen)')).toBeNull()
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
