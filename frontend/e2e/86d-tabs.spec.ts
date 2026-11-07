// Slices 86d and 86e: the tabs over the canvas, one per project - opened by opening one of its chats, gone back to by
// their tab (its chat opened last), closed by their × (no chat goes), brought back with "+", remembered across a
// reload, orange while one of its chats waits for you; switching a chat's main folder after a turn opens a new chat in
// that folder's tab, an empty chat moves; and a narrow window keeps to its width.
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from './fixtures'
import { contrasts, e2eProject, LINK, OWN, openFreshConversation, rail, say, shot } from './helpers'
import { OUTSIDE_DIR } from './paths.mjs'

const tabs = (page: Page) => page.getByRole('tablist', { name: 'Open projects' })
const tab = (page: Page, name: string) => tabs(page).getByRole('tab', { name: new RegExp(`^${name}`) })
const title = (page: Page) => page.locator('.topbar-title strong')

/** A chat, named, made as another window would (null: no folder): the page knows it once it reads the list again. */
async function namedChat(page: Page, name: string, projectId: string | null) {
  const made = await page.request.post('/api/conversations', { data: { project_id: projectId }, headers: OWN })
  expect(made.ok()).toBe(true)
  const id: string = (await made.json()).id
  expect((await page.request.patch(`/api/conversations/${id}`, { data: { title: name }, headers: OWN })).ok()).toBe(true)
  return id
}

/** A folder of its own outside the project, made a project as "Open a folder…" makes it. */
async function folder(page: Page, name: string) {
  const at = path.join(OUTSIDE_DIR, name)
  mkdirSync(at, { recursive: true })
  const made = await page.request.post('/api/projects', { data: { root_path: at }, headers: OWN })
  expect(made.ok()).toBe(true)
  return (await made.json()).id as string
}

for (const theme of ['light', 'dark'] as const) {
  test(`a tab per project: gone back to by its tab, closed by ×, brought back by "+", kept across a reload, orange while one of its chats waits (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const [one, two] = [`make the tab file of slice 86d ${theme} ${Date.now()}`, `tabs two ${theme} ${Date.now()}`]
    await openFreshConversation(page)
    // (The first message names the chat; the scripted Lead asks to write a file of its own - none another spec's chat
    // holds: the chat waits for you.)
    await page.getByLabel('Message').fill(one)
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.locator('[data-run="waiting_approval"]')).toBeVisible()
    await expect(tabs(page).getByRole('tab')).toHaveCount(1)
    await expect(tab(page, 'project')).toHaveAttribute('aria-selected', 'true')

    // A plain chat opened from the list, where its folder's group is closed: the "No folder" tab, the open one.
    const twoId = await namedChat(page, two, null)
    await rail(page, 'Chats').click()
    const list = page.locator('.conv-page')
    // (The open chat waits for you: it stands above the groups.)
    const plain = list.getByRole('button', { name: 'No folder', exact: true })
    await expect(plain).toHaveAttribute('aria-expanded', 'false')
    await plain.click()
    await list.getByRole('button', { name: new RegExp(`^${two}`) }).click()
    await expect(tabs(page).getByRole('tab')).toHaveCount(2)
    await expect(tab(page, 'No folder')).toHaveAttribute('aria-selected', 'true')
    await expect(title(page)).toHaveText(two)
    // The project where a chat waits for you is orange, though it is not the open one.
    await expect(tab(page, 'project').locator('..')).toHaveClass(/open-chat-waits/, { timeout: 10_000 })
    await expect(tab(page, 'project')).toHaveAccessibleName('project, waits for you')
    const pieces = await page.locator('.open-chats').evaluate(contrasts)
    expect(pieces.length).toBeGreaterThan(0)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(page, `86e-tabs-${theme}`)

    // Its tab opens the chat opened last in that project.
    await tab(page, 'project').click()
    await expect(tab(page, 'project')).toHaveAttribute('aria-selected', 'true')
    await expect(title(page)).toHaveText(one)
    await tab(page, 'No folder').click()
    await expect(title(page)).toHaveText(two)

    // A reload keeps them.
    await page.reload()
    await expect(tabs(page).getByRole('tab')).toHaveCount(2)
    await expect(tab(page, 'project')).toBeVisible()
    await expect(tab(page, 'No folder')).toBeVisible()

    // × closes the tab, never a chat.
    await tab(page, 'project').click()
    await expect(title(page)).toHaveText(one)
    await tabs(page).getByRole('button', { name: 'Close No folder' }).click()
    await expect(tabs(page).getByRole('tab')).toHaveCount(1)
    await expect(tab(page, 'project')).toHaveAttribute('aria-selected', 'true')
    expect((await page.request.get(`/api/conversations/${twoId}`)).ok()).toBe(true)

    // "+" brings it back, on its chat opened last.
    await page.getByRole('button', { name: 'Go to another folder' }).click()
    const offered = page.getByRole('dialog', { name: 'Go to another folder' })
    await expect(offered.getByRole('button', { name: 'Open a folder…' })).toBeVisible()
    expect((await offered.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await shot(page, `86e-tabs-add-${theme}`)
    await offered.getByRole('button', { name: /^No folder/ }).click()
    await expect(tab(page, 'No folder')).toHaveAttribute('aria-selected', 'true')
    await expect(title(page)).toHaveText(two)

    // (The file is not written; the scripted Lead says this of any change rejected.)
    await tab(page, 'project').click()
    await page.getByRole('region', { name: 'Chat' }).getByRole('button', { name: 'Reject' }).click()
    await expect(page.getByText('Okay, I left hello.py unchanged.')).toBeVisible()
  })
}

test('switching the main folder after a turn opens a new chat in that folder’s tab, the old one left in its own; an empty chat moves, its tab with it', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const name = `other86e-${Date.now()}`
  const other = await folder(page, name)
  const oldId = await openFreshConversation(page)
  await say(page, 'what can you do here, 86a', 'I can read the files here.')
  await expect(tabs(page).getByRole('tab')).toHaveCount(1)

  // A chat that has a turn: a new chat in the other folder, under its tab.
  await page.getByRole('button', { name: /^Folder: project/ }).click()
  const panel = page.getByRole('dialog', { name: 'This chat’s folders' })
  await panel.getByRole('button', { name: /^Change/ }).click()
  await panel.getByRole('region', { name: 'Switch the main folder' }).getByRole('button', { name: new RegExp(`^${name}`) }).click()
  await expect(page.getByRole('button', { name: `Folder: ${name}` })).toBeVisible()
  await expect(tab(page, name)).toHaveAttribute('aria-selected', 'true')
  await expect(tabs(page).getByRole('tab')).toHaveCount(2)
  await expect(title(page)).toHaveText('New conversation')
  expect((await (await page.request.get(`/api/conversations/${oldId}`)).json()).conversation.project_id).toBe(await e2eProject(page))
  const listed: { id: string; project_id: string | null }[] = await (await page.request.get('/api/conversations')).json()
  const fresh = listed.filter(c => c.project_id === other)
  expect(fresh).toHaveLength(1)
  // The old chat's tab still opens it.
  await tab(page, 'project').click()
  await expect(page.getByRole('button', { name: /^Folder: project/ })).toBeVisible()
  await tab(page, name).click()

  // An empty chat, with no turn yet, moves: its tab, the only one of its folder, becomes the new folder's.
  await page.getByRole('button', { name: `Folder: ${name}` }).click()
  await panel.getByRole('button', { name: /^Change/ }).click()
  await panel.getByRole('region', { name: 'Switch the main folder' }).getByRole('button', { name: /^No folder/ }).click()
  await expect(page.getByRole('button', { name: 'Folder: No folder' })).toBeVisible()
  await expect(tab(page, 'No folder')).toHaveAttribute('aria-selected', 'true')
  await expect(tab(page, name)).toHaveCount(0)
  expect((await (await page.request.get(`/api/conversations/${fresh[0].id}`)).json()).conversation.project_id).toBeNull()
})

for (const theme of ['light', 'dark'] as const)
  test(`at 700 px the tabs keep to the window: names cut short, the rest in "+N", the top bar as it was (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width: 700, height: 800 })
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    const stamp = Date.now()
    const ids: string[] = []
    for (let n = 1; n <= 6; n++) {
      const id = await folder(page, `narrow ${n} ${theme} ${stamp} with a name far too long for its tab`)
      await namedChat(page, `in narrow ${n}`, id)
      ids.push(id)
    }
    // Remembered from before: six tabs (the newest chat's, which KOLONİ opens on, among them).
    await page.addInitScript(remembered => localStorage.setItem('koloni-open-chats', JSON.stringify(remembered)), ids)
    await page.goto(LINK)
    await page.getByLabel('Message').waitFor()
    await expect(tabs(page).getByRole('tab').first()).toBeVisible()
    const more = page.getByRole('button', { name: /^\d+ more open projects$/ })
    await expect(more).toBeVisible()
    expect(await tabs(page).getByRole('tab').count()).toBeLessThan(6)

    const row = page.locator('.open-chats')
    expect(await row.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    const add = page.getByRole('button', { name: 'Go to another folder' })
    const [bar, strip] = [(await page.locator('.topbar').boundingBox())!, (await row.boundingBox())!]
    for (const each of [bar, strip, (await more.boundingBox())!, (await add.boundingBox())!]) expect(each.x + each.width).toBeLessThanOrEqual(700)
    // (the row under the bar, not over it)
    expect(bar.y + bar.height).toBeLessThanOrEqual(strip.y + 1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(700)
    // a name too long for its tab is cut short
    expect(await page.locator('.open-chat-title').first().evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true)
    await shot(page, `86e-tabs-700-${theme}`)

    // One from the list opens, and has a tab in the row.
    await more.click()
    const list = page.getByRole('dialog', { name: 'More open projects' })
    for (const each of [row, list]) expect((await each.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    // (a line each, not a tab's width tall)
    expect((await list.getByRole('button').first().boundingBox())!.height).toBeLessThan(40)
    await shot(page, `86e-tabs-700-more-${theme}`)
    const listed = list.getByRole('button').first()
    const name = (await listed.getAttribute('aria-label'))!.split(',')[0]
    await listed.click()
    await expect(tab(page, name)).toHaveAttribute('aria-selected', 'true')
  })
