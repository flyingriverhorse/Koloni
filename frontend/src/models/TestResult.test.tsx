import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import type { Provider, ProviderTest } from '../api/types'
import { TestResult } from './ProviderConnection'

const found: ProviderTest = { ok: true, error: null, model_id: null, tools_supported: null }
const served = { base_url: 'http://127.0.0.1:8080/v1' } as Provider
const signedIn = { base_url: null } as Provider

test('a CLI that was only found says what was checked: Copilot’s sign-in, a model server of yours, or the command alone', () => {
  const show = (kind: 'copilot_cli' | 'claude_cli', provider: Provider | null, ownServer: boolean) =>
    render(<TestResult tested={found} kind={kind} cli provider={provider} ownServer={ownServer} canAdd={false} onAdd={vi.fn()} />)
  const said = () => screen.getByRole('status')
  let shown = show('copilot_cli', signedIn, true)
  expect(said()).toHaveClass('provider-ok')
  expect(said()).toHaveTextContent(/^The copilot command was found, and Copilot did not say it is signed out\. It was not run\.$/)
  shown.unmount()
  shown = show('copilot_cli', null, false)
  expect(said()).toHaveTextContent(/^The copilot command was found, and Copilot did not say it is signed out\. It was not run\.$/)
  shown.unmount()
  // Copilot on a model server of yours: nothing is signed in to
  shown = show('copilot_cli', served, true)
  expect(said()).toHaveTextContent(/^The copilot command was found, and your model server answered\. It was not run\.$/)
  shown.unmount()
  shown = show('claude_cli', served, true)
  expect(said()).toHaveTextContent(/^The claude command was found, and your model server answered\. It was not run\.$/)
  shown.unmount()
  shown = show('claude_cli', served, false)
  expect(said()).toHaveTextContent(/^The claude command was found\. It was not run, so sign-in is not checked\.$/)
  shown.unmount()
  show('claude_cli', signedIn, true)
  expect(said()).toHaveTextContent(/^The claude command was found\. It was not run, so sign-in is not checked\.$/)
})

test('a service that answered says its model, and that it takes no tools when it does not; one that failed says why', () => {
  const show = (tested: ProviderTest) => render(<TestResult tested={tested} kind="openai_compat" cli={false} provider={served} ownServer={false} canAdd={false} onAdd={vi.fn()} />)
  let shown = show({ ...found, model_id: 'qwen', tools_supported: true })
  expect(screen.getByRole('status')).toHaveTextContent(/^Reachable · qwen$/)
  shown.unmount()
  shown = show({ ...found, model_id: 'qwen', tools_supported: false })
  expect(screen.getByRole('status')).toHaveTextContent(/^Reachable · qwen · this model does not take tools$/)
  shown.unmount()
  show({ ...found, ok: false, error: 'connection refused' })
  expect(screen.getByRole('alert')).toHaveClass('alert')
  expect(screen.getByRole('alert')).toHaveTextContent(/^connection refused$/)
  expect(screen.queryByRole('status')).toBeNull()
})

test('a CLI that was run says what it answered and on which model, with Add it to the list where the model can be added', () => {
  const ran: ProviderTest = { ...found, reply: 'hi', model_id: 'gpt-5.5-codex', model_from: 'settings' }
  const { rerender } = render(<TestResult tested={ran} kind="codex_cli" cli provider={signedIn} ownServer={false} canAdd onAdd={vi.fn()} />)
  expect(screen.getByRole('status')).toHaveTextContent(/^It answered "hi" · model gpt-5\.5-codex \(from Codex's settings\) Add it to the list$/)
  rerender(<TestResult tested={{ ...ran, model_from: null }} kind="codex_cli" cli provider={signedIn} ownServer={false} canAdd={false} onAdd={vi.fn()} />)
  expect(screen.getByRole('status')).toHaveTextContent(/^It answered "hi" · model gpt-5\.5-codex$/)
  expect(screen.queryByRole('button')).toBeNull()
})
