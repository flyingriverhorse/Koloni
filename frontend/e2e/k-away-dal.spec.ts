// ☾ Away on its own branch (0.1.9) in the browser: in a git repository with an origin, a night's job works on
// koloni/<task> in a worktree - it writes, asks for KOLONİ's checks (green), commits; its row says so; back, Waiting
// for you holds its push - Run pushes one commit by KOLONİ to origin. Nothing went into the project.
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { expect, test } from './fixtures'
import { level, LINK, OWN, rail, say } from './helpers'
import { APP_PORT, PYTHON } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

// A repository of the spec's own, outside the checkout (a project may not be in KOLONİ's code), and its bare origin.
const REPO = path.join(os.tmpdir(), `koloni-e2e-awaydal-${APP_PORT}`)
const ORIGIN = `${REPO}-origin.git`
// (Nothing of the user's own git settings - a signing key, a hook - in these commits; a push to a folder allowed.)
const config = `${REPO}.gitconfig`
const git = (cwd: string, ...args: string[]) =>
  execFileSync('git', ['-c', 'user.email=e2e@example.com', '-c', 'user.name=e2e', ...args], {
    cwd,
    env: { ...process.env, GIT_CONFIG_GLOBAL: config, GIT_CONFIG_NOSYSTEM: '1' },
    stdio: 'pipe',
  })
    .toString()
    .trim()

test.beforeAll(() => {
  for (const one of [REPO, ORIGIN]) rmSync(one, { recursive: true, force: true })
  mkdirSync(REPO, { recursive: true })
  writeFileSync(config, '[protocol "file"]\n\tallow = always\n[commit]\n\tgpgsign = false\n')
  writeFileSync(path.join(REPO, 'hello.py'), "print('hi')\n")
  writeFileSync(path.join(REPO, 'check.py'), "print('===== 1 passed in 0.01s =====')\n")
  git(REPO, 'init', '-q', '-b', 'main')
  // (the job's own `git commit` needs a name: the repository's, not the machine's)
  git(REPO, 'config', 'user.email', 'e2e@example.com')
  git(REPO, 'config', 'user.name', 'e2e')
  git(REPO, 'add', '-A')
  git(REPO, 'commit', '-q', '-m', 'first')
  git(os.tmpdir(), 'init', '-q', '--bare', ORIGIN)
  git(REPO, 'remote', 'add', 'origin', ORIGIN)
  git(REPO, 'push', '-q', 'origin', 'main')
})

test('a night job works on its own branch, and its push waits for your Run', async ({ page, request }) => {
  test.setTimeout(120_000)
  const made = await request.post('/api/projects', { data: { root_path: REPO }, headers: OWN })
  const pid: string = (await made.json()).id
  expect((await request.patch(`/api/projects/${pid}`, { data: { lead_work: 'itself' }, headers: OWN })).ok()).toBe(true)
  const test_ = { path: './', command: `${PYTHON} check.py` }
  expect((await request.put(`/api/projects/${pid}/map/test`, { data: test_, headers: OWN })).ok()).toBe(true)
  const cid: string = (
    await (await request.post('/api/conversations', { data: { project_id: pid }, headers: OWN })).json()
  ).id
  await request.patch(`/api/conversations/${cid}`, { data: { plan_first: false }, headers: OWN })
  await page.goto('about:blank')
  await page.goto(LINK)
  await page.getByLabel('Message', { exact: true }).waitFor()
  await level(page, 'full_auto')
  await say(page, "I'm going to sleep, dal: tidy hello", 'press Go away when you go')
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('group', { name: 'Go away now?' }).getByRole('button', { name: 'Go away' }).click()

  // The night: the job on its branch, its checks green, its commit there - done.
  const night = async () => (await (await request.get(`/api/projects/${pid}/away`)).json()) as Record<string, any>
  await expect.poll(async () => (await night())?.jobs[0]?.state, { timeout: 45_000 }).toBe('done')
  const job = (await night()).jobs[0]
  expect(job.branch.name).toMatch(/^koloni\/tidy-hello-dal-[0-9a-f]{4}$/)
  const answers = (await (await request.get(`/api/conversations/${job.conversation_id}`)).json()).tool_calls
    .filter((c: { name: string }) => c.name === 'run_checks')
    .map((c: { result: string }) => c.result)
  expect(answers[0]).toMatch(/^CHECKS: green/)
  await rail(page, 'Work').click()
  await expect(page.getByRole('listitem', { name: /^Tidy hello, dal/ }).first()).toContainText(
    `On branch ${job.branch.name} · 1 commits · 1 files · checks ✓`,
  )
  await page.getByRole('button', { name: 'I’m back' }).first().click()
  await rail(page, 'Canvas').click()

  // Back: Waiting for you holds the push; Run sends one commit by KOLONİ.
  const waiting = chat
    .getByRole('region', { name: 'While you were away' })
    .getByRole('region', { name: 'Waiting for you' })
  await expect(waiting).toContainText(`Push ${job.branch.name} to origin`, { timeout: 10_000 })
  await waiting.getByRole('button', { name: 'Run' }).click()
  await expect(waiting).toContainText(`Pushed ${job.branch.name} to origin as`, { timeout: 30_000 })
  expect(git(REPO, 'log', '--format=%s', job.branch.name).split(/\r?\n/)).toContain('tidy') // (the job's own commit)
  const sha = git(ORIGIN, 'rev-parse', `refs/heads/${job.branch.name}`)
  expect(git(ORIGIN, 'log', '-1', '--format=%ae', sha)).toBe('koloni@localhost')
  // Nothing went into the project: main and its files as they were.
  expect(readFileSync(path.join(REPO, 'hello.py'), 'utf8')).toBe("print('hi')\n")
  expect(git(REPO, 'log', '--format=%s', 'main')).toBe('first')
})
