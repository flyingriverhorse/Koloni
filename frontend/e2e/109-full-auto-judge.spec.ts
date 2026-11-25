// Full auto's judge (0.1.9) in the browser: the Judge model chosen in Settings › The app › Agents, the project's switch
// turned on in the level menu - a command the list does not stop is first sent to the stand-in judge, which finds one
// with JUDGE-RISKY risky: as a project comes it is refused with no card, its row and Decided for you say why, and the
// agent goes on; with Ask me chosen in Settings › This project it waits on a card that says so, with no Always run and
// the box to keep its line. With the switch turned off, the same command runs with no card. Nothing leaves the machine:
// the fake model is the judge.
import { expect, test, type Page } from './fixtures'
import {
  appSettings,
  e2eProject,
  level,
  OWN,
  openFreshConversation,
  projectSettings,
  saveSettings,
  setProject,
} from './helpers'

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
  await setProject(page, { full_auto_judge: false, judge_risky: 'refuse' })
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

test('a command the judge finds risky is refused and the agent goes on; with Ask me it waits on its card; with the switch off, it runs with no card', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)
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
  // Refuse and go on, as a project comes: no card - the row says refused, with the judge's sentence, and the agent goes
  // on; Decided for you, from the top bar's pill, lists it until OK.
  const refused = "KOLONİ's judge refused: The stand-in judge was told it is risky."
  await page.getByLabel('Message').fill(`Judge 109: run ${COMMAND}`)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Went another way, 109.')).toBeVisible({ timeout: 20_000 })
  await expect(chat.getByText('Run this command?')).toHaveCount(0)
  await expect(chat.locator('.tool-row-note', { hasText: refused })).toHaveCount(1)
  await expect(chat.locator('.tool-row', { hasText: refused })).toContainText('refused')
  // (other chats of the run may wait too: the panel's This chat is this one's)
  const pill = page.locator('.ready-pill')
  await expect(pill).toHaveText(/^(1 decided|\d+ waits?)$/)
  await pill.click()
  const panel = page.getByRole('complementary', { name: /^Ready for you/ })
  const decided = panel.getByRole('region', { name: /Decided for you/ })
  await expect(decided).toContainText(`KOLONİ did not run ${COMMAND}`)
  await expect(decided).toContainText('“The stand-in judge was told it is risky.”')
  await decided.getByRole('button', { name: 'OK' }).click()
  await expect(decided).toHaveCount(0)
  await panel.getByRole('button', { name: 'Close Ready for you' }).click()

  // Ask me, chosen in Settings › This project › Asking and away: its card.
  const settings = await projectSettings(page, /^Asking and away/)
  await settings.getByLabel('When the judge finds a command risky').selectOption('ask')
  await saveSettings(page)
  await expect.poll(async () => (await (await request.get(`/api/projects/${pid}`)).json()).judge_risky).toBe('ask')
  await page.getByLabel('Message').fill(`Judge 109: run ${COMMAND}`)
  await page.getByRole('button', { name: 'Send' }).click()
  const card = chat.locator('.cmd-approval:not(.decided)').filter({ hasText: COMMAND })
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
  // (the refused one's line and the card's: none for the one that ran)
  await expect(chat.locator('.tool-row-note', { hasText: "KOLONİ's judge" })).toHaveCount(2)
})
