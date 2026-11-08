// A project deleted from KOLONİ (Settings › This project › This folder): the dialog counts what goes, offers an export, and
// deletes only once the name is typed; then another chat opens, the project's tab is gone, nothing the page asks for is
// missing, and its folder on disk - .koloni/ too - is as it was. A folder of its own: the e2e's project is every spec's.
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { LINK, OWN, openFreshConversation, shot } from './helpers'
import { OUTSIDE_DIR } from './paths.mjs'

test('Delete project: counted, exported first if wished, deleted once its name is typed; another chat opens and the folder stays', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openFreshConversation(page)
  const name = `delete-me-${Date.now()}`
  const root = path.join(OUTSIDE_DIR, name)
  mkdirSync(path.join(root, '.koloni'), { recursive: true })
  writeFileSync(path.join(root, '.koloni', 'rules.md'), 'mine\n')
  writeFileSync(path.join(root, 'hello.py'), "print('hi')\n")
  const made = await page.request.post('/api/projects', { data: { root_path: root }, headers: OWN })
  expect(made.ok()).toBe(true)
  const pid: string = (await made.json()).id
  const chat = await page.request.post('/api/conversations', { data: { project_id: pid }, headers: OWN })
  expect(chat.ok()).toBe(true)
  const cid: string = (await chat.json()).id
  // KOLONİ opens on the chat with the latest activity: this one, touched again where another spec's work came between.
  for (let tries = 1; ; tries++) {
    expect((await page.request.patch(`/api/conversations/${cid}`, { data: { plan_first: false }, headers: OWN })).ok()).toBe(true)
    await page.goto('about:blank')
    await page.goto(LINK)
    await page.getByLabel('Message').waitFor()
    if (await page.getByRole('tab', { name: new RegExp(`^${name}`) }).count()) break
    expect(tries).toBeLessThan(3)
  }

  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  const level = page.getByRole('navigation', { name: 'Settings levels' }).getByRole('button', { name: 'This project' })
  await expect(level).toHaveAttribute('aria-current', 'true')
  await expect(level).toHaveAccessibleDescription(`${name} · every chat of it`)
  // (Under This folder, with its map and rules.)
  await page.getByRole('form', { name: 'Project settings' }).getByRole('button', { name: /^This folder/ }).click()
  const strip = page.getByRole('region', { name: 'Delete project' })
  await expect(strip).toContainText('Its folder on disk is not touched')
  await strip.getByRole('button', { name: 'Delete project…' }).click()
  const dialog = page.getByRole('alertdialog', { name: `Delete ${name} from KOLONİ?` })
  await expect(dialog).toContainText('This deletes 1 chat, 0 memory records, 0 To-do tasks, 0 triggers, 0 knowledge topics')
  await expect(dialog).toContainText('It cannot be undone.')
  await expect(dialog.getByRole('button', { name: 'Export first' })).toBeVisible()
  await shot(page, '108-delete-project')
  const remove = dialog.getByRole('button', { name: 'Delete project' })
  await expect(remove).toBeDisabled()
  await dialog.getByRole('textbox').fill(name.slice(0, -1))
  await expect(remove).toBeDisabled()
  await dialog.getByRole('textbox').fill(name)

  const missing: string[] = []
  page.on('response', r => void (r.status() === 404 && missing.push(r.url())))
  await remove.click()
  // (Another chat opens, maybe of another project: this one is no level now.)
  await expect(page.getByRole('navigation', { name: 'Settings levels' }).getByText(`${name} · every chat of it`)).toHaveCount(0)
  await expect(page.getByRole('tab', { name: new RegExp(`^${name}`) })).toHaveCount(0)
  const projects: { id: string }[] = await (await page.request.get('/api/projects')).json()
  expect(projects.map(p => p.id)).not.toContain(pid)
  expect((await page.request.get(`/api/conversations/${cid}`)).status()).toBe(404)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByLabel('Message')).toBeVisible()
  expect(missing).toEqual([])
  expect(existsSync(path.join(root, 'hello.py'))).toBe(true)
  expect(existsSync(path.join(root, '.koloni', 'rules.md'))).toBe(true)
})
