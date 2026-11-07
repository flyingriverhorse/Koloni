import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { api } from '../api/client'
import { ChangeActions } from '../changes/ChangeActions'
import { agent, assistantMessage, conversation, convState, fileChange, run, toolCall, userMessage } from '../test-fixtures'
import { MessageList } from './MessageList'

const handlers = { onRemoveQueued: vi.fn(), onOpenChange: vi.fn(), onDecide: vi.fn(), onDecideCommand: vi.fn() }
const STARTED = { message_id: 'm', started_at: '2026-10-05T10:00:02Z' }

test('a secret is typed on a hidden card and sent once: its value is nowhere on the page, before or after', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue(undefined)
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'ask_secret', 'pending', '{"name":"STRIPE_API_KEY","why":"to charge the test card"}', STARTED)],
  })
  const { container } = render(<MessageList {...handlers} state={state} onDecideRole={vi.fn()} />)
  expect(screen.getByText(/asks for/)).toHaveTextContent('Orchestrator asks for STRIPE_API_KEY')
  expect(screen.getByText('“to charge the test card”')).toBeInTheDocument()
  const field = screen.getByLabelText('Value of STRIPE_API_KEY')
  expect(field).toHaveAttribute('type', 'password')
  expect(field).toHaveAttribute('autocomplete', 'new-password')
  await userEvent.type(field, 'plain-words-given')
  expect(container.innerHTML).not.toContain('plain-words-given')
  await userEvent.click(screen.getByRole('button', { name: 'Give' }))
  expect(post).toHaveBeenLastCalledWith('/tool-calls/1/secret', { value: 'plain-words-given' })
  expect(field).toHaveValue('')
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(post).toHaveBeenLastCalledWith('/tool-calls/1/secret', { value: null })
  post.mockRestore()
})

test('a path outside the project is asked for under its call: once, for its folder, or not', async () => {
  const onDecideRole = vi.fn().mockResolvedValue(undefined)
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [
      // (the folder: where the path really leads, a link followed)
      toolCall('1', 'r', 'read_file', 'pending', '{"path":"C:\\\\x\\\\notes.md"}', { ...STARTED, outside_folder: 'D:\\real' }),
      // not started yet: one of a batch, waiting its turn - nothing is asked
      toolCall('2', 'r', 'read_file', 'pending', '{"path":"C:\\\\y\\\\a.md"}', { message_id: 'm' }),
      // in a folder not there yet: it can be allowed once only
      toolCall('3', 'r', 'write_file', 'pending', '{"path":"C:\\\\new\\\\a.md"}', STARTED),
    ],
  })
  render(<MessageList {...handlers} state={state} onDecideRole={onDecideRole} />)
  expect(screen.getByText(/wants to read/)).toHaveTextContent('Orchestrator wants to read C:\\x\\notes.md, outside the project')
  expect(screen.getAllByRole('button', { name: 'Allow once' })).toHaveLength(2)
  expect(screen.getAllByRole('button', { name: /Allow reading this folder/ })).toHaveLength(1)
  await userEvent.click(screen.getAllByRole('button', { name: 'Allow once' })[0])
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'approve', 'once')
  await userEvent.click(screen.getByRole('button', { name: 'Allow reading this folder: D:\\real' }))
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'approve', 'folder')
  await userEvent.click(screen.getAllByRole('button', { name: 'Reject' })[0])
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'reject')
})

test('a secret file in the project is asked for with the reason the backend gives: once, or not', async () => {
  const onDecideRole = vi.fn().mockResolvedValue(undefined)
  const why = "This is a secret file (keys, passwords): reading it sends what it holds to the model's provider."
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'read_file', 'pending', '{"path":".env"}', { ...STARTED, why_asked: why })],
  })
  render(<MessageList {...handlers} state={state} onDecideRole={onDecideRole} />)
  expect(screen.getByText(/wants to read/)).toHaveTextContent('Orchestrator wants to read .env')
  expect(screen.getByText(why)).toBeInTheDocument()
  expect(screen.queryByText(/outside the project/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /this folder/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Allow once' }))
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'approve', 'once')
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'reject')
})

const CLI_WHY =
  "This folder is Codex's settings for this whole computer: changing it affects every project. It may hold API keys: those KOLONİ knows by their shape are hidden from the model, the rest of what is read here goes to the model's provider."

test.each([false, true])("a file in a CLI's own folder is asked for once, saying it is that CLI's settings for the whole computer (no folder: %s)", async noFolder => {
  const onDecideRole = vi.fn().mockResolvedValue(undefined)
  const why = CLI_WHY
  const state = convState({
    ...(noFolder ? { conversation: { ...conversation, project_id: null } } : {}),
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [
      toolCall('1', 'r', 'edit_file', 'pending', '{"path":"C:/Users/me/x/../.codex/config.toml"}', {
        ...STARTED,
        why_asked: why,
        outside_folder: 'C:\\Users\\me\\.codex\\config.toml',
      }),
    ],
  })
  render(<MessageList {...handlers} state={state} onDecideRole={onDecideRole} />)
  expect(screen.getByText('Open this computer’s settings?')).toBeInTheDocument()
  expect(screen.getByText(/wants to change/)).toHaveTextContent('Orchestrator wants to change C:\\Users\\me\\.codex\\config.toml')
  expect(screen.getByText(why)).toBeInTheDocument()
  expect(screen.getByText(/A key in it is a secret\. One KOLONİ knows by its shape is hidden from the model/)).toHaveTextContent(
    'This CLI’s logins and past conversations are never opened',
  )
  expect(screen.queryByText(/a secret file/)).not.toBeInTheDocument()
  expect(screen.queryByText(/a file\?/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /this folder/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Allow once' }))
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'approve', 'once')
})

test('a change to a secret file is asked for as a change, and the card does not promise more than it holds', () => {
  const why = "This is a secret file (keys, passwords): reading it sends what it holds to the model's provider."
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'edit_file', 'pending', '{"path":".env"}', { ...STARTED, why_asked: why })],
  })
  render(<MessageList {...handlers} state={state} />)
  expect(screen.getByText(/wants to change/)).toHaveTextContent('Orchestrator wants to change .env')
  expect(screen.getByText(/script that does not name the file can still read it/)).toBeInTheDocument()
})

test('a change asks to open its folder to changes; a command names the folder it reaches', () => {
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [
      toolCall('1', 'r', 'edit_file', 'pending', '{"path":"D:/w/a.md"}', { ...STARTED, outside_folder: 'D:\\w' }),
      toolCall('2', 'r', 'run_command', 'pending', '{"command":"type D:/shelf/a.md"}', { ...STARTED, outside_folder: 'D:\\shelf' }),
    ],
  })
  render(<MessageList {...handlers} state={state} onDecideRole={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Allow changes in this folder: D:\\w' })).toBeInTheDocument()
  expect(screen.getByText(/wants to run a command/)).toHaveTextContent('Orchestrator wants to run a command that reaches D:\\shelf, outside the project')
})

test('in a chat with no folder a file the user named is asked for once: no folder is offered', async () => {
  const onDecideRole = vi.fn().mockResolvedValue(undefined)
  const state = convState({
    conversation: { ...conversation, project_id: null },
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'summarise rapor.txt'), assistantMessage('m', 'r', '')],
    toolCalls: [
      // (as the agent wrote it; the card says where it really leads)
      toolCall('1', 'r', 'read_file', 'pending', '{"path":"~\\\\Desktop\\\\RAPOR~1.TXT"}', {
        ...STARTED,
        why_asked: 'Only this, only now: this chat has no folder.',
        outside_folder: 'C:\\Users\\me\\Desktop\\rapor.txt',
      }),
    ],
  })
  render(<MessageList {...handlers} state={state} onDecideRole={onDecideRole} />)
  expect(screen.getByText('Read a file?')).toBeInTheDocument()
  expect(screen.getByText(/wants to read/)).toHaveTextContent('Orchestrator wants to read C:\\Users\\me\\Desktop\\rapor.txt')
  expect(screen.getByText('Only this, only now: this chat has no folder.')).toBeInTheDocument()
  expect(screen.queryByText(/secret/)).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /this folder/ })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Allow once' }))
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'approve', 'once')
})

test('an agent asking for a folder beforehand shows why and what access: added to this chat, this time only, or denied', async () => {
  const onDecideRole = vi.fn().mockResolvedValue(undefined)
  const asked = '{"path":"D:\\\\docs","access":"read","why":"the API notes are there"}'
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'ask_folder', 'pending', asked, { ...STARTED, outside_folder: 'D:\\docs' })],
  })
  render(<MessageList {...handlers} state={state} onDecideRole={onDecideRole} />)
  expect(screen.getByText(/asks to/)).toHaveTextContent('Orchestrator asks to read in D:\\docs')
  expect(screen.getByText('“the API notes are there”')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Allow once' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add to this chat' }))
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'approve', 'folder')
  await userEvent.click(screen.getByRole('button', { name: 'This time' }))
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'approve', 'once')
  await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
  expect(onDecideRole).toHaveBeenLastCalledWith('1', 'reject')
})

test('a CLI asking for a folder to write in says, in the backend’s words, that its own tools work there unasked', () => {
  const why = 'With “Add to this chat”, Claude Code works there with its own tools from its next turn: what it reads and runs there, secret files too, is not asked about.'
  const asked = '{"path":"D:\\\\docs","access":"write","why":"to fix the docs"}'
  const state = convState({
    runs: [run('r', 'waiting_approval')],
    agents: [agent('r', 'running', { name: 'Lead' })],
    messages: [userMessage('r', 'go'), assistantMessage('m', 'r', '')],
    toolCalls: [toolCall('1', 'r', 'ask_folder', 'pending', asked, { ...STARTED, outside_folder: 'D:\\docs', why_asked: why })],
  })
  render(<MessageList {...handlers} state={state} onDecideRole={vi.fn()} />)
  expect(screen.getByText(/works there with its own tools/)).toHaveTextContent(why)
  expect(screen.queryByText(/as in the project/)).not.toBeInTheDocument()
})

test('a change outside the project says so', () => {
  render(<ChangeActions change={fileChange('f', 'r', { path: 'C:\\work\\api\\app.py', status: 'applied' })} onDecide={vi.fn()} />)
  expect(screen.getByText('outside the project')).toBeInTheDocument()
})
