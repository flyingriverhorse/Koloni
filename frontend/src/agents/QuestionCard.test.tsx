import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import { resetStoreForTests, useApp } from '../state/store'
import { agent, convState, question } from '../test-fixtures'
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
  const asked = question('q', 'r', {
    question: 'May the tool "scan" of the MCP server "rea" run?',
    options: ['Allow', 'Deny'],
    leave: true,
  })
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
  const card = question('q', 'r', {
    question: 'Web app: Write the spec is done. Go on?',
    options: ['Go on', 'Ask for changes', 'Stop'],
    leave: true,
  })
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

test('an agent’s question is its own title; said in one line, the line stands in place of who and title', async () => {
  const asked = question('q', 'r', { options: ['hello', 'hey'] })
  const { container, rerender } = render(<QuestionCard question={asked} onAnswer={vi.fn()} />)
  expect(container.querySelector('form')).toHaveClass('cmd-approval')
  expect(container.querySelector('form')).not.toHaveClass('question-line')
  expect(screen.getByText('The agent asks')).toHaveClass('card-who')
  expect(screen.getByText('Which greeting?')).toHaveClass('kicker', 'cmd-approval-kicker')
  expect(container.querySelector('.card-said')).toBeNull()
  expect(screen.getByLabelText('Your answer')).toHaveAttribute('placeholder', 'Or answer in your own words…')
  expect(screen.queryByRole('button', { name: 'details →' })).toBeNull()

  const onDetails = vi.fn()
  rerender(<QuestionCard question={asked} onAnswer={vi.fn()} line={{ text: 'Pick a greeting', onDetails }} />)
  expect(container.querySelector('form')).toHaveClass('cmd-approval', 'question-line')
  expect(screen.getByText('Pick a greeting')).toHaveClass('question-text')
  expect(container.querySelector('.card-who, .cmd-approval-kicker')).toBeNull()
  expect(screen.queryByLabelText('Your answer')).toBeNull()
  expect(screen.getAllByRole('button').map(button => button.textContent)).toEqual(['hello', 'hey', 'details →'])
  await userEvent.click(screen.getByRole('button', { name: 'details →' }))
  expect(onDetails).toHaveBeenCalledOnce()
})

test('an agent’s card names who asks as the screen calls it, from its chat or another; KOLONİ’s keeps its words, and no agent passes for it', () => {
  const who = (agentId: string, over: Parameters<typeof question>[2] = {}) => {
    const { container, unmount } = render(
      <QuestionCard question={question('q', 'r', { agent_id: agentId, ...over })} onAnswer={vi.fn()} />,
    )
    const said = container.querySelector('.card-who')?.textContent
    unmount()
    return said
  }
  try {
    // the open chat's Orchestrator and its Coder; another chat's Reviewer (Ready for you)
    useApp.setState({
      conv: convState({ agents: [agent('r'), agent('r', 'running', { id: 'kid', role_name: 'Coder', depth: 1 })] }),
      readyChats: { x: convState({ agents: [agent('rx', 'running', { role_name: 'Reviewer' })] }) },
    })
    expect([who('r'), who('kid'), who('rx')]).toEqual(['Orchestrator asks', 'Coder asks', 'Reviewer asks'])
    // one the page does not hold
    expect(who('gone')).toBe('The agent asks')
    expect(who('kid', { leave: true, options: ['Allow', 'Deny'] })).toBe('KOLONİ asks')
    // a role an agent made, named so
    useApp.setState({
      conv: convState({
        agents: [
          agent('r', 'running', { role_name: 'KOLONİ' }),
          agent('r', 'running', { id: 'k2', role_name: 'koloni ' }),
        ],
      }),
    })
    expect([who('r'), who('k2')]).toEqual(['The agent asks', 'The agent asks'])
  } finally {
    resetStoreForTests()
  }
})

test('a question without options asks for the answer alone', () => {
  const { container } = render(<QuestionCard question={question('q', 'r')} onAnswer={vi.fn()} />)
  expect(screen.getByLabelText('Your answer')).toHaveAttribute('placeholder', 'Your answer…')
  expect(container.querySelector('.question-options')).toBeNull()
})
