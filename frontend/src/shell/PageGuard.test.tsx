import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { PageGuard } from './PageGuard'

function Broken(): never {
  throw new Error('turn.tokens is undefined')
}

test('a page that throws shows a short note in its place, not a blank app', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})  // React reports the caught error; the note is the point
  render(
    <>
      <nav>rail</nav>
      <PageGuard>
        <Broken />
      </PageGuard>
    </>,
  )
  expect(screen.getByRole('alert')).toHaveTextContent('This page could not be shown')
  expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  expect(screen.getByText('rail')).toBeInTheDocument()
})
