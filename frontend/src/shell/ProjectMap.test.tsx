import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Project, ProjectMap as MapOf } from '../api/types'
import { ProjectMap } from './ProjectMap'

const project = { id: 'p', name: 'Skyulf' } as Project
const part = (path: string, more: Partial<MapOf['parts'][number]> = {}): MapOf['parts'][number] => ({
  path, language: 'Python', files: 412, more: false, agents_md: false, guess: null, test: null, edited: false, ...more,
})
const map: MapOf = {
  git: true, big: true, partial: false, not_copied: ['data/', 'mlruns/'],
  parts: [
    part('skyulf-core/', { agents_md: true, guess: '..\\.venv\\Scripts\\python.exe -m pytest', test: '..\\.venv\\Scripts\\python.exe -m pytest' }),
    part('frontend/', { language: 'TypeScript', files: 1000, more: true }),
  ],
}

afterEach(() => vi.restoreAllMocks())

test('the map lists each part with its language, files, AGENTS.md and test, and what is not copied', async () => {
  vi.spyOn(api, 'get').mockResolvedValue(map as never)
  render(<ProjectMap project={project} />)
  const table = await screen.findByRole('table', { name: 'Parts of this folder' })
  expect(screen.getByText('Skyulf (git, 2 parts)')).toBeInTheDocument()
  const [core, front] = within(table).getAllByRole('row').slice(1)
  expect(within(core).getByRole('rowheader')).toHaveTextContent('skyulf-core/')
  expect(core).toHaveTextContent(/^skyulf-core\/Python412✓guess$/)
  expect(within(core).getByLabelText('Test command for skyulf-core/')).toHaveValue('..\\.venv\\Scripts\\python.exe -m pytest')
  expect(front).toHaveTextContent('TypeScript1000+✗')
  expect(within(front).getByLabelText('Test command for frontend/')).toHaveAttribute('placeholder', 'no test')
  expect(screen.getByText('Not copied (git ignores, the project is big): data/, mlruns/')).toBeInTheDocument()
  // (what a command written here means: it runs without a card, the guess does not)
  expect(screen.getByText(/A command you write here runs in its part without a card/)).toBeInTheDocument()
  expect(api.get).toHaveBeenCalledWith('/projects/p/map')
})

test('a test command is saved with Enter, taken back with Escape, and Refresh scans again', async () => {
  vi.spyOn(api, 'get').mockResolvedValue(map as never)
  const edited = { ...map, parts: [map.parts[0], { ...map.parts[1], test: 'npm test', edited: true }] }
  const put = vi.spyOn(api, 'put').mockResolvedValue(edited as never)
  const post = vi.spyOn(api, 'post').mockResolvedValue(edited as never)
  render(<ProjectMap project={project} />)
  const box = await screen.findByLabelText('Test command for frontend/')
  await userEvent.type(box, 'npm run x')
  expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(box).toHaveValue('')
  expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  await userEvent.type(box, 'npm test{Enter}')
  expect(put).toHaveBeenCalledWith('/projects/p/map/test', { path: 'frontend/', command: 'npm test' })
  expect(await screen.findByRole('status')).toHaveTextContent('Saved')
  expect(box).toHaveValue('npm test')
  // (the user's own now: no "guess" mark, a way back to the guess instead)
  expect(screen.getByRole('button', { name: 'Use guess for frontend/' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  expect(post).toHaveBeenCalledWith('/projects/p/map/refresh')
  expect(await screen.findByRole('status')).toHaveTextContent('Refreshed')
})

test('a guess saved empty is no test; Use guess brings the guess back', async () => {
  const noTest = { ...map, parts: [{ ...map.parts[0], test: null, edited: true }, map.parts[1]] }
  const get = vi.spyOn(api, 'get').mockResolvedValueOnce(map as never).mockResolvedValueOnce(map as never)
  const put = vi.spyOn(api, 'put').mockResolvedValue(noTest as never)
  const del = vi.spyOn(api, 'delete').mockResolvedValue(undefined)
  render(<ProjectMap project={project} />)
  const box = await screen.findByLabelText('Test command for skyulf-core/')
  await userEvent.clear(box)
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(put).toHaveBeenCalledWith('/projects/p/map/test', { path: 'skyulf-core/', command: '' })
  expect(box).toHaveValue('')
  expect(box).toHaveAttribute('placeholder', 'no test')
  await userEvent.click(await screen.findByRole('button', { name: 'Use guess for skyulf-core/' }))
  expect(del).toHaveBeenCalledWith('/projects/p/map/test?path=skyulf-core%2F')
  expect(get).toHaveBeenCalledTimes(2)
  expect(await screen.findByLabelText('Test command for skyulf-core/')).toHaveValue('..\\.venv\\Scripts\\python.exe -m pytest')
})

test('a refused save is said and the typed command stays', async () => {
  vi.spyOn(api, 'get').mockResolvedValue(map as never)
  vi.spyOn(api, 'put').mockRejectedValue(new Error('origin not allowed'))
  render(<ProjectMap project={project} />)
  const box = await screen.findByLabelText('Test command for frontend/')
  await userEvent.type(box, 'npm test')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('origin not allowed')
  expect(box).toHaveValue('npm test')
})
