import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { command } from '../test-fixtures'
import { CommandRow } from './CommandRow'

const head = () => screen.getByRole('button', { name: /pytest -q/ })

test('in the chat a command is closed on success, open on failure or while output comes; a click wins; elsewhere as before', async () => {
  const ended = render(<CommandRow command={command('a', 'r')} live />)
  expect(head()).toHaveAttribute('aria-expanded', 'false')
  ended.rerender(<CommandRow command={command('a', 'r', { exit_code: 1, output: 'boom' })} live />)
  expect(head()).toHaveAttribute('aria-expanded', 'true')
  ended.unmount()
  const running = (output: string) => command('b', 'r', { status: 'running', exit_code: null, ended_at: null, output })
  const view = render(<CommandRow command={running('')} live />)
  expect(head()).toHaveAttribute('aria-expanded', 'false')
  view.rerender(<CommandRow command={running('tick 1')} live />)
  expect(head()).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(head())
  expect(head()).toHaveAttribute('aria-expanded', 'false')
  view.rerender(<CommandRow command={running('tick 1\ntick 2')} live />)
  expect(head()).toHaveAttribute('aria-expanded', 'false')
  view.unmount()
  // (In an agent's window and the side panel: closed until a click, failed or not.)
  render(<CommandRow command={command('c', 'r', { exit_code: 1, output: 'boom' })} />)
  expect(head()).toHaveAttribute('aria-expanded', 'false')
})
