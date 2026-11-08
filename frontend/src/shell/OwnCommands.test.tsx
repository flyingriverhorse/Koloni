import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { OwnCommand, Project, Role } from '../api/types'
import { resetStoreForTests, useApp } from '../state/store'
import { OwnCommands } from './OwnCommands'
import { ProjectSettings } from './ProjectSettings'

afterEach(() => resetStoreForTests())

const command = (name: string, extra: Partial<OwnCommand> = {}) =>
  ({ id: name, name, description: `${name}'s line`, template: 'Do {args}', role: null, project_id: 'p', ...extra }) as OwnCommand

function setup(ownCommands: OwnCommand[] = []) {
  const saveOwnCommand = vi.fn().mockResolvedValue(undefined)
  const deleteOwnCommand = vi.fn().mockResolvedValue(undefined)
  useApp.setState({
    ownCommands,
    roles: [{ id: 'l', name: 'Lead' }, { id: 't', name: 'Translator' }] as Role[],
    saveOwnCommand,
    deleteOwnCommand,
  })
  render(<OwnCommands projectId="p" />)
  return { saveOwnCommand, deleteOwnCommand }
}

test('a command is added for this project, or for every project, with a role if one is picked', async () => {
  const { saveOwnCommand } = setup()
  expect(screen.getByText('None yet.')).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Name'), 'test-yaz')
  await userEvent.type(screen.getByLabelText('What it does'), 'Write tests')
  await userEvent.type(screen.getByLabelText('Text it puts in the box'), 'Write tests for {{args}')
  // the Lead is not offered: the message goes to it anyway
  expect(within(screen.getByLabelText('Hand it to a role')).getAllByRole('option').map(o => o.textContent)).toEqual(['No role', 'Translator'])
  await userEvent.selectOptions(screen.getByLabelText('Hand it to a role'), 'Translator')
  await userEvent.click(screen.getByLabelText('In every project'))
  await userEvent.click(screen.getByRole('button', { name: 'Add command' }))
  expect(saveOwnCommand).toHaveBeenCalledWith(null, { name: 'test-yaz', description: 'Write tests', template: 'Write tests for {args}', role: 'Translator', project_id: null })
  // emptied for the next
  expect(screen.getByLabelText('Name')).toHaveValue('')
})

test('one is changed in the same form, and deleted; what the server refuses is said', async () => {
  const { saveOwnCommand, deleteOwnCommand } = setup([command('tidy', { project_id: null, role: 'Translator' })])
  const row = screen.getByRole('listitem')
  expect(row).toHaveTextContent('/tidy')
  expect(row).toHaveTextContent('every project')
  await userEvent.click(within(row).getByRole('button', { name: 'Edit /tidy' }))
  expect(screen.getByLabelText('Name')).toHaveValue('tidy')
  expect(screen.getByLabelText('In every project')).toBeChecked()
  expect(screen.getByLabelText('Hand it to a role')).toHaveValue('Translator')
  await userEvent.selectOptions(screen.getByLabelText('Hand it to a role'), '')
  saveOwnCommand.mockRejectedValueOnce(new ApiError(409, 'there is already a command named /tidy there'))
  await userEvent.click(screen.getByRole('button', { name: 'Save command' }))
  expect(saveOwnCommand).toHaveBeenCalledWith('tidy', expect.objectContaining({ role: null, project_id: null }))
  expect(screen.getByRole('alert')).toHaveTextContent('there is already a command named /tidy there')
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.getByRole('button', { name: 'Add command' })).toBeInTheDocument()
  await userEvent.click(within(row).getByRole('button', { name: 'Delete /tidy' }))
  expect(deleteOwnCommand).toHaveBeenCalledWith('tidy')
})

test('the project settings list it as a section of its own, with no Save of the project’s', async () => {
  const project = {
    id: 'p', name: 'demo', root_path: 'C:/demo', created_at: 't', exec_location: 'host', docker_image: null, docker_network: false,
    search_url: null, search_order: 'builtin', search_agy: false, has_notify_url: false, notify_format: 'slack', notify_desktop: false,
    turn_token_limit: null, max_agents: null, monthly_budget: null, check_command: null, git_commit: false, auto_notes: false, observe_reports: false, day_note_at: null, also_in: [], read_in: [],
    hide_secrets: true, lead_work: 'delegates', pass_env: null, held_env: [], koloni: { settings_kept: false, rules_kept: false, rules: null, broken: [], asks: {} },
  } as Project
  useApp.setState({ ownCommands: [command('a'), command('b')] })
  render(<ProjectSettings project={project} dockerAvailable dockerError={null} desktopAvailable onSave={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Slash commands/ }))
  expect(screen.getByRole('heading', { name: 'Slash commands' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
})

test('the focus follows: Edit to the name, Delete to the next row, and Add says it saved', async () => {
  const { saveOwnCommand, deleteOwnCommand } = setup([command('a'), command('b')])
  deleteOwnCommand.mockImplementation(async (id: string) => useApp.setState({ ownCommands: useApp.getState().ownCommands.filter(c => c.id !== id) }))
  await userEvent.click(screen.getByRole('button', { name: 'Edit /a' }))
  expect(screen.getByLabelText('Name')).toHaveFocus()
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete /a' }))
  expect(screen.getByRole('button', { name: 'Edit /b' })).toHaveFocus()
  await userEvent.click(screen.getByRole('button', { name: 'Delete /b' }))
  // none left: back to adding one
  expect(screen.getByLabelText('Name')).toHaveFocus()
  expect(screen.getByRole('status')).toHaveTextContent('')
  await userEvent.type(screen.getByLabelText('Name'), 'c')
  await userEvent.type(screen.getByLabelText('Text it puts in the box'), 't')
  await userEvent.click(screen.getByRole('button', { name: 'Add command' }))
  expect(saveOwnCommand).toHaveBeenCalled()
  expect(screen.getByRole('status')).toHaveTextContent('Saved')
  // written in again, it is no longer said
  await userEvent.type(screen.getByLabelText('Name'), 'd')
  expect(screen.getByRole('status')).toHaveTextContent('')
})
