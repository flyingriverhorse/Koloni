import type { Agent, Provider } from '../api/types'

/** A moment as a day and a time here: "Tue 14:00". */
export const dayAndTime = (iso: string) => new Date(iso).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' })

/**
 * Why an agent's model failed, in plain words, where its provider itself said why:
 * "Codex: limit reached, resets Tue 14:00". Null where it did not - the error is then all there is.
 */
export function failureText(agent: Pick<Agent, 'failure' | 'failure_resets_at' | 'provider_name'>): string | null {
  const resets = agent.failure_resets_at ? `, resets ${dayAndTime(agent.failure_resets_at)}` : ''
  const why = {
    rate_limited: `limit reached${resets}`,
    credits_exhausted: 'out of credits',
    signed_out: 'not signed in, or its key was refused',
    cli_crashed: 'the CLI stopped without finishing',
    empty_output: 'it ended without an answer',
    other: null,
  }[agent.failure ?? 'other']
  return why && `${agent.provider_name ?? 'Its provider'}: ${why}`
}

// A plan key's quota used up, as Alibaba's Token Plan words its 429 (as app/limits.py `_USED_UP` reads it); its plain
// throttle is a 429 without them.
const USED_UP = /insufficient_quota|token-plan quota has been exhausted/i
// Where the user sees their plan's quota (24 Oct; the Token Plan is in Singapore alone, its docs say).
// shortcut: the personal plan's page; a team plan's is not known - add it if one is used.
export const ALIBABA_CONSOLE = 'https://modelstudio.console.alibabacloud.com/ap-southeast-1/subscription/token-plan/personal'
// Alibaba's own: a host of aliyuncs.com, as app/catalog.py `catalogue_of` knows its services.
const ALIBABA = /^https?:\/\/([^/?#@]*\.)?aliyuncs\.com([:/?#]|$)/i

type Paid = Pick<Provider, 'plan' | 'base_url'>
const usedUp = (agent: Pick<Agent, 'failure' | 'error'>, provider?: Paid) =>
  agent.failure === 'rate_limited' && !!provider?.plan && USED_UP.test(agent.error ?? '')

/** Where to see what is left of a plan whose quota was used up: Alibaba's console (no API says it); null elsewhere. */
export const planConsole = (agent: Pick<Agent, 'failure' | 'error'>, provider?: Paid) =>
  usedUp(agent, provider) && ALIBABA.test(provider!.base_url ?? '') ? ALIBABA_CONSOLE : null

/**
 * The one thing to do about a failure, as slice 40's card says how to install or sign in: by
 * what its provider said, and otherwise by the error. Null where nothing is known to help.
 */
export function nextStep(agent: Pick<Agent, 'failure' | 'failure_resets_at' | 'error'>, provider?: Paid): string | null {
  switch (agent.failure) {
    case 'rate_limited':
      if (usedUp(agent, provider)) return 'Plan quota used up – it comes back at the start of its next subscription month, or with a usage bundle.'
      return agent.failure_resets_at ? 'Wait until it resets, or pick another model.' : 'Wait a while, or pick another model.'
    case 'credits_exhausted':
      return 'Add credits to that account, or pick another model.'
    case 'signed_out':
      return 'Sign in to it again, or pick another model.'
    case 'cli_crashed':
    case 'empty_output':
      return 'Send the message again.'
  }
  // shortcut: two errors known by their words (app/model_client.py, app/api/health.py); upgrade when the server says what kind an error is.
  if (agent.error?.startsWith('model server unreachable')) return 'Check that the model server is running, or pick another model.'
  if (agent.error === 'no model provider is set up') return 'Add one on the Models page.'
  return null
}
