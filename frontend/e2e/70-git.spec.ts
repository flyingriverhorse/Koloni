import { execFileSync } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { expect, test } from './fixtures'
import { contrasts, LINK, OWN } from './helpers'
import { APP_PORT } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

// A project that is a git repository of its own (slice 70), in a folder of the e2e's outside the checkout: a project
// may not be in KOLONİ's own code (as OUTSIDE_DIR in paths.mjs).
const REPO = path.join(os.tmpdir(), `koloni-e2e-git70-${APP_PORT}`)
const SHOTS = path.join(os.tmpdir(), 'koloni-docs', 'g70-shots')
// (Nothing of the user's own git settings - a signing key, a hook - in these commits.)
const empty = `${REPO}.gitconfig`
const git = (...args: string[]) =>
  execFileSync('git', ['-c', 'user.email=e2e@example.com', '-c', 'user.name=e2e', '-c', 'commit.gpgsign=false', ...args], {
    cwd: REPO,
    env: { ...process.env, GIT_CONFIG_GLOBAL: empty, GIT_CONFIG_NOSYSTEM: '1' },
    stdio: 'pipe',
  }).toString()

test.beforeAll(() => {
  rmSync(REPO, { recursive: true, force: true })
  mkdirSync(REPO, { recursive: true })
  writeFileSync(empty, '')
  writeFileSync(path.join(REPO, 'hello.py'), "print('hi')\n")
  git('init', '-q', '-b', 'main')
  git('add', '-A')
  git('commit', '-q', '-m', 'first')
  // A branch already in main, and one with a save of its own.
  git('branch', 'docs')
  git('switch', '-q', '-c', 'spike')
  writeFileSync(path.join(REPO, 'spike.txt'), 'spike\n')
  git('add', 'spike.txt')
  git('commit', '-q', '-m', 'spike')
  git('switch', '-q', 'main')
  writeFileSync(path.join(REPO, 'hello.py'), "print('hi there')\n") // changed, not committed
  mkdirSync(SHOTS, { recursive: true })
})

/** Light and dark, as the theme button sets them (`applyTheme`) - without a click, which would close an open map. */
async function both(page: Page, target: Locator | Page, name: string) {
  await target.screenshot({ path: path.join(SHOTS, `${name}-light.png`) })
  await page.evaluate(() => document.documentElement.classList.add('dark'))
  await target.screenshot({ path: path.join(SHOTS, `${name}-dark.png`) })
  await page.evaluate(() => document.documentElement.classList.remove('dark'))
}

test('the project’s git in the top bar, its map, a copy’s way back to main, and a branch switched in a turn', async ({ page }) => {
  test.setTimeout(120_000)
  const made = await page.request.post('/api/projects', { data: { root_path: REPO }, headers: OWN })
  expect(made.ok()).toBe(true)
  const pid = (await made.json()).id
  const conversation = await page.request.post('/api/conversations', { data: { project_id: pid }, headers: OWN })
  const cid = (await conversation.json()).id
  // (The Lead writes itself: the project's, every chat's - tek-ev. A touch makes this chat the one opened.)
  expect((await page.request.patch(`/api/projects/${pid}`, { data: { lead_work: 'itself' }, headers: OWN })).ok()).toBe(true)
  expect((await page.request.patch(`/api/conversations/${cid}`, { data: { plan_first: false }, headers: OWN })).ok()).toBe(true)
  await page.goto('about:blank')
  await page.goto(LINK)
  await page.getByLabel('Message').waitFor()

  // The top bar: the branch and what is not committed, read with git.
  // (What waits on git's read waits longer: the server gives git up to 5 s, LOOK_SECONDS - under load one read took 4.7 s
  // - and an open map reads again 3 s after each answer.)
  const READ = { timeout: 15_000 }
  const bar = page.locator('.topbar')
  const status = page.getByRole('button', { name: '⑂ main · 1 changed' })
  await expect(status).toBeVisible(READ)

  await page.getByLabel('Permission level').selectOption('ask')
  await page.getByLabel('Message').fill('two coders in their own copies, in git')
  await page.getByRole('button', { name: 'Send' }).click()
  const chat = page.getByRole('region', { name: 'Chat' })
  for (const _ of [1, 2]) await chat.getByRole('button', { name: 'Open agent' }).first().click()
  // Coder 2 is done and asks; Coder is still at work in its copy.
  await expect(chat.getByText("Take in Coder 2's work? · 1 file")).toBeVisible({ timeout: 15_000 })

  // Where the work is: your branch, the agents' copies of this chat, the other branches - each in words.
  await status.click()
  const map = page.getByRole('region', { name: 'Where the work is' })
  await expect(map).toBeVisible()
  const row = (what: string | RegExp) => map.locator('.git-row', { hasText: what })
  await expect(row(/^Coder · working/)).toContainText('1 file so far')
  await expect(row(/^Coder · /)).toContainText('goes into main when you take it in')
  await expect(row(/^Coder 2 · /)).toContainText('finished, waits for you')
  await expect(row(/^Coder 2 · /).getByRole('button', { name: 'Take in…' })).toBeVisible()
  await expect(row('Branch spike')).toContainText('not joined')
  await expect(row('Branch spike')).toContainText('1 commit ahead of main')
  await expect(row('Branch spike')).toContainText('nobody said where it goes')
  await expect(row('Branch docs')).toContainText('joined ✓')
  await expect(map).toContainText('main · now1 file not saved in git yet')
  // K-dallar: each branch with its last commit; no switch while a coder works in the project.
  await expect(row('Branch spike')).toContainText(/[0-9a-f]{7} spike · /)
  await expect(map).toContainText("Can't switch branches now: Coder is at work — wait for the turn to end.", READ)
  await expect(row('Branch spike').getByRole('button', { name: 'Switch to' })).toBeDisabled()
  await both(page, map, 'map')
  // Every word of it stands out from what it is on, light and dark (contrast 4.5 or more).
  for (const dark of [false, true]) {
    await page.evaluate(on => document.documentElement.classList.toggle('dark', on), dark)
    await expect.poll(async () => (await map.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
  }
  await page.evaluate(() => document.documentElement.classList.remove('dark'))
  await both(page, bar, 'top-bar')
  await page.keyboard.press('Escape')
  await expect(map).toBeHidden()
  await expect(status).toBeFocused()

  // The agent window: its working copy so far, its diff in the Workspace.
  await page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: /^Coder$/ }) }).locator('.node-head').click()
  // (each Coder's file, in its own copy - its window says)
  for (const name of [/^Coder$/, /^Coder 2$/])
    await expect(page.locator('.react-flow__node-agent').filter({ has: page.locator('.node-title', { hasText: name }) })).toContainText('1 file')
  const inspector = page.getByRole('complementary', { name: 'Inspector' })
  await inspector.getByRole('button', { name: 'Open window' }).click()
  const own = page.getByRole('region', { name: 'Agent window' })
  const copy = own.locator('.working-copy')
  await expect(copy).toContainText('Working copy: 1 file changed +1 −0')
  await both(page, own, 'agent-window')
  await copy.getByRole('button', { name: 'See changes' }).click()
  const files = page.getByRole('region', { name: 'Workspace' })
  await expect(files.getByRole('tab', { name: /Coder's copy/ })).toBeVisible()
  await expect(files.getByRole('region', { name: 'alpha.txt' })).toContainText('alpha')
  await files.getByRole('button', { name: 'Close workspace' }).click()

  // A branch switched while the turn works is said in the chat at its end, with the way to the map.
  git('switch', '-q', '-c', 'fix-login')
  await chat.getByRole('button', { name: 'Take in', exact: true }).click()
  await expect(chat.getByText("Take in Coder's work? · 1 file")).toBeVisible({ timeout: 40_000 })
  // (its copy was made on main: what it takes in goes onto fix-login now)
  await expect(chat.getByText('made on main, the project is now on fix-login')).toBeVisible()
  await chat.getByRole('button', { name: 'Discard' }).click()
  const said = chat.locator('.git-said')
  await expect(said).toContainText('The project was switched to branch fix-login during this turn (it was on main). Not reported.', { timeout: 15_000 })
  await both(page, said, 'chat-warning')
  await said.getByRole('button', { name: 'Show git' }).click()
  await expect(map).toBeVisible()
  await expect(page.getByRole('button', { name: /^⑂ fix-login/ })).toBeVisible(READ)
  await expect(row('Branch main')).toContainText('joined ✓', READ)
  // K-dallar: what is not committed keeps the branch where it is; Look reads another one read only, from git.
  await expect(map).toContainText(/Can't switch branches now: \d+ files? changed, not saved in git/, READ)
  await row('Branch spike').getByRole('button', { name: 'Look' }).click()
  const looked = page.getByRole('region', { name: 'Workspace' })
  await expect(looked).toContainText('spike · read only')
  await looked.getByRole('treeitem', { name: 'spike.txt' }).click()
  await expect(looked.locator('.diff-text').first()).toHaveText('spike')
  await looked.getByRole('button', { name: 'Back to the project' }).click()
  await expect(looked.getByRole('treeitem', { name: 'spike.txt' })).toBeHidden()
  git('switch', '-q', 'main')
})
