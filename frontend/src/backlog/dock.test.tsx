import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { BacklogTask } from '../api/types'
import { DOCK_SAYS, SelectionDock } from './Dock'

const task = (title: string): BacklogTask => ({
  id: title,
  title,
  detail: null,
  criteria: null,
  priority: 'normal',
  status: 'todo',
  position: 0,
  conversation_id: null,
  created_by: 'user',
  pending: null,
  assessment: null,
  not_in: false,
  after: [],
  queued: false,
  stuck: null,
  waiting: false,
  kind: 'task',
  created_at: '2026-11-24T10:00:00Z',
})

const three = [task('a'), task('b'), task('c')]

test('the dock gives the ticked tasks, in their order, to this chat or a new one', async () => {
  const onDo = vi.fn(async () => {})
  render(<SelectionDock selected={three} lastChat={{ id: 'c1', title: 'Auth work' }} onDo={onDo} />)
  expect(screen.getByRole('region', { name: 'Selected tasks' })).toHaveTextContent('3 selected')
  expect(screen.getByText(DOCK_SAYS)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Do in chat/ }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'This chat — “Auth work”' }))
  expect(onDo).toHaveBeenLastCalledWith(['a', 'b', 'c'], 'c1')
  await userEvent.click(screen.getByRole('button', { name: /Do in chat/ }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'A new chat' }))
  expect(onDo).toHaveBeenLastCalledWith(['a', 'b', 'c'], null)
})

test('with no chat of this folder open, only a new chat can take them', async () => {
  render(<SelectionDock selected={three} lastChat={null} onDo={async () => {}} />)
  await userEvent.click(screen.getByRole('button', { name: /Do in chat/ }))
  expect(screen.getByRole('menuitem', { name: 'This chat' })).toBeDisabled()
  expect(screen.getByRole('menuitem', { name: 'A new chat' })).toBeEnabled()
})

test('nothing ticked: no dock', () => {
  const { container } = render(<SelectionDock selected={[]} lastChat={null} onDo={async () => {}} />)
  expect(container).toBeEmptyDOMElement()
})

test('a refusal is said under the dock', async () => {
  render(
    <SelectionDock
      selected={three}
      lastChat={null}
      onDo={async () => {
        throw new Error('"b" is not to do now: it is done')
      }}
    />,
  )
  await userEvent.click(screen.getByRole('button', { name: /Do in chat/ }))
  await userEvent.click(screen.getByRole('menuitem', { name: 'A new chat' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('it is done')
})
