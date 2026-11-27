import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { type APIRequestContext, type Browser, expect, type Locator, type Page, test } from './fixtures'
import {
  LINK,
  OWN,
  appSettings,
  e2eProject,
  level,
  openFreshConversation,
  rail,
  say,
  setProject,
  settled,
  story,
  todo,
} from './helpers'
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
    [
      (el as HTMLElement).innerText,
      ...[...el.querySelectorAll('input, textarea')].map(one => (one as HTMLInputElement).value),
    ]
      .join('\n')
      .toLowerCase(),
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
  const context = await browser.newContext({
    baseURL: APP_URL,
    viewport: FRAME,
    recordVideo: { dir: path.join(os.tmpdir(), 'koloni-guide-videos'), size: FRAME },
  })
  await context.addInitScript(() => localStorage.setItem('koloni-theme', 'light'))
  const page = await context.newPage()
  await page.goto(LINK)
  await page.getByLabel('Message').waitFor()
  await flow(page, async () => {
    await showsNoHome(page, name)
    await page.screenshot({
      path: path.join(VIDEOS, `${name}.jpg`),
      type: 'jpeg',
      quality: 80,
      animations: 'disabled',
      caret: 'hide',
    })
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
  await page
    .getByRole('region', { name: 'Chat' })
    .getByRole('button', { name: /Reviewer.*Review hello\.py/ })
    .click()
  await page.getByRole('complementary', { name: 'Inspector' }).getByRole('button', { name: 'Open window' }).click()
  await expect(page.getByRole('region', { name: 'Agent window' }).getByText('Did', { exact: true })).toBeVisible()
  await picture(page, 'agent-window')
})

test('an approval card in Ready for you', async ({ page }) => {
  const id = await openFreshConversation(page)
  expect(
    (await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { permission_mode: 'ask' } })).ok(),
  ).toBe(true)
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
    arrows: [
      { from: 'start', to: 'build' },
      { from: 'build', to: 'end' },
    ],
  }
  await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })
  const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(
    r => r.name === RECIPE,
  )
  const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(
    t => t.name === 'Web app',
  )
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
  // (As a new project has it, 0.1.5: the harness's own is "everything waits", 10 minutes - and, 0.1.9, Full auto's
  // judge on.)
  await setProject(page, { when_away: 'lead', away_minutes: 5, full_auto_judge: true })
  await page.reload()
  await page.getByLabel('Message').waitFor()
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const settings = page.getByRole('form', { name: 'Project settings' })
  // (At Asking and away: when you're away, Full auto's judge (0.1.9) and its box for your words (§8), disposable deletes.)
  await settings.getByRole('button', { name: /^Asking and away/ }).click()
  await expect(settings.getByRole('checkbox', { name: /^Full auto’s judge/ })).toBeChecked()
  await expect(settings.getByRole('checkbox', { name: /^It also lets a delete or a push run/ })).toBeDisabled()
  await picture(page, 'settings-project')
  await page.getByRole('button', { name: 'Close settings' }).click()
  await page.getByRole('button', { name: 'Memory', exact: true }).click()
  await page.getByRole('tab', { name: /^Sources to look things up in/ }).click()
  await expect(page.getByRole('article', { name: 'MLflow' })).toBeVisible()
  await picture(page, 'knowledge')
})

test('To-do’s rough note, split into tasks by the Hive keeper', async ({ page }) => {
  await openFreshConversation(page)
  const half = await todo(page)
  const box = half.getByRole('form', { name: 'Your rough note' })
  await box.getByLabel('Your rough note').fill('the login page breaks on mobile, and we need a password reset')
  await box.getByRole('button', { name: 'Split into tasks', exact: true }).click()
  const drafts = page.getByRole('region', { name: 'Drafted tasks' })
  await expect(drafts.getByRole('group', { name: 'Draft 2' }).getByLabel('Title')).toHaveValue('Add a password reset')
  await box.scrollIntoViewIfNeeded()
  await picture(page, 'todo-draft')
})

test('the To-do tree', async ({ page }) => {
  await openFreshConversation(page)
  const pid = await e2eProject(page)
  const tree = {
    stories: [
      {
        title: 'Login works on mobile',
        notes: ['The form is shared with the desktop page.'],
        tasks: [
          { title: 'Find the rule that breaks it', priority: 'high', kind: 'task' },
          { title: 'The button slips under the keyboard', kind: 'bug' },
        ],
      },
      {
        title: 'Password reset',
        notes: ['Mails go through the queue.', 'Links last one hour.'],
        tasks: [
          { title: 'Send the reset mail', kind: 'task' },
          { title: 'Rate-limit the reset form', kind: 'task' },
        ],
      },
    ],
    tasks: [{ title: 'The footer shows last year', kind: 'bug' }],
  }
  const added = await (
    await page.request.post(`/api/projects/${pid}/backlog/tree`, { headers: OWN, data: tree })
  ).json()
  const [login, reset] = added.story_ids
  try {
    const [rule, button, mail] = added.task_ids
    for (const id of [rule, button])
      await page.request.patch(`/api/backlog/${id}`, { headers: OWN, data: { status: 'done' } })
    await page.request.patch(`/api/stories/${login}`, { headers: OWN, data: { closed: true } })
    await page.request.patch(`/api/backlog/${mail}`, { headers: OWN, data: { status: 'doing' } })
    const half = await todo(page)
    await expect(half.getByRole('button', { name: 'Password reset: 0 of 2 done' })).toContainText('at work')
    await expect(half.getByRole('button', { name: 'Login works on mobile: 2 of 2 done' })).toBeVisible()
    // (0.1.10: the page whole - what was done and what waits on the left, To-do's cards on the right.)
    await picture(page, 'ready-todo')
    // (A story opened: its panel over To-do - its facts, its notebook, its tasks; one ticked, the dock says what Do in
    // chat does.)
    const panel = await story(page, 'Password reset')
    await panel.getByRole('checkbox', { name: 'Tick Rate-limit the reset form' }).check()
    await expect(panel.getByRole('region', { name: 'Selected tasks' })).toContainText('1 selected')
    await picture(page, 'todo-tree')
  } finally {
    // (Gone again, whatever happened: the pictures after it show their own To-do.)
    for (const id of added.task_ids) await page.request.delete(`/api/backlog/${id}`, { headers: OWN })
    for (const id of [login, reset]) await page.request.delete(`/api/stories/${id}`, { headers: OWN })
    await page.request.delete(`/api/goals/${added.goal_id}`, { headers: OWN })
  }
})

test('To-do in a chat', async ({ page }) => {
  await openFreshConversation(page)
  const pid = await e2eProject(page)
  const tree = {
    stories: [
      {
        title: 'Two-step sign-in',
        notes: [],
        tasks: [
          { title: 'Send a code by mail', criteria: 'a six-digit code is mailed, valid for ten minutes' },
          { title: 'Check the code on sign-in' },
          { title: 'Turn it on in Settings' },
        ],
      },
    ],
    tasks: [],
  }
  const added = await (
    await page.request.post(`/api/projects/${pid}/backlog/tree`, { headers: OWN, data: tree })
  ).json()
  try {
    await todo(page)
    const panel = await story(page, 'Two-step sign-in')
    await panel.getByRole('checkbox', { name: 'Tick the story Two-step sign-in' }).check()
    await panel
      .getByRole('region', { name: 'Selected tasks' })
      .getByRole('button', { name: /Do in chat/ })
      .click()
    await page.getByRole('menuitem', { name: 'A new chat' }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    await expect(chat.getByRole('group', { name: 'Done? — “Send a code by mail”' })).toBeVisible({ timeout: 20_000 })
    await expect(chat.getByRole('group', { name: 'Done? — “Turn it on in Settings”' })).toBeVisible({
      timeout: 20_000,
    })
    await picture(page, 'todo-in-chat')
  } finally {
    for (const id of added.task_ids) await page.request.delete(`/api/backlog/${id}`, { headers: OWN })
    for (const id of added.story_ids) await page.request.delete(`/api/stories/${id}`, { headers: OWN })
  }
})

test('a story’s strip and notebook', async ({ page }) => {
  await openFreshConversation(page)
  const pid = await e2eProject(page)
  const tree = {
    stories: [
      {
        title: 'Two-step sign-in',
        notes: ['Codes go by mail, not SMS.'],
        tasks: [
          { title: 'Send a code by mail', criteria: 'a six-digit code is mailed, valid for ten minutes' },
          { title: 'Check the code on sign-in' },
          { title: 'Turn it on in Settings' },
        ],
      },
    ],
    tasks: [],
  }
  const added = await (
    await page.request.post(`/api/projects/${pid}/backlog/tree`, { headers: OWN, data: tree })
  ).json()
  try {
    // (The two after the first wait for it: once it waits at "done?", the strip says the next.)
    const [first, ...later] = added.task_ids
    for (const id of later) await page.request.patch(`/api/backlog/${id}`, { headers: OWN, data: { after: [first] } })
    await todo(page)
    const panel = await story(page, 'Two-step sign-in')
    await panel.getByRole('checkbox', { name: 'Tick the story Two-step sign-in' }).check()
    await panel
      .getByRole('region', { name: 'Selected tasks' })
      .getByRole('button', { name: /Do in chat/ })
      .click()
    await page.getByRole('menuitem', { name: 'A new chat' }).click()
    const chat = page.getByRole('region', { name: 'Chat' })
    await expect(chat.getByRole('group', { name: 'Done? — “Send a code by mail”' })).toBeVisible({ timeout: 20_000 })
    const strip = page.getByRole('region', { name: 'Story' })
    await expect(strip).toHaveText('Story · Two-step sign-in · 2 / 3 · next: Turn it on in Settings · 📓 notes', {
      timeout: 20_000,
    })
    await strip.getByRole('button', { name: 'notes' }).click()
    await expect(page.getByRole('dialog', { name: 'Notebook of Two-step sign-in' })).toContainText(
      '“Send a code by mail” — done?',
    )
    await picture(page, 'story-notebook')
  } finally {
    for (const id of added.task_ids) await page.request.delete(`/api/backlog/${id}`, { headers: OWN })
    for (const id of added.story_ids) await page.request.delete(`/api/stories/${id}`, { headers: OWN })
  }
})

/** Everything in effect or waiting goes to Past, and your words are emptied: the pictures after start from an empty memory. */
async function clearMemory(request: APIRequestContext, pid: string) {
  const memory = await (await request.get(`/api/projects/${pid}/memory`)).json()
  for (const one of [...memory.proposals, ...memory.core, ...memory.journal] as { id: string }[])
    await request.post(`/api/memory/${one.id}/reject`, { headers: OWN })
  await request.put(`/api/projects/${pid}/rules`, { headers: OWN, data: { rules: '' } })
  await request.put(`/api/projects/${pid}/project-notes`, { headers: OWN, data: { text: '' } })
  await request.put('/api/preferences', { headers: OWN, data: { text: '' } })
}

test('the Memory page as cells', async ({ page, request }) => {
  await openFreshConversation(page)
  const pid = await e2eProject(page)
  const shown = path.join(PROJECT_DIR, 'settings.txt')
  const moved = path.join(PROJECT_DIR, 'deploy-notes.txt')
  await clearMemory(request, pid)
  writeFileSync(shown, '# settings\nThe service listens on port 8123.\n')
  writeFileSync(moved, '# deploy\nStaging runs on host stage-1.\n')
  const write = async (data: object) =>
    expect((await request.post(`/api/projects/${pid}/memory`, { headers: OWN, data })).status()).toBe(201)
  try {
    // A fact the lead's note would take the place of; one of your words; one too general to be given; one whose lines
    // change after it was written.
    await write({ text: 'The service listens on port 8000.', about: 'port', file: 'settings.txt', start_line: 1 })
    await write({ text: 'Commits are signed off.', about: 'commits' })
    await write({ text: 'Docs are Markdown.', about: 'md' })
    await write({
      text: 'Staging runs on host stage-1.',
      about: 'staging host',
      file: 'deploy-notes.txt',
      start_line: 2,
    })
    writeFileSync(moved, '# deploy\nStaging runs on host stage-2.\n')
    await request.put('/api/preferences', { headers: OWN, data: { text: 'Answer in short sentences.' } })
    await request.put(`/api/projects/${pid}/rules`, {
      headers: OWN,
      data: { rules: 'Sign off every commit.\nNever push to main.' },
    })
    await request.put(`/api/projects/${pid}/project-notes`, {
      headers: OWN,
      data: { text: '- The export module is being rewritten: leave export.py alone.' },
    })
    await say(page, 'note the port', 'Noted where the port is set. It waits for you.')
    // (Loaded again: the turn's "Done" toast is not in the picture.)
    await page.reload()
    await rail(page, 'Memory').click()
    await expect(
      page.getByRole('region', { name: 'Waits for you' }).getByRole('group', { name: 'Would replace' }),
    ).toBeVisible()
    await expect(page.getByRole('region', { name: 'Facts', exact: true }).getByRole('article')).toHaveCount(4)
    // (Taller than the others: the box that waits, the facts with their cells and your words, in one picture.)
    await page.setViewportSize({ width: 1280, height: 1300 })
    await picture(page, 'memory')
  } finally {
    await clearMemory(request, pid)
    rmSync(moved, { force: true })
  }
})

test('Memory search and Usage', async ({ page, request }) => {
  const id = await openFreshConversation(page)
  await say(page, 'Answer only: The ZEPPELIN hangar is in Kayseri.', 'The ZEPPELIN hangar is in Kayseri.')
  expect(
    (await request.patch(`/api/conversations/${id}`, { headers: OWN, data: { title: 'Morning checks' } })).ok(),
  ).toBe(true)
  // (Loaded again: the turn's "Done" toast is not in the pictures.)
  await page.reload()
  await rail(page, 'Memory').click()
  const search = page.getByRole('region', { name: 'Search', exact: true })
  await search.getByLabel('Search everything this project remembers').fill('zeppelin')
  await search.getByRole('button', { name: 'Search deeper' }).click()
  await expect(search.getByRole('list', { name: 'In earlier messages' }).getByRole('listitem').first()).toBeVisible()
  await picture(page, 'memory-search')

  await rail(page, 'Usage').click()
  await expect(page.getByRole('table', { name: 'Usage by provider and model' })).toBeVisible()
  await picture(page, 'usage')
})

test('the Chats page: each chat’s cell and line, and Now', async ({ page, request }) => {
  test.setTimeout(90_000)
  const name = (id: string, title: string) =>
    request
      .patch(`/api/conversations/${id}`, { headers: OWN, data: { title } })
      .then(said => expect(said.ok()).toBe(true))
  await name(await openFreshConversation(page), 'Ideas for the logo')
  const done = await openFreshConversation(page)
  await say(page, 'review the greeting', 'The reviewer found no problems.')
  await name(done, 'Review the greeting')
  const asks = await openFreshConversation(page)
  expect(
    (await request.patch(`/api/conversations/${asks}`, { headers: OWN, data: { permission_mode: 'ask' } })).ok(),
  ).toBe(true)
  await say(page, 'run the tests', 'Run this command?')
  await name(asks, 'Run the tests')
  // (Loaded again: the turn's "Done" toast is not in the picture.)
  await page.reload()
  await rail(page, 'Chats').click()
  const list = page.locator('.conv-page')
  await expect(list.getByRole('button', { name: /^Run the tests/ })).toContainText('Waits for your word · Command')
  await expect(list.getByRole('button', { name: /^Review the greeting/ })).toContainText('Done')
  await expect(list.getByRole('complementary', { name: 'Now every folder' })).toContainText(
    '1 thing waits for your word',
  )
  await picture(page, 'chats')
  // (Answered: what runs after finds nothing waiting.)
  await list.getByRole('button', { name: /^Run the tests/ }).click()
  await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByText('Okay, I left hello.py unchanged.')).toBeVisible({ timeout: 20_000 })
})

test('the Tools page: its cells, a server watched, one trusted and one whose trust a reading took back; KOLONİ’s tools; skills', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000)
  // The stand-in MCP server, started as `python -m` with its folder in a variable: no folder of this machine is on a
  // card. Each server its own plan: its own tools, in place of the stand-in's.
  const plans = path.join(os.tmpdir(), `koloni-guide-mcp-${process.env.KOLONI_E2E_PORT ?? 'e2e'}`)
  mkdirSync(plans, { recursive: true })
  const tool = (name: string, description: string) => ({
    name,
    description,
    inputSchema: { type: 'object', properties: {} },
  })
  const OWN_TOOLS = ['echo', 'where', 'boom', 'picture', 'big', 'hang', 'die', 'sample']
  const plan = (name: string, tools: ReturnType<typeof tool>[]) => {
    const file = path.join(plans, `${name}.json`)
    writeFileSync(file, JSON.stringify({ record: path.join(plans, 'record.jsonl'), without: OWN_TOOLS, more: tools }))
    return file
  }
  const serve = async (name: string, tools: ReturnType<typeof tool>[]) => {
    const added = await request.post('/api/mcp-servers', {
      headers: OWN,
      data: {
        name,
        command: ['python', '-m', 'tests.fake_mcp_server'],
        env: { PYTHONPATH: REPO_ROOT, FAKE_MCP_PLAN: plan(name, tools) },
      },
    })
    expect(added.status()).toBe(201)
    const { id } = await added.json()
    const read = await request.post(`/api/mcp-servers/${id}/read`, { headers: OWN, data: { osv: false } })
    expect((await read.json()).server.read_error).toBeNull()
    return id as string
  }
  const trust = (id: string, marks?: Record<string, string>) =>
    request.patch(`/api/mcp-servers/${id}`, { headers: OWN, data: { trusted: true, ...(marks && { marks }) } })
  const browserTools = [
    tool('take_screenshot', 'Takes a picture of the page'),
    tool('read_console', 'Reads the console'),
  ]
  const ids = [
    await serve('browser-tools', browserTools),
    await serve('github', [
      tool('list_issues', 'Lists the issues of a repository'),
      tool('create_issue', 'Opens an issue'),
    ]),
    await serve('postgres', [
      tool('query', 'Runs a read-only SQL query'),
      tool('list_tables', 'Lists the tables'),
      tool('describe', 'Shows a table’s columns'),
      tool('vacuum', 'Reclaims storage'),
    ]),
  ]
  const [browserId, , postgresId] = ids
  expect((await trust(browserId)).ok()).toBe(true)
  expect((await trust(postgresId, { query: 'free', list_tables: 'free', describe: 'ask', vacuum: 'off' })).ok()).toBe(
    true,
  )
  // Two skills, uploaded (a folder's path would name this machine's folders).
  const upload = (name: string, line: string, text: string) =>
    request.post('/api/skills', {
      headers: OWN,
      data: {
        upload: {
          files: [
            {
              path: `${name}/SKILL.md`,
              data: Buffer.from(`---\nname: ${name}\ndescription: ${line}\n---\n${text}\n`).toString('base64'),
            },
          ],
        },
      },
    })
  const skills = [
    await upload('release-notes', 'Writes a CHANGELOG entry in the user’s words.', 'Added, Changed, Fixed.'),
    await upload('systematic-debugging', 'Finds the root cause before a fix.', 'Read, repeat, find what changed.'),
  ]
  const skillIds = await Promise.all(skills.map(async added => ((await added.json()) as { id: string }).id))
  // The Coder is given postgres and release-notes: their cards name it.
  type Given = { id: string; name: string; mcp: string[]; skills: string[] }
  const coder = ((await (await request.get('/api/roles')).json()) as Given[]).find(role => role.name === 'Coder')!
  const give = (mcp: string[], skills: string[]) =>
    request.patch(`/api/roles/${coder.id}`, { headers: OWN, data: { mcp, skills } })
  expect((await give([...coder.mcp, 'postgres'], [...coder.skills, 'release-notes'])).ok()).toBe(true)
  try {
    await openFreshConversation(page)
    // (A server's trust taken back is known from a reading on the page: the plan grows a tool, then it is read there.)
    writeFileSync(
      path.join(plans, 'browser-tools.json'),
      JSON.stringify({
        record: path.join(plans, 'record.jsonl'),
        without: OWN_TOOLS,
        more: [...browserTools, tool('evaluate', 'Runs a script in the page')],
      }),
    )
    await rail(page, 'Tools').click()
    const head = (name: string) => page.getByRole('button', { name: new RegExp(`^${name}`) })
    await expect(head('browser-tools')).toHaveAttribute('aria-expanded', 'true')
    await page.getByRole('button', { name: 'Read its tools' }).click()
    await expect(head('browser-tools')).toContainText('trust taken back')
    // every card closed: their heads, their cells and their trust
    await head('browser-tools').click()
    await page.getByRole('button', { name: 'See the difference' }).click()
    await expect(page.getByText(/^New: evaluate\./)).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Servers 2 watching' })).toBeVisible()
    await picture(page, 'tools-servers')
    // the trusted one open: its tools, each with its three marks
    await head('postgres').click()
    const postgres = page.getByRole('listitem').filter({ has: head('postgres') })
    await expect(postgres.getByRole('table', { name: 'Tools of postgres' })).toBeVisible()
    // (Taller than the window: a window it fits in, so that the page's own scroll box does not cut it.)
    await page.setViewportSize({ width: 1280, height: 1400 })
    await picture(postgres, 'tools-server-open')
    await page.setViewportSize({ width: 1280, height: 800 })

    await page.getByRole('tab', { name: /^KOLONİ’s tools/ }).click()
    await expect(page.getByRole('region', { name: 'KOLONİ’s tools' })).toBeVisible()
    await picture(page, 'tools-koloni')

    await page.getByRole('tab', { name: /^Skills/ }).click()
    await expect(page.getByRole('button', { name: /^systematic-debugging/ })).toBeVisible()
    await picture(page, 'tools-skills')
  } finally {
    for (const id of ids) await request.delete(`/api/mcp-servers/${id}`, { headers: OWN })
    await give(coder.mcp, coder.skills)
    for (const id of skillIds) await request.delete(`/api/skills/${id}`, { headers: OWN })
    rmSync(plans, { recursive: true, force: true })
  }
})

test.describe('the guide’s videos', () => {
  test.use({ viewport: FRAME })

  test('an agent asks, you approve', async ({ page, browser }) => {
    test.setTimeout(60_000)
    const id = await openFreshConversation(page)
    expect(
      (await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { permission_mode: 'ask' } })).ok(),
    ).toBe(true)
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
      arrows: [
        { from: 'start', to: 'build' },
        { from: 'build', to: 'end' },
      ],
    }
    await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })
    const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(
      r => r.name === RECIPE,
    )
    const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(
      t => t.name === 'Web app',
    )
    await setProject(page, { spawn_approval: 'never' })
    const set = await request.patch(`/api/conversations/${id}`, {
      headers: OWN,
      data: {
        permission_mode: 'auto_edit',
        teams_mode: 'manual',
        teams: [{ team_id: web!.id, recipe_id: recipe!.id }],
      },
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
      expect(
        (await page.request.patch(`/api/conversations/${id}`, { headers: OWN, data: { permission_mode: 'ask' } })).ok(),
      ).toBe(true)
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
      await expect(shown.getByRole('region', { name: 'Chat' }).getByText('The tests pass.')).toBeVisible({
        timeout: 15_000,
      })
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
  await say(
    page,
    "I'm going away for the night, guide: add a bye line and say hello twice",
    'Two tasks are on your To-do: press Go away when you go.',
  )
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
  // (0.1.10: the morning's Ready for you - the night's report on the left, To-do's cards on the right.)
  await rail(page, 'Ready').click()
  await expect(page.getByRole('region', { name: /^Last night, / })).toContainText('2 of 2 jobs done.')
  await picture(page, 'ready-morning')
  await rail(page, 'Canvas').click()
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
  ...[
    'runner',
    'runner_cli',
    'runner_log',
    'runner_conf',
    'runner_util',
    'auth_check',
    'auth_rules',
    'auth_util',
    'netcheck',
    'netcheck_cli',
    'netcheck_util',
  ].map(one => `${one}.py`),
]
const WORKFLOW =
  'name: ci\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: python -m pytest -q\n'

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

  test('Settings: After a change, Fix rounds and Check by kind of work; the app’s test runs; the level menu’s switch', async ({
    page,
  }) => {
    await openFreshConversation(page)
    // (Full auto's judge as a project has it, 0.1.9: on - its switch in the menu.)
    await setProject(page, { after_change: 'check', full_auto_judge: true })
    // (No message yet: the First steps panel would show the project's folder - under this machine's user.)
    await page.addInitScript(() => localStorage.setItem('koloni-first-steps', 'hidden'))
    await page.reload()
    await page.getByLabel('Message').waitFor()
    // The permission level's menu: Test and review changes, for this chat.
    const chat = page.getByRole('region', { name: 'Chat' })
    await chat.getByRole('button', { name: /^Permission level:/ }).click()
    await expect(
      chat.getByRole('dialog', { name: 'Permission level' }).getByText('Test and review changes'),
    ).toBeVisible()
    await expect(chat.getByRole('switch', { name: 'Full auto’s judge' })).toBeChecked()
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
    // The app › Agents: KOLONİ's test runs at once, the test processes each may use, and Show experimental features and the
    // Judge model (0.1.9) under Save (read once shown) - the fake model the Fast tier's first, as on a machine set up.
    type Local = { id: string; models: { name: string }[] }
    const local: Local = (await (await page.request.get('/api/providers')).json()).find(
      (one: { name: string }) => one.name === 'Local',
    )
    const tiered = [...local.models.filter(one => one.name !== 'fake-qwen'), { name: 'fake-qwen', tier: 'fast' }]
    const models = async (data: unknown[]) =>
      expect(
        (await page.request.patch(`/api/providers/${local.id}`, { headers: OWN, data: { models: data } })).ok(),
      ).toBe(true)
    await models(tiered)
    try {
      const app = await appSettings(page, 'Agents')
      const experimental = app.getByRole('checkbox', { name: /Show experimental features/ })
      await expect(experimental).toBeEnabled()
      const judge = app.getByLabel('Judge model')
      await expect(judge).toHaveValue('')
      await expect(judge.locator('option').first()).toHaveText('Fast tier’s first (now: fake-qwen)')
      // (Under More limits since 0.1.10.)
      await app.getByText(/^More limits/).click()
      await judge.scrollIntoViewIfNeeded()
      await expect(app.getByText('KOLONİ’s test runs at once')).toBeInViewport()
      await expect(app.getByText('Test processes per run')).toBeInViewport()
      await expect(experimental).toBeInViewport()
      await picture(page, 'settings-app-test-runs')
    } finally {
      await models(local.models)
    }
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
      await expect(
        page.getByRole('complementary', { name: 'Inspector' }).getByRole('region', { name: 'Round 3' }),
      ).toBeVisible()
      await settled(page)
      // (Drawn larger - fitted beside the panel, its cards' words are too small to read -, the turn moved to the middle of the canvas.)
      await page.locator('.react-flow__controls-zoomin').click()
      await settled(page)
      const [first, last, stage] = await Promise.all(
        [page.locator('.react-flow__node-request').first(), box, page.locator('.react-flow')].map(
          async one => (await one.boundingBox())!,
        ),
      )
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

  // tuval-kontrol-dongusu, the recipe case: a one-step recipe's turn - its Coder in the frame, KOLONİ's look in the Checks box,
  // the frame's last part, right of the step.
  // shortcut: one look that lets it stand (the plain box) - a recipe's turn KOLONİ sends back needs the fake model's recipe
  // flow scripted for it (k-dongu's three Coders and its Security reviewer are the Orchestrator's, not a recipe's).
  test('a recipe’s turn: the Checks box is its frame’s last part', async ({ page, request }) => {
    test.setTimeout(180_000)
    const conversation = await openFreshConversation(page)
    const id = await e2eProject(page)
    const { spawn_approval: spawns } = await (await page.request.get(`/api/projects/${id}`)).json()
    const RECIPE = 'Write it (guide)'
    const graph = {
      version: 1,
      steps: [{ id: 'write', name: 'Write it', who: { role: 'Coder' } }],
      ends: [{ id: 'end', then: 'in' }],
      arrows: [
        { from: 'start', to: 'write' },
        { from: 'write', to: 'end' },
      ],
    }
    await request.post('/api/recipes', { headers: OWN, data: { name: RECIPE, graph } })
    const recipe = ((await (await request.get('/api/recipes')).json()).recipes as { id: string; name: string }[]).find(
      r => r.name === RECIPE,
    )
    const web = ((await (await request.get('/api/teams')).json()) as { id: string; name: string }[]).find(
      t => t.name === 'Web app',
    )
    await setProject(page, { spawn_approval: 'never' })
    try {
      await checksOn(page, PASSING)
      await level(page, 'full_auto')
      const set = await request.patch(`/api/conversations/${conversation}`, {
        headers: OWN,
        data: { teams_mode: 'manual', teams: [{ team_id: web!.id, recipe_id: recipe!.id }] },
      })
      expect(set.ok()).toBe(true)
      await page.getByLabel('Message').fill('write the looped change, k-dongu')
      await page.getByRole('button', { name: 'Send' }).click()
      const box = page.locator('.react-flow__node-checks')
      await expect(box).toContainText('MERGE', { timeout: 150_000 })
      await expect(box).toContainText('✓ check.py', { timeout: 30_000 })
      await page.getByRole('button', { name: 'Hide chat' }).click()
      await settled(page)
      for (let times = 0; times < 2; times++) await page.locator('.react-flow__controls-zoomin').click()
      await settled(page)
      await picture(page, 'checks-recipe')
    } finally {
      await setProject(page, { spawn_approval: spawns })
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
