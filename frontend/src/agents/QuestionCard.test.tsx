import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import { question } from '../test-fixtures'
import { QuestionCard } from './QuestionCard'

test('an option is answered with one click', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  render(<QuestionCard question={question('q', 'r', { options: ['hello', 'hey'] })} onAnswer={onAnswer} />)
  expect(screen.getByText('Which greeting?')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'hey' }))
  expect(onAnswer).toHaveBeenCalledWith('hey')
})

test('any question can be answered in your own words, but not with nothing', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  render(<QuestionCard question={question('q', 'r', { options: ['hello', 'hey'] })} onAnswer={onAnswer} />)
  const send = screen.getByRole('button', { name: 'Send answer' })
  expect(send).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Your answer'), '   ')
  expect(send).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Your answer'), 'neither, say hi')
  await userEvent.click(send)
  expect(onAnswer).toHaveBeenCalledWith('neither, say hi')
})

test('leave asked for a tool is KOLONİ’s question, and its options are all there is to say', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  const asked = question('q', 'r', { question: 'May the tool "scan" of the MCP server "rea" run?', options: ['Allow', 'Deny'], leave: true })
  render(<QuestionCard question={asked} onAnswer={onAnswer} />)
  // a title of KOLONİ's own (sample A), its text whole under it, and who asks
  expect(screen.getByText('Allow this?')).toHaveClass('cmd-approval-kicker')
  expect(screen.getByText('May the tool "scan" of the MCP server "rea" run?')).toHaveClass('card-said')
  expect(screen.getByText('KOLONİ asks')).toBeInTheDocument()
  // any other answer would be a no: none is offered
  expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument()
  // its no is shown in the one word for no; what is sent is KOLONİ's own option
  expect(screen.getAllByRole('button').map(button => button.textContent)).toEqual(['Allow', 'Reject'])
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onAnswer).toHaveBeenCalledWith('Deny')
})

test('a question without options offers only the free answer', () => {
  render(<QuestionCard question={question('q', 'r')} onAnswer={vi.fn()} />)
  expect(screen.getAllByRole('button')).toHaveLength(1)
})

test('the card locks while the answer travels and says why it failed', async () => {
  let fail: (err: unknown) => void = () => {}
  const onAnswer = vi.fn(() => new Promise<void>((_, reject) => (fail = reject)))
  render(<QuestionCard question={question('q', 'r', { options: ['a', 'b'] })} onAnswer={onAnswer} />)
  await userEvent.click(screen.getByRole('button', { name: 'a' }))
  expect(screen.getByRole('button', { name: 'b' })).toBeDisabled()
  expect(screen.getByLabelText('Your answer')).toBeDisabled()
  fail(new ApiError(409, 'this question is no longer waiting for an answer'))
  expect(await screen.findByRole('alert')).toHaveTextContent('no longer waiting')
  expect(screen.getByRole('button', { name: 'b' })).toBeEnabled()
})

test('Ask for changes on a recipe’s card asks what to change, and sends it with it or alone (B-114)', async () => {
  const onAnswer = vi.fn().mockResolvedValue(undefined)
  const card = question('q', 'r', { question: 'Web app: Write the spec is done. Go on?', options: ['Go on', 'Ask for changes', 'Stop'], leave: true })
  const { unmount } = render(<QuestionCard question={card} onAnswer={onAnswer} />)
  await userEvent.click(screen.getByRole('button', { name: 'Ask for changes' }))
  expect(onAnswer).not.toHaveBeenCalled()
  await userEvent.type(screen.getByLabelText('What to change'), 'also add whisper')
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(onAnswer).toHaveBeenCalledWith('Ask for changes: also add whisper')
  unmount()
  render(<QuestionCard question={card} onAnswer={onAnswer} />)
  await userEvent.click(screen.getByRole('button', { name: 'Ask for changes' }))
  await userEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(onAnswer).toHaveBeenLastCalledWith('Ask for changes')
})
