// Full auto's judge (0.1.9) in the browser: the Judge model chosen in Settings › The app › Agents, the project's switch
// turned on in the level menu - a command the list does not stop is first sent to the stand-in judge, which finds one
// with JUDGE-RISKY risky: it waits on a card that says so, with no Always run and the box to keep its line. With the
// switch turned off there, the same command runs with no card. Nothing leaves the machine: the fake model is the judge.
import { expect, test, type Page } from './fixtures'
import { appSettings, e2eProject, level, OWN, openFreshConversation, setProject } from './helpers'

type Model = { name: string; tier: string | null }
let local: { id: string; models: Model[] }
const COMMAND = 'python hello.py JUDGE-RISKY'

test.beforeEach(async ({ request }) => {
  local = (await (await request.get('/api/providers')).json()).find((p: { name: string }) => p.name === 'Local')
  // The fake model given a tier: one of the models the Judge model may be chosen from.
  const models = [...local.models.filter(m => m.name !== 'fake-qwen'), { name: 'fake-qwen', tier: 'fast' }]
  expect((await request.patch(`/api/providers/${local.id}`, { headers: OWN, data: { models } })).ok()).toBe(true)
})

test.afterEach(async ({ page, request }) => {
  const none = { provider_id: null, model_id: null }
  expect((await request.put('/api/judge', { headers: OWN, data: none })).ok()).toBe(true)
  const models = local.models
  expect((await request.patch(`/api/providers/${local.id}`, { headers: OWN, data: { models } })).ok()).toBe(true)
  await setProject(page, { full_auto_judge: false })
})

/** The level menu's switch for Full auto's judge, clicked; the project's setting then, as the server has it. */
async function flipJudge(page: Page, pid: string, now: boolean) {
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('button', { name: /^Permission level:/ }).click()
  const judge = chat.getByRole('switch', { name: 'Full auto’s judge' })
  await expect(judge).toBeChecked({ checked: !now })
  await judge.click()
  await expect
    .poll(async () => (await (await page.request.get(`/api/projects/${pid}`)).json()).full_auto_judge)
    .toBe(now)
  await page.keyboard.press('Escape')
}

test('a command the judge finds risky waits on its card; with the switch off, the same command runs with no card', async ({
  page,
  request,
}) => {
  test.setTimeout(90_000)
  await openFreshConversation(page)
  const pid = await e2eProject(page)
  const chat = page.getByRole('region', { name: 'Chat' })

  // Settings › The app › Agents: the Judge model, kept as it is chosen.
  const app = await appSettings(page, 'Agents')
  const model = app.getByLabel('Judge model')
  await expect(model).toBeEnabled()
  await model.selectOption({ label: 'Local · fake-qwen (fast)' })
  await expect.poll(async () => (await (await request.get('/api/judge')).json()).model_id).toBe('fake-qwen')
  await page.getByRole('button', { name: 'Close settings' }).click()

  await level(page, 'full_auto')
  await flipJudge(page, pid, true)
  await page.getByLabel('Message').fill(`Judge 109: run ${COMMAND}`)
  await page.getByRole('button', { name: 'Send' }).click()
  const card = chat.locator('.cmd-approval').filter({ hasText: COMMAND })
  await expect(card).toContainText("KOLONİ's judge: The stand-in judge was told it is risky.", { timeout: 20_000 })
  await expect(card.getByRole('button', { name: /Always run/ })).toHaveCount(0)
  // (Its box is not ticked here: a kept line would outlive a retry of this spec.)
  await expect(card.getByRole('checkbox', { name: 'Don’t ask about this line again here' })).not.toBeChecked()
  await card.getByRole('button', { name: 'Reject' }).click()
  await expect(chat.getByText('Left it alone, 109.')).toBeVisible({ timeout: 20_000 })
  // Answered, its sentence stays under the command's row.
  await expect(chat.locator('.tool-row-note', { hasText: "KOLONİ's judge: The stand-in" })).toHaveCount(1)

  await flipJudge(page, pid, false)
  await page.getByLabel('Message').fill(`Judge 109: run ${COMMAND}`)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Ran it, 109.')).toBeVisible({ timeout: 20_000 })
  await expect(chat.getByText('Run this command?')).toHaveCount(0)
  await expect(chat.locator('.tool-row-note', { hasText: "KOLONİ's judge" })).toHaveCount(1)
})
