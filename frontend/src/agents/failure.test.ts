import { expect, test } from 'vitest'
import { ALIBABA_CONSOLE, nextStep, planConsole } from './failure'

const failed = { failure: null, failure_resets_at: null, error: null }

test('a failure says the one step to take, where one is known', () => {
  expect(nextStep({ ...failed, failure: 'rate_limited', failure_resets_at: '2026-10-20T14:00:00Z' })).toBe('Wait until it resets, or pick another model.')
  expect(nextStep({ ...failed, failure: 'rate_limited' })).toBe('Wait a while, or pick another model.')
  expect(nextStep({ ...failed, failure: 'credits_exhausted' })).toBe('Add credits to that account, or pick another model.')
  expect(nextStep({ ...failed, failure: 'signed_out' })).toBe('Sign in to it again, or pick another model.')
  expect(nextStep({ ...failed, failure: 'cli_crashed' })).toBe('Send the message again.')
  expect(nextStep({ ...failed, failure: 'empty_output' })).toBe('Send the message again.')
  expect(nextStep({ ...failed, failure: 'other', error: 'model server unreachable: [Errno 111] refused' })).toBe(
    'Check that the model server is running, or pick another model.',
  )
  expect(nextStep({ ...failed, error: 'no model provider is set up' })).toBe('Add one on the Models page.')
  // nothing known to help: nothing made up
  expect(nextStep({ ...failed, failure: 'other', error: 'the tool broke' })).toBeNull()
  expect(nextStep(failed)).toBeNull()
})

test("a plan key's quota used up says when it comes back, and Alibaba's where to see what is left", () => {
  const alibaba = { plan: true, base_url: 'https://token-plan.ap-southeast-1.maas.aliyuncs.com/v1' }
  const other = { plan: true, base_url: 'https://api.example.com/v1' }
  const usedUp = { ...failed, failure: 'rate_limited' as const, error: 'model server returned 429: Your token-plan quota has been exhausted.' }
  const byCode = { ...usedUp, error: 'model server returned 429: {"error": {"code": "insufficient_quota"}}' }
  const throttle = { ...usedUp, error: 'model server returned 429: Requests rate limit exceeded' }
  const back = 'Plan quota used up – it comes back at the start of its next subscription month, or with a usage bundle.'
  expect(nextStep(usedUp, alibaba)).toBe(back)
  expect(nextStep(byCode, other)).toBe(back)
  expect(planConsole(usedUp, alibaba)).toBe(ALIBABA_CONSOLE)
  expect(planConsole(byCode, other)).toBeNull()
  // A plain throttle waits as before; so does a key that is no plan, or a provider not known.
  expect(nextStep(throttle, alibaba)).toBe('Wait a while, or pick another model.')
  expect(planConsole(throttle, alibaba)).toBeNull()
  expect(nextStep(usedUp, { ...alibaba, plan: false })).toBe('Wait a while, or pick another model.')
  expect(nextStep(usedUp)).toBe('Wait a while, or pick another model.')
  expect(planConsole(usedUp, { ...alibaba, plan: false })).toBeNull()
})
