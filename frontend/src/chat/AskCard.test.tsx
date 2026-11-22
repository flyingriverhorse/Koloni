import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { when } from '../canvas/turns'
import type { ChatTab } from '../state/store'
import { agent, convState, question, run } from '../test-fixtures'
import { AskCard, AskLine } from './AskCard'

const asking = (...questions: ReturnType<typeof question>[]) =>
  convState({ runs: [run('r', 'waiting_approval')], agents: [agent('r')], questions: questions.length ? questions : [question('q', 'r', { options: ['hey', 'hello'] })] })

/** The card over the box, and the message box under it (the focus goes back there). */
function draw(conv = asking(), onAnswer = vi.fn(async () => {}), { open = true, tab = 'Chat' as ChatTab } = {}) {
  const view = render(
    <>
      <AskCard conv={conv} open={open} tab={tab} onAnswer={onAnswer} />
      <textarea className="composer-input" aria-label="Message" />
    </>,
  )
  return { ...view, onAnswer }
}
const card = () => screen.getByRole('form', { name: 'Orchestrator asks' })
const radio = (name: string | RegExp) => within(card()).getByRole('radio', { name })

test('the Orchestrator’s question waits over the message box: who asks and in which turn, numbered options, your own answer and Submit', async () => {
  const { onAnswer } = draw()
  expect(card()).toHaveTextContent(`Orchestrator asks · ${when(run('r').created_at)}`)
  expect(within(card()).getByText('Which greeting?')).toBeInTheDocument()
  expect(within(card()).getByRole('radiogroup')).toBeInTheDocument()
  expect(radio(/hey/).closest('label')).toHaveTextContent(/^1hey$/)
  expect(radio(/hello/).closest('label')).toHaveTextContent(/^2hello$/)
  expect(within(card()).getByLabelText('Your answer')).toBeInTheDocument()
  const submit = within(card()).getByRole('button', { name: 'Submit' })
  expect(submit).toBeDisabled()
  await userEvent.click(radio(/hello/))
  expect(radio(/hello/)).toBeChecked()
  await userEvent.click(submit)
  expect(onAnswer).toHaveBeenCalledWith('q', 'hello')
})

test('keys 1-9 pick an option and Enter sends it; in your own answer digits are text', async () => {
  const { onAnswer } = draw()
  await userEvent.click(radio(/hey/))
  await userEvent.keyboard('2{Enter}')
  expect(onAnswer).toHaveBeenCalledWith('q', 'hello')
  await userEvent.type(within(card()).getByLabelText('Your answer'), 'good 2{Enter}')
  expect(onAnswer).toHaveBeenLastCalledWith('q', 'good 2')
})

test('two questions: ‹ 1/2 › goes between them; no ✕; ⌄ folds it to its head', async () => {
  draw(asking(question('q', 'r', { question: 'First?' }), question('q2', 'r', { question: 'Second?', tool_call_id: '2' })))
  expect(within(card()).getByText('1/2')).toBeInTheDocument()
  expect(within(card()).getByText('First?')).toBeInTheDocument()
  await userEvent.click(within(card()).getByRole('button', { name: 'Next question' }))
  expect(within(card()).getByText('2/2')).toBeInTheDocument()
  expect(within(card()).getByText('Second?')).toBeInTheDocument()
  expect(within(card()).queryByRole('button', { name: /close|skip|dismiss/i })).toBeNull()
  const fold = within(card()).getByRole('button', { name: 'Fold the question' })
  expect(fold).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(fold)
  expect(fold).toHaveAttribute('aria-expanded', 'false')
  expect(within(card()).queryByRole('radiogroup')).toBeNull()
  // (One question alone has no pager.)
})

test('answered, the focus goes back to the message box; an answer refused says why, and the card stays', async () => {
  const { onAnswer } = draw()
  await userEvent.click(radio(/hey/))
  await userEvent.click(within(card()).getByRole('button', { name: 'Submit' }))
  expect(onAnswer).toHaveBeenCalledWith('q', 'hey')
  expect(screen.getByLabelText('Message')).toHaveFocus()
  onAnswer.mockRejectedValueOnce({ detail: 'the question is over' })
  await userEvent.click(within(card()).getByRole('button', { name: 'Submit' }))
  expect(await within(card()).findByRole('alert')).toHaveTextContent('the question is over')
})

test('only the Orchestrator’s own question: KOLONİ’s card, a ready card, a sub-agent’s question show none; closed or on Talk, none', () => {
  const conv = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r'), agent('r', 'running', { id: 'k', depth: 1, parent_agent_id: 'r' })],
    questions: [
      question('koloni', 'r', { leave: true, question: 'Allow?', options: ['Allow', 'Deny'] }),
      question('ready', 'r', { leave: true, question: 'Ready for you: Web app. Take it in?', options: ['Take in'] }),
      question('sub', 'r', { agent_id: 'k' }),
    ],
  })
  const { container, unmount } = draw(conv)
  expect(container.querySelector('.ask-card')).toBeNull()
  unmount()
  // (Closed, or on Talk: hidden, not gone - an answer half written in it stays.)
  expect(draw(asking(), undefined, { open: false }).container.querySelector('.ask-card')).not.toBeVisible()
  expect(draw(asking(), undefined, { tab: 'Talk' }).container.querySelector('.ask-card')).not.toBeVisible()
})

test('Enter on the card’s own buttons does what they do, not Submit: ›, ⌄', async () => {
  const { onAnswer } = draw(asking(question('q', 'r', { question: 'First?', options: ['a', 'b'] }), question('q2', 'r', { question: 'Second?', tool_call_id: '2' })))
  await userEvent.click(radio(/^a$/))
  const next = within(card()).getByRole('button', { name: 'Next question' })
  next.focus()
  await userEvent.keyboard('{Enter}')
  expect(onAnswer).not.toHaveBeenCalled()
  expect(within(card()).getByText('2/2')).toBeInTheDocument()
  const fold = within(card()).getByRole('button', { name: 'Fold the question' })
  fold.focus()
  await userEvent.keyboard('{Enter}')
  expect(fold).toHaveAttribute('aria-expanded', 'false')
  expect(onAnswer).not.toHaveBeenCalled()
})

test('going between two questions keeps the focus on the pager and each question’s choice', async () => {
  draw(asking(question('q', 'r', { question: 'First?', options: ['a', 'b'] }), question('q2', 'r', { question: 'Second?', tool_call_id: '2', options: ['c'] })))
  await userEvent.click(radio(/^b$/))
  const next = within(card()).getByRole('button', { name: 'Next question' })
  await userEvent.click(next)
  expect(within(card()).getByText('Second?')).toBeInTheDocument()
  expect(within(card()).getByRole('button', { name: 'Previous question' })).toBeInTheDocument()
  // (› is off on the last: the focus stays on the pager, not on the page.)
  expect(card()).toContainElement(document.activeElement as HTMLElement)
  await userEvent.click(within(card()).getByRole('button', { name: 'Previous question' }))
  expect(card()).toContainElement(document.activeElement as HTMLElement)
  expect(radio(/^b$/)).toBeChecked()
})

const two = () => [question('q', 'r', { question: 'First?', options: ['a', 'b'] }), question('q2', 'r', { question: 'Second?', tool_call_id: '2', options: ['c', 'd'] })]

test('a question’s line in its turn pages the card to that question and puts the focus on its first option', async () => {
  const [first, second] = two()
  render(
    <>
      <AskLine question={second} who="Orchestrator" />
      <AskCard conv={asking(first, second)} open tab="Chat" onAnswer={vi.fn(async () => {})} />
    </>,
  )
  expect(within(card()).getByText('1/2')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Orchestrator asks: Second? · waits for you' }))
  expect(within(card()).getByText('Second?')).toBeInTheDocument()
  expect(radio(/^c$/)).toHaveFocus()
})

test('the card follows its question by id: another one answered, it stays on the one shown; a refusal of one is not said on another', async () => {
  const [first, second] = two()
  const third = question('q3', 'r', { question: 'Third?', tool_call_id: '3', options: ['e'] })
  const onAnswer = vi.fn(async () => {})
  const { rerender } = render(<AskCard conv={asking(first, second, third)} open tab="Chat" onAnswer={onAnswer} />)
  await userEvent.click(within(card()).getByRole('button', { name: 'Next question' }))
  expect(within(card()).getByText('Second?')).toBeInTheDocument()
  rerender(<AskCard conv={asking({ ...first, status: 'answered', answer: 'a' }, second, third)} open tab="Chat" onAnswer={onAnswer} />)
  expect(within(card()).getByText('Second?')).toBeInTheDocument()
  onAnswer.mockRejectedValueOnce({ detail: 'the question is over' })
  await userEvent.click(radio(/^c$/))
  await userEvent.click(within(card()).getByRole('button', { name: 'Submit' }))
  expect(await within(card()).findByRole('alert')).toHaveTextContent('the question is over')
  await userEvent.click(within(card()).getByRole('button', { name: 'Next question' }))
  expect(within(card()).getByText('Third?')).toBeInTheDocument()
  expect(within(card()).queryByRole('alert')).toBeNull()
})

test('folded in one chat, the card is open in another', async () => {
  const conv = asking()
  const { rerender } = render(<AskCard conv={conv} open tab="Chat" onAnswer={vi.fn(async () => {})} />)
  await userEvent.click(within(card()).getByRole('button', { name: 'Fold the question' }))
  expect(within(card()).queryByRole('radiogroup')).toBeNull()
  rerender(<AskCard conv={{ ...conv, conversation: { ...conv.conversation, id: 'c2' } }} open tab="Chat" onAnswer={vi.fn(async () => {})} />)
  expect(within(card()).getByRole('radiogroup')).toBeInTheDocument()
})

test('a digit with Ctrl, Alt or Meta is left to the browser', async () => {
  draw()
  await userEvent.click(radio(/hey/))
  await userEvent.keyboard('{Control>}2{/Control}{Alt>}2{/Alt}')
  expect(radio(/hey/)).toBeChecked()
  expect(radio(/hello/)).not.toBeChecked()
})

test('☾ Away: your own answer as you type holds the Orchestrator off it - the page says so at most once in 30 s', async () => {
  const { api } = await import('../api/client')
  const { useApp } = await import('../state/store')
  const post = vi.spyOn(api, 'post').mockResolvedValue(undefined as never)
  const now = vi.spyOn(Date, 'now').mockReturnValue(1_000_000)
  draw(asking(question('qt', 'r', { options: ['hey', 'hello'] })))
  await userEvent.type(within(card()).getByLabelText('Your answer'), 'by name')
  expect(post.mock.calls.filter(([path]) => path === '/questions/qt/typing')).toHaveLength(1)
  now.mockReturnValue(1_031_000)
  useApp.getState().typing('qt')
  expect(post.mock.calls.filter(([path]) => path === '/questions/qt/typing')).toHaveLength(2)
  post.mockRestore()
  now.mockRestore()
})
