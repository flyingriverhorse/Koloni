import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Provider } from '../api/types'
import { ModelPicker } from './ModelPicker'
import { ModelsPage } from './ModelsPage'

// K-model-sec: what the Models page and the chat's picker say of an Anthropic provider must be what a run does.

const provider = (over: Partial<Provider>): Provider => ({
  id: 'p1',
  name: 'Local',
  kind: 'openai_compat',
  base_url: 'http://127.0.0.1:8080/v1',
  default_model: null,
  executable: null,
  mode: null,
  options: null,
  for_agents: false,
  note: null,
  models: [],
  only_listed: false,
  max_running: null, plan: false, step_down_at: null, day_limit: null, month_limit: null,
  has_key: false,
  position: 0,
  created_at: 't',
  updated_at: 't',
  ...over,
})
const WARNING = 'this looks like a Claude subscription token - the API does not accept it; add Claude Code instead'
const api = provider({ id: 'p3', name: 'Claude-Subscription-API', kind: 'anthropic', base_url: null, has_key: true, position: 1, key_warning: WARNING })

const handlers = () => ({
  onCreate: vi.fn().mockResolvedValue(undefined),
  onSave: vi.fn().mockResolvedValue(undefined),
  onDelete: vi.fn().mockResolvedValue(undefined),
  onTest: vi.fn().mockResolvedValue({ ok: true, model_id: 'qwen', tools_supported: true, error: null }),
})

test('a key the API will not take is warned of on its card', () => {
  render(<ModelsPage providers={[provider({}), api]} {...handlers()} />)
  expect(screen.getByRole('button', { name: /^Claude-Subscription-API/ })).toHaveTextContent(WARNING)
  expect(screen.getByRole('button', { name: /^Local/ })).not.toHaveTextContent('subscription token')
})

test('a CLI version KOLONİ did not measure is said on its card, louder where it runs the old way', () => {
  const quiet = provider({ id: 'p4', name: 'Claude', kind: 'claude_cli', mode: 'native', version_note: 'Claude Code 2.1.312 not measured with KOLONİ' })
  const old = provider({ id: 'p5', name: 'Codex', kind: 'codex_cli', mode: 'native', version_note: 'Codex 0.170.0 not measured; running the old way' })
  // B-310: an agy too old for KOLONİ's tools - where a Lead or a Spec writer would be picked on it
  const agy = "agy 1.4.8 cannot open sub-agents here (KOLONİ's tools reach agy from 1.4.9 on): running the old way"
  const older = provider({ id: 'p6', name: 'agy', kind: 'agy_cli', mode: 'reads', version_note: agy })
  render(<ModelsPage providers={[quiet, old, older]} {...handlers()} />)
  expect(screen.getByText('Claude Code 2.1.312 not measured with KOLONİ')).toHaveClass('provider-card-version')
  expect(screen.getByText('Codex 0.170.0 not measured; running the old way')).toHaveClass('provider-card-state')
  expect(screen.getByText(agy)).toHaveClass('provider-card-state')
})

test('an Anthropic provider’s Default model says it is needed, not what looks like a default', async () => {
  render(<ModelsPage providers={[provider({}), api]} {...handlers()} />)
  await userEvent.click(screen.getByRole('button', { name: /^Claude-Subscription-API/ }))
  await userEvent.click(screen.getByRole('tab', { name: 'Connection' }))
  expect(screen.getByLabelText('Default model')).toHaveAttribute('placeholder', 'Needed, e.g. claude-sonnet-5-5')
})

test('the picker does not offer “the provider’s default” where there is none', async () => {
  render(<ModelPicker providers={[provider({}), api]} providerId="p3" modelId={null} onSave={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: /Model: Claude-Subscription-API/ }))
  expect(screen.getByLabelText('Model name')).toHaveAttribute('placeholder', 'Needed: this provider has no default model')
  await userEvent.selectOptions(screen.getByLabelText('Provider'), 'p1')
  // A server of one's own does run its first model with none named.
  expect(screen.getByLabelText('Model name')).toHaveAttribute('placeholder', "The provider's default")
})
