// Slice 86a in the browser: no setup page; a plain chat talks with no file tools; a folder opened from KOLONİ's
// own folder browser opens a new chat there (the plain chat had a turn: slice 86e), whose files are read, and the list
// shows each chat under its folder.
import { expect, test, type Locator } from './fixtures'
import { contrasts, e2eProject, LINK, openFreshConversation, OWN, rail, say, shot } from './helpers'

test('KOLONİ opens with no setup page; a plain chat is given no file tools; a folder opened from the browser after a turn opens a new chat there, whose files are read', async ({ page }) => {
  // 1. A start, whatever is there: no "Open a project" page, the chat's box and the folder button.
  await page.goto(LINK)
  await expect(page.getByLabel('Message')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Folder: / })).toBeVisible()
  await expect(page.getByLabel('Project folder')).toHaveCount(0)

  // 2. A chat with no folder (the newest, so KOLONİ opens on it): a plain talk, with no file tool and no Workspace.
  await e2eProject(page) // (a folder used before: the browser opens beside it)
  const made = await page.request.post('/api/conversations', { data: {}, headers: OWN })
  expect(made.status()).toBe(201)
  const id: string = (await made.json()).id
  await page.goto('about:blank')
  await page.goto(LINK)
  const folder = page.getByRole('button', { name: 'Folder: No folder' })
  await expect(folder).toBeVisible()
  // (The button says "No folder" before any chat is open too: its tab is there once the chat is.)
  await expect(page.getByRole('tab', { name: 'No folder' })).toHaveAttribute('aria-selected', 'true')
  await say(page, 'what can you do here, 86a', 'No file tools here: a plain chat.')
  await expect(page.getByRole('button', { name: /^Workspace/ })).toHaveCount(0)
  // (No folder, nothing of a project: where commands run is not said; Settings has App alone - App.test.tsx.)
  await expect(page.locator('.topbar-title > .tag')).toHaveCount(0)

  // 3. Open a folder…: the browser opens in the folder the project is in; double-click goes in, the path goes back.
  await folder.click()
  await page.getByRole('dialog', { name: 'This chat’s folders' }).getByRole('button', { name: 'Open a folder…' }).click()
  const browser = page.getByRole('dialog', { name: 'Open a folder' })
  const here = browser.getByRole('navigation', { name: 'Where' }).locator('[aria-current]')
  await expect(here).toHaveText('e2e')
  const folders = browser.getByRole('list', { name: /^Folders in / })
  await folders.getByRole('button', { name: /^project/ }).dblclick()
  await expect(here).toHaveText('project')
  // A folder inside KOLONİ's own checkout is no project: shown, marked, never chosen.
  const blocked = folders.getByRole('button', { name: /^game42/ })
  await expect(blocked).toContainText('always blocked')
  await blocked.click()
  await expect(browser.getByRole('button', { name: 'Open "project"' })).toBeVisible()
  await browser.getByRole('navigation', { name: 'Where' }).getByRole('button', { name: 'e2e', exact: true }).click()
  await expect(here).toHaveText('e2e')
  await folders.getByRole('button', { name: /^project/ }).click()
  await browser.getByRole('button', { name: 'Open "project"' }).click()
  await expect(browser).toHaveCount(0)
  // (The plain chat had a turn: it stays as it is, and a new chat opens in the folder - slice 86e.)
  await expect(page.getByRole('button', { name: 'Folder: project' })).toBeVisible()
  expect((await (await page.request.get(`/api/conversations/${id}`)).json()).conversation.project_id).toBeNull()

  // 4. A turn there has the folder's files.
  await say(page, 'read the port, 86a', /^It listens on port \d+, says settings\.txt\.$/)

  // 5. The list has the new chat under its folder's name, open, and the plain one under "No folder", closed.
  await rail(page, 'Chats').click()
  const list = page.locator('.conv-page')
  await expect(list.getByRole('region', { name: 'project', exact: true }).getByRole('button', { name: /^read the port, 86a/ }).first()).toBeVisible()
  await list.getByRole('button', { name: 'No folder', exact: true }).click()
  await expect(list.getByRole('region', { name: 'No folder', exact: true }).getByRole('button', { name: /^what can you do here, 86a/ }).first()).toBeVisible()
})

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme the folder button, its panel and the folder browser read at 4.5 or more, a blocked folder too`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    const check = async (root: Locator, least: number) => {
      const pieces = await root.evaluate(contrasts)
      expect(pieces.length).toBeGreaterThanOrEqual(least)
      expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    }
    const button = page.getByRole('button', { name: /^Folder: / })
    await check(button, 1)
    await button.click()
    const panel = page.getByRole('dialog', { name: 'This chat’s folders' })
    await panel.getByRole('button', { name: /^Change/ }).click()
    await check(panel, 6)
    await panel.getByRole('button', { name: 'Open a folder…' }).click()
    const browser = page.getByRole('dialog', { name: 'Open a folder' })
    // (where the e2e's project is: beside KOLONİ's own folders, shown blocked)
    await expect(browser.getByText('always blocked').first()).toBeVisible()
    await check(browser, 8)
    if (process.env.KOLONI_SHOTS) await shot(page, `86a-browser-${theme}`)
  })
