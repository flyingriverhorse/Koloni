import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Project, ProjectMap as MapOf } from '../api/types'
import { useApp } from '../state/store'
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
  // (and the project, read again after each: `reread`)
  const get = vi.spyOn(api, 'get').mockImplementation(async path => (path === '/projects/p' ? project : map) as never)
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
  expect(get.mock.calls.filter(([path]) => path === '/projects/p/map')).toHaveLength(2)
  expect(await screen.findByLabelText('Test command for skyulf-core/')).toHaveValue('..\\.venv\\Scripts\\python.exe -m pytest')
})

test('a saved test command reads the project again: Settings › After a change names it', async () => {
  const read = { ...project, test_commands: { 'frontend/': 'npm test' } }
  useApp.setState({ projects: [project] })
  const get = vi.spyOn(api, 'get').mockImplementation(async path => (path === '/projects/p' ? read : map) as never)
  vi.spyOn(api, 'put').mockResolvedValue(map as never)
  render(<ProjectMap project={project} />)
  await userEvent.type(await screen.findByLabelText('Test command for frontend/'), 'npm test{Enter}')
  await vi.waitFor(() => expect(useApp.getState().projects).toEqual([read]))
  expect(get).toHaveBeenCalledWith('/projects/p')
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

test('the map’s line: one part, no git, and that not every folder was looked in; while it is read, Looking…; none found says so', async () => {
  let told: (read: MapOf) => void = () => {}
  vi.spyOn(api, 'get').mockImplementation(() => new Promise(resolve => (told = resolve as typeof told)))
  const { rerender } = render(<ProjectMap project={project} />)
  expect(screen.getByRole('status')).toHaveTextContent(/^Looking…$/)
  expect(screen.queryByText(/^Skyulf \(/)).toBeNull()
  told({ ...map, git: false, big: false, partial: true, not_copied: [], parts: [part('app/')] })
  expect(await screen.findByText(/^Skyulf \(1 part\)/)).toHaveTextContent(/^Skyulf \(1 part\) · not every folder was looked in$/)
  expect(screen.getByText('· not every folder was looked in')).toHaveClass('muted')
  expect(screen.getByRole('status')).toHaveTextContent(/^$/)
  expect(screen.queryByText(/Not copied|Too big to copy|No part found/)).toBeNull()
  rerender(<ProjectMap project={{ ...project, id: 'q' }} />)
  told({ ...map, git: false, parts: [] })
  expect(await screen.findByText('Skyulf (0 parts)')).toBeInTheDocument()
  expect(screen.getByText('No part found: no folder has a project file.')).toHaveClass('muted')
  expect(screen.getByText('Too big to copy: agents work in the folder itself.')).toHaveClass('choice-note')
  expect(screen.queryByRole('table')).toBeNull()
})

test('a map that cannot be read says why, and no longer says it is looking', async () => {
  vi.spyOn(api, 'get').mockRejectedValue(new Error('down'))
  render(<ProjectMap project={project} />)
  expect(await screen.findByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(/^$/)
})
