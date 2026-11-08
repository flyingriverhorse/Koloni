import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Availability, Provider } from '../api/types'
import { ModelsPage } from './ModelsPage'

// Slice 40: the team guide filled from the catalogue, a mark beside each model, and what to
// run when a CLI is missing or signed out.
const codex: Provider = {
  id: 'c1',
  name: 'Codex',
  kind: 'codex_cli',
  base_url: null,
  default_model: null,
  executable: null,
  mode: 'step',
  options: null,
  for_agents: true,
  note: null,
  models: [{ name: 'my-model', note: 'mine', tier: 'fast', agents: true }],
  only_listed: false,
  max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
  has_key: false,
  position: 0,
  created_at: 't',
  updated_at: 't',
}
const told = (over: Partial<Availability> = {}): Availability => ({
  installed: true,
  install: null,
  signed_in: true,
  sign_in: null,
  models: [],
  ...over,
})

function open(availability: Availability, fill = vi.fn()) {
  const h = {
    onCreate: vi.fn().mockResolvedValue(undefined),
    onSave: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onTest: vi.fn(),
    onFill: fill,
    onAvailability: vi.fn().mockResolvedValue(availability),
  }
  render(<ModelsPage providers={[codex]} picked="c1" {...h} />)
  return h
}

test('Fill from the catalogue puts the proposal in the list unsaved, says what was left out, and its Save keeps it', async () => {
  const fill = vi.fn().mockResolvedValue({
    models: [
      { name: 'my-model', note: 'mine', tier: 'fast' },
      { name: 'gpt-6-astra', note: 'Most capable', tier: 'strongest' },
    ],
    left_out: 2,
  })
  const h = open(told(), fill)
  await userEvent.click(screen.getByRole('button', { name: 'Fill from the catalogue' }))
  expect(fill).toHaveBeenCalledWith('c1')
  expect(screen.getByText('gpt-6-astra')).toBeInTheDocument()
  expect(screen.getByLabelText('Tier of gpt-6-astra')).toHaveValue('strongest')
  expect(screen.getByText(/not saved yet/)).toHaveTextContent('2 left out')
  // A change made to a proposal waits for it: nothing is saved before its own Save.
  await userEvent.selectOptions(screen.getByLabelText('Tier of gpt-6-astra'), 'balanced')
  expect(h.onSave).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Save these models' }))
  // (a model added joins the provider's way: agents may use its others)
  expect(h.onSave.mock.calls[0][1].models).toEqual([
    { name: 'my-model', note: 'mine', tier: 'fast', agents: true },
    { name: 'gpt-6-astra', note: 'Most capable', tier: 'balanced', agents: true },
  ])
  expect(await screen.findByText('The proposed models are saved.')).toBeInTheDocument()
  expect(screen.queryByText(/not saved yet/)).not.toBeInTheDocument()
})

test('beside each model: usable, or not usable with its why', async () => {
  open(
    told({
      models: [
        { name: 'my-model', state: 'unusable', why: 'not offered by the provider now', retired: false },
        { name: 'other', state: 'usable', why: null, retired: true },
      ],
    }),
  )
  const mark = await screen.findByRole('img', { name: 'Cannot be used: not offered by the provider now' })
  expect(mark).toHaveAttribute('title', 'Cannot be used: not offered by the provider now')
  await userEvent.click(screen.getByRole('button', { name: 'Add a model' }))
  await userEvent.type(screen.getByLabelText('New model’s name'), 'other{Enter}')
  expect(screen.getByRole('img', { name: 'Usable now' })).toBeInTheDocument()
  // models.dev says it is being retired: marked, and still in the list
  expect(screen.getAllByText('being retired')).toHaveLength(1)
})

test('a model not known to be usable is marked so, with why', async () => {
  open(told({ models: [{ name: 'my-model', state: 'unknown', why: 'the provider does not list its models', retired: false }] }))
  expect(
    await screen.findByRole('img', { name: 'Not known if usable: the provider does not list its models' }),
  ).toHaveTextContent('?')
})

test('a CLI that is not installed: its install command to copy and its docs; Check reads it again', async () => {
  const h = open(
    told({
      installed: false,
      signed_in: null,
      install: { command: 'npm install -g @openai/codex', docs: 'https://github.com/openai/codex' },
      models: [{ name: 'my-model', state: 'unusable', why: 'not installed', retired: false }],
    }),
  )
  // (what to run is beside the provider's connection; Check is under its models)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  const card = await screen.findByRole('note', { name: 'How to install codex' })
  expect(card).toHaveTextContent('npm install -g @openai/codex')
  expect(screen.getByRole('link', { name: 'Install docs' })).toHaveAttribute('href', 'https://github.com/openai/codex')
  const copied = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: copied } })
  await userEvent.click(screen.getByRole('button', { name: 'Copy the command' }))
  expect(copied).toHaveBeenCalledWith('npm install -g @openai/codex')
  await userEvent.click(screen.getByRole('tab', { name: 'Models' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check' }))
  expect(h.onAvailability).toHaveBeenCalledTimes(2)
})

test('a CLI that is not signed in: its sign-in command', async () => {
  open(
    told({
      signed_in: false,
      sign_in: { command: 'codex login', docs: 'https://learn.chatgpt.com/docs/auth' },
      models: [{ name: 'my-model', state: 'unusable', why: 'not signed in', retired: false }],
    }),
  )
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(await screen.findByRole('note', { name: 'How to sign in to codex' })).toHaveTextContent('codex login')
})

const notInstalled = () =>
  told({
    installed: false,
    signed_in: null,
    install: { command: 'npm install -g @openai/codex', docs: 'https://github.com/openai/codex' },
  })

test('a copy the browser refuses says so, and how to copy it instead', async () => {
  open(notInstalled())
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } })
  await userEvent.click(await screen.findByRole('button', { name: 'Copy the command' }))
  expect(await screen.findByText('Copy failed — select the text')).toBeInTheDocument()
})

test('"Copied" goes back to "Copy" after a few seconds', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  try {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    open(notInstalled())
    await user.click(screen.getByRole('tab', { name: 'Connection' }))
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
    const copy = await screen.findByRole('button', { name: 'Copy the command' })
    await user.click(copy)
    expect(copy).toHaveTextContent('Copied')
    await act(() => vi.advanceTimersByTimeAsync(4000))
    expect(copy).toHaveTextContent('Copy')
  } finally {
    vi.useRealTimers()
  }
})

test('a note being typed is saved as it is left, so a fill never proposes over an edit not saved', async () => {
  const fill = vi.fn().mockResolvedValue({ models: [{ name: 'my-model', note: 'mine!', tier: 'fast' }], left_out: 0 })
  const h = open(told(), fill)
  await userEvent.click(screen.getByRole('button', { name: 'What is known of my-model' }))
  await userEvent.type(screen.getByLabelText('Note of my-model'), '!')
  await userEvent.click(screen.getByRole('button', { name: 'Fill from the catalogue' }))
  expect(h.onSave).toHaveBeenCalledWith('c1', { models: [{ name: 'my-model', note: 'mine!', tier: 'fast', agents: true }] })
  expect(fill).toHaveBeenCalledWith('c1')
})

// Slice 40b: a provider not added yet is filled from the catalogue too, before Add.
test('a new provider is filled from the catalogue once its kind and address say which, unsaved until Add', async () => {
  const fillNew = vi.fn().mockResolvedValue({ models: [{ name: 'gpt-6-astra', note: 'Most capable', tier: 'strongest' }], left_out: 0 })
  const h = { onCreate: vi.fn().mockResolvedValue(undefined), onSave: vi.fn(), onDelete: vi.fn(), onTest: vi.fn(), onFill: vi.fn(), onFillNew: fillNew }
  render(<ModelsPage providers={[]} picked="new" {...h} />)
  // An OpenAI-compatible server's catalogue is the service's at its address: none until there is one.
  expect(screen.queryByRole('button', { name: 'Fill from the catalogue' })).not.toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'codex_cli')
  expect(screen.getByRole('button', { name: 'Fill from the catalogue' })).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Kind'), 'openai_compat')
  await userEvent.type(screen.getByLabelText('Address'), 'https://api.openai.com/v1')
  await userEvent.click(screen.getByRole('button', { name: 'Fill from the catalogue' }))
  expect(fillNew).toHaveBeenCalledWith({ kind: 'openai_compat', base_url: 'https://api.openai.com/v1', models: [] })
  expect(screen.getByText('gpt-6-astra')).toBeInTheDocument()
  expect(screen.getByLabelText('Tier of gpt-6-astra')).toHaveValue('strongest')
  expect(h.onCreate).not.toHaveBeenCalled()
  await userEvent.type(screen.getByLabelText('Name'), 'OpenAI')
  await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
  // (not for agents until the user says so: no model of a new provider is yet)
  expect(h.onCreate.mock.calls[0][0].models).toEqual([{ name: 'gpt-6-astra', note: 'Most capable', tier: 'strongest', agents: false }])
})

test('a new provider at an address with no catalogue is told its models come once it is added', async () => {
  const fillNew = vi.fn().mockResolvedValue({ models: [], left_out: 0 })
  render(<ModelsPage providers={[]} picked="new" onCreate={vi.fn()} onSave={vi.fn()} onDelete={vi.fn()} onTest={vi.fn()} onFillNew={fillNew} />)
  await userEvent.type(screen.getByLabelText('Address'), 'http://127.0.0.1:8080/v1')
  await userEvent.click(screen.getByRole('button', { name: 'Fill from the catalogue' }))
  expect(fillNew).toHaveBeenCalledWith({ kind: 'openai_compat', base_url: 'http://127.0.0.1:8080/v1', models: [] })
  expect(screen.getByText('No catalogue for this address; the models will be listed once it is added.')).toBeInTheDocument()
  expect(screen.queryByText(/not saved yet/)).not.toBeInTheDocument()
})

test('K-claude-hesap: a provider with its own sign-in folder says how to log in there, and Check again reads it anew', async () => {
  const login = { command: "$env:CODEX_HOME='C:/koloni/runtime/cli-homes/c1'; codex login", docs: 'https://learn.chatgpt.com/docs/auth' }
  const h = open(told({ signed_in: false, sign_in: login, login }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Log in to Codex for this provider' }))
  const note = screen.getByRole('note', { name: 'How to log in to Codex for this provider' })
  expect(note).toHaveTextContent(login.command)
  expect(note).toHaveTextContent('Log in there once; KOLONİ never sees the token.')
  // (not the plain sign-in note as well)
  expect(screen.queryByRole('note', { name: 'How to sign in to codex' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Check again' }))
  expect(h.onAvailability).toHaveBeenCalledTimes(2)
})

test('K-giris-cmd: the login is shown for PowerShell and for Command Prompt, each with its own Copy', async () => {
  const login = {
    command: "$env:CODEX_HOME='C:\\koloni\\runtime\\cli-homes\\c1'; codex login",
    cmd: 'set "CODEX_HOME=C:\\koloni\\runtime\\cli-homes\\c1"\ncodex login',
    docs: 'https://learn.chatgpt.com/docs/auth',
  }
  open(told({ login }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Log in to Codex for this provider' }))
  const note = screen.getByRole('note', { name: 'How to log in to Codex for this provider' })
  expect(note).toHaveTextContent('Run this in your own PowerShell or Command Prompt.')
  expect(note).toHaveTextContent(`PowerShell: ${login.command}`)
  expect(note).toHaveTextContent('Command Prompt: set "CODEX_HOME=C:\\koloni\\runtime\\cli-homes\\c1" codex login')
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
  await userEvent.click(screen.getByRole('button', { name: 'Copy the PowerShell command' }))
  expect(writeText).toHaveBeenLastCalledWith(login.command)
  await userEvent.click(screen.getByRole('button', { name: 'Copy the Command Prompt command' }))
  expect(writeText).toHaveBeenLastCalledWith(login.cmd)
})
