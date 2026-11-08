import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { ModelsPage } from './ModelsPage'

const base: Provider = {
  id: 'p1',
  name: 'Claude',
  kind: 'anthropic',
  base_url: 'https://api.anthropic.com',
  default_model: 'claude-haiku',
  executable: null,
  mode: null,
  options: { workspace_id: 'wrkspc_01' },
  for_agents: false,
  note: null,
  models: [],
  only_listed: false,
  max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
  has_key: true,
  position: 0,
  created_at: 't',
  updated_at: 't',
}

const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'm', tools_supported: true, error: null }),
})

/** A provider's window, open on its Connection tab. */
async function connection(ui: ReactElement) {
  const shown = render(ui)
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  return shown
}

const save = () => userEvent.click(screen.getByRole('button', { name: 'Save' }))

test('an Anthropic provider shows the workspace its key belongs to, and says when it is needed', async () => {
  await connection(<ModelsPage picked="p1" providers={[base]} {...handlers()} />)
  expect(screen.getByLabelText('Workspace ID')).toHaveValue('wrkspc_01')
  expect(screen.getByText(/only needed for a key that is not scoped to a workspace/i)).toBeInTheDocument()
})

test('saving an Anthropic provider without touching the workspace says nothing about its options: they stay', async () => {
  const h = handlers()
  await connection(<ModelsPage picked="p1" providers={[base]} {...h} />)
  await userEvent.clear(screen.getByLabelText('Name'))
  await userEvent.type(screen.getByLabelText('Name'), 'Claude API')
  await save()
  expect(h.onSave).toHaveBeenCalledTimes(1)
  const [, sent] = h.onSave.mock.calls[0]
  expect(sent).toEqual({ name: 'Claude API', base_url: 'https://api.anthropic.com', default_model: 'claude-haiku' })
  expect('options' in sent).toBe(false)
})

test('a changed workspace is sent, and an emptied one is sent as none', async () => {
  const h = handlers()
  await connection(<ModelsPage picked="p1" providers={[base]} {...h} />)
  const field = screen.getByLabelText('Workspace ID')
  await userEvent.clear(field)
  await userEvent.type(field, '  wrkspc_02 ')
  await save()
  expect(h.onSave.mock.calls[0][1].options).toEqual({ workspace_id: 'wrkspc_02' })
  await userEvent.clear(field)
  await save()
  expect(h.onSave.mock.calls[1][1].options).toEqual({ workspace_id: null })
})

test('a new Anthropic provider is added with its workspace only when one was typed', async () => {
  for (const typed of ['', 'wrkspc_03']) {
    const h = handlers()
    const { unmount } = render(<ModelsPage providers={[base]} {...h} />)
    await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
    await userEvent.type(screen.getByLabelText('Name'), 'Second')
    // no other kind has the field
    expect(screen.queryByLabelText('Workspace ID')).not.toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Kind'), 'anthropic')
    if (typed) await userEvent.type(screen.getByLabelText('Workspace ID'), typed)
    await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
    const sent = h.onCreate.mock.calls[0][0]
    if (typed) expect(sent.options).toEqual({ workspace_id: typed })
    else expect('options' in sent).toBe(false)
    unmount()
  }
})

test('saving a Copilot provider untouched sends every option it had, as it was', async () => {
  const h = handlers()
  const options = { provider_type: 'anthropic', max_prompt_tokens: 70000, max_output_tokens: 8000, offline: false }
  const copilot: Provider = { ...base, kind: 'copilot_cli', name: 'Copilot', base_url: 'http://localhost:8080/v1', mode: 'session', options, has_key: false }
  await connection(<ModelsPage picked="p1" providers={[copilot]} {...h} />)
  await save()
  expect(h.onSave.mock.calls[0][1].options).toEqual(options)
})

const OWN_SETUP = 'Use my own Claude Code setup'
const claudeCode: Provider = { ...base, kind: 'claude_cli', name: 'Claude Code', base_url: null, mode: 'native', options: null, has_key: false }

test('native Claude Code, and nothing else, can be told to start with your own setup', async () => {
  for (const [provider, shown] of [
    [claudeCode, true],
    [{ ...claudeCode, mode: 'session' }, false],
    [{ ...claudeCode, mode: 'step' }, false],
    [{ ...claudeCode, kind: 'codex_cli', name: 'Codex' }, false],
    [{ ...claudeCode, kind: 'copilot_cli', name: 'Copilot', base_url: 'http://localhost:8080/v1' }, false],
  ] as [Provider, boolean][]) {
    const { unmount } = await connection(<ModelsPage picked="p1" providers={[provider]} {...handlers()} />)
    expect(screen.queryAllByLabelText(OWN_SETUP)).toHaveLength(shown ? 1 : 0)
    unmount()
  }
  await connection(<ModelsPage picked="p1" providers={[claudeCode]} {...handlers()} />)
  expect(screen.getByLabelText(OWN_SETUP)).not.toBeChecked()
  expect(screen.getByText(/Off: only the project's own \.claude settings are loaded/)).toHaveTextContent(
    "Off: only the project's own .claude settings are loaded — none of your personal skills, plugins, hooks or MCP servers. On: the agent starts with your own setup, which KOLONİ neither shows nor approves.",
  )
  // it goes with the way of running
  await userEvent.selectOptions(screen.getByLabelText('How it runs'), 'session')
  expect(screen.queryByLabelText(OWN_SETUP)).not.toBeInTheDocument()
})

test('your own Claude Code setup is saved when it is switched on or off, and left alone otherwise', async () => {
  const h = handlers()
  const { unmount } = await connection(<ModelsPage picked="p1" providers={[claudeCode]} {...h} />)
  await save()
  expect('options' in h.onSave.mock.calls[0][1]).toBe(false)
  await userEvent.click(screen.getByLabelText(OWN_SETUP))
  await save()
  expect(h.onSave.mock.calls[1][1].options).toEqual({ own_setup: true })
  unmount()
  await connection(<ModelsPage picked="p1" providers={[{ ...claudeCode, options: { own_setup: true } }]} {...h} />)
  expect(screen.getByLabelText(OWN_SETUP)).toBeChecked()
  await userEvent.click(screen.getByLabelText(OWN_SETUP))
  await save()
  expect(h.onSave.mock.calls[2][1].options).toEqual({ own_setup: false })
})

test('a new native Claude Code provider is added with your own setup only when it was ticked', async () => {
  for (const ticked of [false, true]) {
    const h = handlers()
    const { unmount } = render(<ModelsPage providers={[base]} {...h} />)
    await userEvent.click(screen.getByRole('button', { name: /Add a provider/ }))
    await userEvent.type(screen.getByLabelText('Name'), 'Second')
    await userEvent.selectOptions(screen.getByLabelText('Kind'), 'claude_cli')
    await userEvent.selectOptions(screen.getByLabelText('How it runs'), 'native')
    if (ticked) await userEvent.click(screen.getByLabelText(OWN_SETUP))
    await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
    const sent = h.onCreate.mock.calls[0][0]
    if (ticked) expect(sent.options).toEqual({ own_setup: true })
    else expect('options' in sent).toBe(false)
    unmount()
  }
})

test('a kind with no options of its own is saved without any: agy, and a plain model server', async () => {
  for (const provider of [
    { ...base, kind: 'agy_cli', name: 'agy', base_url: null, mode: 'reads', options: null, has_key: false },
    { ...base, kind: 'openai_compat', name: 'Local', options: null, has_key: false },
  ] as Provider[]) {
    const h = handlers()
    const { unmount } = await connection(<ModelsPage picked="p1" providers={[provider]} {...h} />)
    expect(screen.queryByLabelText('Workspace ID')).not.toBeInTheDocument()
    await save()
    expect('options' in h.onSave.mock.calls[0][1]).toBe(false)
    unmount()
  }
})

test('K-claude-hesap: Claude Code and Codex may sign in with a folder of their own, saved with the other setting', async () => {
  const h = handlers()
  const { unmount } = await connection(<ModelsPage picked="p1" providers={[claudeCode]} {...h} />)
  expect(screen.getByLabelText('Sign-in')).toHaveValue('own')
  expect(screen.getByText(/Uses the claude command you are signed in to on this machine/)).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Sign-in'), 'koloni')
  // (R125: before it is saved - its own sign-in is not the one of this machine, and none is in it yet)
  expect(screen.getByRole('status', { name: '' })).toHaveTextContent(/^Not signed in yet: save, then “Log in to Claude for this provider”/)
  expect(screen.queryByText(/you are signed in to on this machine/)).not.toBeInTheDocument()
  await save()
  expect(h.onSave.mock.calls[0][1].options).toEqual({ own_setup: false, sign_in: 'koloni' })
  unmount()
  const again = await connection(<ModelsPage picked="p1" providers={[{ ...claudeCode, options: { sign_in: 'koloni' } }]} {...h} />)
  expect(screen.getByLabelText('Sign-in')).toHaveValue('koloni')
  await save()
  expect('options' in h.onSave.mock.calls[1][1]).toBe(false) // left alone
  await userEvent.selectOptions(screen.getByLabelText('Sign-in'), 'own')
  await save()
  expect(h.onSave.mock.calls[2][1].options).toEqual({ own_setup: false })
  again.unmount()
  const codex = { ...claudeCode, kind: 'codex_cli', name: 'Codex', mode: 'step' } as Provider
  await connection(<ModelsPage picked="p1" providers={[codex]} {...h} />)
  expect(screen.queryByText(/other accounts: not used for a limit/)).not.toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Sign-in'), 'koloni')
  expect(screen.getByText(/other accounts: not used for a limit/)).toHaveTextContent(
    'The other Codex providers are other accounts: not used for a limit. When this one reaches its limit, KOLONİ never moves its work to one of them.',
  )
  await save()
  expect(h.onSave.mock.calls[3][1].options).toEqual({ sign_in: 'koloni' })
})

test('a provider with its own sign-in moved to a model server of your own leaves it', async () => {
  const h = handlers()
  await connection(<ModelsPage picked="p1" providers={[{ ...claudeCode, mode: 'step', options: { sign_in: 'koloni' } }]} {...h} />)
  await userEvent.type(screen.getByLabelText('Model server address'), 'http://127.0.0.1:8080/v1')
  await save()
  expect(h.onSave.mock.calls[0][1]).toMatchObject({ base_url: 'http://127.0.0.1:8080/v1', options: { own_setup: false } })
  expect(h.onSave.mock.calls[0][1].options).not.toHaveProperty('sign_in')
})

test('no Sign-in on a model server of your own, nor for Copilot', async () => {
  for (const provider of [
    { ...claudeCode, base_url: 'http://127.0.0.1:8080/v1' },
    { ...claudeCode, kind: 'copilot_cli', name: 'Copilot', base_url: null },
  ] as Provider[]) {
    const { unmount } = await connection(<ModelsPage picked="p1" providers={[provider]} {...handlers()} />)
    expect(screen.queryByLabelText('Sign-in')).not.toBeInTheDocument()
    unmount()
  }
})
