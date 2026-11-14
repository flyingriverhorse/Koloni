import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Health, Provider } from '../api/types'
import { FirstSteps } from './FirstSteps'

const down = { model_reachable: false, not_listed: false, provider_id: 'p-local', provider_name: 'Local' } as Health
const provider = (id: string, name: string, over: Partial<Provider> = {}) => ({ id, name, kind: 'claude_cli', ...over }) as Provider
const LOCAL = provider('p-local', 'Local', { kind: 'openai_compat' })

const steps = (over: Partial<Parameters<typeof FirstSteps>[0]> = {}) => {
  const props = {
    health: down,
    project: false,
    folder: null,
    wrote: false,
    turn: false,
    again: false,
    providers: [LOCAL, provider('p-off', 'Off', { enabled: false }), provider('p-cli', 'Claude Code')],
    pinned: false,
    onProvider: vi.fn(),
    onUse: vi.fn(async () => {}),
    onHidden: vi.fn(),
    onSaysProvider: vi.fn(),
    ...over,
  }
  render(<FirstSteps {...props} />)
  return props
}
const buttons = () => screen.getAllByRole('button').map(button => button.textContent)
const OLD = "Local isn't answering - add another provider, or start its model server."

test('while the default does not answer, the first other switched-on provider is offered for new chats - and the step is not done by it', () => {
  steps()
  // (Nothing is known of it but that it is on the list: it "is set up", not "answering".)
  const step = screen.getByText('A provider: the model your agents run on.').closest('li')
  expect(step).toHaveAttribute('aria-current', 'step')
  expect(step).toHaveTextContent("Local isn't answering, and new chats run on it. Claude Code is set up too.")
  expect(buttons()).toEqual(['Add a provider', 'Use Claude Code for new chats', 'Hide the first steps'])
})

test('no other switched-on provider on the list: nothing is offered', () => {
  steps({ providers: [LOCAL, provider('p-off', 'Off', { enabled: false })] })
  expect(screen.getByText(OLD)).toBeInTheDocument()
  expect(buttons()).toEqual(['Add a provider', 'Hide the first steps'])
})

test('a chat on a provider chosen for it: another default would change nothing for it, so none is offered', () => {
  steps({ pinned: true })
  expect(screen.getByText(OLD)).toBeInTheDocument()
  expect(buttons()).toEqual(['Add a provider', 'Hide the first steps'])
})

test('a press that is refused says why beside the button, which can be pressed again', async () => {
  const props = steps({ onUse: vi.fn(async () => Promise.reject({ detail: 'provider not found' })) })
  const use = screen.getByRole('button', { name: 'Use Claude Code for new chats' })
  await userEvent.click(use)
  expect(props.onUse).toHaveBeenCalledWith('p-cli')
  expect(await screen.findByRole('alert')).toHaveTextContent('provider not found')
  expect(use).toBeEnabled()
  expect(use).toHaveFocus()
})
