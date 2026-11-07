// Slice 86b in the browser: an agent's ask_folder card adds the folder to this chat, which the folder button counts
// and its panel lists ("Also in this chat") and takes off with ×; in a chat with no folder, a file the user named is
// read once, on "Allow once", and no folder is put on any list. K-buyuk-proje: the panel sets the chat to a part.
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from './fixtures'
import { contrasts, LINK, openFreshConversation, OWN, shot } from './helpers'
import { OUTSIDE_DIR, PROJECT_DIR } from './paths.mjs'

const SHELF = path.join(OUTSIDE_DIR, 'shelf86b')

for (const theme of ['light', 'dark'] as const)
  test(`“Add to this chat” puts the folder an agent asked for in the chat’s folders, where × takes it off (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    mkdirSync(SHELF, { recursive: true })
    const id = await openFreshConversation(page)
    const chat = page.getByRole('region', { name: 'Chat' })
    // No row under the top bar: the folder button alone, with no count while the chat has no other folder.
    const folder = page.getByRole('button', { name: /^Folder: / })
    await expect(folder).not.toHaveAccessibleName(/more folder/)

    await page.getByLabel('Message').fill('ask for the shelf, 86b')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(chat.getByText(`Orchestrator asks to read in ${SHELF}`)).toBeVisible({ timeout: 20_000 })
    await expect(chat.getByRole('button', { name: 'This time' })).toBeVisible()
    await chat.getByRole('button', { name: 'Add to this chat' }).click()
    await expect(chat.getByText('I may read the shelf now.')).toBeVisible({ timeout: 20_000 })

    // Counted on the folder button and listed in its panel, to read; taken off with ×, it is the chat's no more.
    await expect(folder).toHaveAccessibleName(/, and 1 more folder in this chat$/)
    await expect(folder).toContainText('+1')
    expect((await folder.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
    await folder.click()
    const also = page.getByRole('dialog', { name: 'This chat’s folders' }).getByRole('region', { name: 'Also in this chat' })
    await expect(also.getByRole('button', { name: `Access to ${SHELF}: read; click for read & write` })).toHaveText('read')
    const pieces = await page.getByRole('dialog', { name: 'This chat’s folders' }).evaluate(contrasts)
    expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
    if (process.env.KOLONI_SHOTS) await shot(page, `86b-folders-${theme}`)
    // Kept for the project (K-75-kalan): on its default, which its new chats start with - taken back after, for the next run.
    await also.getByRole('button', { name: `Keep ${SHELF} for this project` }).click()
    await expect(also.getByRole('button', { name: `Keep ${SHELF} for this project` })).toHaveCount(0)
    const pid: string = (await (await page.request.get(`/api/conversations/${id}`)).json()).conversation.project_id
    expect((await (await page.request.get(`/api/projects/${pid}`)).json()).read_in).toEqual([SHELF])
    await page.request.patch(`/api/projects/${pid}`, { data: { read_in: [] }, headers: OWN })
    await also.getByRole('button', { name: `Remove ${SHELF} from this chat` }).click()
    await expect(also.getByRole('button', { name: `Remove ${SHELF} from this chat` })).toHaveCount(0)
    await expect(folder).not.toHaveAccessibleName(/more folder/)
    expect((await (await page.request.get(`/api/conversations/${id}`)).json()).conversation.read_in).toEqual([])
  })

test('in a chat with no folder a file the user names is read once on “Allow once”, and no folder is opened', async ({ page }) => {
  mkdirSync(OUTSIDE_DIR, { recursive: true })
  const report = path.join(OUTSIDE_DIR, 'rapor.txt')
  writeFileSync(report, 'The report: three parts.\n')
  const made = await page.request.post('/api/conversations', { data: {}, headers: OWN })
  const id: string = (await made.json()).id
  await page.goto('about:blank')
  await page.goto(LINK)
  await expect(page.getByRole('button', { name: 'Folder: No folder' })).toBeVisible()
  const chat = page.getByRole('region', { name: 'Chat' })

  await page.getByLabel('Message').fill(`summarise the report, 86b: ${report}`)
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(chat.getByText('Read a file?')).toBeVisible({ timeout: 20_000 })
  await expect(chat.getByText(`Orchestrator wants to read ${report}`)).toBeVisible()
  await expect(chat.getByRole('button', { name: /this folder/ })).toHaveCount(0)
  await chat.getByRole('button', { name: 'Allow once' }).click()
  await expect(chat.getByText('The report has three parts.')).toBeVisible({ timeout: 20_000 })
  const { conversation } = await (await page.request.get(`/api/conversations/${id}`)).json()
  expect([...conversation.also_in, ...conversation.read_in]).toEqual([])
})

for (const theme of ['light', 'dark'] as const)
  test(`the folder button’s panel sets the chat to a part of its folder, by keyboard, and back to the whole project (${theme})`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    // A part of the project for this test alone: a folder with a marker file.
    const part = path.join(PROJECT_DIR, 'part86b')
    mkdirSync(part, { recursive: true })
    writeFileSync(path.join(part, 'pyproject.toml'), '[project]\nname = "part86b"\n')
    const partOf = async (id: string) => (await (await page.request.get(`/api/conversations/${id}`)).json()).conversation.part
    try {
      const id = await openFreshConversation(page)
      await page.getByRole('button', { name: /^Folder: / }).click()
      const panel = page.getByRole('dialog', { name: 'This chat’s folders' })
      const picker = panel.getByRole('combobox', { name: 'Agents work in' })
      await expect(picker).toHaveValue('')
      await picker.focus()
      await page.keyboard.press('ArrowDown')
      await expect.poll(() => partOf(id)).toBe('part86b/')
      await expect(picker).toHaveValue('part86b/')
      expect((await panel.evaluate(contrasts)).filter(piece => piece.ratio < 4.5)).toEqual([])
      if (process.env.KOLONI_SHOTS) await shot(page, `86b-part-${theme}`)
      await picker.selectOption({ label: 'Whole project' })
      await expect.poll(() => partOf(id)).toBe(null)
    } finally {
      rmSync(part, { recursive: true, force: true })
    }
  })
