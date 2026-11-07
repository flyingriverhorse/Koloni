import { expect, type APIRequestContext, test } from './fixtures'
import { OWN, openFreshConversation, rail, shot } from './helpers'
import { FAKE_AGY, FAKE_CLAUDE } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

const NAMES = ['Limits Claude', 'Limits agy', 'Limits Codex']

// The backend is shared: the providers made here are not left for whatever runs after.
async function remove(request: APIRequestContext) {
  for (const provider of await (await request.get('/api/providers')).json())
    if (NAMES.includes(provider.name)) await request.delete(`/api/providers/${provider.id}`, { headers: OWN })
}

test.beforeEach(async ({ request }) => {
  await remove(request)
  // Stand-ins for the CLIs: nothing is started for this page, and no real CLI is near it.
  // (Codex's command is one that is not there: asked afresh, it is looked for, not found, and
  // nothing is started - no stand-in for its app-server, whose line would carry the skills of
  // whoever runs the test.)
  for (const [name, kind, executable] of [
    ['Limits Claude', 'claude_cli', FAKE_CLAUDE],
    ['Limits agy', 'agy_cli', FAKE_AGY],
    ['Limits Codex', 'codex_cli', 'no-such-codex-for-the-limits-test'],
  ])
    expect((await request.post('/api/providers', { headers: OWN, data: { name, kind, executable } })).ok()).toBeTruthy()
})

test.afterEach(async ({ request }) => {
  await remove(request)
})

test('the Usage page says what each CLI says of its plan, and what is not known is not made up', async ({ page }) => {
  const afresh: string[] = []
  page.on('request', request => {
    if (request.url().endsWith('/limits/check')) afresh.push(request.method())
  })
  await openFreshConversation(page)
  await rail(page, 'Usage').click()
  const limits = page.getByRole('region', { name: 'Plan limits' })
  const rows = limits.getByRole('table', { name: 'Plan limits by provider' })
  // Claude Code says its limits only in a run of its own: before one, nothing is known - and it is not asked.
  await expect(rows.getByRole('row', { name: /^Limits Claude/ })).toContainText('not known — not run yet')
  // (agy says its plan without a turn: the top bar's look has it read in the background, so its row may say either.)
  // Opening the page starts nothing: Codex's row says it was not read, and how to have it read.
  await expect(rows.getByRole('row', { name: /^Limits Codex/ })).toContainText('not read yet — Check now')
  expect(afresh).toEqual([])
  // A model server is not a CLI on a plan: it has no row.
  await expect(rows.getByRole('row', { name: /^Local/ })).toHaveCount(0)
  await expect(limits.getByText(/These are the limits of the account the CLI on this machine is signed in to\./)).toBeVisible()
  await limits.getByRole('button', { name: 'Check now' }).click()
  await expect(limits.getByRole('button', { name: 'Check now' })).toBeEnabled()
  // Only now is anything read afresh - from the app's own page, which the server takes it from.
  await expect(rows.getByRole('row', { name: /^Limits Codex/ })).toContainText('not known — the codex command was not found')
  // agy's /quota, from its stand-in (tests/fake_agy_cli.py): a week of its Gemini models, by their name.
  await expect(rows.getByRole('row', { name: /^Limits agy/ })).toContainText('8% of Gemini Models this week used')
  await expect(rows.getByRole('row', { name: /^Limits Claude/ })).toContainText('not known — not run yet')
  expect(afresh.length).toBeGreaterThan(0)
  expect(new Set(afresh)).toEqual(new Set(['POST']))
  await shot(page, '25a-plan-limits')
})
