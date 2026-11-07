import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { api } from '../api/client'
import type { Project } from '../api/types'
import { useApp } from '../state/store'
import { DeleteProject, KEPT_ON_DISK } from './DeleteProject'

afterEach(() => vi.restoreAllMocks())

const project = { id: 'p', name: 'demo' } as Project
const PREVIEW = { chats: 12, memory: 34, tasks: 5, triggers: 1, knowledge: 0 }

async function opened() {
  vi.spyOn(api, 'get').mockResolvedValue(PREVIEW)
  render(<DeleteProject project={project} />)
  expect(screen.getByRole('region', { name: 'Delete project' })).toHaveTextContent(KEPT_ON_DISK)
  await userEvent.click(screen.getByRole('button', { name: 'Delete project…' }))
  expect(api.get).toHaveBeenCalledWith('/projects/p/delete-preview')
  return screen.findByRole('alertdialog', { name: 'Delete demo from KOLONİ?' })
}

test('Delete project… asks with what goes counted, says the folder stays and it cannot be undone, offers an export, and deletes only once the name is typed', async () => {
  const gone = vi.spyOn(useApp.getState(), 'deleteProject').mockResolvedValue()
  const dialog = await opened()
  expect(dialog).toHaveTextContent('This deletes 12 chats, 34 memory records, 5 To-do tasks, 1 trigger, 0 knowledge topics')
  expect(dialog).toHaveTextContent(KEPT_ON_DISK)
  expect(dialog).toHaveTextContent('It cannot be undone.')
  // the export: saved with no key in its address, its keys left out
  const zip = vi.fn(async () => new Response('PK', { headers: { 'Content-Disposition': 'attachment; filename="koloni-2026-11-06.zip"' } }))
  vi.stubGlobal('fetch', zip)
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:zip'), revokeObjectURL: vi.fn() })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await userEvent.click(within(dialog).getByRole('button', { name: 'Export first' }))
  await waitFor(() => expect(click).toHaveBeenCalledTimes(1))
  expect(zip).toHaveBeenCalledWith('/api/backup/export?secrets=false', expect.objectContaining({ method: 'POST' }))
  vi.unstubAllGlobals()

  const remove = within(dialog).getByRole('button', { name: 'Delete project' })
  const name = within(dialog).getByLabelText('Type the project’s name, demo, to delete it')
  expect(remove).toBeDisabled()
  await userEvent.type(name, 'Demo')
  expect(remove).toBeDisabled()
  await userEvent.clear(name)
  await userEvent.type(name, 'demo')
  expect(remove).toBeEnabled()
  await userEvent.click(remove)
  expect(gone).toHaveBeenCalledWith('p')
})

test('a refusal is said in the dialog, and Keep it closes it with nothing deleted', async () => {
  const gone = vi.spyOn(useApp.getState(), 'deleteProject').mockRejectedValue(new Error('a turn of the project is running — wait for it to end'))
  const dialog = await opened()
  await userEvent.type(within(dialog).getByRole('textbox'), 'demo')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Delete project' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('a turn of the project is running')
  expect(within(dialog).getByRole('button', { name: 'Delete project' })).toBeEnabled()
  await userEvent.click(within(dialog).getByRole('button', { name: 'Keep it' }))
  expect(screen.queryByRole('alertdialog')).toBeNull()
  expect(gone).toHaveBeenCalledTimes(1)
})

test('the name matches as it reads: an İ typed as I and its dot is the same İ; the case is not', async () => {
  vi.spyOn(api, 'get').mockResolvedValue(PREVIEW)
  render(<DeleteProject project={{ id: 'p', name: 'İz' } as Project} />)
  await userEvent.click(screen.getByRole('button', { name: 'Delete project…' }))
  const dialog = await screen.findByRole('alertdialog')
  const name = within(dialog).getByRole('textbox')
  const remove = within(dialog).getByRole('button', { name: 'Delete project' })
  fireEvent.change(name, { target: { value: 'İz' } })
  expect(remove).toBeEnabled()
  fireEvent.change(name, { target: { value: 'i̇z' } })
  expect(remove).toBeDisabled()
})
