// ☾ Away, park and continue (§10) in the browser: at Ask, a night's job asks to run a command - KOLONİ parks it for
// the morning and the job goes on ("1 parked"); back, Waiting for you lists it; Run - the command runs in the job's
// copy and the same Orchestrator goes on in the same chat on KOLONİ's message; the job is done; nothing went into
// the project.
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { e2eProject, level, openFreshConversation, rail, say } from './helpers'
import { PROJECT_DIR } from './paths.mjs'

test.use({ viewport: { width: 1440, height: 900 } })

test('a command a night job asks for is parked, Run in the morning runs it and the job goes on', async ({
  page,
  request,
}) => {
  test.setTimeout(90_000)
  await openFreshConversation(page)
  await level(page, 'ask')
  const hello = readFileSync(path.join(PROJECT_DIR, 'hello.py'), 'utf8')
  await say(page, "I'm going to sleep, park: check node", 'Two tasks are on your To-do: press Go away when you go.')
  const chat = page.getByRole('region', { name: 'Chat' })
  await chat.getByRole('group', { name: 'Go away now?' }).getByRole('button', { name: 'Go away' }).click()

  // The night: its job parks the command and goes on - it waits, "1 parked".
  const pid = await e2eProject(page)
  const night = async () => (await (await request.get(`/api/projects/${pid}/away`)).json()) as Record<string, any>
  await expect.poll(async () => (await night()).jobs[0]?.why, { timeout: 30_000 }).toBe('1 parked')
  await rail(page, 'Work').click()
  await page.getByRole('button', { name: 'I’m back' }).first().click()
  await rail(page, 'Canvas').click()

  // Back: Waiting for you, on the summary - the line whole, Run.
  const summary = chat.getByRole('region', { name: 'While you were away' })
  const waiting = summary.getByRole('region', { name: 'Waiting for you' })
  await expect(waiting).toContainText('node --version', { timeout: 10_000 })
  await expect(waiting).toContainText('Check node, park')
  await waiting.getByRole('button', { name: 'Run' }).click()

  // The same Orchestrator goes on in the job's chat, on KOLONİ's message; the job is done.
  await expect.poll(async () => (await night()).jobs[0]?.state, { timeout: 30_000 }).toBe('done')
  const cid = (await night()).jobs[0].conversation_id
  const snap = await (await request.get(`/api/conversations/${cid}`)).json()
  const said = snap.messages
    .filter((m: { role: string }) => m.role === 'user')
    .map((m: { content: string }) => m.content)
  expect(said.some((one: string) => one.startsWith('KOLONİ: the user decided: ran "node --version"'))).toBe(true)
  const ran = snap.commands.filter((c: { status: string }) => c.status === 'exited')
  expect(ran.map((c: { command: string }) => c.command)).toEqual(['node --version'])
  expect(snap.runs.map((r: { status: string }) => r.status)).toEqual(['completed', 'completed'])
  await expect(waiting).toContainText('You said Run')
  // Nothing went into the project: the job's work waits for Take in.
  expect(readFileSync(path.join(PROJECT_DIR, 'hello.py'), 'utf8')).toBe(hello)
})
