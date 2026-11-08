import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { Help } from './Help'

afterEach(() => vi.restoreAllMocks())

const help = () => screen.queryByRole('dialog', { name: 'Help' })

test('`?` lists the keyboard shortcuts - not while something is typed - and Esc closes the list, the focus back where it was', async () => {
  render(
    <>
      <textarea className="composer-input" aria-label="Message" />
      <button type="button">elsewhere</button>
      <Help onFirstSteps={() => {}} />
    </>,
  )
  await userEvent.type(screen.getByLabelText('Message'), 'why?')
  expect(help()).not.toBeInTheDocument()
  expect(screen.getByLabelText('Message')).toHaveValue('why?')
  screen.getByRole('button', { name: 'elsewhere' }).focus()
  await userEvent.keyboard('?')
  expect(help()).toHaveFocus()
  const keys = within(help()!).getAllByRole('term').map(term => term.textContent)
  expect(keys).toEqual(['Ctrl+K', '?', '/', '/ in the box', 'C', 'Enter', 'Esc'])
  expect(within(help()!).getByText(/^Commands, at the start of the message box/)).toHaveTextContent('or one of your own (Settings › This project › Slash commands)')
  await userEvent.keyboard('{Escape}')
  expect(help()).not.toBeInTheDocument()
  // back where `?` was pressed
  expect(screen.getByRole('button', { name: 'elsewhere' })).toHaveFocus()
  // opened from its button, back on the button
  await userEvent.click(screen.getByRole('button', { name: 'Help' }))
  await userEvent.keyboard('{Escape}')
  expect(screen.getByRole('button', { name: 'Help' })).toHaveFocus()
})

test('`/` puts the focus in the message box, and is not typed into it', async () => {
  render(
    <>
      <textarea className="composer-input" aria-label="Message" />
      <Help onFirstSteps={() => {}} />
    </>,
  )
  await userEvent.keyboard('/')
  expect(screen.getByLabelText('Message')).toHaveFocus()
  expect(screen.getByLabelText('Message')).toHaveValue('')
})

test('opened from the top bar, the list stands under its button, inside the window', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    () => ({ left: 980, top: 10, width: 32, height: 32, x: 980, y: 10, right: 1012, bottom: 42, toJSON: () => ({}) }) as DOMRect,
  )
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(340)
  const onFirstSteps = vi.fn()
  render(<Help onFirstSteps={onFirstSteps} />)
  await userEvent.click(screen.getByRole('button', { name: 'Help' }))
  expect(help()!.style.top).toBe('50px')
  expect(help()!.style.left).toBe(`${window.innerWidth - 340 - 8}px`)
  await userEvent.click(within(help()!).getByRole('button', { name: 'Show the first steps' }))
  expect(onFirstSteps).toHaveBeenCalled()
  expect(help()).not.toBeInTheDocument()
})

test('C opens the closed chat - not while something is typed', async () => {
  const opened = vi.fn()
  render(
    <>
      <textarea aria-label="Note" />
      <button type="button" className="chat-line" onClick={opened}>Chat</button>
      <Help onFirstSteps={() => {}} />
    </>,
  )
  await userEvent.type(screen.getByLabelText('Note'), 'c')
  expect(opened).not.toHaveBeenCalled()
  screen.getByRole('button', { name: 'Help' }).focus()
  await userEvent.keyboard('c')
  expect(opened).toHaveBeenCalledTimes(1)
})

test('closed after the focus was put somewhere else, it is left there', async () => {
  render(
    <>
      <button type="button">elsewhere</button>
      <button type="button">other</button>
      <Help onFirstSteps={() => {}} />
    </>,
  )
  screen.getByRole('button', { name: 'elsewhere' }).focus()
  await userEvent.keyboard('?')
  await userEvent.click(screen.getByRole('button', { name: 'other' }))
  expect(help()).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'other' })).toHaveFocus()
})
