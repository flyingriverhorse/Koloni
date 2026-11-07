import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { Health } from '../api/types'
import { ModelBanner } from './ModelBanner'

const health = (over: Partial<Health>): Health => ({
  model_reachable: true,
  model_id: 'qwen',
  tools_supported: true,
  model_base_url: 'http://127.0.0.1:8080/v1',
  provider_id: 'p-local',
  provider_name: 'Local',
  error: null,
  not_listed: false,
  docker_available: false,
  docker_error: null,
  desktop_available: true,
  api_hash: import.meta.env.VITE_API_HASH,
  shell: 'PowerShell 7',
  shell_note: null,
  ...over,
})
const down = health({ model_reachable: false, model_id: null, tools_supported: null, error: 'model server unreachable: refused' })
const copilot = health({ model_reachable: false, provider_id: 'p-copilot', provider_name: 'Copilot', model_base_url: '', error: 'the copilot command was not found' })
const claude = health({ provider_id: 'p-claude', provider_name: 'Claude Code', model_base_url: '' })

// (A dismissal is kept for the session: each test starts with none.)
beforeEach(() => sessionStorage.clear())

test('nothing is shown while every provider in use is reachable and supports tools', () => {
  const { container } = render(<ModelBanner onModels={() => {}} readings={[health({}), claude]} />)
  expect(container).toBeEmptyDOMElement()
})

test('nothing is shown before the first readings, nor while the open conversation is still being read', () => {
  const { container } = render(<ModelBanner onModels={() => {}} readings={null} />)
  expect(container).toBeEmptyDOMElement()
})

test('a provider not in use is not read: with only the ones in use answering, there is no bar (sample A, Local down and unused)', () => {
  // (The store reads only the providers the chat would run on - shell/inUse.ts: Local, down, is not among them.)
  const { container } = render(<ModelBanner onModels={() => {}} readings={[claude, health({ provider_id: 'p-copilot', provider_name: 'Copilot' })]} />)
  expect(container).toBeEmptyDOMElement()
})

test('a provider in use that is down: one short line with its address; the reason behind Details', async () => {
  render(<ModelBanner onModels={() => {}} readings={[claude, down]} />)
  expect(screen.getByRole('status')).toHaveTextContent(/^Local isn't answering at 127\.0\.0\.1:8080\.$/)
  const reason = screen.getByText('model server unreachable: refused')
  expect(reason).not.toBeVisible()
  const details = screen.getByRole('button', { name: 'Details' })
  expect(details).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(details)
  expect(details).toHaveAttribute('aria-expanded', 'true')
  expect(reason).toBeVisible()
})

test('two in use down: one bar naming both, each with its reason behind Details', async () => {
  render(<ModelBanner onModels={() => {}} readings={[down, claude, copilot]} />)
  expect(screen.getAllByRole('status')).toHaveLength(1)
  expect(screen.getByRole('status')).toHaveTextContent("2 providers aren't answering: Local, Copilot.")
  await userEvent.click(screen.getByRole('button', { name: 'Details' }))
  expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual([
    "Local isn't answering at 127.0.0.1:8080. model server unreachable: refused",
    "Copilot isn't answering. the copilot command was not found",
  ])
})

test('several with different troubles are named all the same', () => {
  render(<ModelBanner onModels={() => {}} readings={[health({ tools_supported: false }), copilot]} />)
  expect(screen.getByRole('status')).toHaveTextContent('2 need a look: Local, Copilot.')
})

test('two providers whose models take no tool calls: each named in the list, each its own item', async () => {
  render(<ModelBanner onModels={() => {}} readings={[health({ tools_supported: false }), { ...claude, tools_supported: false }]} />)
  await userEvent.click(screen.getByRole('button', { name: 'Details' }))
  expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual([
    'Local: qwen does not support tool calls; chat works, file tools are off.',
    'Claude Code: qwen does not support tool calls; chat works, file tools are off.',
  ])
})

test("a role in use that cannot run where it would: '<Role> can't run: <why>', alone or beside a provider down", async () => {
  const cannot = [{ who: 'Orchestrator', why: 'Copilot runs only the models listed for it' }]
  const { rerender } = render(<ModelBanner onModels={() => {}} readings={[claude]} cannot={cannot} />)
  expect(screen.getByRole('status')).toHaveTextContent(/^Orchestrator can't run: Copilot runs only the models listed for it$/)
  expect(screen.queryByRole('button', { name: 'Details' })).not.toBeInTheDocument()
  rerender(<ModelBanner onModels={() => {}} readings={[down]} cannot={cannot} />)
  expect(screen.getByRole('status')).toHaveTextContent('2 need a look: Local, Orchestrator.')
})

test('a model without tool support says file tools are off', () => {
  render(<ModelBanner onModels={() => {}} readings={[health({ tools_supported: false })]} />)
  expect(screen.getByRole('status')).toHaveTextContent('qwen does not support tool calls; chat works, file tools are off.')
  // (nothing more to it)
  expect(screen.queryByRole('button', { name: 'Details' })).not.toBeInTheDocument()
})

test('a provider with no address is named without one', () => {
  render(<ModelBanner onModels={() => {}} readings={[copilot]} />)
  expect(screen.getByRole('status')).toHaveTextContent(/^Copilot isn't answering\.$/)
})

test('a provider that may not run with its default model is not called out of reach', () => {
  render(<ModelBanner onModels={() => {}} readings={[health({ model_reachable: false, not_listed: true, error: 'Local runs only with the models listed for it (a)' })]} />)
  const banner = screen.getByRole('status')
  expect(banner).toHaveTextContent('Local has no model it may run with by default')
  expect(banner).not.toHaveTextContent("isn't answering")
})

test('while First steps say a provider is down, the bar does not say it - but another one in use down, it does', () => {
  const { container, rerender } = render(<ModelBanner onModels={() => {}} readings={[down, claude]} quietFor="p-local" />)
  expect(container).toBeEmptyDOMElement()
  rerender(<ModelBanner onModels={() => {}} readings={[down, copilot]} quietFor="p-local" />)
  expect(screen.getByRole('status')).toHaveTextContent(/^Copilot isn't answering\.$/)
})

test('Pick another model opens the Models page', async () => {
  const onModels = vi.fn()
  render(<ModelBanner onModels={onModels} readings={[down]} />)
  await userEvent.click(screen.getByRole('button', { name: 'Pick another model' }))
  expect(onModels).toHaveBeenCalledOnce()
})

test('the address is said without its scheme or path - nor a password or key it carries -, wherever the provider is', () => {
  for (const [url, host] of [
    ['http://user:pass@127.0.0.1:8080/v1', '127.0.0.1:8080'],
    ['https://token@api.example.com/v1', 'api.example.com'],
    ['https://api.example.com?key=s3cret', 'api.example.com'],
    ['https://api.example.com#frag', 'api.example.com'],
    ['https://models.example.com/v1', 'models.example.com'],
    ['http://localhost:8080/v1', 'localhost:8080'],
    ['http://[::1]:8080/v1', '[::1]:8080'],
    ['not a url', 'not a url'],
  ]) {
    cleanup()
    render(<ModelBanner onModels={() => {}} readings={[{ ...down, model_base_url: url }]} />)
    expect(screen.getByText(`Local isn't answering at ${host}.`)).toBeInTheDocument()
  }
  // (and in the list of several)
  cleanup()
  render(<ModelBanner onModels={() => {}} readings={[{ ...down, model_base_url: 'http://user:pass@127.0.0.1:8080/v1' }, copilot]} />)
  expect(document.body).toHaveTextContent('at 127.0.0.1:8080.')
  expect(document.body).not.toHaveTextContent('user:pass')
})

test('only the line is announced, the whole of it under the pointer; dismissed and shown again, its reason is folded again', async () => {
  const { rerender } = render(<ModelBanner onModels={() => {}} readings={[down]} />)
  expect(screen.getByRole('status')).toHaveAttribute('title', "Local isn't answering at 127.0.0.1:8080.")
  await userEvent.click(screen.getByRole('button', { name: 'Details' }))
  expect(screen.getByText('model server unreachable: refused')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss model notice' }))
  rerender(<ModelBanner onModels={() => {}} readings={[{ ...down, model_base_url: 'http://127.0.0.1:9090/v1' }]} />)
  expect(screen.getByRole('button', { name: 'Details' })).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('model server unreachable: refused')).not.toBeVisible()
})

test('dismissed, the bar stays gone - over the next readings, a chat being read and a reload - until what is wrong changes', async () => {
  const at = (readings: Health[] | null) => (
    <div className="main" tabIndex={-1} data-testid="page">
      <ModelBanner onModels={() => {}} readings={readings} />
    </div>
  )
  const { rerender, unmount } = render(at([down]))
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss model notice' }))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  // the focus is not dropped on the page's body
  expect(screen.getByTestId('page')).toHaveFocus()
  // the next reading says the same; another conversation being read; another one using it too, beside a provider that is well
  rerender(at([{ ...down }]))
  rerender(at(null))
  rerender(at([claude, { ...down }]))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  // the page reloaded: still dismissed (sessionStorage)
  unmount()
  const again = render(at([down]))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  // another provider goes down too: shown again, both named
  again.rerender(at([down, copilot]))
  expect(screen.getByRole('status')).toHaveTextContent("2 providers aren't answering: Local, Copilot.")
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss model notice' }))
  // another address that cannot be reached either: shown again
  again.rerender(at([{ ...down, model_base_url: 'http://127.0.0.1:9090/v1' }]))
  expect(screen.getByRole('status')).toHaveTextContent('at 127.0.0.1:9090')
  await userEvent.click(screen.getByRole('button', { name: 'Dismiss model notice' }))
  // back, then down again: shown again
  again.rerender(at([health({ model_base_url: 'http://127.0.0.1:9090/v1' })]))
  again.rerender(at([{ ...down, model_base_url: 'http://127.0.0.1:9090/v1' }]))
  expect(screen.getByRole('status')).toHaveTextContent("isn't answering")
})
