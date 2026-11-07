import { mkdirSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { type Browser, expect, type Locator, type Page, test } from './fixtures'
import { LINK, OWN, e2eProject, openFreshConversation, rail, say, setProject, settled } from './helpers'
import { APP_URL, REPO_ROOT } from './paths.mjs'

// The guide's pictures (docs/images) and short videos (docs/videos), taken from the real app with the fake model, light,
// at 1280×800 and 1280×720. Taken on request (KOLONI_SHOTS=1), after `npm run build`: an ordinary run leaves them alone.
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
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByRole('form', { name: 'Project settings' })).toBeVisible()
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

  await rail(page, 'Usage').click()
  await expect(page.getByRole('table', { name: 'Usage by provider and model' })).toBeVisible()
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
