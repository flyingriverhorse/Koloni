import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { type Browser, expect, type Locator, type Page, test } from './fixtures'
import { LINK, OWN, appSettings, e2eProject, level, openFreshConversation, rail, say, setProject, settled } from './helpers'
import { APP_URL, PROJECT_DIR, REPO_ROOT } from './paths.mjs'

// The guide's pictures (docs/images) and short videos (docs/videos), taken from the real app with the fake model, light,
// at 1280×800 (the Away panel at 1280×900) and 1280×720. Taken on request (KOLONI_SHOTS=1), after `npm run build`: an ordinary run leaves them alone.
test.skip(!process.env.KOLONI_SHOTS, 'the guide’s pictures are taken with KOLONI_SHOTS=1')
test.use({ viewport: { width: 1280, height: 800 } })
test.beforeEach(({ page }) => page.addInitScript(() => localStorage.setItem('koloni-theme', 'light')))

const IMAGES = path.join(REPO_ROOT, 'docs', 'images')
const HOMES = [os.homedir(), os.homedir().replaceAll('\\', '/')].map(one => one.toLowerCase())

/** What a picture shows as text, its fields' values too: none may name this machine's user's folders (the e2e project is under one). */
async function showsNoHome(target: Page | Locator, name: string) {
  const root = 'mainFrame' in target ? target.locator('body') : target
  const seen = await root.evaluate(el =>
    [(el as HTMLElement).innerText, ...[...el.querySelectorAll('input, textarea')].map(one => (one as HTMLInputElement).value)].join('\n').toLowerCase(),
  )
  for (const home of HOMES) expect(seen, `${name} shows ${home}`).not.toContain(home)
}

/** A picture for the guide, in docs/images. */
async function picture(target: Page | Locator, name: string) {
  await showsNoHome(target, name)
  mkdirSync(IMAGES, { recursive: true })
  await target.screenshot({ path: path.join(IMAGES, `${name}.png`), animations: 'disabled', caret: 'hide' })
}

const VIDEOS = path.join(REPO_ROOT, 'docs', 'videos')
const FRAME = { width: 1280, height: 720 }
/** A moment to look, between steps of a video. */
const beat = (page: Page, ms = 1000) => page.waitForTimeout(ms)

/**
 * A video for the guide, in docs/videos (WebM: Playwright's own recording; no ffmpeg here), with its poster (JPEG) taken
 * where `flow` says. It records a page of its own, opened once the scene is set: what set it is not in the video.
 */
async function video(browser: Browser, name: string, flow: (page: Page, poster: () => Promise<void>) => Promise<void>) {
  mkdirSync(VIDEOS, { recursive: true })
  const context = await browser.newContext({ baseURL: APP_URL, viewport: FRAME, recordVideo: { dir: path.join(os.tmpdir(), 'koloni-guide-videos'), size: FRAME } })
  await context.addInitScript(() => localStorage.setItem('koloni-theme', 'light'))
  const page = await context.newPage()
  await page.goto(LINK)
  await page.getByLabel('Message').waitFor()
  await flow(page, async () => {
    await showsNoHome(page, name)
    await page.screenshot({ path: path.join(VIDEOS, `${name}.jpg`), type: 'jpeg', quality: 80, animations: 'disabled', caret: 'hide' })
  })
  await showsNoHome(page, name)
  await beat(page, 1500)
  await page.close()
  await page.video()!.saveAs(path.join(VIDEOS, `${name}.webm`))
  await context.close()
}

test('the main screen and the agent window', async ({ page }) => {
  await openFreshConversation(page)
  await say(page, 'review the greeting', 'The reviewer found no problems.')
  await expect(page.locator('.react-flow__node-agent')).toHaveCount(2)
  await settled(page)
  await picture(page, 'main-screen')
  await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: /Reviewer.*Review hello\.py/ }).click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  await expect(page.getByRole('region', { name: 'Agent window' }).getByText('Did', { exact: true })).toBeVisible()
  await picture(page, 'agent-window')
})

test('an approval card in Ready for you', async ({ page }) => {
  const id = await openFreshConversation(page)
  expect((await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { permission_mode: 'ask' } })).ok()).toBe(true)
  await page.getByLabel('Message').fill('run the tests')
  await page.getByRole('button', { name: 'Send' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByText('Run this command?')).toBeVisible({ timeout: 20_000 })
  await page.locator('.ready-pill').click()
  const panel = page.getByRole('complementary', { name: /^Ready for you · \d+$/ })
  await expect(panel.getByRole('heading', { name: 'This chat · 1' })).toBeVisible()
  await picture(page, 'ready-approval')
  await panel.getByRole('region', { name: 'Needs your answer' }).getByRole('button', { name: 'Run once' }).click()
  await expect(chat.getByText('The tests pass.')).toBeVisible({ timeout: 15_000 })
})

test('a team on the canvas, and Take in', async ({ page, request }) => {
  test.setTimeout(60_000)
  const id = await openFreshConversation(page, { leadWrites: false })
  // One step, by the Coder, then "ask me, then in" (as 84b2-recipe-run).
  const RECIPE = 'Build only (guide)'
  const graph = {
    version: 1,
    steps: [{ id: 'build', name: 'Build it', who: { role: 'Coder' } }],
    ends: [{ id: 'end', then: 'in' }],
    arrows: [{ from: 'start', to: 'build' }, { from: 'build', to: 'end' }],
  }
  await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })
  const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(r => r.name === RECIPE)
  const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Web app')
  await setProject(page, { spawn_approval: 'never' })
  const set = await request.patch(`/api/conversations/${id}`, {
    headers: OWN,
    data: { permission_mode: 'auto_edit', teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe!.id }] },
  })
  expect(set.ok()).toBe(true)
  await page.getByLabel('Message').fill('build it by the recipe, 84b2 guide')
  await page.getByRole('button', { name: 'Send' }).click()
  const ready = page.locator('.ready-node')
  await expect(ready).toContainText('NEEDS YOU', { timeout: 20_000 })
  // (The chat put away, and the turn drawn larger: it fits to a width where its words are too small to read.)
  await page.getByRole('button', { name: 'Hide chat' }).click()
  await settled(page)
  for (let times = 0; times < 3; times++) await page.locator('.react-flow__controls-zoomin').click()
  await settled(page)
  await picture(page, 'team-canvas')
  await ready.getByRole('button', { name: 'Open the list →' }).click()
  const list = page.getByRole('region', { name: 'Ready to take in' })
  await expect(list.getByRole('button', { name: 'Take in' })).toBeVisible()
  await picture(page, 'take-in')
  await list.getByRole('button', { name: 'Take in' }).click()
  await expect(ready).toContainText('In the project ✓', { timeout: 20_000 })
})

test('the Models, Settings › This project and Knowledge pages', async ({ page }) => {
  await openFreshConversation(page)
  await rail(page, 'Models').click()
  await expect(page.getByRole('heading', { name: 'Models' })).toBeVisible()
  await picture(page, 'models')
  // (As a new project has it, 0.1.5: the harness's own is "everything waits", 10 minutes.)
  await setProject(page, { when_away: 'lead', away_minutes: 5 })
  await page.reload()
  await page.getByLabel('Message').waitFor()
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  // (At Asking and away: when you're away, Full auto's check of your words, disposable deletes - 0.1.5.)
  await settings.getByRole('button', { name: /^Asking and away/ }).click()
  await expect(settings.getByText('A harmful-looking command at Full auto')).toBeVisible()
  await picture(page, 'settings-project')
  await page.getByRole('button', { name: 'Close settings' }).click()
  await page.getByRole('button', { name: 'Knowledge', exact: true }).click()
  await expect(page.getByRole('article', { name: 'MLflow' })).toBeVisible()
  await picture(page, 'knowledge')
})

test('the To-do page with the Product owner’s draft', async ({ page }) => {
  await openFreshConversation(page)
  await rail(page, 'To-do').click()
  const form = page.getByRole('form', { name: 'Add a task' })
  await form.getByLabel('Title').fill('the login page breaks on mobile, and we need a password reset')
  await form.getByRole('button', { name: 'Write it with the Product owner' }).click()
  const drafts = page.getByRole('region', { name: 'Drafted tasks' })
  await expect(drafts.getByRole('group', { name: 'Draft 2' }).getByLabel('Title')).toHaveValue('Add a password reset')
  await form.getByRole('button', { name: 'Write it with the Product owner' }).scrollIntoViewIfNeeded()
  await page.mouse.wheel(0, 300)
  await picture(page, 'todo-draft')
})

test('Memory search, Triggers and Usage', async ({ page, request }) => {
  const id = await openFreshConversation(page)
  await say(page, 'Answer only: The ZEPPELIN hangar is in Kayseri.', 'The ZEPPELIN hangar is in Kayseri.')
  expect((await request.patch(`/api/conversations/${id}`, { headers: OWN, data: { title: 'Morning checks' } })).ok()).toBe(true)
  // (Loaded again: the turn's "Done" toast is not in the pictures.)
  await page.reload()
  await rail(page, 'Memory').click()
  const search = page.getByRole('region', { name: 'Search', exact: true })
  await search.getByLabel('Search everything this project remembers').fill('zeppelin')
  await search.getByRole('button', { name: 'Search deeper' }).click()
  await expect(search.getByRole('list', { name: 'In earlier messages' }).getByRole('listitem').first()).toBeVisible()
  await picture(page, 'memory-search')

  const pid = await e2eProject(page)
  const made = await request.post(`/api/projects/${pid}/triggers`, {
    headers: OWN,
    data: { name: 'Morning check', kind: 'schedule', conversation_id: id, message: 'Run the tests and say what failed.', config: { at: '07:30', days: 'weekdays' } },
  })
  expect(made.ok(), await made.text()).toBe(true)
  await rail(page, 'Triggers').click()
  await expect(page.getByRole('article', { name: 'Morning check' })).toBeVisible()
  await picture(page, 'triggers')
  expect((await request.delete(`/api/triggers/${(await made.json()).id}`, { headers: OWN })).ok()).toBe(true)

  // (0.1.7: a command card answered, so Cards has one to count - asked at Ask, run once)
  await openFreshConversation(page)
  const chat = page.getByRole('region', { name: 'Chat' })
  await page.getByLabel('Message').fill('run the tests')
  await page.getByRole('button', { name: 'Send' }).click()
  await chat.getByRole('button', { name: 'Run once' }).click()
  await expect(chat.getByText('The tests pass.')).toBeVisible()
  await page.reload()
  await rail(page, 'Usage').click()
  await expect(page.getByRole('table', { name: 'Usage by provider and model' })).toBeVisible()
  const cards = page.getByRole('region', { name: 'Cards' })
  await expect(cards.getByRole('table', { name: 'Cards by reason' })).toBeVisible()
  await cards.scrollIntoViewIfNeeded()
  await picture(page, 'usage')
})

test.describe('the guide’s videos', () => {
  test.use({ viewport: FRAME })

  test('an agent asks, you approve', async ({ page, browser }) => {
    test.setTimeout(60_000)
    const id = await openFreshConversation(page)
    expect((await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { permission_mode: 'ask' } })).ok()).toBe(true)
    await video(browser, 'approval', async (shown, poster) => {
      await beat(shown, 500)
      await shown.getByLabel('Message').pressSequentially('run the tests', { delay: 50 })
      await shown.getByRole('button', { name: 'Send' }).click()
      const chat = shown.getByRole('tabpanel', { name: 'Chat' })
      await expect(chat.getByText('Run this command?')).toBeVisible({ timeout: 20_000 })
      await poster()
      await beat(shown, 1500)
      await chat.getByRole('button', { name: 'Run once' }).click()
      await expect(chat.getByText('The tests pass.')).toBeVisible({ timeout: 15_000 })
    })
  })

  test('a team at work on the canvas, then Take in', async ({ page, browser, request }) => {
    test.setTimeout(90_000)
    const id = await openFreshConversation(page, { leadWrites: false })
    const RECIPE = 'Build only (guide)'
    const graph = {
      version: 1,
      steps: [{ id: 'build', name: 'Build it', who: { role: 'Coder' } }],
      ends: [{ id: 'end', then: 'in' }],
      arrows: [{ from: 'start', to: 'build' }, { from: 'build', to: 'end' }],
    }
    await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })
    const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(r => r.name === RECIPE)
    const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(t => t.name === 'Web app')
    await setProject(page, { spawn_approval: 'never' })
    const set = await request.patch(`/api/conversations/${id}`, {
      headers: OWN,
      data: { permission_mode: 'auto_edit', teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe!.id }] },
    })
    expect(set.ok()).toBe(true)
    await video(browser, 'team', async (shown, poster) => {
      await beat(shown, 500)
      await shown.getByLabel('Message').pressSequentially('build it by the recipe, 84b2 video', { delay: 40 })
      await shown.getByRole('button', { name: 'Send' }).click()
      await beat(shown, 500)
      await shown.getByRole('button', { name: 'Hide chat' }).click()
      await expect(shown.locator('.ready-node')).toContainText('NEEDS YOU', { timeout: 20_000 })
      await settled(shown)
      await poster()
    })
    await video(browser, 'take-in', async (shown, poster) => {
      const ready = shown.locator('.ready-node')
      await expect(ready).toContainText('NEEDS YOU')
      await settled(shown)
      await beat(shown)
      await ready.getByRole('button', { name: 'Open the list →' }).click()
      const list = shown.getByRole('region', { name: 'Ready to take in' })
      await expect(list.getByRole('button', { name: 'Take in' })).toBeVisible()
      await poster()
      await beat(shown, 1500)
      await list.getByRole('button', { name: 'Take in' }).click()
      await expect(ready).toContainText('In the project ✓', { timeout: 20_000 })
    })
  })

  test('Ready for you: what waits in two chats, answered from the panel and the page', async ({ page, browser }) => {
    test.setTimeout(90_000)
    for (const words of ['run the tests, the shop', 'run the tests, the blog']) {
      const id = await openFreshConversation(page)
      expect((await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { permission_mode: 'ask' } })).ok()).toBe(true)
      await say(page, words, 'Run this command?')
    }
    await video(browser, 'ready', async (shown, poster) => {
      await beat(shown, 500)
      await shown.locator('.ready-pill').click()
      const panel = shown.getByRole('complementary', { name: /^Ready for you · \d+$/ })
      await expect(panel.getByRole('heading', { name: 'This chat · 1' })).toBeVisible()
      await poster()
      await beat(shown)
      await panel.getByRole('region', { name: 'Needs your answer' }).getByRole('button', { name: 'Run once' }).click()
      await expect(shown.getByRole('region', { name: 'Chat' }).getByText('The tests pass.')).toBeVisible({ timeout: 15_000 })
      await beat(shown)
      await panel.getByRole('button', { name: 'Open all as a page →' }).click()
      const row = shown.locator('.ready-page').getByRole('group', { name: /the shop/ })
      await expect(row).toBeVisible()
      await beat(shown)
      await row.getByRole('button', { name: 'Open chat' }).click()
      const chat = shown.getByRole('tabpanel', { name: 'Chat' })
      await beat(shown)
      await chat.getByRole('button', { name: 'Run once' }).click()
      await expect(chat.getByText('The tests pass.')).toBeVisible({ timeout: 15_000 })
    })
  })
})

// Last: its two To-do tasks would wait in Ready for you in the videos above.
test('☾ Away: the Away panel, and the summary when you are back', async ({ page }) => {
  test.setTimeout(90_000)
  // (A little taller than the others: the panel whole, with its Go away.)
  await page.setViewportSize({ width: 1280, height: 900 })
  await openFreshConversation(page)
  await say(page, "I'm going away for the night, guide: add a bye line and say hello twice", 'Two tasks are on your To-do: press Go away when you go.')
  const chat = page.getByRole('region', { name: 'Chat' })
  await expect(chat.getByRole('group', { name: 'Go away now?' })).toBeVisible()
  // (From ☾ Away on the status line: the panel whole, over the message box.)
  await page.locator('.away-chip').click()
  const panel = page.getByRole('dialog', { name: 'Away' })
  await expect(panel.getByRole('checkbox', { name: 'Say hello twice' })).toBeChecked()
  await panel.getByLabel('Until').fill('08:00')
  await panel.getByLabel(/spend at most/).fill('2')
  await picture(page, 'away-panel')
  await panel.getByRole('button', { name: 'Go away' }).click()
  await expect(page.locator('.composer-status')).toContainText('Away · To-do 2 of 2 looked at', { timeout: 30_000 })
  await page.getByRole('button', { name: 'I’m back' }).first().click()
  const summary = chat.getByRole('region', { name: 'While you were away' })
  await expect(summary).toContainText('2 of 2 To-do done', { timeout: 10_000 })
  await picture(page, 'away-summary')
  // (Seen: KOLONİ goes to the report once, and not again in the tests after this one.)
  await summary.getByRole('button', { name: 'On the canvas' }).click()
  await expect(page.locator('.away-node')).toBeVisible()
})

// --- 0.1.6, proven finish: what KOLONİ checks after a change, where it is set, and what it says --------------------------
// (The backend is shared: what these set and write in the e2e project is put back after each.)
// (The e2e project's own check.py and slow.py: the Checks node names a command by its script.)
const PASSING = 'python check.py'
const SLOW = 'python slow.py'
const WRITTEN = [
  'kanit.py',
  ...['a', 'b', 'c', 'd'].map(one => `rehber_${one}.py`),
  // (The Checks loop's turn: its three Coders' modules - fake-model.mjs `LOOPED_WORK`.)
  ...['runner', 'runner_cli', 'runner_log', 'runner_conf', 'runner_util', 'auth_check', 'auth_rules', 'auth_util', 'netcheck', 'netcheck_cli', 'netcheck_util'].map(one => `${one}.py`),
]
const WORKFLOW = 'name: ci\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python -m pytest -q\n'

/** The project's After a change on, with `command`, and the page read again: the composer says what the chat checks. */
async function checksOn(page: Page, command: string) {
  await setProject(page, { check_command: command, after_change: 'check' })
  await page.reload()
  await page.getByLabel('Message').waitFor()
}

test.describe('proven finish (0.1.6)', () => {
  test.afterEach(async ({ page }) => {
    for (const name of WRITTEN) rmSync(path.join(PROJECT_DIR, name), { force: true })
    rmSync(path.join(PROJECT_DIR, '.github'), { recursive: true, force: true })
    await setProject(page, { check_command: '', after_change: 'nothing' })
  })

  test('Settings: After a change, Fix rounds and Check by kind of work; the app’s test runs; the level menu’s switch', async ({ page }) => {
    await openFreshConversation(page)
    await setProject(page, { after_change: 'check' })
    // (No message yet: the First steps panel would show the project's folder - under this machine's user.)
    await page.addInitScript(() => localStorage.setItem('koloni-first-steps', 'hidden'))
    await page.reload()
    await page.getByLabel('Message').waitFor()
    // The permission level's menu: Test and review changes, for this chat.
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('button', { name: /^Permission level:/ }).click()
    await expect(chat.getByRole('dialog', { name: 'Permission level' }).getByText('Test and review changes')).toBeVisible()
    await picture(page, 'level-menu-checks')
    await page.keyboard.press('Escape')
    // This project › Checks and git: After a change with its live line, Fix rounds (Then a stronger model, once in),
    // Check by kind of work, Found by KOLONİ.
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    const settings = page.getByRole('form', { name: 'Project settings' })
    await settings.getByRole('button', { name: /^Checks and git/ }).click()
    await expect(settings.getByLabel('After a change')).toBeVisible()
    await expect(settings.getByLabel('Fix rounds')).toBeVisible()
    await picture(page, 'settings-checks')
    await page.getByRole('button', { name: 'Close settings' }).click()
    // The app › Agents: KOLONİ's test runs at once, and the test processes each may use.
    const app = await appSettings(page, 'Agents')
    await app.getByText('KOLONİ’s test runs at once').scrollIntoViewIfNeeded()
    await picture(page, 'settings-app-test-runs')
  })

  test('Checked under the answer, and the Checks node with its ⋯ menu', async ({ page }) => {
    await openFreshConversation(page)
    await checksOn(page, PASSING)
    await level(page, 'auto_edit') // (the write is applied; the user's own command runs unasked)
    await say(page, 'write the checked file, k-kanit', 'Wrote kanit.py.')
    const checked = page.getByRole('region', { name: 'Chat' }).getByRole('region', { name: 'Checked' })
    await expect(checked).toContainText(`Tests passed: ${PASSING} - 2 passed`, { timeout: 20_000 })
    await picture(checked, 'checked-section')
    await settled(page)
    // (The node's lines: in checks-running with its ⋯ menu, in checks-loop with its rounds.)
    await page.getByRole('button', { name: 'Checks: more' }).click()
    await expect(page.getByRole('menu', { name: 'Checks: more' })).toBeVisible()
  })

  test('a check at work: the node runs, its ⋯ menu stops it', async ({ page }) => {
    await openFreshConversation(page)
    await checksOn(page, SLOW)
    await level(page, 'auto_edit')
    await page.getByLabel('Message').fill('write the checked file, k-kanit')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.locator('.react-flow__node-checks')).toContainText('slow.py', { timeout: 20_000 })
    await settled(page)
    await page.getByRole('button', { name: 'Checks: more' }).click()
    await expect(page.getByRole('menuitem', { name: 'Stop this check' })).toBeVisible()
    await picture(page, 'checks-running')
    await page.getByRole('menuitem', { name: 'Stop this check' }).click()
    const checked = page.getByRole('region', { name: 'Chat' }).getByRole('region', { name: 'Checked' })
    await expect(checked).toContainText('Tests not run: you stopped the check', { timeout: 20_000 })
    await picture(checked, 'checked-stopped')
  })

  test('a big change looked over: the Reviewer’s rows, and the Reviewer in the Checks box', async ({ page }) => {
    test.setTimeout(90_000) // (KOLONİ's Reviewer looks after the tests: on a busy machine over the default 30 s)
    await openFreshConversation(page)
    await checksOn(page, PASSING)
    await level(page, 'auto_edit')
    await say(page, 'write the reviewed change, k-rehber', 'Wrote the change.')
    const checked = page.getByRole('region', { name: 'Chat' }).getByRole('region', { name: 'Checked' })
    await expect(checked).toContainText('Review: Reviewer', { timeout: 30_000 })
    await picture(checked, 'checked-review')
    await settled(page)
    await picture(page, 'checks-reviewer')
  })

  // tuval-kontrol-dongusu (0.1.7): KOLONİ's looks and the fixes it sent back, one loop on the canvas and its rounds in the panel.
  test('a turn sent back twice: the loop of its looks and fixes, and its rounds in the inspector', async ({ page }) => {
    test.setTimeout(180_000)
    await openFreshConversation(page)
    const id = await e2eProject(page)
    const had = (await (await page.request.get(`/api/projects/${id}`)).json()).fix_rounds
    await setProject(page, { fix_rounds: 2 })
    try {
      await checksOn(page, PASSING)
      await level(page, 'full_auto') // (the Orchestrator's Coders open, and their work is taken in, unasked)
      await page.getByLabel('Message').fill('write the looped change, k-dongu')
      await page.getByRole('button', { name: 'Send' }).click()
      const box = page.locator('.react-flow__node-checks')
      await expect(box).toContainText('⟲ 3 looks · 2 fix rounds · on hold', { timeout: 150_000 })
      // (The chat closed: the canvas has the room for the whole turn beside the panel.)
      await page.getByRole('button', { name: 'Hide chat' }).click()
      await settled(page)
      await box.getByText('Checks · KOLONİ').click()
      await expect(page.getByRole('complementary', { name: 'Inspector' }).getByRole('region', { name: 'Round 3' })).toBeVisible()
      await settled(page)
      // (Drawn larger - fitted beside the panel, its cards' words are too small to read -, the turn moved to the middle of the canvas.)
      await page.locator('.react-flow__controls-zoomin').click()
      await settled(page)
      const [first, last, stage] = await Promise.all([page.locator('.react-flow__node-request').first(), box, page.locator('.react-flow')].map(async one => (await one.boundingBox())!))
      const shift = stage.x + (stage.width - (last.x + last.width - first.x)) / 2 - first.x
      await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height - 180)
      await page.mouse.down()
      await page.mouse.move(stage.x + stage.width / 2 + shift, stage.y + stage.height - 180, { steps: 6 })
      await page.mouse.up()
      await settled(page)
      await picture(page, 'checks-loop')
    } finally {
      await setProject(page, { fix_rounds: had })
    }
  })

  test('your CI’s lines offered under the answer: Run these', async ({ page }) => {
    mkdirSync(path.join(PROJECT_DIR, '.github', 'workflows'), { recursive: true })
    writeFileSync(path.join(PROJECT_DIR, '.github', 'workflows', 'guide.yml'), WORKFLOW)
    await openFreshConversation(page)
    await checksOn(page, '')
    await level(page, 'auto_edit')
    await say(page, 'write the checked file, k-kanit', 'Wrote kanit.py.')
    const checked = page.getByRole('region', { name: 'Chat' }).getByRole('region', { name: 'Checked' })
    await expect(checked.getByRole('button', { name: 'Run these' })).toBeVisible({ timeout: 20_000 })
    await picture(checked, 'checked-ci-offer')
  })

  test('the recipe editor: every recipe ends in its locked Checks step', async ({ page }) => {
    await openFreshConversation(page)
    await page.getByRole('button', { name: 'Agents', exact: true }).click()
    await page.getByRole('tab', { name: 'Recipes' }).click()
    await page.getByRole('button', { name: /^Bugfix/ }).click()
    await page.locator('.recipe-flow .react-flow__node[data-id="checks:end"]').getByRole('button').click()
    await expect(page.getByRole('complementary', { name: 'Recipe part Checks' })).toBeVisible()
    await picture(page, 'recipe-checks-step')
  })
})
