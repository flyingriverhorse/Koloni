import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { FROM_WORDS_WHY, useFromWords } from './sections/FromWords'

afterEach(() => vi.restoreAllMocks())

function FromWords() {
  return useFromWords()
}

test('The app › Agents: New preferences from your words is Add them, tell me until you choose Ask me first', async () => {
  vi.spyOn(api, 'get').mockResolvedValue({ mode: 'add' } as never)
  const put = vi.spyOn(api, 'put').mockImplementation(async (_path, body) => body as never)
  render(<FromWords />)
  const box = screen.getByLabelText('New preferences from your words')
  await waitFor(() => expect(box).toBeEnabled())
  expect(
    within(box)
      .getAllByRole('option')
      .map(one => one.textContent),
  ).toEqual(['Add them, tell me', 'Ask me first'])
  expect(box).toHaveDisplayValue('Add them, tell me')
  expect(screen.getByText(FROM_WORDS_WHY)).toBeInTheDocument()
  await userEvent.selectOptions(box, 'Ask me first')
  expect(put).toHaveBeenLastCalledWith('/preferences/from-words', { mode: 'ask' })
  await waitFor(() => expect(box).toHaveDisplayValue('Ask me first'))
})
