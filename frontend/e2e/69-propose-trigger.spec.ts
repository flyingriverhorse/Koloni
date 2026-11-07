// Slice 69, K-tetik-bitis and K-tetik-degismedi in the browser: asked to keep an eye on something, the Lead proposes
// a trigger on a card - in the chat and in Ready for you - and nothing is made before Approve; approved, it is on the
// Triggers page reading only, with its end. The form warns when a trigger has no end. A clock trigger in a git
// project that finds nothing changed since its last run is skipped, and says so.
import { execFileSync } from 'node:child_process'
import { rmSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type APIRequestContext, type Page } from './fixtures'
import { OWN, contrasts, e2eProject, openFreshConversation, rail, say, shot } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

/** No trigger is left behind and the project is no repository again: the specs after this one share the backend. */
async function tidy(request: APIRequestContext) {
  const projects: { id: string }[] = await (await request.get('/api/projects')).json()
  for (const project of projects) {
    const triggers: { id: string }[] = await (await request.get(`/api/projects/${project.id}/triggers`)).json()
    for (const trigger of triggers) await request.delete(`/api/triggers/${trigger.id}`, { headers: OWN })
  }
  rmSync(path.join(PROJECT_DIR, '.git'), { recursive: true, force: true })
}

test.beforeEach(async ({ request }) => tidy(request))
test.afterEach(async ({ request }) => tidy(request))

async function reads(page: Page, selector: string) {
  const pieces = await page.locator(selector).first().evaluate(contrasts)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

async function dark(page: Page, on: boolean) {
  await page.getByRole('button', { name: `Theme: switch to ${on ? 'dark' : 'light'}` }).click()
  if (on) await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  else await expect(page.locator('html')).not.toHaveClass(/\bdark\b/)
  await expect(page.locator('html')).not.toHaveClass(/theme-switching/)
}

test('the Lead proposes a trigger on a card; Approve makes it, reading only, with its end', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await say(page, 'Check the dependencies on Fridays, 69', 'The trigger is on a card: approve it if you want it.')
  const card = chat.getByRole('region', { name: 'Proposed trigger: Dependencies, 69' })
  await expect(card).toContainText('Fridays at 17:00 · ends after 10 runs')
  await expect(card).toContainText('Look over the dependencies')
  await expect(card).toContainText('reads only · no sub-agents · 15 model steps and 10 minutes a run · 24 runs a day')
  // Nothing is made before your word.
  expect(await (await page.request.get(`/api/projects/${await e2eProject(page)}/triggers`)).json()).toEqual([])
  await reads(page, '.cmd-approval')
  // (The chat made taller, so the whole card is in the picture.)
  for (let step = 0; step < 4; step++) await page.getByRole('separator', { name: 'Chat height' }).press('ArrowUp')
  await card.scrollIntoViewIfNeeded()
  await shot(chat, '69-card-light')
  await dark(page, true)
  await reads(page, '.cmd-approval')
  await shot(chat, '69-card-dark')
  await dark(page, false)
  for (let step = 0; step < 4; step++) await page.getByRole('separator', { name: 'Chat height' }).press('ArrowDown')

  // It waits in Ready for you too (tek-ev §1: the top bar's pill opens its panel), with the same card.
  await page.locator('.ready-pill').click()
  const panel = page.getByRole('complementary', { name: /^Ready for you/ })
  const waiting = panel.getByRole('region', { name: 'Proposed trigger: Dependencies, 69' })
  await expect(waiting).toBeVisible()
  await waiting.getByRole('button', { name: 'Approve' }).click()
  await expect(panel.getByText('Nothing waits for you.')).toBeVisible()
  await panel.getByRole('button', { name: 'Close Ready for you' }).click()
  await expect(chat.getByText('The trigger “Dependencies, 69” was made: it is on the Triggers page.')).toBeVisible()

  await rail(page, 'Triggers').click()
  const made = page.getByRole('article', { name: 'Dependencies, 69' })
  await expect(made).toContainText('Fridays at 17:00')
  await expect(made).toContainText('reads only')
  await expect(made).toContainText('after 10 runs · 0 done')
  await shot(made, '69-approved-light')
  await dark(page, true)
  await reads(page, '.trigger-card')
  await shot(made, '69-approved-dark')
  await dark(page, false)
})

test('Edit opens the form filled in; with no end it warns and says the cost', async ({ page }) => {
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await say(page, 'Check the dependencies on Fridays, 69', 'The trigger is on a card: approve it if you want it.')
  await chat.getByRole('region', { name: 'Proposed trigger: Dependencies, 69' }).getByRole('button', { name: 'Edit' }).click()
  const form = page.getByRole('form', { name: 'New trigger' })
  await expect(form.getByLabel('Name', { exact: true })).toHaveValue('Dependencies, 69')
  await expect(form.getByRole('radio', { name: 'After so many runs' })).toBeChecked()
  await expect(form.getByLabel('May change files', { exact: true })).not.toBeChecked()
  await form.getByRole('radio', { name: 'No end' }).click()
  const warning = form.getByRole('note', { name: 'No end' })
  await expect(warning).toContainText('No end: it runs until you switch it off. Up to 24 runs a day, each up to 15 model steps and 10 minutes')
  await warning.scrollIntoViewIfNeeded()
  await shot(page, '69-form-no-end-light')
  await dark(page, true)
  await reads(page, '.trigger-form')
  await shot(page, '69-form-no-end-dark')
  await dark(page, false)
  await form.getByRole('radio', { name: 'After a day' }).click()
  await expect(warning).toHaveCount(0)
  await form.getByRole('button', { name: 'Add trigger' }).click()
  const made = page.getByRole('article', { name: 'Dependencies, 69' })
  await expect(made).toContainText(/after \d{4}-\d\d-\d\d/)
  // The card in the chat is done with.
  await rail(page, 'Canvas').click()
  await expect(chat.getByText('The trigger “Dependencies, 69” was made: it is on the Triggers page.')).toBeVisible()
})

test('a clock trigger that finds nothing changed in its git project is skipped, and says so', async ({ page, request }) => {
  const cid = await openFreshConversation(page)
  for (const argv of [['init', '-q'], ['add', '-A'], ['-c', 'user.name=e2e', '-c', 'user.email=e2e@e2e', 'commit', '-q', '-m', 'e2e']]) {
    execFileSync('git', argv, { cwd: PROJECT_DIR, timeout: 30_000, stdio: 'pipe' })
  }
  const pid = await e2eProject(page)
  const made = await request.post(`/api/projects/${pid}/triggers`, {
    headers: OWN,
    data: { name: 'Quiet look, 69', kind: 'schedule', conversation_id: cid, message: 'A quiet look, 69: say what you see.', config: { every_minutes: 60 } },
  })
  expect(made.ok()).toBe(true)
  const id: string = (await made.json()).id
  type Runs = { runs: { outcome: string | null; note: string | null }[] }
  const runs = async () => ((await (await request.get(`/api/triggers/${id}`)).json()) as Runs).runs
  // Its first look is at once: a run, which ends.
  await expect.poll(async () => (await runs())[0]?.outcome, { timeout: 30_000 }).toBe('completed')
  // Switched off and on again, it is due at once - and nothing changed since that run.
  for (const enabled of [false, true]) expect((await request.patch(`/api/triggers/${id}`, { headers: OWN, data: { enabled } })).ok()).toBe(true)
  await expect.poll(async () => (await runs())[0]?.outcome, { timeout: 30_000 }).toBe('skipped_same')
  expect((await runs())[0].note).toBe('nothing changed since the last run')

  await rail(page, 'Triggers').click()
  const card = page.getByRole('article', { name: 'Quiet look, 69' })
  await card.getByRole('button', { name: /^Recent runs/ }).click()
  await expect(card.getByRole('list', { name: 'Recent runs of Quiet look, 69' })).toContainText('skipped: nothing changed since the last run')
  await shot(card, '69-skipped-light')
  await dark(page, true)
  await reads(page, '.trigger-card')
  await shot(card, '69-skipped-dark')
  await dark(page, false)
})
