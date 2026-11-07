// Slice 53 in the browser: a slash command of the user's own, added in Settings › This project, is in
// the box's `/` menu under the built-ins; chosen, its text is put in the box with what was typed
// after its name, to change before sending; with a role it is that role's chip. Both themes read
// at 4.5; the command is deleted again, so no other spec's menu holds it.
import { type APIRequestContext, expect, test, type Locator } from './fixtures'
import { contrasts, OWN, openFreshConversation, shot } from './helpers'

test.use({ viewport: { width: 1440, height: 900 } })

// The backend is shared with the other specs: what this one adds goes, failed or not.
test.afterEach(async ({ request }: { request: APIRequestContext }) => {
  const [project] = await (await request.get('/api/projects')).json()
  if (!project) return
  for (const command of await (await request.get(`/api/own-commands?project_id=${project.id}`)).json())
    if (command.name.startsWith('test-yaz-')) await request.delete(`/api/own-commands/${command.id}`, { headers: OWN })
})

async function reads(root: Locator) {
  const pieces = await root.evaluate(contrasts)
  expect(pieces.filter(piece => piece.ratio < 4.5)).toEqual([])
}

for (const theme of ['light', 'dark'] as const)
  test(`in the ${theme} theme: added in the settings, used from the / menu`, async ({ page }) => {
    await page.addInitScript(chosen => localStorage.setItem('koloni-theme', chosen), theme)
    await openFreshConversation(page)
    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    const settings = page.getByRole('form', { name: 'Project settings' })
    await settings.getByRole('button', { name: /^Slash commands/ }).click()
    await settings.getByLabel('Name').fill(`test-yaz-${theme}`)
    await settings.getByLabel('What it does').fill('Write tests for it')
    await settings.getByLabel('Text it puts in the box').fill('Write tests for {args}')
    await settings.getByLabel('Hand it to a role').selectOption('Tester')
    await settings.getByRole('button', { name: 'Add command' }).click()
    const row = settings.getByRole('listitem').filter({ hasText: `/test-yaz-${theme}` })
    await expect(row).toContainText('this project · to Tester')
    await reads(settings.locator('.role-editor'))
    if (process.env.KOLONI_SHOTS) await shot(page, `53-settings-${theme}`)
    await page.getByRole('button', { name: 'Close settings' }).click()

    const chat = page.getByRole('region', { name: 'Chat' })
    const box = chat.getByRole('textbox', { name: 'Message' })
    const menu = chat.getByRole('listbox', { name: 'Commands' })
    await box.fill('/')
    await expect(menu.getByRole('option').last()).toContainText(`/test-yaz-${theme}`)
    await expect(menu.getByRole('option').last()).toContainText('Write tests for it')
    await reads(menu)
    await box.fill(`/test-yaz-${theme} login form`)
    await expect(menu.getByRole('option')).toHaveCount(1)
    await page.keyboard.press('Enter')
    await expect(chat.locator('.composer-chip')).toHaveText(/^\/Tester/)
    await expect(box).toHaveValue('Write tests for login form')
    await expect(menu).toHaveCount(0)
    await box.fill('')

    await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
    await settings.getByRole('button', { name: /^Slash commands/ }).click()
    await settings.getByRole('button', { name: `Delete /test-yaz-${theme}` }).click()
    await expect(row).toHaveCount(0)
  })
