import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test } from 'vitest'
import { HowItWorks } from './HowItWorks'

beforeEach(() => localStorage.clear())

const fold = () => screen.getByText('How this works').closest('details')!

test('closed at first, the text in it all the same', () => {
  render(<HowItWorks page="memory"><p>The long part.</p></HowItWorks>)
  expect(fold()).not.toHaveAttribute('open')
  expect(fold()).toHaveTextContent('The long part.')
})

test('opened, it is open again the next time that page is shown - and only that page', async () => {
  render(<HowItWorks page="memory"><p>a</p></HowItWorks>)
  await userEvent.click(screen.getByText('How this works'))
  expect(fold()).toHaveAttribute('open')
  cleanup()
  render(<HowItWorks page="memory"><p>a</p></HowItWorks>)
  expect(fold()).toHaveAttribute('open')
  cleanup()
  render(<HowItWorks page="usage"><p>a</p></HowItWorks>)
  expect(fold()).not.toHaveAttribute('open')
  cleanup()
  // closed again, it stays closed
  render(<HowItWorks page="memory"><p>a</p></HowItWorks>)
  await userEvent.click(screen.getByText('How this works'))
  cleanup()
  render(<HowItWorks page="memory"><p>a</p></HowItWorks>)
  expect(fold()).not.toHaveAttribute('open')
})

test('a stored value it does not know is read as closed', () => {
  localStorage.setItem('koloni-how:memory', '{"open":tru')
  render(<HowItWorks page="memory"><p>a</p></HowItWorks>)
  expect(fold()).not.toHaveAttribute('open')
})
